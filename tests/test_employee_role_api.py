from django.test import TestCase
from rest_framework import serializers
from rest_framework.test import APIClient

from module.employee.module.role.repository.employees_roles import (
    EmployeesRolesRepository,
)
from module.employee.module.role.service.employee_role_validator import (
    EmployeeRoleValidator,
)


class EmployeeRoleApiTest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

        employee_response = self.client.post(
            "/api/employees/",
            {
                "first_name": "Anna",
                "last_name": "Muster",
                "email": "anna@example.com",
            },
            format="json",
        )

        self.assertEqual(employee_response.status_code, 201)

        self.employee_id = int(
            employee_response.json()["id"]
        )
        self.collection_url = (
            f"/api/employees/{self.employee_id}/role/"
        )

    def test_employee_role_crud(self) -> None:
        create_response = self.client.post(
            self.collection_url,
            {"role_name": "manager"},
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(
            create_response.json()["employee_id"],
            self.employee_id,
        )
        self.assertEqual(
            create_response.json()["role_name"],
            "manager",
        )

        list_response = self.client.get(
            self.collection_url
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(
            list_response.json()[0]["role_name"],
            "manager",
        )

        detail_url = f"{self.collection_url}manager/"

        detail_response = self.client.get(detail_url)

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.json()["role_name"],
            "manager",
        )

        put_response = self.client.put(
            detail_url,
            {"role_name": "supervisor"},
            format="json",
        )

        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(
            put_response.json()["role_name"],
            "supervisor",
        )

        old_detail_response = self.client.get(detail_url)

        self.assertEqual(
            old_detail_response.status_code,
            404,
        )

        supervisor_url = (
            f"{self.collection_url}supervisor/"
        )

        patch_response = self.client.patch(
            supervisor_url,
            {"role_name": "administrator"},
            format="json",
        )

        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(
            patch_response.json()["role_name"],
            "administrator",
        )

        administrator_url = (
            f"{self.collection_url}administrator/"
        )

        delete_response = self.client.delete(
            administrator_url
        )

        self.assertEqual(delete_response.status_code, 204)

        deleted_response = self.client.get(
            administrator_url
        )

        self.assertEqual(
            deleted_response.status_code,
            404,
        )

    def test_duplicate_role_returns_400(self) -> None:
        first_response = self.client.post(
            self.collection_url,
            {"role_name": "manager"},
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)

        duplicate_response = self.client.post(
            self.collection_url,
            {"role_name": "manager"},
            format="json",
        )

        self.assertEqual(
            duplicate_response.status_code,
            400,
        )
        self.assertIn(
            "role_name",
            duplicate_response.json(),
        )

    def test_put_accepts_unchanged_role_name(
            self,
    ) -> None:
        self.client.post(
            self.collection_url,
            {"role_name": "manager"},
            format="json",
        )

        detail_url = f"{self.collection_url}manager/"

        response = self.client.put(
            detail_url,
            {"role_name": "manager"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["role_name"],
            "manager",
        )

    def test_put_rejects_role_already_assigned_to_employee(
            self,
    ) -> None:
        self.client.post(
            self.collection_url,
            {"role_name": "manager"},
            format="json",
        )

        self.client.post(
            self.collection_url,
            {"role_name": "supervisor"},
            format="json",
        )

        response = self.client.put(
            f"{self.collection_url}manager/",
            {"role_name": "supervisor"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("role_name", response.json())

    def test_patch_rejects_role_already_assigned_to_employee(
            self,
    ) -> None:
        self.client.post(
            self.collection_url,
            {"role_name": "manager"},
            format="json",
        )

        self.client.post(
            self.collection_url,
            {"role_name": "supervisor"},
            format="json",
        )

        response = self.client.patch(
            f"{self.collection_url}manager/",
            {"role_name": "supervisor"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("role_name", response.json())

    def test_blank_role_name_returns_400(self) -> None:
        response = self.client.post(
            self.collection_url,
            {"role_name": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("role_name", response.json())

    def test_unknown_employee_returns_404(self) -> None:
        response = self.client.post(
            "/api/employees/999999/role/",
            {"role_name": "manager"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)


class EmployeeRoleValidatorTest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

        employee_response = self.client.post(
            "/api/employees/",
            {
                "first_name": "Ali",
                "last_name": "Example",
                "email": "ali@example.com",
            },
            format="json",
        )

        self.assertEqual(employee_response.status_code, 201)

        self.employee_id = int(
            employee_response.json()["id"]
        )
        self.repository = EmployeesRolesRepository()
        self.validator = EmployeeRoleValidator(
            self.repository
        )

        self.repository.create(
            self.employee_id,
            "manager",
        )

    def test_rejects_duplicate_role_for_same_employee(
            self,
    ) -> None:
        with self.assertRaises(
                serializers.ValidationError
        ):
            self.validator.validate(
                self.employee_id,
                "manager",
            )

    def test_accepts_new_role(self) -> None:
        result = self.validator.validate(
            self.employee_id,
            "supervisor",
        )

        self.assertEqual(result, "supervisor")

    def test_accepts_unchanged_current_role(
            self,
    ) -> None:
        result = self.validator.validate(
            employee_id=self.employee_id,
            role_name="manager",
            current_role_name="manager",
        )

        self.assertEqual(result, "manager")

    def test_normalizes_role_name(self) -> None:
        result = self.validator.validate(
            self.employee_id,
            "  supervisor  ",
        )

        self.assertEqual(result, "supervisor")

    def test_rejects_blank_role_name(self) -> None:
        with self.assertRaises(
                serializers.ValidationError
        ):
            self.validator.validate(
                self.employee_id,
                "   ",
            )