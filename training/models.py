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