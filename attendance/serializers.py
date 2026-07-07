from rest_framework import serializers
from .models import Employee, SickLeave, ActivityLog


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