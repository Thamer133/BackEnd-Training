from django.contrib import admin
from .models import Employee, SickLeave, ActivityLog


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