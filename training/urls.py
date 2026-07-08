from django.urls import path
from . import views

urlpatterns = [
    path('persons/', views.person_list),
    path('persons/<int:pk>/', views.person_detail),
    path('civil-records/', views.civil_record_list),
    path('check-id/', views.check_id),
    path('assign-unified/', views.assign_unified),
    path('filter-records/', views.filter_records),
]