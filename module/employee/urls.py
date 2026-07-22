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
        "time-tracking/statistics/",
        GlobalStatisticsView.as_view(),
    ),
    path(
        "<int:employee_id>/time-tracking/",
        include("module.employee.module.time_tracking.urls"),
    ),
    path(
        "<int:employee_id>/",
        EmployeeDetailView.as_view(),
    ),
]