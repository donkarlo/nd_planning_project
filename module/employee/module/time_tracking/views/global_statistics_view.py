from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from module.employee.module.time_tracking.repositories.work_shift_repository import (
    WorkShiftRepository,
)
from module.employee.module.time_tracking.services.global_statistics_service import (
    GlobalStatisticsService,
)


class GlobalStatisticsView(APIView):
    service = GlobalStatisticsService(WorkShiftRepository())

    def get(self, request: Request) -> Response:
        return Response(self.service.build())
