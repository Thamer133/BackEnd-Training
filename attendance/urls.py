from django.urls import path
from . import views

urlpatterns = [
    path('employees/', views.employee_list),
    path('sick-leaves/', views.sick_leave_list),
    path('sick-leaves/<int:pk>/', views.sick_leave_detail),
    path('activity-logs/', views.activity_log_list),
    path('attendance-records/', views.attendance_record_list),
    path('excuses/', views.excuse_list),
]
