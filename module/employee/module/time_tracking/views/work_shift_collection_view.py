from datetime import datetime
from typing import cast

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from module.employee.repositories.employee_repository import EmployeeRepository
from module.employee.module.time_tracking.repositories.work_shift_repository import (
    WorkShiftRepository,
)
from module.employee.module.time_tracking.serializers.work_shift_serializer import (
    WorkShiftSerializer,
)
from module.employee.module.time_tracking.services.work_shift_validator import (
    WorkShiftValidator,
)


class WorkShiftCollectionView(APIView):
    employee_repository = EmployeeRepository()
    repository = WorkShiftRepository()
    validator = WorkShiftValidator(repository)

    def get(self, request: Request, employee_id: int) -> Response:
        if self.employee_repository.get_by_id(employee_id) is None:
            return self._employee_not_found()
        shifts = self.repository.list_for_employee(employee_id)
        return Response([shift.to_dict() for shift in shifts])

    def post(self, request: Request, employee_id: int) -> Response:
        if self.employee_repository.get_by_id(employee_id) is None:
            return self._employee_not_found()

        serializer = WorkShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        start_time = cast(datetime, data["start_time"])
        end_time = cast(datetime, data["end_time"])
        note = str(data.get("note", ""))

        self.validator.validate(employee_id, start_time, end_time)
        shift = self.repository.create(employee_id, start_time, end_time, note)
        return Response(shift.to_dict(), status=status.HTTP_201_CREATED)

    @staticmethod
    def _employee_not_found() -> Response:
        return Response(
            {"detail": "Employee not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
