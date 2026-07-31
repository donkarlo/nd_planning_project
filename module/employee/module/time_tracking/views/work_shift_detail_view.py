from datetime import datetime
from typing import cast

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from module.employee.module.time_tracking.exceptions.overlapping_work_shift_error import (
    OverlappingWorkShiftError,
)
from module.employee.module.time_tracking.repositories.work_shift_repository import (
    WorkShiftRepository,
)
from module.employee.module.time_tracking.serializers.work_shift_serializer import (
    WorkShiftSerializer,
)
from module.employee.module.time_tracking.services.work_shift_validator import (
    WorkShiftValidator,
)
from module.employee.repositories.employee_repository import (
    EmployeeRepository,
)


class WorkShiftDetailView(APIView):
    employee_repository = EmployeeRepository()
    repository = WorkShiftRepository()
    validator = WorkShiftValidator()

    def get(
            self,
            request: Request,
            employee_id: int,
            shift_id: int,
    ) -> Response:
        shift = self.repository.get_by_id(
            employee_id,
            shift_id,
        )

        if shift is None:
            return self._not_found()

        return Response(
            shift.to_dict()
        )

    def put(
            self,
            request: Request,
            employee_id: int,
            shift_id: int,
    ) -> Response:
        if (
                self.employee_repository.get_by_id(
                    employee_id
                )
                is None
        ):
            return self._not_found()

        serializer = WorkShiftSerializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )

        data = serializer.validated_data

        start_time = cast(
            datetime,
            data["start_time"],
        )
        end_time = cast(
            datetime,
            data["end_time"],
        )
        note = str(
            data.get(
                "note",
                "",
            )
        )

        self.validator.validate(
            start_time,
            end_time,
        )

        try:
            shift = self.repository.replace(
                employee_id,
                shift_id,
                start_time,
                end_time,
                note,
            )
        except OverlappingWorkShiftError:
            return self._overlap_error()

        if shift is None:
            return self._not_found()

        return Response(
            shift.to_dict()
        )

    def patch(
            self,
            request: Request,
            employee_id: int,
            shift_id: int,
    ) -> Response:
        current = self.repository.get_by_id(
            employee_id,
            shift_id,
        )

        if current is None:
            return self._not_found()

        serializer = WorkShiftSerializer(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(
            raise_exception=True
        )

        changes = serializer.validated_data

        start_time = cast(
            datetime,
            changes.get(
                "start_time",
                current.start_time,
            ),
        )

        end_time = cast(
            datetime,
            changes.get(
                "end_time",
                current.end_time,
            ),
        )

        self.validator.validate(
            start_time,
            end_time,
        )

        try:
            shift = self.repository.partial_update(
                employee_id,
                shift_id,
                changes,
            )
        except OverlappingWorkShiftError:
            return self._overlap_error()

        if shift is None:
            return self._not_found()

        return Response(
            shift.to_dict()
        )

    def delete(
            self,
            request: Request,
            employee_id: int,
            shift_id: int,
    ) -> Response:
        if not self.repository.delete(
                employee_id,
                shift_id,
        ):
            return self._not_found()

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )

    @staticmethod
    def _not_found() -> Response:
        return Response(
            {
                "detail": "Work shift not found."
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    @staticmethod
    def _overlap_error() -> Response:
        return Response(
            {
                "non_field_errors": [
                    (
                        "This work shift overlaps "
                        "another shift."
                    )
                ]
            },
            status=status.HTTP_400_BAD_REQUEST,
        )