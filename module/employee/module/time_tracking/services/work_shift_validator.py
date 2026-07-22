from datetime import datetime

from rest_framework import serializers

from module.employee.module.time_tracking.repositories.work_shift_repository import (
    WorkShiftRepository,
)


class WorkShiftValidator:
    def __init__(self, repository: WorkShiftRepository) -> None:
        self.repository = repository

    def validate(
        self,
        employee_id: int,
        start_time: datetime,
        end_time: datetime,
        excluded_shift_id: int | None = None,
    ) -> None:
        if end_time <= start_time:
            raise serializers.ValidationError(
                {"end_time": "end_time must be after start_time."}
            )

        if self.repository.overlap_exists(
            employee_id=employee_id,
            start_time=start_time,
            end_time=end_time,
            excluded_shift_id=excluded_shift_id,
        ):
            raise serializers.ValidationError(
                {"non_field_errors": ["This work shift overlaps another shift."]}
            )
