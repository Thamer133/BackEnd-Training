from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord
from .serializers import (
    EmployeeSerializer,
    SickLeaveSerializer,
    ActivityLogSerializer,
    AttendanceRecordSerializer,
)

SICK_LEAVE_LIMIT = 15
ATTENDANCE_WINDOW = 30  # آخر 30 عملية بس تنعرض


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
    ActivityLog.objects.create(action='delete', description=description)
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

        log = ActivityLog.objects.create(action=action, description=description)
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
        )
        serializer = AttendanceRecordSerializer(record)
        return Response(serializer.data, status=status.HTTP_201_CREATED)