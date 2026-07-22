from django.test import TestCase
from rest_framework.test import APIClient


class SummaryApiTest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_employee_summary_and_global_statistics(self) -> None:
        employee_response = self.client.post(
            "/api/employees/",
            {
                "first_name": "Anna",
                "last_name": "Muster",
                "email": "anna@example.com",
            },
            format="json",
        )

        employee_id = employee_response.json()["id"]
        shift_url = f"/api/employees/{employee_id}/time-tracking/"

        self.client.post(
            shift_url,
            {
                "start_time": "2026-07-18T08:00:00Z",
                "end_time": "2026-07-18T16:00:00Z",
            },
            format="json",
        )

        summary_response = self.client.get(f"{shift_url}summary/")

        # Checks that the employee summary request was successful.
        self.assertEqual(summary_response.status_code, 200)

        # Checks that the employee has exactly one registered work shift.
        self.assertEqual(summary_response.json()["shift_count"], 1)

        # Checks that the employee worked a total of eight hours.
        self.assertEqual(summary_response.json()["total_hours"], 8.0)

        statistics_response = self.client.get(
            "/api/employees/time-tracking/statistics/"
        )

        # Checks that the global statistics request was successful.
        self.assertEqual(statistics_response.status_code, 200)

        # Checks that exactly one employee exists in the system.
        self.assertEqual(statistics_response.json()["employee_count"], 1)

        # Checks that exactly one work shift exists in the whole system.
        self.assertEqual(statistics_response.json()["shift_count"], 1)

