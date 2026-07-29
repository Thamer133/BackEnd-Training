from datetime import date, datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from django.db.models import Q
from django.utils import timezone as dj_timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse, Vacation, Supervisor
from .serializers import (
    EmployeeSerializer,
    SickLeaveSerializer,
    ActivityLogSerializer,
    AttendanceRecordSerializer,
    ExcuseSerializer,
    VacationSerializer,
    SupervisorSerializer,
)

SICK_LEAVE_LIMIT = 15
ATTENDANCE_WINDOW = 30  # آخر 30 عملية بس تنعرض
MONTHLY_EXCUSE_LIMIT = 4
MAX_EXCUSE_HOURS_PER_DAY   = 3                                    # أقصى مدة للاستئذان الواحد
MONTHLY_EXCUSE_HOURS_LIMIT = MAX_EXCUSE_HOURS_PER_DAY * MONTHLY_EXCUSE_LIMIT * 60  # 12 ساعة = 720 دقيقة بالشهر (بالدقايق)
PERIODIC_VACATION_YEARLY_LIMIT  = 35
EMERGENCY_VACATION_YEARLY_LIMIT = 4

# ══ نظام دقايق التأخير وأيام الدوام ══
# فترة الحضور المسموحة: من 7:00 وطالع (بدون أي وقت أدنى فعلي) - 8:00 (بدون تأخير) — من 8:01 يبدأ احتساب التأخير
CHECK_IN_ON_TIME_END    = dt_time(8, 0)
# فترة الانصراف المسموحة بدون تأخير: 1:30 - 2:30 — قبل 1:30 ممنوع تماماً تسجيله،
# وبعد 2:30 بنفس اليوم يُحسب تأخير (الفرق بين 2:30 ووقت الانصراف الفعلي).
CHECK_OUT_ON_TIME_START = dt_time(13, 30)
CHECK_OUT_ON_TIME_END   = dt_time(14, 30)

# نطاق ساعات الدوام الفعلي — أي وقت استئذان (من/إلى) لازم يقع بالكامل ضمن هذا
# المدى (من 7:30 لين 2:30 نهاية فترة الانصراف — ما يصير استئذان قبل 7:30).
WORK_HOURS_START = dt_time(7, 30)
WORK_HOURS_END   = dt_time(14, 30)

YEARLY_LATE_MINUTES_LIMIT  = 7 * 60  # 7 ساعات = 420 دقيقة بالسنة — بعدها إشعار "تجاوز الحد الأقصى"
YEARLY_WORKDAYS_MIN_TARGET = 180     # 180 يوم عمل بالسنة — الحد الأدنى للدوام

# توقيت الكويت ثابت (UTC+3) — نحوّل له مباشرة بدل الاعتماد على settings.TIME_ZONE
# (لو الإعداد مو مضبوط بالضبط على الكويت بيصير فرق ساعات بكل حسابات التأخير)
KUWAIT_TZ = ZoneInfo("Asia/Kuwait")


def to_local_time(dt):
    """يحوّل أي datetime (aware أو naive) لتوقيت الكويت المحلي مباشرة."""
    if dj_timezone.is_naive(dt):
        dt = dj_timezone.make_aware(dt, timezone=dj_timezone.utc)
    return dt.astimezone(KUWAIT_TZ)


def _parse_time_string(value):
    """
    يحاول يفهم صيغة وقت مرنة من اللي مخزّن بحقل Excuse.time_from/time_to (نص حر
    زي '10:30' أو '10:30 AM' أو '10:30 ص' أو '02:30 م'). يرجع datetime.time أو
    None لو ما قدر يفهم الصيغة (بدون ما يوقف باقي المنطق).
    """
    if not value:
        return None
    raw = str(value).strip()
    normalized = (
        raw.replace('صباحاً', 'AM').replace('صباحا', 'AM').replace('ص', 'AM')
           .replace('مساءً', 'PM').replace('مساءا', 'PM').replace('م', 'PM')
    )
    for candidate in (raw, normalized):
        for fmt in ('%H:%M', '%I:%M %p', '%I:%M%p', '%H:%M:%S'):
            try:
                return datetime.strptime(candidate.strip(), fmt).time()
            except ValueError:
                continue
    return None


