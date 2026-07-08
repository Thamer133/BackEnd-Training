from datetime import date
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import Person, CivilRecord
from .serializers import PersonSerializer, CivilRecordSerializer

# GET ALL - POST
@api_view(['GET', 'POST'])
def person_list(request):
    if request.method == 'GET':
        persons = Person.objects.all()
        serializer = PersonSerializer(persons, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = PersonSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# GET ONE - PUT - PATCH - DELETE
@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def person_detail(request, pk):
    try:
        person = Person.objects.get(pk=pk)
    except Person.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = PersonSerializer(person)
        return Response(serializer.data)
    elif request.method == 'PUT':
        serializer = PersonSerializer(person, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    elif request.method == 'PATCH':
        serializer = PersonSerializer(person, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    elif request.method == 'DELETE':
        person.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# GET ALL CIVIL RECORDS
@api_view(['GET'])
def civil_record_list(request):
    records = CivilRecord.objects.all()
    serializer = CivilRecordSerializer(records, many=True)
    return Response(serializer.data)


# CHECK CIVIL ID / UNIFIED NUMBER
@api_view(['POST'])
def check_id(request):
    number = request.data.get('number', '').strip()

    if not number.isdigit():
        return Response({"error": "الرقم يجب أن يحتوي على أرقام فقط"}, status=status.HTTP_400_BAD_REQUEST)

    length = len(number)

    if length == 12:
        try:
            person = CivilRecord.objects.get(civil_id=number)
            return Response({
                "found": True,
                "has_unified": bool(person.unified_number),
                "data": {
                    "id": person.id,
                    "name": person.name,
                    "age": person.age,
                    "civil_id": person.civil_id,
                    "unified_number": person.unified_number or "",
                    "nationality": person.nationality or "",
                    "gender": person.get_gender_display() or "",
                }
            }, status=status.HTTP_200_OK)
        except CivilRecord.DoesNotExist:
            return Response({"found": False, "message": "لا توجد بيانات"}, status=status.HTTP_200_OK)

    elif length == 9:
        try:
            person = CivilRecord.objects.get(unified_number=number)
            return Response({
                "found": True,
                "has_unified": True,
                "data": {
                    "id": person.id,
                    "name": person.name,
                    "age": person.age,
                    "civil_id": person.civil_id or "",
                    "unified_number": person.unified_number,
                    "nationality": person.nationality or "",
                    "gender": person.get_gender_display() or "",
                }
            }, status=status.HTTP_200_OK)
        except CivilRecord.DoesNotExist:
            return Response({"found": False, "message": "لا توجد بيانات لهذا الرقم"}, status=status.HTTP_404_NOT_FOUND)

    else:
        return Response({"error": "الرقم يجب أن يكون 12 رقم (مدني) أو 9 أرقام (موحد)"}, status=status.HTTP_400_BAD_REQUEST)


# ASSIGN UNIFIED NUMBER
@api_view(['POST'])
def assign_unified(request):
    person_id      = request.data.get('person_id')
    unified_number = request.data.get('unified_number', '').strip()

    if not unified_number.isdigit() or len(unified_number) != 9:
        return Response({"error": "الرقم الموحد يجب أن يكون 9 أرقام"}, status=status.HTTP_400_BAD_REQUEST)

    if CivilRecord.objects.filter(unified_number=unified_number).exists():
        return Response({"error": "هذا الرقم الموحد مستخدم مسبقاً، الرجاء إدخال رقم آخر"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        person = CivilRecord.objects.get(id=person_id)
    except CivilRecord.DoesNotExist:
        return Response({"error": "الشخص غير موجود"}, status=status.HTTP_404_NOT_FOUND)

    person.unified_number = unified_number
    person.save()

    return Response({"success": True, "message": "تم حفظ الرقم الموحد بنجاح", "unified_number": unified_number}, status=status.HTTP_200_OK)


# FILTER RECORDS — بالجنسية / الجنس / مدى العمر (محسوب من تاريخين)
@api_view(['POST'])
def filter_records(request):
    nationality   = request.data.get('nationality', '').strip()
    gender        = request.data.get('gender', '').strip()          # 'M' أو 'F' أو 'ذكر'/'أنثى' أو فاضي = الكل
    birth_from    = request.data.get('birth_date_from', '').strip() # YYYY-MM-DD (أقدم تاريخ ميلاد = أكبر عمر)
    birth_to      = request.data.get('birth_date_to', '').strip()   # YYYY-MM-DD (أحدث تاريخ ميلاد = أصغر عمر)

    records = CivilRecord.objects.all()

    # ── فلترة الجنسية ──
    if nationality and nationality != 'عرض الكل':
        records = records.filter(nationality=nationality)

    # ── فلترة الجنس ──
    if gender and gender != 'عرض الكل':
        gender_map = {'ذكر': 'M', 'أنثى': 'F', 'M': 'M', 'F': 'F'}
        gender_code = gender_map.get(gender)
        if gender_code:
            records = records.filter(gender=gender_code)

    # ── فلترة العمر (محسوبة من التاريخين) ──
    today = date.today()

    def age_from_date_str(date_str):
        try:
            y, m, d = map(int, date_str.split('-'))
            born = date(y, m, d)
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            return age
        except (ValueError, AttributeError):
            return None

    min_age = None
    max_age = None

    if birth_to:
        # تاريخ ميلاد أحدث → عمر أصغر → هذا هو الحد الأدنى للعمر
        min_age = age_from_date_str(birth_to)
    if birth_from:
        # تاريخ ميلاد أقدم → عمر أكبر → هذا هو الحد الأعلى للعمر
        max_age = age_from_date_str(birth_from)

    if min_age is not None:
        records = records.filter(age__gte=min_age)
    if max_age is not None:
        records = records.filter(age__lte=max_age)

    serializer = CivilRecordSerializer(records, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)