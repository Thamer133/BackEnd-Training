from django.db import models


class Employee(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class SickLeave(models.Model):
    employee    = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='sick_leaves')
    date        = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)  # وقت الحفظ الفعلي بالسيرفر

    class Meta:
        unique_together = ('employee', 'date')  # يمنع نفس التاريخ مرتين لنفس الموظف
        ordering = ['date']

    def __str__(self):
        return f"{self.employee.name} - {self.date}"


class ActivityLog(models.Model):
    ACTION_CHOICES = [
        ('create', 'إضافة'),
        ('delete', 'حذف'),
    ]
    action      = models.CharField(max_length=10, choices=ACTION_CHOICES)
    description = models.CharField(max_length=255)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_action_display()} — {self.description} ({self.created_at})"


class AttendanceRecord(models.Model):
    ACTION_CHOICES = [
        ('check_in', 'حضور'),
        ('check_out', 'انصراف'),
    ]
    employee  = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records')
    action    = models.CharField(max_length=10, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.employee.name} - {self.get_action_display()} - {self.timestamp}"


class Excuse(models.Model):
    employee    = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='excuses')
    date        = models.DateField()          # تاريخ الاستئذان المطلوب
    time_from   = models.CharField(max_length=20)   # نص وقت البداية (مثل "10:30 صباحا")
    time_to     = models.CharField(max_length=20)   # نص وقت النهاية
    period      = models.CharField(max_length=50)   # بداية الدوام / أثناء الدوام / نهاية الدوام
    recorded_at = models.DateTimeField(auto_now_add=True)  # وقت الحفظ الفعلي بالسيرفر

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.employee.name} - {self.date} ({self.period})"