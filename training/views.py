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


# CHECK CIVIL ID / UNIFIED NUMBER
@api_view(['POST'])
def check_id(request):
    number = request.data.get('number', '').strip()

    if not number.isdigit():
        return Response({"error": "الرقم يجب أن يحتوي على أرقام فقط"}, status=status.HTTP_400_BAD_REQUEST)

    length = len(number)

    if length == 12:
        return Response({"is_kuwaiti": True, "message": "لا توجد بيانات"}, status=status.HTTP_200_OK)

    elif length == 8:
        try:
            person = CivilRecord.objects.get(unified_number=number)
            serializer = CivilRecordSerializer(person)
            return Response({"is_kuwaiti": False, "data": serializer.data}, status=status.HTTP_200_OK)
        except CivilRecord.DoesNotExist:
            return Response({"is_kuwaiti": False, "message": "لا توجد بيانات لهذا الرقم"}, status=status.HTTP_404_NOT_FOUND)

    else:
        return Response({"error": "الرقم يجب أن يكون 12 رقم (مدني) أو 8 أرقام (موحد)"}, status=status.HTTP_400_BAD_REQUEST)