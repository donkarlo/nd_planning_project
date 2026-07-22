from django.test import TestCase
from rest_framework.test import APIClient


class EmployeeCrudApiTest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_employee_crud(self) -> None:
        """
        Test in employee table crud
        """
        create_response = self.client.post(
            "/api/employees/",
            {
                "first_name": "Anna",
                "last_name": "Muster",
                "email": "anna@example.com",
            },
            format="json",
        )
        # INSERT check
        self.assertEqual(create_response.status_code, 201)
        employee_id = create_response.json()["id"]

        # SELECT all check test
        list_response = self.client.get("/api/employees/")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        # SELECT * FROM employee.id = ? test
        detail_url = f"/api/employees/{employee_id}/"
        detail_response = self.client.get(detail_url)
        self.assertEqual(detail_response.status_code, 200)

        # UPDATE partially test
        patch_response = self.client.patch(
            detail_url,
            {"last_name": "Example"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["last_name"], "Example")

        # DELETE test
        delete_response = self.client.delete(detail_url)
        self.assertEqual(delete_response.status_code, 204)
