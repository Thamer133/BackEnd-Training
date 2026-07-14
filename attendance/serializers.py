from rest_framework import serializers
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse, Vacation


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'name', 'civil_id']


class SickLeaveSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.name', read_only=True)

    class Meta:
        model = SickLeave
        fields = ['id', 'employee', 'employee_name', 'date', 'recorded_at']


class ActivityLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = ActivityLog
        fields = ['id', 'action', 'action_display', 'description', 'ip_address', 'created_at']


class AttendanceRecordSerializer(serializers.ModelSerializer):
    employee_name  = serializers.CharField(source='employee.name', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = ['id', 'employee', 'employee_name', 'action', 'action_display', 'timestamp']


class ExcuseSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.name', read_only=True)

    class Meta:
        model = Excuse
        fields = ['id', 'employee', 'employee_name', 'date', 'time_from', 'time_to', 'period', 'recorded_at']


class VacationSerializer(serializers.ModelSerializer):
    employee_name         = serializers.CharField(source='employee.name', read_only=True)
    vacation_type_display = serializers.CharField(source='get_vacation_type_display', read_only=True)
    status_display        = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Vacation
        fields = [
            'id', 'employee', 'employee_name', 'vacation_type', 'vacation_type_display',
            'date_from', 'date_to', 'status', 'status_display', 'recorded_at',
        ]