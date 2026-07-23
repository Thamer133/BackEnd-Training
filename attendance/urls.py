from django.urls import path
from . import views

urlpatterns = [
    path('employees/', views.employee_list),
    path('employees/<int:pk>/', views.employee_detail),
    path('supervisors/', views.supervisor_list),
    path('supervisors/<int:pk>/', views.supervisor_detail),
    path('sick-leaves/', views.sick_leave_list),
    path('sick-leaves/<int:pk>/', views.sick_leave_detail),
    path('activity-logs/', views.activity_log_list),
    path('attendance-records/', views.attendance_record_list),
    path('excuses/', views.excuse_list),
    path('vacations/', views.vacation_list),
    path('vacations/<int:pk>/', views.vacation_detail),
    path('employee-profile/', views.employee_full_profile),
    path('reports/', views.reports),
]