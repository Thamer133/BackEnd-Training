from django.contrib import admin
from django.utils.html import format_html
from .models import Employee, SickLeave, ActivityLog, AttendanceRecord, Excuse, Vacation, Supervisor
from .views import calculate_late_minutes_for_employee, to_local_time


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['name', 'civil_id', 'phone_number', 'job_title', 'user', 'photo_link']
    list_filter = ['user']
    search_fields = ['name', 'civil_id', 'phone_number', 'job_title', 'user__username']

    def photo_link(self, obj):
        if obj.photo:
            return format_html('<a href="{}" target="_blank">فتح الصورة</a>', obj.photo.url)
        return "—"
    photo_link.short_description = "الصورة الشخصية"


@admin.register(Supervisor)
class SupervisorAdmin(admin.ModelAdmin):
    list_display = ['name', 'civil_id', 'phone_number', 'job_title', 'user', 'photo_link']
    list_filter = ['user']
    search_fields = ['name', 'civil_id', 'phone_number', 'user__username']

    def photo_link(self, obj):
        if obj.photo:
            return format_html('<a href="{}" target="_blank">فتح الصورة</a>', obj.photo.url)
        return "—"
    photo_link.short_description = "الصورة الشخصية"


@admin.register(SickLeave)
class SickLeaveAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'recorded_at']
    list_filter = ['employee']
    search_fields = ['employee__name']


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'description', 'table', 'ip_address', 'created_at']
    list_filter = ['action', 'source', 'user']
    search_fields = ['description', 'ip_address', 'user__username']

    # سجل الأنشطة سجل تدقيقي — ما يصير حذفه نهائياً، لا فردياً ولا جماعياً
    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def table(self, obj):
        return obj.get_source_display()
    table.short_description = "table"


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['employee', 'action', 'timestamp', 'late_minutes']
    list_filter = ['employee', 'action']
    search_fields = ['employee__name']
    # timestamp صار حقل عادي قابل للتعديل (مو auto_now_add) — يعني يظهر بفورم
    # الإضافة/التعديل بلوحة الأدمن وتقدر تختار الوقت يدوياً من هني بس.

    def save_model(self, request, obj, form, change):
        # نعيد احتساب دقايق التأخير تلقائياً كل مرة يتغيّر فيها وقت الحضور/الانصراف
        # يدوياً من الأدمن، عشان الإحصائيات تضل صحيحة ومتوافقة مع الوقت الجديد.
        local_dt = to_local_time(obj.timestamp)
        obj.late_minutes = calculate_late_minutes_for_employee(obj.employee, obj.action, local_dt)
        super().save_model(request, obj, form, change)


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