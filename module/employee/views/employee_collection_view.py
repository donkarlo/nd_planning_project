from django.db import IntegrityError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from module.employee.repositories.employee_repository import EmployeeRepository
from module.employee.serializers.employee_serializer import EmployeeSerializer


class EmployeeCollectionView(APIView):
    """
    This class is responsible for employees set and it doesnt need role_name
    """

    # the repository shared between all objects built based on this class
    repository = EmployeeRepository()

    def get(self, request: Request) -> Response:
        """
        To return the list of all employees
        """
        employees = self.repository.list_all()
        return Response([employee.to_dict() for employee in employees])

    def post(self, request: Request) -> Response:
        serializer = EmployeeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            # Request to insert a new employee
            employee = self.repository.create(
                first_name=str(data["first_name"]),
                last_name=str(data["last_name"]),
                email=str(data["email"]),
            )
        except IntegrityError:
            return Response(
                {"email": ["An employee with this email already exists."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(employee.to_dict(), status=status.HTTP_201_CREATED)
