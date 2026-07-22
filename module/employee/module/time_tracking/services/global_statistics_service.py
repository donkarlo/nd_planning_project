from module.employee.module.time_tracking.repositories.work_shift_repository import (
    WorkShiftRepository,
)


class GlobalStatisticsService:
    def __init__(self, repository: WorkShiftRepository) -> None:
        self.repository = repository

    def build(self) -> dict[str, object]:
        employee_count, shift_count, total_hours = self.repository.global_statistics()
        average_hours = (
            round(total_hours / employee_count, 2) if employee_count > 0 else 0.0
        )
        return {
            "employee_count": employee_count,
            "shift_count": shift_count,
            "total_hours": total_hours,
            "average_hours_per_employee": average_hours,
        }