def _excuse_duration_minutes(time_from, time_to):
    """
    يحسب مدة الاستئذان بالدقايق من نصوص الوقت الحرة (time_from/time_to). يرجع
    None لو ما قدر يفهم أي وحد منهم (بدون ما يوقف باقي المنطق). لو النهاية قبل
    البداية (خطأ إدخال) يرجع None بدل رقم سالب.
    """
    parsed_from = _parse_time_string(time_from)
    parsed_to = _parse_time_string(time_to)
    if not parsed_from or not parsed_to:
        return None
    anchor = date.today()
    minutes = int((datetime.combine(anchor, parsed_to) - datetime.combine(anchor, parsed_from)).total_seconds() // 60)
    return minutes if minutes > 0 else None


def _checkin_effective_cutoff(employee, local_date):
    """
    وقت القطع الفعلي لحضور هذا اليوم لهذا الموظف — عادةً 8:00، إلا لو عنده
    استئذان "بداية الدوام" بنفس اليوم ينتهي بعد 8:00؛ حينها القطع يمتد لوقت
    نهاية الاستئذان — نفس منطق الانصراف بالضبط: بالوقت أو قبله = صفر تأخير،
    وأي دقيقة بعده تُحسب تأخير فوراً بدون فترة سماح.
    نفلتر بـ period='بداية الدوام' فقط عشان استئذان نهاية الدوام ما يأثر على
    حساب الحضور بالغلط.
    """
    cutoff = CHECK_IN_ON_TIME_END
    for excuse in Excuse.objects.filter(employee=employee, date=local_date, period='بداية الدوام'):
        parsed_to = _parse_time_string(excuse.time_to)
        if parsed_to and parsed_to > cutoff:
            cutoff = parsed_to
    return cutoff


def _checkout_excuse_window(employee, local_date):
    """
    لو عند الموظف استئذان "نهاية الدوام" بنفس اليوم، يرجع (وقت البداية، وقت
    النهاية) — أي انصراف يقع **داخل** هذا المدى بالكامل (بين الوقتين، بأي
    لحظة، مو بس بدايته) = صفر تأخير، لأنه أصلاً مغطى بالاستئذان. برّا هذا
    المدى، القاعدة العادية تطبّق زي ما هي (ممنوع قبل 1:30، تأخير بعد 2:30).
    يرجع None لو ما فيه استئذان نهاية دوام بنفس اليوم.
    نفلتر بـ period='نهاية الدوام' فقط عشان استئذان بداية الدوام ما يأثر على
    حساب الانصراف بالغلط. لو فيه أكثر من استئذان نهاية دوام بنفس اليوم (نادر)،
    ناخذ أوسع مدى (أبكر بداية، أبعد نهاية).
    """
    earliest_from = None
    latest_to = None
    for excuse in Excuse.objects.filter(employee=employee, date=local_date, period='نهاية الدوام'):
        parsed_from = _parse_time_string(excuse.time_from)
        parsed_to = _parse_time_string(excuse.time_to)
        if not parsed_from or not parsed_to:
            continue
        if earliest_from is None or parsed_from < earliest_from:
            earliest_from = parsed_from
        if latest_to is None or parsed_to > latest_to:
            latest_to = parsed_to
    if earliest_from is None or latest_to is None:
        return None
    return (earliest_from, latest_to)


def _exemption_reason(employee, local_date):
    """
    يرجّع سبب إعفاء هذا اليوم من احتساب التأخير — 'sick_leave' أو 'vacation' أو
    None لو مافيه إعفاء. مفيدة لتتبّع سبب أي صفر تأخير غير متوقع (تُسجّل بسجل الأنشطة).
    """
    if SickLeave.objects.filter(employee=employee, date=local_date).exists():
        return 'sick_leave'

    accepted_vacation_covers_day = Vacation.objects.filter(
        employee=employee, status='accepted', date_from__lte=local_date,
    ).filter(
        Q(date_to__gte=local_date) | Q(date_to__isnull=True, date_from=local_date)
    ).exists()
    if accepted_vacation_covers_day:
        return 'vacation'

    return None


def _is_exempt_day(employee, local_date):
    """
    يوم فيه طبية مسجّلة، أو إجازة (دورية أو طارئة) مقبولة تغطي هذا التاريخ =
    يوم معفى بالكامل من احتساب أي دقايق تأخير — لأنه أصلاً يوم إجازة مرضية أو
    إجازة رسمية، مو يوم دوام عادي.
    """
    return _exemption_reason(employee, local_date) is not None


def _first_checkin_date_between(employee, start_date, end_date):
    """
    يرجّع أول تاريخ (بالتوقيت المحلي) بين start_date و end_date (شاملة) فيه
    بصمة حضور فعلية مسجّلة لهذا الموظف، أو None لو ما فيه أي تعارض. يُستخدم
    لمنع تسجيل طبية أو إجازة تغطي يوم أصلاً بصمت فيه حضور.
    """
    checkin_dates = sorted({
        to_local_time(ts).date()
        for ts in AttendanceRecord.objects.filter(employee=employee, action='check_in').values_list('timestamp', flat=True)
        if start_date <= to_local_time(ts).date() <= end_date
    })
    return checkin_dates[0] if checkin_dates else None


def calculate_late_minutes(action, local_dt, checkin_cutoff=None, checkout_excuse_window=None):
    """
    يحسب دقايق التأخير لعملية حضور أو انصراف واحدة حسب وقتها المحلي (local_dt هو
    datetime بتوقيت الكويت الفعلي، مو UTC). الثواني تُهمل (تُقرّب للدقيقة الأقل).
    - حضور: بعد checkin_cutoff (افتراضياً 8:00، أو وقت نهاية استئذان اليوم لو
      موجود) يُحسب تأخير = (وقت الحضور - القطع) بالدقايق.
    - انصراف بيوم فيه استئذان نهاية دوام (checkout_excuse_window = (من، إلى)):
      أي انصراف يقع **داخل** مدى الاستئذان بالكامل (بأي لحظة بينهم) = صفر
      تأخير، لأنه مغطى بالاستئذان. برّا هذا المدى ترجع القاعدة العادية.
    - انصراف بدون تغطية استئذان: قبل 1:30 يُحسب تأخير (خروج مبكر)، بعد 2:30
      يُحسب تأخير (خروج متأخر)، وبينهم صفر تأخير.
    """
    cutoff_time = checkin_cutoff or CHECK_IN_ON_TIME_END
    t = local_dt.time().replace(second=0, microsecond=0)

    if action == 'check_in':
        if t <= cutoff_time:
            return 0
        cutoff = local_dt.replace(hour=cutoff_time.hour, minute=cutoff_time.minute, second=0, microsecond=0)
        return max(int((local_dt.replace(second=0, microsecond=0) - cutoff).total_seconds() // 60), 0)

    if action == 'check_out':
        if checkout_excuse_window:
            window_start, window_end = checkout_excuse_window
            if window_start <= t <= window_end:
                return 0

        if t < CHECK_OUT_ON_TIME_START:
            cutoff = local_dt.replace(hour=13, minute=30, second=0, microsecond=0)
            return max(int((cutoff - local_dt.replace(second=0, microsecond=0)).total_seconds() // 60), 0)
        if t > CHECK_OUT_ON_TIME_END:
            cutoff = local_dt.replace(hour=14, minute=30, second=0, microsecond=0)
            return max(int((local_dt.replace(second=0, microsecond=0) - cutoff).total_seconds() // 60), 0)
        return 0

    return 0


def calculate_late_minutes_for_employee(employee, action, local_dt):
    """
    نفس calculate_late_minutes بس تربط باقي الصفحات مع بعض:
    - يوم فيه طبية أو إجازة مقبولة → صفر تأخير مباشرة (معفى بالكامل).
    - حضور بيوم فيه استئذان → القطع يمتد لوقت نهاية الاستئذان بدل 8:00 الثابتة.
    - انصراف بيوم فيه استئذان نهاية دوام → أي انصراف داخل مدى الاستئذان
      بالكامل = صفر تأخير.
    """
    local_date = local_dt.date()

    if _is_exempt_day(employee, local_date):
        return 0

    checkin_cutoff = _checkin_effective_cutoff(employee, local_date) if action == 'check_in' else None
    checkout_excuse_window = _checkout_excuse_window(employee, local_date) if action == 'check_out' else None
    return calculate_late_minutes(action, local_dt, checkin_cutoff=checkin_cutoff, checkout_excuse_window=checkout_excuse_window)


def minutes_to_hm_label(total_minutes):
    """يحوّل عدد دقايق لصيغة نصية بالساعات والدقايق (مثال: 100 → 'ساعة و 40 دقيقة')."""
    total_minutes = int(total_minutes or 0)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} ساعة و {minutes} دقيقة"
    if hours:
        return f"{hours} ساعة"
    return f"{minutes} دقيقة"


def get_client_ip(request):
    """
    يرجّع عنوان IP الحقيقي للجهاز اللي سوّى الطلب.
    لو الطلب مار عبر بروكسي/لود بالانسر (X-Forwarded-For)، ناخذ أول IP بالسلسلة
    (وهو IP العميل الأصلي). وإلا نرجع REMOTE_ADDR مباشرة (الاتصال المحلي المباشر).
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# GET ALL EMPLOYEES — POST (إضافة موظف جديد)
@api_view(['GET', 'POST'])
def employee_list(request):
    if request.method == 'GET':
        civil_id     = request.query_params.get('civil_id', '').strip()
        name         = request.query_params.get('name', '').strip()
        phone_number = request.query_params.get('phone_number', '').strip()

        employees = Employee.objects.all().order_by('name')
        if civil_id:
            employees = employees.filter(civil_id__icontains=civil_id)
        if name:
            employees = employees.filter(name__icontains=name)
        if phone_number:
            employees = employees.filter(phone_number__icontains=phone_number)

        search_terms = ", ".join(f"{k}={v}" for k, v in [("civil_id", civil_id), ("name", name), ("phone_number", phone_number)] if v)
        ActivityLog.objects.create(
            action='view',
            description=f"تم عرض/بحث بقائمة الموظفين{f' ({search_terms})' if search_terms else ''} — {employees.count()} نتيجة",
            source='employee',
            ip_address=get_client_ip(request),
        )

        serializer = EmployeeSerializer(employees, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = EmployeeSerializer(data=request.data)
        if serializer.is_valid():
            employee = serializer.save()
            ActivityLog.objects.create(
                action='create',
                description=f"تم إضافة موظف جديد: {employee.name}",
                source='employee',
                ip_address=get_client_ip(request),
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# GET ALL SUPERVISORS (المسؤولين — تُعبّى يدوياً من لوحة الأدمن) — POST (إضافة مسؤول جديد)
@api_view(['GET', 'POST'])
def supervisor_list(request):
    if request.method == 'GET':
        civil_id     = request.query_params.get('civil_id', '').strip()
        name         = request.query_params.get('name', '').strip()
        phone_number = request.query_params.get('phone_number', '').strip()

        supervisors = Supervisor.objects.all().order_by('name')
        if civil_id:
            supervisors = supervisors.filter(civil_id__icontains=civil_id)
        if name:
            supervisors = supervisors.filter(name__icontains=name)
        if phone_number:
            supervisors = supervisors.filter(phone_number__icontains=phone_number)

        search_terms = ", ".join(f"{k}={v}" for k, v in [("civil_id", civil_id), ("name", name), ("phone_number", phone_number)] if v)
        ActivityLog.objects.create(
            action='view',
            description=f"تم عرض/بحث بقائمة المسؤولين{f' ({search_terms})' if search_terms else ''} — {supervisors.count()} نتيجة",
            source='supervisor',
            ip_address=get_client_ip(request),
        )

        serializer = SupervisorSerializer(supervisors, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = SupervisorSerializer(data=request.data)
        if serializer.is_valid():
            supervisor = serializer.save()
            ActivityLog.objects.create(
                action='create',
                description=f"تم إضافة مسؤول جديد: {supervisor.name}",
                source='supervisor',
                ip_address=get_client_ip(request),
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# GET (سجل واحد) — PUT (تعديل كامل) — PATCH (تعديل جزئي) — DELETE (حذف موظف)
@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def employee_detail(request, pk):
    try:
        employee = Employee.objects.get(pk=pk)
    except Employee.DoesNotExist:
        return Response({"error": "الموظف غير موجود"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        ActivityLog.objects.create(
            action='view',
            description=f"تم عرض بيانات الموظف {employee.name}",
            source='employee',
            ip_address=get_client_ip(request),
        )
        serializer = EmployeeSerializer(employee)
        return Response(serializer.data)

    elif request.method in ('PUT', 'PATCH'):
        old_name = employee.name
        is_partial = request.method == 'PATCH'
        serializer = EmployeeSerializer(employee, data=request.data, partial=is_partial)
        if serializer.is_valid():
            serializer.save()
            changed_fields = ", ".join(request.data.keys())
            ActivityLog.objects.create(
                action='update',
                description=f"تم تعديل بيانات الموظف {old_name} (الحقول: {changed_fields})",
                source='employee',
                ip_address=get_client_ip(request),
            )
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        employee_name = employee.name
        employee.delete()
        ActivityLog.objects.create(
            action='delete',
            description=f"تم حذف الموظف {employee_name}",
            source='employee',
            ip_address=get_client_ip(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# GET (سجل واحد) — PUT (تعديل كامل) — PATCH (تعديل جزئي) — DELETE (حذف مسؤول)
@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def supervisor_detail(request, pk):
    try:
        supervisor = Supervisor.objects.get(pk=pk)
    except Supervisor.DoesNotExist:
        return Response({"error": "المسؤول غير موجود"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        ActivityLog.objects.create(
            action='view',
            description=f"تم عرض بيانات المسؤول {supervisor.name}",
            source='supervisor',
            ip_address=get_client_ip(request),
        )
        serializer = SupervisorSerializer(supervisor)
        return Response(serializer.data)

    elif request.method in ('PUT', 'PATCH'):
        old_name = supervisor.name
        is_partial = request.method == 'PATCH'
        serializer = SupervisorSerializer(supervisor, data=request.data, partial=is_partial)
        if serializer.is_valid():
            serializer.save()
            changed_fields = ", ".join(request.data.keys())
            ActivityLog.objects.create(
                action='update',
                description=f"تم تعديل بيانات المسؤول {old_name} (الحقول: {changed_fields})",
                source='supervisor',
                ip_address=get_client_ip(request),
            )
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        supervisor_name = supervisor.name
        supervisor.delete()
        ActivityLog.objects.create(
            action='delete',
            description=f"تم حذف المسؤول {supervisor_name}",
            source='supervisor',
            ip_address=get_client_ip(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# GET (كل الطبيات لكل الموظفين) - POST (إضافة طبية جديدة)
@api_view(['GET', 'POST'])
def sick_leave_list(request):
    if request.method == 'GET':
        leaves = SickLeave.objects.select_related('employee').all()
        serializer = SickLeaveSerializer(leaves, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        employee_id = request.data.get('employee')
        date_str    = request.data.get('date')

        if not employee_id or not date_str:
            return Response({"error": "الرجاء تحديد الموظف والتاريخ"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            employee = Employee.objects.get(id=employee_id)
        except Employee.DoesNotExist:
            return Response({"error": "الموظف غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        current_count = SickLeave.objects.filter(employee=employee).count()
        if current_count >= SICK_LEAVE_LIMIT:
            return Response(
                {"error": f"تم استخدام كل عدد الطبيات المسموح ({SICK_LEAVE_LIMIT}) لهذا الموظف"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if SickLeave.objects.filter(employee=employee, date=date_str).exists():
            return Response(
                {"error": "هذا التاريخ مسجل مسبقاً كطبية لهذا الموظف"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ما يصير تسجيل طبية بيوم أصلاً بصمت فيه حضور — الطبية تبدأ من اليوم اللي بعده
        try:
            sick_date = date.fromisoformat(date_str)
            if _first_checkin_date_between(employee, sick_date, sick_date):
                return Response(
                    {"error": "بصمت حضور بهذا التاريخ بالفعل"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except ValueError:
            pass

        leave = SickLeave.objects.create(employee=employee, date=date_str)
        ActivityLog.objects.create(
            action='create',
            description=f"تسجيل طبية لـ {employee.name} بتاريخ {date_str}",
            source='sick_leave',
            ip_address=get_client_ip(request),
        )
        serializer = SickLeaveSerializer(leave)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# DELETE طبية معينة
@api_view(['DELETE'])
def sick_leave_detail(request, pk):
    try:
        leave = SickLeave.objects.get(pk=pk)
    except SickLeave.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    description = f"حذف طبية لـ {leave.employee.name} بتاريخ {leave.date}"
    leave.delete()
    ActivityLog.objects.create(action='delete', description=description, source='sick_leave', ip_address=get_client_ip(request))
    return Response(status=status.HTTP_204_NO_CONTENT)


# GET سجل آخر العمليات (آخر 200 عملية) — POST تسجيل عملية جديدة من الفرونت إند
@api_view(['GET', 'POST'])
def activity_log_list(request):
    if request.method == 'GET':
        logs = ActivityLog.objects.all()[:200]
        serializer = ActivityLogSerializer(logs, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        description = request.data.get('description', '').strip()
        action = request.data.get('action', 'create')
        source = request.data.get('source', 'other')

        if not description:
            return Response({"error": "الوصف مطلوب"}, status=status.HTTP_400_BAD_REQUEST)

        log = ActivityLog.objects.create(action=action, description=description, source=source, ip_address=get_client_ip(request))
        serializer = ActivityLogSerializer(log)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# GET (آخر 30 عملية حضور/انصراف لموظف معين) — POST (تسجيل حضور أو انصراف جديد)
@api_view(['GET', 'POST'])
def attendance_record_list(request):
    if request.method == 'GET':
        employee_name = request.query_params.get('employee_name', '').strip()
        records = AttendanceRecord.objects.select_related('employee').all()
        if employee_name:
            records = records.filter(employee__name=employee_name)
        records = records[:ATTENDANCE_WINDOW]
        serializer = AttendanceRecordSerializer(records, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        employee_id = request.data.get('employee')
        action      = request.data.get('action')

        if not employee_id or action not in ('check_in', 'check_out'):
            return Response({"error": "بيانات غير صحيحة"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            employee = Employee.objects.get(id=employee_id)
        except Employee.DoesNotExist:
            return Response({"error": "الموظف غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        # ما يصير تسجيل حضور ولا انصراف إطلاقاً بيوم فيه إجازة (طبية، أو
        # إجازة دورية/طارئة مقبولة) — بغض النظر عن نوعها، اليوم يعتبر إجازة كاملة.
        today_local = to_local_time(dj_timezone.now()).date()
        today_leave_reason = _exemption_reason(employee, today_local)
        if today_leave_reason:
            reason_label = 'طبية مسجّلة' if today_leave_reason == 'sick_leave' else 'إجازة مقبولة'
            return Response(
                {"error": f"عندك {reason_label} بتاريخ اليوم — ما يصير تسجيل حضور أو انصراف يوم إجازة"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        last_record = AttendanceRecord.objects.filter(employee=employee).order_by('-timestamp').first()
        has_open_checkin = bool(last_record and last_record.action == 'check_in')

        # ما يفتح تسجيل حضور جديد إلا لو آخر عملية كانت انصراف (أو ما فيه سجلات
        # أصلاً) — لازم تسجّل انصراف أول قبل ما يفتح الحضور من جديد، بغض النظر
        # عن اليوم (حتى لو دخل يوم جديد وأنت لسا ما سجّلت انصراف).
        if action == 'check_in' and has_open_checkin:
            return Response(
                {"error": "عندك بصمة حضور مفتوحة — لازم تسجّل انصراف أول قبل ما تقدر تسجّل حضور جديد"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # لو آخر عملية انصراف، وهذا الانصراف صار اليوم، والحضور اللي فتحه صار
        # اليوم كمان (يعني دورة حضور/انصراف كاملة بنفس اليوم) — ما يفتح حضور
        # جديد إلا مع بداية يوم جديد. (لو الحضور كان من يوم سابق وتجاوز منتصف
        # الليل، ما ينطبق هذا القيد ويفتح الحضور فوراً — نفس منطق الفرونت إند.)
        if action == 'check_in' and last_record and last_record.action == 'check_out':
            today_local_date = to_local_time(dj_timezone.now()).date()
            checkout_local_date = to_local_time(last_record.timestamp).date()
            if checkout_local_date == today_local_date:
                second_last = AttendanceRecord.objects.filter(employee=employee).exclude(
                    id=last_record.id
                ).order_by('-timestamp').first()
                if (
                    second_last and second_last.action == 'check_in'
                    and to_local_time(second_last.timestamp).date() == today_local_date
                ):
                    return Response(
                        {"error": "سجّلت حضور وانصراف كاملين اليوم — ما يصير حضور جديد إلا مع بداية يوم جديد"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        # ما يفتح تسجيل انصراف إلا لو فيه بصمة حضور مفتوحة أصلاً
        if action == 'check_out' and not has_open_checkin:
            return Response(
                {"error": "ما فيه بصمة حضور مفتوحة تقدر تسجّل عليها انصراف"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        open_checkin_local_date = None
        crosses_into_new_day = False
        checkout_excuse_window_used = None
        if action == 'check_out':
            open_checkin_local_date = to_local_time(last_record.timestamp).date()
            now_local = to_local_time(dj_timezone.now())
            crosses_into_new_day = now_local.date() != open_checkin_local_date

            # الانصراف بنفس يوم الحضور يفتح بداية من 1:30 عادةً. لو فيه استئذان
            # نهاية دوام بنفس اليوم وكان وقت الانصراف الحالي داخل مدى الاستئذان
            # نفسه، ما فيه أي قيد وقت أدنى — مسموح ينصرف بأي لحظة داخل المدى.
            # لو الانصراف صار بيوم تالي (نسى يسجّل انصراف بوقته) يُسمح بأي وقت
            # كمان لأنه أصلاً متأخر جداً (تُحسب الفترة كتأخير كامل بالأسفل).
            if not crosses_into_new_day:
                checkout_excuse_window_used = _checkout_excuse_window(employee, open_checkin_local_date)
                within_excuse_window = bool(
                    checkout_excuse_window_used
                    and checkout_excuse_window_used[0] <= now_local.time() <= checkout_excuse_window_used[1]
                )
                if not within_excuse_window and now_local.time() < CHECK_OUT_ON_TIME_START:
                    return Response(
                        {"error": "لا يمكن تسجيل الانصراف قبل الساعة 1:30"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        record = AttendanceRecord.objects.create(employee=employee, action=action)
        local_dt = to_local_time(record.timestamp)

        # الإعفاء (طبية/إجازة) يُحسب دايماً على يوم الحضور نفسه — عشان لو صار
        # الانصراف متأخر ليوم تالي، يضل مربوط بنفس يوم الحضور الأصلي لغرض الإعفاء.
        exemption_date = open_checkin_local_date if action == 'check_out' else local_dt.date()
        exemption = _exemption_reason(employee, exemption_date)

        checkin_cutoff_used = None
        if exemption:
            record.late_minutes = 0
        elif action == 'check_out' and crosses_into_new_day:
            # نسى يسجّل انصراف بوقته وتجاوزنا لليوم التالي — كل الفترة اللي مرّت
            # من لحظة الحضور لين لحظة الانصراف تُحسب تأخير كامل.
            elapsed_minutes = int((record.timestamp - last_record.timestamp).total_seconds() // 60)
            record.late_minutes = max(elapsed_minutes, 0)
        elif action == 'check_in':
            # نجيب وقت القطع الفعلي بشكل صريح (مو مخفي جوا الدالة) عشان نقدر
            # نسجّله بسجل الأنشطة لو امتد بسبب استئذان — يفيد بتتبّع أي صفر
            # تأخير غير متوقع بالمستقبل.
            checkin_cutoff_used = _checkin_effective_cutoff(employee, local_dt.date())
            record.late_minutes = calculate_late_minutes(action, local_dt, checkin_cutoff=checkin_cutoff_used)
        elif action == 'check_out':
            # checkout_excuse_window_used محسوبة أعلى وقت التحقق — نفس القيمة
            # تُستخدم بالحساب عشان تطابق استئذان نهاية الدوام (لو موجود).
            record.late_minutes = calculate_late_minutes(action, local_dt, checkout_excuse_window=checkout_excuse_window_used)
        else:
            record.late_minutes = calculate_late_minutes_for_employee(employee, action, local_dt)

        if record.late_minutes:
            record.save(update_fields=['late_minutes'])

        if exemption:
            reason_label = 'طبية مسجّلة' if exemption == 'sick_leave' else 'إجازة مقبولة'
            late_note = f" — معفى من احتساب التأخير (يوجد {reason_label} بنفس التاريخ)"
        elif checkin_cutoff_used and checkin_cutoff_used != CHECK_IN_ON_TIME_END:
            note_tail = f"متأخر {record.late_minutes} دقيقة" if record.late_minutes else "بدون تأخير"
            late_note = f" — وقت القطع امتد لـ {checkin_cutoff_used.strftime('%H:%M')} بسبب استئذان مسجّل بنفس اليوم ({note_tail})"
        elif checkout_excuse_window_used:
            note_tail = f"متأخر {record.late_minutes} دقيقة" if record.late_minutes else "بدون تأخير"
            w_start, w_end = checkout_excuse_window_used
            late_note = f" — مغطى باستئذان نهاية دوام من {w_start.strftime('%H:%M')} إلى {w_end.strftime('%H:%M')} بنفس اليوم ({note_tail})"
        elif record.late_minutes:
            late_note = f" — متأخر {record.late_minutes} دقيقة ({minutes_to_hm_label(record.late_minutes)})"
        else:
            late_note = ""

        ActivityLog.objects.create(
            action='create',
            description=f"{employee.name} سجّل {record.get_action_display()} بتاريخ {record.timestamp}{late_note}",
            source='attendance',
            ip_address=get_client_ip(request),
        )
        serializer = AttendanceRecordSerializer(record)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# GET — إحصائيات دقايق التأخير وأيام الدوام السنوية لموظف معين.
# الاحتساب دايماً على أساس السنة الميلادية الحالية تلقائياً (بدون أي زر Reset يدوي) —
# بمجرد ما تدخل سنة ميلادية جديدة تبدأ الأرقام من الصفر لوحدها، وسجلات السنوات
# القديمة تضل محفوظة بالكامل بقاعدة البيانات وتُقرأ بفلتر ?year= عشان الرجوع لها.
# مثال: /api/attendance/attendance-stats/?employee_name=ثامر فريد&year=2025
@api_view(['GET'])
def attendance_stats(request):
    employee_name = request.query_params.get('employee_name', '').strip()
    year_param    = request.query_params.get('year', '').strip()

    if not employee_name:
        return Response({"error": "الرجاء تحديد employee_name"}, status=status.HTTP_400_BAD_REQUEST)

    employee = Employee.objects.filter(name=employee_name).first()
    if not employee:
        return Response({"error": "الموظف غير موجود"}, status=status.HTTP_404_NOT_FOUND)

    current_year = date.today().year
    if year_param:
        try:
            year = int(year_param)
        except ValueError:
            return Response({"error": "سنة غير صحيحة"}, status=status.HTTP_400_BAD_REQUEST)
    else:
        year = current_year

    all_records = AttendanceRecord.objects.filter(employee=employee)

    # نفلتر بالسنة اعتماداً على توقيت الكويت المحسوب يدوياً (مو فلتر __year بقاعدة
    # البيانات) — عشان نتفادى أي فرق ساعات قريب من منتصف الليل بنهاية السنة لو
    # إعداد settings.TIME_ZONE مو مضبوط بالضبط على الكويت.
    total_late_minutes = 0
    days_actions = {}
    all_years = set()

    for rec_action, rec_timestamp, rec_late in all_records.values_list('action', 'timestamp', 'late_minutes'):
        local_dt = to_local_time(rec_timestamp)
        all_years.add(local_dt.year)
        if local_dt.year != year:
            continue
        total_late_minutes += rec_late or 0
        local_date = local_dt.date()
        days_actions.setdefault(local_date, set()).add(rec_action)

    # يوم عمل = يوم فيه حضور وانصراف بنفس اليوم الميلادي — بغض النظر عن وجود
    # تأخير بأي منهم (حتى لو تأخر بالحضور أو انصرف متأخر، طالما حضر وانصرف
    # فعلياً نفس اليوم يُحتسب يوم دوام كامل)
    workdays_count = sum(
        1 for actions in days_actions.values()
        if {'check_in', 'check_out'}.issubset(actions)
    )

    available_years = sorted(all_years, reverse=True)
    if current_year not in available_years:
        available_years.insert(0, current_year)

    exceeded_late_limit    = total_late_minutes > YEARLY_LATE_MINUTES_LIMIT
    reached_min_attendance = workdays_count >= YEARLY_WORKDAYS_MIN_TARGET

    ActivityLog.objects.create(
        action='view',
        description=f"تم عرض إحصائيات التأخير/الدوام لسنة {year} للموظف {employee.name}",
        source='attendance',
        ip_address=get_client_ip(request),
    )

    # اليوم إجازة (طبية أو دورية/طارئة مقبولة)؟ — يُستخدم بالفرونت إند لقفل
    # زري الحضور والانصراف مباشرة بدون ما يحتاج المستخدم يضغط ويشوف رسالة خطأ.
    today_leave_reason = _exemption_reason(employee, date.today())

    return Response({
        "employee": employee.name,
        "year": year,
        "is_current_year": year == current_year,
        "total_late_minutes": total_late_minutes,
        "total_late_display": minutes_to_hm_label(total_late_minutes),
        "workdays_count": workdays_count,
        "workdays_target": YEARLY_WORKDAYS_MIN_TARGET,
        "is_on_leave_today": today_leave_reason is not None,
        "leave_reason_today": today_leave_reason,
        "alerts": {
            "exceeded_late_limit": exceeded_late_limit,
            "late_limit_minutes": YEARLY_LATE_MINUTES_LIMIT,
            "late_limit_display": minutes_to_hm_label(YEARLY_LATE_MINUTES_LIMIT),
            "reached_min_attendance": reached_min_attendance,
        },
        "available_years": available_years,
    }, status=status.HTTP_200_OK)


# GET (كل استئذانات موظف معين) — POST (تسجيل استئذان جديد)
@api_view(['GET', 'POST'])
def excuse_list(request):
    if request.method == 'GET':
        employee_name = request.query_params.get('employee_name', '').strip()
        excuses = Excuse.objects.select_related('employee').all()
        if employee_name:
            excuses = excuses.filter(employee__name=employee_name)
        serializer = ExcuseSerializer(excuses, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        employee_id = request.data.get('employee')
        date_str    = request.data.get('date')
        time_from   = request.data.get('time_from')
        time_to     = request.data.get('time_to')
        period      = request.data.get('period')

        if not all([employee_id, date_str, time_from, time_to, period]):
            return Response({"error": "الرجاء تعبئة كل الحقول"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            employee = Employee.objects.get(id=employee_id)
        except Employee.DoesNotExist:
            return Response({"error": "الموظف غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        today = date.today()

        # ── قفل يومي: استئذان واحد بس باليوم (بناءً على وقت التسجيل الفعلي) ──
        if Excuse.objects.filter(employee=employee, recorded_at__date=today).exists():
            return Response(
                {"error": "تم تسجيل استئذان اليوم، ولا يمكن تسجيل استئذان آخر إلا بعد مرور يوم كامل"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # استئذان "بداية الدوام" معناه أساساً إنك ما بدأت الدوام لسا (بتتأخر أو
        # تجي متأخر) — لو أصلاً بصمت حضور بهذا التاريخ، الاستئذان يصير متناقض
        # مع الواقع، فنرفضه. (نهاية الدوام وأثناء الدوام ما يتأثرون — أصلاً
        # مفروض يكون فيه حضور مسبق لهذولا النوعين.)
        if period == 'بداية الدوام':
            try:
                excuse_date = date.fromisoformat(date_str)
                if _first_checkin_date_between(employee, excuse_date, excuse_date):
                    return Response(
                        {"error": "بصمت حضور بهذا التاريخ بالفعل"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except ValueError:
                pass

        # ── مدة الاستئذان الواحد: أقصى حد 3 ساعات ──
        requested_minutes = _excuse_duration_minutes(time_from, time_to)
        if requested_minutes is None:
            return Response(
                {"error": "تعذّر فهم وقت البداية/النهاية — تأكد إن وقت النهاية بعد وقت البداية"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── الوقت لازم يقع بالكامل ضمن ساعات الدوام الفعلي (7:00 - 2:30) ──
        parsed_from = _parse_time_string(time_from)
        parsed_to = _parse_time_string(time_to)
        if (
            parsed_from is None or parsed_to is None
            or parsed_from < WORK_HOURS_START or parsed_from > WORK_HOURS_END
            or parsed_to < WORK_HOURS_START or parsed_to > WORK_HOURS_END
        ):
            return Response(
                {"error": "الوقت اللي اخترته خارج ساعات الدوام — الاستئذان لازم يكون بين 7:30 و2:30"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if requested_minutes > MAX_EXCUSE_HOURS_PER_DAY * 60:
            return Response(
                {"error": f"أقصى مدة مسموحة للاستئذان الواحد {MAX_EXCUSE_HOURS_PER_DAY} ساعات"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── الحد الشهري (عدد الاستئذانات) ──
        month_excuses = Excuse.objects.filter(
            employee=employee,
            recorded_at__year=today.year,
            recorded_at__month=today.month,
        )
        month_count = month_excuses.count()
        if month_count >= MONTHLY_EXCUSE_LIMIT:
            return Response(
                {"error": f"تم استخدام كل الاستئذانات المسموحة هذا الشهر ({MONTHLY_EXCUSE_LIMIT})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── الحد الشهري (إجمالي الساعات) — دفاعياً بالإضافة لحد العدد+حد المدة ──
        existing_minutes = sum(
            _excuse_duration_minutes(exc.time_from, exc.time_to) or 0 for exc in month_excuses
        )
        if existing_minutes + requested_minutes > MONTHLY_EXCUSE_HOURS_LIMIT:
            remaining = max(MONTHLY_EXCUSE_HOURS_LIMIT - existing_minutes, 0)
            return Response(
                {"error": f"تجاوزت الحد الأقصى لساعات الاستئذان الشهرية ({MONTHLY_EXCUSE_HOURS_LIMIT // 60} ساعة) — المتبقي لك {minutes_to_hm_label(remaining)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        excuse = Excuse.objects.create(
            employee=employee, date=date_str, time_from=time_from, time_to=time_to, period=period,
        )
        ActivityLog.objects.create(
            action='create',
            description=f"{employee.name} سجّل استئذان بتاريخ {date_str} من {time_from} إلى {time_to} ({period})",
            source='excuse',
            ip_address=get_client_ip(request),
        )
        serializer = ExcuseSerializer(excuse)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def _effective_periodic_vacation_days(vacation):
    """
    عدد أيام الإجازة الدورية الفعلي المحسوب على رصيد السنة:
    - طول ما الإجازة شغالة أو مستقبلية (اليوم <= تاريخ نهايتها): كل الأيام
      تُحسب بما فيها الجمعة (خصم كامل مؤقت من الرصيد).
    - بعد ما تنتهي الإجازة فعلياً (اليوم > تاريخ نهايتها): كل يوم جمعة وقع
      بمدى الإجازة يرجع للرصيد تلقائياً (ما يُحسب ضمن الأيام المستهلكة).
    ملاحظة: هذا يأثر بس على حساب الرصيد المتبقي — المدة المعروضة لكل إجازة
    لحالها بالجداول تضل زي ما هي (كل الأيام المحجوزة الفعلية، بدون تعديل).
    """
    total_days = (vacation.date_to - vacation.date_from).days + 1
    if date.today() <= vacation.date_to:
        return total_days
    fridays = sum(
        1 for i in range(total_days)
        if (vacation.date_from + timedelta(days=i)).weekday() == 4  # الجمعة = 4 (الاثنين=0 بمكتبة datetime)
    )
    return total_days - fridays


# GET (كل إجازات موظف معين) — POST (تسجيل إجازة جديدة: دورية أو طارئة)
@api_view(['GET', 'POST'])
def vacation_list(request):
    if request.method == 'GET':
        employee_name = request.query_params.get('employee_name', '').strip()
        vacations = Vacation.objects.select_related('employee').all()
        if employee_name:
            vacations = vacations.filter(employee__name=employee_name)
        serializer = VacationSerializer(vacations, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        employee_id   = request.data.get('employee')
        vacation_type = request.data.get('vacation_type')
        date_from     = request.data.get('date_from')
        date_to       = request.data.get('date_to')

        if not employee_id or vacation_type not in ('periodic', 'emergency') or not date_from:
            return Response({"error": "بيانات غير صحيحة"}, status=status.HTTP_400_BAD_REQUEST)

        if vacation_type == 'periodic' and not date_to:
            return Response({"error": "الرجاء تحديد تاريخ النهاية للإجازة الدورية"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            employee = Employee.objects.get(id=employee_id)
        except Employee.DoesNotExist:
            return Response({"error": "الموظف غير موجود"}, status=status.HTTP_404_NOT_FOUND)

        year = date.today().year

        if vacation_type == 'periodic':
            if date_to < date_from:
                return Response({"error": "تاريخ النهاية يجب أن يكون بعد تاريخ البداية"}, status=status.HTTP_400_BAD_REQUEST)

            # ما يصير تقديم طلب إجازة دورية جديد طول ما فيه طلب سابق لسا "قيد
            # الانتظار" — لازم يصدر قرار (قبول أو رفض) على الطلب الحالي أول
            if Vacation.objects.filter(employee=employee, vacation_type='periodic', status='pending').exists():
                return Response(
                    {"error": "عندك طلب إجازة دورية قيد الانتظار"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ── تحقق من التعارض: هذا التاريخ (أو المدى) يتقاطع مع أي إجازة أخرى مسجلة مسبقاً ──
        # (دورية أو طارئة، غير المرفوضة) — يطبّق على النوعين معاً بما إن الموظف ما يقدر
        # يكون بإجازتين بنفس اليوم مهما كان نوعهم
        new_from = date.fromisoformat(date_from)
        new_to = date.fromisoformat(date_to) if vacation_type == 'periodic' else new_from

        # ما يصير تسجيل إجازة تغطي يوم أصلاً بصمت فيه حضور — الإجازة تبدأ من
        # اليوم اللي بعد آخر بصمة حضور بمداها.
        conflicting_checkin_date = _first_checkin_date_between(employee, new_from, new_to)
        if conflicting_checkin_date:
            return Response(
                {"error": f"بصمت حضور بتاريخ {conflicting_checkin_date} بالفعل — ما يصير تاخذ إجازة بنفس يوم بصمت فيه، لازم تبدأ الإجازة من اليوم اللي بعده"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        overlapping = Vacation.objects.filter(employee=employee).exclude(status='rejected')
        for v in overlapping:
            existing_from = v.date_from
            existing_to = v.date_to if v.date_to else v.date_from
            # تقاطع مدَيين: يتقاطعون إذا بداية أحدهم قبل أو تساوي نهاية الثاني، والعكس
            if new_from <= existing_to and new_to >= existing_from:
                conflict_range = (
                    f"{existing_from}" if existing_from == existing_to else f"{existing_from} إلى {existing_to}"
                )
                return Response(
                    {"error": f"يوجد تعارض مع إجازة {v.get_vacation_type_display()} مسجلة مسبقاً بتاريخ {conflict_range}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if vacation_type == 'periodic':
            # حساب عدد الأيام المستخدمة هذي السنة — المقبولة بس (قيد الانتظار
            # ما يخصم من الرصيد إلا لو صار قبول فعلي)
            existing = Vacation.objects.filter(
                employee=employee, vacation_type='periodic', date_from__year=year, status='accepted',
            )
            used_days = sum(_effective_periodic_vacation_days(v) for v in existing)
            new_days = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days + 1

            if used_days + new_days > PERIODIC_VACATION_YEARLY_LIMIT:
                remaining = max(0, PERIODIC_VACATION_YEARLY_LIMIT - used_days)
                return Response(
                    {"error": f"تجاوزت الحد المسموح للإجازة الدورية هذه السنة (المتبقي: {remaining} يوم من {PERIODIC_VACATION_YEARLY_LIMIT})"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            date_to = None
            # الإجازة الطارئة تُقبل تلقائياً فور التسجيل، فـ'accepted' هنا يشمل عملياً كل الطارئة المسجّلة
            used_count = Vacation.objects.filter(
                employee=employee, vacation_type='emergency', date_from__year=year, status='accepted',
            ).count()

            if used_count >= EMERGENCY_VACATION_YEARLY_LIMIT:
                return Response(
                    {"error": f"تم استخدام كل الإجازات الطارئة المسموحة هذه السنة ({EMERGENCY_VACATION_YEARLY_LIMIT})"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # الإجازة الطارئة تُقبل تلقائياً فور التسجيل (بدون مراجعة أدمن) —
        # الدورية بس هي اللي تدخل قائمة "طلبات الإجازات" بانتظار قرار المسؤول
        initial_status = 'accepted' if vacation_type == 'emergency' else 'pending'

        vacation = Vacation.objects.create(
            employee=employee, vacation_type=vacation_type,
            date_from=date_from, date_to=date_to, status=initial_status,
        )
        auto_note = " (تم القبول تلقائياً)" if vacation_type == 'emergency' else ""
        ActivityLog.objects.create(
            action='create',
            description=f"{employee.name} سجّل إجازة {vacation.get_vacation_type_display()} بتاريخ {date_from}{auto_note}",
            source='vacation',
            ip_address=get_client_ip(request),
        )
        serializer = VacationSerializer(vacation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# PATCH — تحديث حالة إجازة (قبول/رفض/إرجاع لقيد الانتظار)، أو تقليل مدة إجازة
# دورية مقبولة (يرجّع الفرق للرصيد تلقائياً). DELETE — حذف إجازة مقبولة
# بالكامل (يرجّع كل الأيام للرصيد). التعديل والحذف مسموحين بس للإجازات
# المقبولة، ويستخدمهم الأدمن بس.
@api_view(['PATCH', 'DELETE'])
def vacation_detail(request, pk):
    try:
        vacation = Vacation.objects.get(pk=pk)
    except Vacation.DoesNotExist:
        return Response({"error": "الإجازة غير موجودة"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PATCH' and request.data.get('mark_reviewed'):
        # الأدمن فتح تفاصيل الطلب بس لسا ما اتخذ قرار — نعلّم الطلب "تمت
        # مراجعته" عشان الموظف يشوف بمتابعته إن الطلب صار قيد نظر فعلي
        if not vacation.is_opened_by_admin:
            vacation.is_opened_by_admin = True
            vacation.save(update_fields=['is_opened_by_admin'])
        serializer = VacationSerializer(vacation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    if request.method == 'DELETE':
        # الرصيد يُحسب حي من سجلات Vacation الموجودة فعلياً، فحذف السجل كافي
        # لرجوع كل أيامه للرصيد تلقائياً — بدون أي حساب إضافي مطلوب هنا.
        if vacation.status != 'accepted':
            return Response(
                {"error": "الحذف مسموح بس للإجازات المقبولة"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        employee_name = vacation.employee.name
        type_label = vacation.get_vacation_type_display()
        days_count = (vacation.date_to - vacation.date_from).days + 1 if vacation.date_to else 1
        vacation.delete()
        ActivityLog.objects.create(
            action='delete',
            description=f"تم حذف إجازة {employee_name} ({type_label} — {days_count} يوم) بالكامل — رجعت كل الأيام للرصيد",
            source='vacation',
            ip_address=get_client_ip(request),
        )
        return Response({"deleted": True}, status=status.HTTP_200_OK)

    # ── PATCH: تقليل مدة إجازة دورية مقبولة (مو توسيعها) ──
    new_date_from = request.data.get('date_from')
    new_date_to = request.data.get('date_to')
    if new_date_from or new_date_to:
        if vacation.status != 'accepted':
            return Response(
                {"error": "تعديل المدة مسموح بس للإجازات المقبولة"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if vacation.vacation_type != 'periodic':
            return Response(
                {"error": "تعديل المدة متاح بس للإجازة الدورية — الإجازة الطارئة يوم واحد بس، احذفها كاملة لو تبي ترجّع الرصيد"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed_from = datetime.strptime(new_date_from, '%Y-%m-%d').date() if new_date_from else vacation.date_from
            parsed_to = datetime.strptime(new_date_to, '%Y-%m-%d').date() if new_date_to else vacation.date_to
        except (ValueError, TypeError):
            return Response({"error": "صيغة التاريخ غير صحيحة"}, status=status.HTTP_400_BAD_REQUEST)

        if parsed_to < parsed_from:
            return Response({"error": "تاريخ النهاية لازم يكون بعد تاريخ البداية"}, status=status.HTTP_400_BAD_REQUEST)

        # ما يصير توسيع المدة الأصلية، بس تقليلها — لازم المدى الجديد يقع
        # بالكامل داخل المدى الأصلي
        if parsed_from < vacation.date_from or parsed_to > vacation.date_to:
            return Response(
                {"error": "ما يصير توسيع مدة الإجازة، بس تقليلها ضمن المدى الأصلي"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_days = (vacation.date_to - vacation.date_from).days + 1
        new_days = (parsed_to - parsed_from).days + 1

        vacation.date_from = parsed_from
        vacation.date_to = parsed_to
        vacation.save()

        ActivityLog.objects.create(
            action='update',
            description=f"تم تقليل إجازة {vacation.employee.name} من {old_days} يوم إلى {new_days} يوم — رجع {old_days - new_days} يوم للرصيد",
            source='vacation',
            ip_address=get_client_ip(request),
        )
        serializer = VacationSerializer(vacation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ── PATCH: تغيير الحالة (قبول/رفض/إرجاع لقيد الانتظار) ──
    new_status = request.data.get('status')
    valid_statuses = [choice[0] for choice in Vacation.STATUS_CHOICES]
    if new_status not in valid_statuses:
        return Response({"error": "حالة غير صحيحة"}, status=status.HTTP_400_BAD_REQUEST)

    reviewed_by_id = request.data.get('reviewed_by')
    supervisor = None
    # نطلب تحديد المسؤول إلزامياً بس لما القرار يكون قبول أو رفض فعلي (مو رجوع لقيد الانتظار)
    if new_status in ('accepted', 'rejected'):
        if not reviewed_by_id:
            return Response({"error": "الرجاء اختيار اسم المسؤول قبل اتخاذ القرار"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            supervisor = Supervisor.objects.get(id=reviewed_by_id)
        except Supervisor.DoesNotExist:
            return Response({"error": "المسؤول المحدد غير موجود"}, status=status.HTTP_404_NOT_FOUND)

    # الخصم من الرصيد يصير بس عند القبول الفعلي — نتأكد وقت القبول نفسه إن
    # الرصيد يكفي (ممكن يكون تراكم أكثر من طلب قيد الانتظار بنفس الوقت)
    if new_status == 'accepted' and vacation.vacation_type == 'periodic' and vacation.date_to:
        year = vacation.date_from.year
        already_accepted = Vacation.objects.filter(
            employee=vacation.employee, vacation_type='periodic', date_from__year=year, status='accepted',
        ).exclude(pk=vacation.pk)
        used_days = sum(_effective_periodic_vacation_days(v) for v in already_accepted)
        this_request_days = (vacation.date_to - vacation.date_from).days + 1
        if used_days + this_request_days > PERIODIC_VACATION_YEARLY_LIMIT:
            remaining = max(0, PERIODIC_VACATION_YEARLY_LIMIT - used_days)
            return Response(
                {"error": f"قبول هذا الطلب يتجاوز الحد المسموح للإجازة الدورية هذه السنة (المتبقي فعلياً: {remaining} يوم من {PERIODIC_VACATION_YEARLY_LIMIT})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    vacation.status = new_status
    if supervisor:
        vacation.reviewed_by = supervisor
    vacation.save()

    reviewer_note = f" بواسطة {supervisor.name}" if supervisor else ""
    ActivityLog.objects.create(
        action='create',
        description=f"تم تحديث حالة إجازة {vacation.employee.name} ({vacation.get_vacation_type_display()}) إلى {vacation.get_status_display()}{reviewer_note}",
        source='vacation',
        ip_address=get_client_ip(request),
    )

    serializer = VacationSerializer(vacation)
    return Response(serializer.data, status=status.HTTP_200_OK)


# GET — الملف الشامل لموظف عن طريق الرقم المدني: بياناته + كل سجلاته
# (حضور/انصراف، طبيات، استئذانات، إجازات) دفعة وحدة
# مثال: /api/attendance/employee-profile/?civil_id=303011201404
@api_view(['GET'])
def employee_full_profile(request):
    civil_id     = request.query_params.get('civil_id', '').strip()
    name         = request.query_params.get('name', '').strip()
    phone_number = request.query_params.get('phone_number', '').strip()

    if not civil_id and not name and not phone_number:
        return Response(
            {"error": "الرجاء إرسال معيار بحث واحد على الأقل: civil_id أو name أو phone_number"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    employees = Employee.objects.all()
    if civil_id:
        employees = employees.filter(civil_id__icontains=civil_id)
    if name:
        employees = employees.filter(name__icontains=name)
    if phone_number:
        employees = employees.filter(phone_number__icontains=phone_number)

    if not employees.exists():
        return Response({"error": "لا يوجد موظف مطابق لبيانات البحث"}, status=status.HTTP_404_NOT_FOUND)

    # نرجّع قائمة (Array) دايماً — حتى لو نتيجة واحدة بس — عشان شكل الرد يضل
    # ثابت بغض النظر عن عدد المطابقات (تسهيلاً على أي كود يقرأ الرد لاحقاً)
    results = []
    for employee in employees:
        attendance_records = AttendanceRecord.objects.filter(employee=employee)
        sick_leaves        = SickLeave.objects.filter(employee=employee)
        excuses            = Excuse.objects.filter(employee=employee)
        vacations          = Vacation.objects.filter(employee=employee)

        results.append({
            "employee": EmployeeSerializer(employee).data,
            "attendance_records": AttendanceRecordSerializer(attendance_records, many=True).data,
            "sick_leaves": SickLeaveSerializer(sick_leaves, many=True).data,
            "excuses": ExcuseSerializer(excuses, many=True).data,
            "vacations": VacationSerializer(vacations, many=True).data,
        })
        ActivityLog.objects.create(
            action='view',
            description=f"تم عرض الملف الشامل (كل السجلات) للموظف {employee.name}",
            source='employee',
            ip_address=get_client_ip(request),
        )

    return Response(results, status=status.HTTP_200_OK)


# GET — تقارير موحّدة: إجازات / طبيات / استئذانات / حضور وانصراف — بمعيار "type" واحد
# يحدد نوع السجل، مع فلترة اختيارية بمدى تاريخ (from/to) — وللإجازات بس، فلترة
# إضافية بنوع الإجازة (vecation_type: دورية/طارئة)، وللحضور والانصراف بس، فلترة
# إضافية بنوع العملية (action: حضور/انصراف).
#
# أمثلة استخدام (نفس صيغة DD-MM-YYYY للتواريخ):
#   /api/attendance/reports/?type=vacations&vecation_type=دورية&from=25-04-2025&to=25-05-2025
#   /api/attendance/reports/?type=sick_leaves&from=20-04-2025&to=25-05-2025
#   /api/attendance/reports/?type=excuses&from=20-04-2025&to=25-05-2025
#   /api/attendance/reports/?type=attendance_records&action=حضور&from=20-04-2025&to=25-05-2025
VACATION_TYPE_LABEL_TO_CODE = {
    'دورية': 'periodic',
    'طارئة': 'emergency',
    'periodic': 'periodic',
    'emergency': 'emergency',
}


def _parse_ddmmyyyy(value):
    try:
        return datetime.strptime(value, '%d-%m-%Y').date()
    except ValueError:
        return None


@api_view(['GET'])
def reports(request):
    report_type   = request.query_params.get('type', '').strip()
    date_from_str = request.query_params.get('from', '').strip()
    date_to_str   = request.query_params.get('to', '').strip()

    parsed_from = None
    parsed_to = None

    if date_from_str:
        parsed_from = _parse_ddmmyyyy(date_from_str)
        if not parsed_from:
            return Response({"error": "صيغة تاريخ from غير صحيحة، استخدم DD-MM-YYYY (مثال: 25-04-2025)"}, status=status.HTTP_400_BAD_REQUEST)

    if date_to_str:
        parsed_to = _parse_ddmmyyyy(date_to_str)
        if not parsed_to:
            return Response({"error": "صيغة تاريخ to غير صحيحة، استخدم DD-MM-YYYY (مثال: 25-05-2025)"}, status=status.HTTP_400_BAD_REQUEST)

    if report_type == 'vacations':
        vacation_type_param = request.query_params.get('vecation_type', '').strip()
        queryset = Vacation.objects.select_related('employee').all()

        if vacation_type_param:
            code = VACATION_TYPE_LABEL_TO_CODE.get(vacation_type_param)
            if not code:
                return Response({"error": "نوع الإجازة (vecation_type) يجب أن يكون 'دورية' أو 'طارئة'"}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(vacation_type=code)

        if parsed_from:
            queryset = queryset.filter(date_from__gte=parsed_from)
        if parsed_to:
            queryset = queryset.filter(date_from__lte=parsed_to)

        queryset = queryset.order_by('date_from')
        results_data = VacationSerializer(queryset, many=True).data
        source_label = 'vacation'

    elif report_type == 'sick_leaves':
        queryset = SickLeave.objects.select_related('employee').all()

        if parsed_from:
            queryset = queryset.filter(date__gte=parsed_from)
        if parsed_to:
            queryset = queryset.filter(date__lte=parsed_to)

        queryset = queryset.order_by('date')
        results_data = SickLeaveSerializer(queryset, many=True).data
        source_label = 'sick_leave'

    elif report_type == 'excuses':
        queryset = Excuse.objects.select_related('employee').all()

        if parsed_from:
            queryset = queryset.filter(date__gte=parsed_from)
        if parsed_to:
            queryset = queryset.filter(date__lte=parsed_to)

        queryset = queryset.order_by('date')
        results_data = ExcuseSerializer(queryset, many=True).data
        source_label = 'excuse'

    elif report_type == 'attendance_records':
        action_param = request.query_params.get('action', '').strip()
        ACTION_LABEL_TO_CODE = {
            'حضور':     'check_in',
            'انصراف':   'check_out',
            'check_in':  'check_in',
            'check_out': 'check_out',
        }

        queryset = AttendanceRecord.objects.select_related('employee').all()

        if action_param:
            action_code = ACTION_LABEL_TO_CODE.get(action_param)
            if not action_code:
                return Response({"error": "action يجب أن يكون 'حضور' أو 'انصراف'"}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(action=action_code)

        # نفلتر بمدى التاريخ اعتماداً على توقيت الكويت المحسوب يدوياً (نفس منطق باقي
        # نظام الحضور) بدل فلتر __date بقاعدة البيانات، تفادياً لأي فرق ساعات.
        if parsed_from or parsed_to:
            ids_in_range = [
                rec_id for rec_id, ts in queryset.values_list('id', 'timestamp')
                if (not parsed_from or to_local_time(ts).date() >= parsed_from)
                and (not parsed_to or to_local_time(ts).date() <= parsed_to)
            ]
            queryset = queryset.filter(id__in=ids_in_range)

        queryset = queryset.order_by('-timestamp')
        results_data = AttendanceRecordSerializer(queryset, many=True).data
        source_label = 'attendance'

    else:
        return Response(
            {"error": "الرجاء تحديد type بقيمة صحيحة: vacations أو sick_leaves أو excuses أو attendance_records"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    count = queryset.count()

    REPORT_TYPE_ARABIC_LABEL = {
        'vacations':          'إجازات',
        'sick_leaves':        'طبيات',
        'excuses':            'استئذانات',
        'attendance_records': 'حضور وانصراف',
    }
    report_type_label = REPORT_TYPE_ARABIC_LABEL.get(report_type, report_type)

    ActivityLog.objects.create(
        action='view',
        description=(
            f"تم توليد تقرير {report_type_label} من {date_from_str or 'البداية'} "
            f"إلى {date_to_str or 'الآن'} — {count} نتيجة"
        ),
        source=source_label,
        ip_address=get_client_ip(request),
    )

    return Response({
        "type": report_type,
        "from": date_from_str or None,
        "to": date_to_str or None,
        "count": count,
        "results": results_data,
    }, status=status.HTTP_200_OK)