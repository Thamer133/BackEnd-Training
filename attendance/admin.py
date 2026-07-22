from django.contrib import admin
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse, Vacation, Supervisor


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['name', 'civil_id', 'phone_number']
    search_fields = ['name', 'civil_id', 'phone_number']


@admin.register(Supervisor)
class SupervisorAdmin(admin.ModelAdmin):
    list_display = ['name', 'civil_id', 'phone_number']
    search_fields = ['name', 'civil_id', 'phone_number']


@admin.register(SickLeave)
class SickLeaveAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'recorded_at']
    list_filter = ['employee']
    search_fields = ['employee__name']


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'description', 'table', 'ip_address', 'created_at']
    list_filter = ['action', 'source']
    search_fields = ['description', 'ip_address']

    def table(self, obj):
        return obj.get_source_display()
    table.short_description = "table"


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


@admin.register(Vacation)
class VacationAdmin(admin.ModelAdmin):
    list_display = ['employee', 'vacation_type', 'date_from', 'date_to', 'status', 'reviewed_by', 'recorded_at']
    list_filter = ['employee', 'vacation_type', 'status']
    search_fields = ['employee__name']