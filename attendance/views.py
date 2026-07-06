from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Employee
from .serializers import EmployeeSerializer


@api_view(['GET'])
def employee_list(request):
    employees = Employee.objects.all().order_by('name')
    serializer = EmployeeSerializer(employees, many=True)
    return Response(serializer.data)
