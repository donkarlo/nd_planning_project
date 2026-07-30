from typing import Any

from rest_framework import serializers


class EmployeesRoles(serializers.Serializer):
    """
    View uses to validate the input and output.
    """
    role_name = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=100,
    )
