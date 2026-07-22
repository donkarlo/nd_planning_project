from django.test import TestCase
from rest_framework.test import APIClient


class WorkShiftCrudApiTest(TestCase):
    """
    For testing shift updates
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
        self.employee_id = response.json()["id"]

    def test_work_shift_crud(self) -> None:
        collection_url = f"/api/employees/{self.employee_id}/time-tracking/"
        create_response = self.client.post(
            collection_url,
            {
                "start_time": "2026-07-18T08:00:00Z",
                "end_time": "2026-07-18T16:00:00Z",
                "note": "Day shift",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        shift_id = create_response.json()["id"]

        list_response = self.client.get(collection_url)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        detail_url = f"{collection_url}{shift_id}/"
        patch_response = self.client.patch(
            detail_url,
            {"note": "Updated shift"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["note"], "Updated shift")

        delete_response = self.client.delete(detail_url)
        self.assertEqual(delete_response.status_code, 204)
