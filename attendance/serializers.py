from rest_framework import serializers
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'name']


class SickLeaveSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.name', read_only=True)

    class Meta:
        model = SickLeave
        fields = ['id', 'employee', 'employee_name', 'date', 'recorded_at']


class ActivityLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = ActivityLog
        fields = ['id', 'action', 'action_display', 'description', 'created_at']


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