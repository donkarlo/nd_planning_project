from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from module.employee.module.role.repository.employees_roles import (
    EmployeesRolesRepository,
)
from module.employee.module.role.serializer.employees_roles import (
    EmployeesRoles,
)
from module.employee.module.role.service.employee_role_validator import (
    EmployeeRoleValidator,
)


class EmployeesRolesDetail(APIView):
    repository = EmployeesRolesRepository()
    validator = EmployeeRoleValidator(repository)

    def get(
            self,
            request: Request,
            employee_id: int,
            role_name: str,
    ) -> Response:
        role = self.repository.get_by_employee_id_and_role_name(
            employee_id,
            role_name,
        )

        if role is None:
            return self._not_found()

        return Response(role.to_dict())

    def put(
            self,
            request: Request,
            employee_id: int,
            role_name: str,
    ) -> Response:
        current_role = self.repository.get_by_employee_id_and_role_name(
            employee_id,
            role_name,
        )

        if current_role is None:
            return self._not_found()

        serializer = EmployeesRoles(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_role_name = self.validator.validate(
            employee_id=employee_id,
            role_name=str(serializer.validated_data["role_name"]),
            current_role_name=current_role.role_name,
        )

        role = self.repository.replace(
            employee_id=employee_id,
            old_role_name=current_role.role_name,
            new_role_name=new_role_name,
        )

        if role is None:
            return self._not_found()

        return Response(role.to_dict())

    def patch(
            self,
            request: Request,
            employee_id: int,
            role_name: str,
    ) -> Response:
        current_role = self.repository.get_by_employee_id_and_role_name(
            employee_id,
            role_name,
        )

        if current_role is None:
            return self._not_found()

        serializer = EmployeesRoles(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        changes: dict[str, object] = dict(
            serializer.validated_data
        )

        if "role_name" in changes:
            changes["role_name"] = self.validator.validate(
                employee_id=employee_id,
                role_name=str(changes["role_name"]),
                current_role_name=current_role.role_name,
            )

        role = self.repository.partial_update(
            employee_id=employee_id,
            role_name=current_role.role_name,
            changes=changes,
        )

        if role is None:
            return self._not_found()

        return Response(role.to_dict())

    def delete(
            self,
            request: Request,
            employee_id: int,
            role_name: str,
    ) -> Response:
        deleted = (
            self.repository.delete_role_for_employee_by_role_name(
                employee_id,
                role_name,
            )
        )

        if not deleted:
            return self._not_found()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _not_found() -> Response:
        return Response(
            {"detail": "Employee role not found."},
            status=status.HTTP_404_NOT_FOUND,
        )