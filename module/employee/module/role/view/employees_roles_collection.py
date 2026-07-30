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
from module.employee.repositories.employee_repository import EmployeeRepository


class EmployeesRolesCollection(APIView):
    employee_repository = EmployeeRepository()
    repository = EmployeesRolesRepository()
    validator = EmployeeRoleValidator(repository)

    def get(self, request: Request, employee_id: int) -> Response:
        if self.employee_repository.get_by_id(employee_id) is None:
            return self._employee_not_found()

        roles = self.repository.list_roles_by_employee_id(employee_id)
        return Response([role.to_dict() for role in roles])

    def post(self, request: Request, employee_id: int) -> Response:
        if self.employee_repository.get_by_id(employee_id) is None:
            return self._employee_not_found()

        serializer = EmployeesRoles(data=request.data)
        serializer.is_valid(raise_exception=True)

        role_name = self.validator.validate(
            employee_id=employee_id,
            role_name=str(serializer.validated_data["role_name"]),
        )

        role = self.repository.create(employee_id, role_name)

        return Response(
            role.to_dict(),
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _employee_not_found() -> Response:
        return Response(
            {"detail": "Employee not found."},
            status=status.HTTP_404_NOT_FOUND,
        )