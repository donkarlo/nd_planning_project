from django.test import TestCase
from rest_framework.test import APIClient


class WorkShiftValidationApiTest(TestCase):
    """
    SRP: to validate overlapping workshifts
    """
    def setUp(self) -> None:
        self.client = APIClient()
        response = self.client.post(
            "/api/employees/",
            {
                "first_name": "Anna",
                "last_name": "Muster",
                "email": "anna@example.com",
            },
            format="json",
        )
        self.collection_url = (
            f"/api/employees/{response.json()['id']}/time-tracking/"
        )

    def test_rejects_invalid_and_overlapping_shifts(self) -> None:
        """
        To test if overlapping system works fine
        """
        invalid_response = self.client.post(
            self.collection_url,
            {
                "start_time": "2026-07-18T16:00:00Z",
                "end_time": "2026-07-18T08:00:00Z",
            },
            format="json",
        )
        self.assertEqual(invalid_response.status_code, 400)

        first_response = self.client.post(
            self.collection_url,
            {
                "start_time": "2026-07-18T08:00:00Z",
                "end_time": "2026-07-18T16:00:00Z",
            },
            format="json",
        )
        self.assertEqual(first_response.status_code, 201)

        overlap_response = self.client.post(
            self.collection_url,
            {
                "start_time": "2026-07-18T12:00:00Z",
                "end_time": "2026-07-18T18:00:00Z",
            },
            format="json",
        )
        self.assertEqual(overlap_response.status_code, 400)

        adjacent_response = self.client.post(
            self.collection_url,
            {
                "start_time": "2026-07-18T16:00:00Z",
                "end_time": "2026-07-18T20:00:00Z",
            },
            format="json",
        )
        self.assertEqual(adjacent_response.status_code, 201)
