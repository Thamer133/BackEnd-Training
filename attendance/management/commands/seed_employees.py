from django.core.management.base import BaseCommand
from attendance.models import Employee


EMPLOYEE_NAMES = [
    "ثامر فريد",
    "يعقوب القلاف",
    "براك السميط",
    "فيصل",
    "محمد المهندي",
    "عثمان علي",
    "احمد",
    "علي جاسم",
]


class Command(BaseCommand):
    help = "يضيف أسماء موظفين وهمية لتطبيق attendance (مختلفة عن أسماء training)"

    def handle(self, *args, **options):
        created_count = 0
        for name in EMPLOYEE_NAMES:
            obj, created = Employee.objects.get_or_create(name=name)
            if created:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"تم إضافة {created_count} موظف جديد.")
        )