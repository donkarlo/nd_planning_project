from rest_framework import serializers

from module.employee.module.role.repository.employees_roles import (
    EmployeesRolesRepository,
)


class EmployeeRoleValidator:
    def __init__(self, repository: EmployeesRolesRepository) -> None:
        self.repository = repository

    def validate(
            self,
            employee_id: int,
            role_name: str,
            current_role_name: str | None = None,
    ) -> str:
        normalized_role_name = role_name.strip()

        if not normalized_role_name:
            raise serializers.ValidationError(
                {"role_name": ["Role name must not be blank."]}
            )

        normalized_current_role_name = (
            current_role_name.strip()
            if current_role_name is not None
            else None
        )

        if normalized_current_role_name == normalized_role_name:
            return normalized_role_name

        existing_role = self.repository.get_by_employee_id_and_role_name(
            employee_id=employee_id,
            role_name=normalized_role_name,
        )

        if existing_role is not None:
            raise serializers.ValidationError(
                {"role_name": ["This employee already has this role."]}
            )

        return normalized_role_name