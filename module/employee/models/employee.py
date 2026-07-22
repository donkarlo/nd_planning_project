from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Employee:
    """
    Respinsible for modeling emplyee data
    """
    id: int
    first_name: str
    last_name: str
    email: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
