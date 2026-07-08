from rest_framework import serializers
from .models import Person, CivilRecord


class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ['id', 'name', 'civil_id', 'nationality']


class CivilRecordSerializer(serializers.ModelSerializer):
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)

    class Meta:
        model = CivilRecord
        fields = ['id', 'civil_id', 'unified_number', 'name', 'age', 'nationality', 'gender', 'gender_display']