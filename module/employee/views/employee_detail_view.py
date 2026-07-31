from django.db import IntegrityError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from module.employee.repositories.employee_repository import EmployeeRepository
from module.employee.serializers.employee_serializer import EmployeeSerializer


class EmployeeDetailView(APIView):
    """
    This class is working with a explicit given employee, that is, all its methods need role_name
    - an employee id is needed for all methods in this request
    """
    repository = EmployeeRepository()

    def get(self, request: Request, employee_id: int) -> Response:
        """
        Employee id is comming from the URL and not PUT or POST etc request
        """
        employee = self.repository.get_by_id(employee_id)
        if employee is None:
            return self._not_found()
        return Response(employee.to_dict())

    def put(self, request: Request, employee_id: int) -> Response:
        serializer = EmployeeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            employee = self.repository.replace(
                employee_id=employee_id,
                first_name=str(data["first_name"]),
                last_name=str(data["last_name"]),
                email=str(data["email"]),
            )
        except IntegrityError:
            return self._duplicate_email()

        if employee is None:
            return self._not_found()
        return Response(employee.to_dict())

    def patch(self, request: Request, employee_id: int) -> Response:
        serializer = EmployeeSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            employee = self.repository.partial_update(
                employee_id,
                serializer.validated_data,
            )
        except IntegrityError:
            return self._duplicate_email()

        if employee is None:
            return self._not_found()
        return Response(employee.to_dict())

    def delete(self, request: Request, employee_id: int) -> Response:
        if not self.repository.delete(employee_id):
            return self._not_found()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _not_found() -> Response:
        return Response(
            {"detail": "Employee not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    @staticmethod
    def _duplicate_email() -> Response:
        return Response(
            {"email": ["An employee with this email already exists."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
