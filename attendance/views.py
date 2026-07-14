from datetime import date
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse, Vacation
from .serializers import (
    EmployeeSerializer,
    SickLeaveSerializer,
    ActivityLogSerializer,
    AttendanceRecordSerializer,
    ExcuseSerializer,
    VacationSerializer,
)

SICK_LEAVE_LIMIT = 15
ATTENDANCE_WINDOW = 30  # آخر 30 عملية بس تنعرض
MONTHLY_EXCUSE_LIMIT = 4
PERIODIC_VACATION_YEARLY_LIMIT  = 35
EMERGENCY_VACATION_YEARLY_LIMIT = 4


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


# GET ALL EMPLOYEES
@api_view(['GET'])
def employee_list(request):
    employees = Employee.objects.all().order_by('name')
    serializer = EmployeeSerializer(employees, many=True)
    return Response(serializer.data)


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

        leave = SickLeave.objects.create(employee=employee, date=date_str)
        ActivityLog.objects.create(
            action='create',
            description=f"تسجيل طبية لـ {employee.name} بتاريخ {date_str}",
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
    ActivityLog.objects.create(action='delete', description=description, ip_address=get_client_ip(request))
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

        if not description:
            return Response({"error": "الوصف مطلوب"}, status=status.HTTP_400_BAD_REQUEST)

        log = ActivityLog.objects.create(action=action, description=description, ip_address=get_client_ip(request))
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

        record = AttendanceRecord.objects.create(employee=employee, action=action)
        ActivityLog.objects.create(
            action='create',
            description=f"{employee.name} سجّل {record.get_action_display()} بتاريخ {record.timestamp}",
            ip_address=get_client_ip(request),
        )
        serializer = AttendanceRecordSerializer(record)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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

        # ── الحد الشهري ──
        month_count = Excuse.objects.filter(
            employee=employee,
            recorded_at__year=today.year,
            recorded_at__month=today.month,
        ).count()
        if month_count >= MONTHLY_EXCUSE_LIMIT:
            return Response(
                {"error": f"تم استخدام كل الاستئذانات المسموحة هذا الشهر ({MONTHLY_EXCUSE_LIMIT})"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        excuse = Excuse.objects.create(
            employee=employee, date=date_str, time_from=time_from, time_to=time_to, period=period,
        )
        ActivityLog.objects.create(
            action='create',
            description=f"{employee.name} سجّل استئذان بتاريخ {date_str} من {time_from} إلى {time_to} ({period})",
            ip_address=get_client_ip(request),
        )
        serializer = ExcuseSerializer(excuse)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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

        # ── تحقق من التعارض: هذا التاريخ (أو المدى) يتقاطع مع أي إجازة أخرى مسجلة مسبقاً ──
        # (دورية أو طارئة، غير المرفوضة) — يطبّق على النوعين معاً بما إن الموظف ما يقدر
        # يكون بإجازتين بنفس اليوم مهما كان نوعهم
        new_from = date.fromisoformat(date_from)
        new_to = date.fromisoformat(date_to) if vacation_type == 'periodic' else new_from

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
            # حساب عدد الأيام المستخدمة هذي السنة من الإجازات الدورية (غير المرفوضة)
            existing = Vacation.objects.filter(
                employee=employee, vacation_type='periodic', date_from__year=year,
            ).exclude(status='rejected')
            used_days = sum((v.date_to - v.date_from).days + 1 for v in existing)
            new_days = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days + 1

            if used_days + new_days > PERIODIC_VACATION_YEARLY_LIMIT:
                remaining = max(0, PERIODIC_VACATION_YEARLY_LIMIT - used_days)
                return Response(
                    {"error": f"تجاوزت الحد المسموح للإجازة الدورية هذه السنة (المتبقي: {remaining} يوم من {PERIODIC_VACATION_YEARLY_LIMIT})"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            date_to = None
            used_count = Vacation.objects.filter(
                employee=employee, vacation_type='emergency', date_from__year=year,
            ).exclude(status='rejected').count()

            if used_count >= EMERGENCY_VACATION_YEARLY_LIMIT:
                return Response(
                    {"error": f"تم استخدام كل الإجازات الطارئة المسموحة هذه السنة ({EMERGENCY_VACATION_YEARLY_LIMIT})"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        vacation = Vacation.objects.create(
            employee=employee, vacation_type=vacation_type,
            date_from=date_from, date_to=date_to, status='pending',
        )
        ActivityLog.objects.create(
            action='create',
            description=f"{employee.name} سجّل إجازة {vacation.get_vacation_type_display()} بتاريخ {date_from}",
            ip_address=get_client_ip(request),
        )
        serializer = VacationSerializer(vacation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)