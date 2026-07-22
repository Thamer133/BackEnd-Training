from django.db import models
from django.core.validators import RegexValidator

# تحقق: رقم التلفون لازم يكون 8 أرقام بالضبط (بدون مسافات أو رموز)
phone_number_validator = RegexValidator(
    regex=r'^\d{8}$',
    message='رقم التلفون يجب أن يتكون من 8 أرقام بالضبط',
)

# تحقق: الرقم المدني لازم يكون 12 رقم بالضبط (بدون مسافات أو رموز)
civil_id_validator = RegexValidator(
    regex=r'^\d{12}$',
    message='الرقم المدني يجب أن يتكون من 12 رقم بالضبط',
)


class Employee(models.Model):
    name         = models.CharField(max_length=255)
    civil_id     = models.CharField(max_length=12, validators=[civil_id_validator], null=True, blank=True)  # الرقم المدني للموظف
    phone_number = models.CharField(max_length=8, validators=[phone_number_validator], null=True, blank=True)  # رقم تلفون الموظف (8 أرقام)

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
        ('update', 'تعديل'),
        ('delete', 'حذف'),
        ('view',   'عرض'),
    ]
    # القسم/الجدول اللي صار فيه التعديل — يظهر بعمود منفصل بالأدمن جنب IP
    SOURCE_CHOICES = [
        ('attendance', 'حضور و انصراف'),
        ('excuse',     'الاستئذانات'),
        ('sick_leave', 'الطبيات'),
        ('vacation',   'الإجازات'),
        ('employee',   'الموظفين'),
        ('supervisor', 'المسؤولين'),
        ('other',      'أخرى'),
    ]
    action      = models.CharField(max_length=10, choices=ACTION_CHOICES)
    description = models.CharField(max_length=255)
    source      = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='other')
    ip_address  = models.GenericIPAddressField(null=True, blank=True)  # عنوان IP للجهاز اللي سوّى العملية
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


class Supervisor(models.Model):
    """
    جدول المسؤولين (اللي يوافقون/يرفضون طلبات الإجازات) — نفس هيكل Employee
    تقريباً (اسم + رقم مدني + رقم تلفون)، بس منفصل تماماً. يُعبّى يدوياً من لوحة الأدمن.
    """
    name         = models.CharField(max_length=255)
    civil_id     = models.CharField(max_length=12, validators=[civil_id_validator], null=True, blank=True)
    phone_number = models.CharField(max_length=8, validators=[phone_number_validator], null=True, blank=True)

    def __str__(self):
        return self.name


class Vacation(models.Model):
    TYPE_CHOICES = [
        ('periodic', 'دورية'),
        ('emergency', 'طارئة'),
    ]
    STATUS_CHOICES = [
        ('pending',  'قيد الانتظار'),
        ('accepted', 'مقبولة'),
        ('rejected', 'مرفوضة'),
    ]

    employee      = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='vacations')
    vacation_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    date_from     = models.DateField()                        # دورية: تاريخ البداية / طارئة: نفس تاريخ اليوم
    date_to       = models.DateField(null=True, blank=True)   # دورية بس — الطارئة يوم واحد فبدون تاريخ نهاية
    status        = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    # المسؤول اللي وافق/رفض الطلب — يتحدد لحظة اتخاذ القرار (فاضي لحد يصير قرار)
    reviewed_by   = models.ForeignKey(Supervisor, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_vacations')
    recorded_at   = models.DateTimeField(auto_now_add=True)   # وقت الحفظ الفعلي بالسيرفر

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.employee.name} - {self.get_vacation_type_display()} - {self.date_from}"