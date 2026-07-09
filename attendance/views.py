from datetime import date
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse
from .serializers import (
    EmployeeSerializer,
    SickLeaveSerializer,
    ActivityLogSerializer,
    AttendanceRecordSerializer,
    ExcuseSerializer,
)

SICK_LEAVE_LIMIT = 15
ATTENDANCE_WINDOW = 30
MONTHLY_EXCUSE_LIMIT = 4


@api_view(['GET'])
def employee_list(request):
    employees = Employee.objects.all().order_by('name')
    serializer = EmployeeSerializer(employees, many=True)
    return Response(serializer.data)


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
        )
        serializer = SickLeaveSerializer(leave)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
def sick_leave_detail(request, pk):
    try:
        leave = SickLeave.objects.get(pk=pk)
    except SickLeave.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    description = f"حذف طبية لـ {leave.employee.name} بتاريخ {leave.date}"
    leave.delete()
    ActivityLog.objects.create(action='delete', description=description)
    return Response(status=status.HTTP_204_NO_CONTENT)


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

        log = ActivityLog.objects.create(action=action, description=description)
        serializer = ActivityLogSerializer(log)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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
        )
        serializer = AttendanceRecordSerializer(record)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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

        if Excuse.objects.filter(employee=employee, recorded_at__date=today).exists():
            return Response(
                {"error": "تم تسجيل استئذان اليوم، ولا يمكن تسجيل استئذان آخر إلا بعد مرور يوم كامل"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        )
        serializer = ExcuseSerializer(excuse)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
