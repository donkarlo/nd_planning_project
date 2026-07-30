from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EmployeeRole:
    """
    Models only one employee_role ent
    """
    id: int
    employee_id: int
    role_name: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "role_name": self.role_name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }