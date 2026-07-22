from module.employee.models.employee import Employee
from module.employee.module.time_tracking.repositories.work_shift_repository import (
    WorkShiftRepository,
)


class EmployeeSummaryService:
    def __init__(self, repository: WorkShiftRepository) -> None:
        self.repository = repository

    def build(self, employee: Employee) -> dict[str, object]:
        shift_count, total_hours = self.repository.employee_summary(employee.id)
        return {
            "employee": employee.to_dict(),
            "shift_count": shift_count,
            "total_hours": total_hours,
        }
