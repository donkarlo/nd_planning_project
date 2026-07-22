from typing import Any

from rest_framework import serializers


class WorkShiftSerializer(serializers.Serializer):
    """
    View uses to validate the input and output.
    """
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=1000,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """
        To validate the set data
        """
        start_time = attrs.get("start_time")
        end_time = attrs.get("end_time")
        # To validate if start and end times are empty and they are ordered correctly
        if start_time is not None and end_time is not None and end_time <= start_time:
            raise serializers.ValidationError(
                {"end_time": "end_time must be after start_time."}
            )
        return attrs
