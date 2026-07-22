from django.urls import path

from module.employee.module.time_tracking.views.employee_summary_view import (
    EmployeeSummaryView,
)
from module.employee.module.time_tracking.views.work_shift_collection_view import (
    WorkShiftCollectionView,
)
from module.employee.module.time_tracking.views.work_shift_detail_view import (
    WorkShiftDetailView,
)

urlpatterns = [
    path("", WorkShiftCollectionView.as_view()),
    path("summary/", EmployeeSummaryView.as_view()),
    path("<int:shift_id>/", WorkShiftDetailView.as_view()),
]