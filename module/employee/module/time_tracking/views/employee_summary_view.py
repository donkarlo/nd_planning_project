from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from module.employee.repositories.employee_repository import EmployeeRepository
from module.employee.module.time_tracking.repositories.work_shift_repository import (
    WorkShiftRepository,
)
from module.employee.module.time_tracking.services.employee_summary_service import (
    EmployeeSummaryService,
)


class EmployeeSummaryView(APIView):
    employee_repository = EmployeeRepository()
    service = EmployeeSummaryService(WorkShiftRepository())

    def get(self, request: Request, employee_id: int) -> Response:
        employee = self.employee_repository.get_by_id(employee_id)
        if employee is None:
            return Response(
                {"detail": "Employee not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(self.service.build(employee))
