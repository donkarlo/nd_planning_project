from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class WorkShift:
    id: int
    employee_id: int
    start_time: datetime
    end_time: datetime
    note: str
    created_at: datetime
    updated_at: datetime

    @property
    def duration_hours(self) -> float:
        seconds = (self.end_time - self.start_time).total_seconds()
        return round(seconds / 3600, 2)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_hours": self.duration_hours,
            "note": self.note,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
