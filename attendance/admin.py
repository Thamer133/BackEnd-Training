from django.contrib import admin
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']


@admin.register(SickLeave)
class SickLeaveAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'recorded_at']
    list_filter = ['employee']
    search_fields = ['employee__name']


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'description', 'created_at']
    list_filter = ['action']
    search_fields = ['description']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['employee', 'action', 'timestamp']
    list_filter = ['employee', 'action']
    search_fields = ['employee__name']


@admin.register(Excuse)
class ExcuseAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'time_from', 'time_to', 'period', 'recorded_at']
    list_filter = ['employee', 'period']
    search_fields = ['employee__name']