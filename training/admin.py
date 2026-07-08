from django.contrib import admin
from .models import CivilRecord, Person


@admin.register(CivilRecord)
class CivilRecordAdmin(admin.ModelAdmin):
    list_display = ['name', 'civil_id', 'unified_number', 'nationality', 'gender', 'age']
    search_fields = ['name', 'civil_id', 'unified_number']
    list_filter = ['gender', 'nationality']


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ['name', 'civil_id', 'nationality']