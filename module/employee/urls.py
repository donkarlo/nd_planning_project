from django.urls import include, path

from module.employee.module.time_tracking.views.global_statistics_view import (
    GlobalStatisticsView,
)
from module.employee.views.employee_collection_view import EmployeeCollectionView
from module.employee.views.employee_detail_view import EmployeeDetailView

urlpatterns = [
    path(
        "",
        EmployeeCollectionView.as_view(),
    ),


    path(
        "<int:employee_id>/",
        EmployeeDetailView.as_view(),
    ),

    # this one doesnt need role_name
    path(
        "time-tracking/statistics/",
        GlobalStatisticsView.as_view(),
    ),

    # including the urls related to work shifts and time tracking
    path(
        "<int:employee_id>/time-tracking/",
        include("module.employee.module.time_tracking.urls"),
    ),
    # Adding the urls for role
    path(
        "<int:employee_id>/role/",
        include("module.employee.module.role.urls"),
    )
]