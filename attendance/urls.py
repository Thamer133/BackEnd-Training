# ضعه بالمسار: attendance/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('employees/', views.employee_list),
]