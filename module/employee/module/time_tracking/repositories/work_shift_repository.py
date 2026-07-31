from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, cast

from django.db import IntegrityError, connection, transaction

from module.employee.module.time_tracking.exceptions.overlapping_work_shift_error import (
    OverlappingWorkShiftError,
)
from module.employee.module.time_tracking.models.work_shift import WorkShift


class WorkShiftRepository:
    _columns = (
        "id, employee_id, start_time, end_time, note, created_at, updated_at"
    )

    def list_for_employee(self, employee_id: int) -> list[WorkShift]:
        sql = f"""
            SELECT {self._columns}
            FROM employee_work_shift
            WHERE employee_id = %s
            ORDER BY start_time, id
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id])
            rows = cursor.fetchall()

        return [
            self._to_work_shift(cast(tuple[Any, ...], row))
            for row in rows
        ]

    def get_by_id(
            self,
            employee_id: int,
            shift_id: int,
    ) -> WorkShift | None:
        sql = f"""
            SELECT {self._columns}
            FROM employee_work_shift
            WHERE employee_id = %s
              AND id = %s
        """

        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [employee_id, shift_id],
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return self._to_work_shift(
            cast(tuple[Any, ...], row)
        )

    def create(
            self,
            employee_id: int,
            start_time: datetime,
            end_time: datetime,
            note: str,
    ) -> WorkShift:
        sql = f"""
            INSERT INTO employee_work_shift (
                employee_id,
                start_time,
                end_time,
                note
            )
            VALUES (%s, %s, %s, %s)
            RETURNING {self._columns}
        """

        row = self._execute_write(
            sql,
            [
                employee_id,
                start_time,
                end_time,
                note,
            ],
        )

        if row is None:
            raise RuntimeError(
                "Work-shift insert returned no row."
            )

        return self._to_work_shift(row)

    def replace(
            self,
            employee_id: int,
            shift_id: int,
            start_time: datetime,
            end_time: datetime,
            note: str,
    ) -> WorkShift | None:
        sql = f"""
            UPDATE employee_work_shift
            SET start_time = %s,
                end_time = %s,
                note = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE employee_id = %s
              AND id = %s
            RETURNING {self._columns}
        """

        row = self._execute_write(
            sql,
            [
                start_time,
                end_time,
                note,
                employee_id,
                shift_id,
            ],
        )

        if row is None:
            return None

        return self._to_work_shift(row)

    def partial_update(
            self,
            employee_id: int,
            shift_id: int,
            changes: Mapping[str, object],
    ) -> WorkShift | None:
        allowed_fields = (
            "start_time",
            "end_time",
            "note",
        )

        assignments: list[str] = []
        parameters: list[Any] = []

        for field in allowed_fields:
            if field in changes:
                assignments.append(f"{field} = %s")
                parameters.append(changes[field])

        if not assignments:
            return self.get_by_id(
                employee_id,
                shift_id,
            )

        assignments.append(
            "updated_at = CURRENT_TIMESTAMP"
        )

        parameters.extend(
            [
                employee_id,
                shift_id,
            ]
        )

        sql = f"""
            UPDATE employee_work_shift
            SET {", ".join(assignments)}
            WHERE employee_id = %s
              AND id = %s
            RETURNING {self._columns}
        """

        row = self._execute_write(
            sql,
            parameters,
        )

        if row is None:
            return None

        return self._to_work_shift(row)

    def delete(
            self,
            employee_id: int,
            shift_id: int,
    ) -> bool:
        sql = """
            DELETE FROM employee_work_shift
            WHERE employee_id = %s
              AND id = %s
            RETURNING id
        """

        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [employee_id, shift_id],
            )
            row = cursor.fetchone()

        return row is not None

    def employee_summary(
            self,
            employee_id: int,
    ) -> tuple[int, float]:
        sql = """
            SELECT
                COUNT(*),
                COALESCE(
                    SUM(
                        EXTRACT(
                            EPOCH FROM (
                                end_time - start_time
                            )
                        ) / 3600.0
                    ),
                    0
                )
            FROM employee_work_shift
            WHERE employee_id = %s
        """

        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [employee_id],
            )
            row = cursor.fetchone()

        if row is None:
            return 0, 0.0

        return (
            int(row[0]),
            self._number_to_float(row[1]),
        )

    def global_statistics(
            self,
    ) -> tuple[int, int, float]:
        sql = """
            SELECT
                (SELECT COUNT(*) FROM employee),
                COUNT(*),
                COALESCE(
                    SUM(
                        EXTRACT(
                            EPOCH FROM (
                                end_time - start_time
                            )
                        ) / 3600.0
                    ),
                    0
                )
            FROM employee_work_shift
        """

        with connection.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()

        if row is None:
            return 0, 0, 0.0

        return (
            int(row[0]),
            int(row[1]),
            self._number_to_float(row[2]),
        )

    @staticmethod
    def _execute_write(
            sql: str,
            parameters: list[Any],
    ) -> tuple[Any, ...] | None:
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql,
                        parameters,
                    )
                    row = cursor.fetchone()

        except IntegrityError as error:
            constraint_name = getattr(
                getattr(
                    error.__cause__,
                    "diag",
                    None,
                ),
                "constraint_name",
                None,
            )

            if (
                    constraint_name
                    == "employee_work_shift_no_overlap"
            ):
                raise OverlappingWorkShiftError(
                    "This work shift overlaps another shift."
                ) from error

            raise

        if row is None:
            return None

        return cast(
            tuple[Any, ...],
            row,
        )

    @staticmethod
    def _number_to_float(
            value: object,
    ) -> float:
        if isinstance(value, Decimal):
            return round(
                float(value),
                2,
            )

        if isinstance(value, (int, float)):
            return round(
                float(value),
                2,
            )

        return 0.0

    @staticmethod
    def _to_work_shift(
            row: tuple[Any, ...],
    ) -> WorkShift:
        return WorkShift(
            id=cast(int, row[0]),
            employee_id=cast(int, row[1]),
            start_time=row[2],
            end_time=row[3],
            note=cast(str, row[4]),
            created_at=row[5],
            updated_at=row[6],
        )