from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, cast

from django.db import connection

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
        return [self._to_work_shift(cast(tuple[Any, ...], row)) for row in rows]

    def get_by_id(self, employee_id: int, shift_id: int) -> WorkShift | None:
        sql = f"""
            SELECT {self._columns}
            FROM employee_work_shift
            WHERE employee_id = %s AND id = %s
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id, shift_id])
            row = cursor.fetchone()
        if row is None:
            return None
        return self._to_work_shift(cast(tuple[Any, ...], row))

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
        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id, start_time, end_time, note])
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Work-shift insert returned no row.")
        return self._to_work_shift(cast(tuple[Any, ...], row))

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
            WHERE employee_id = %s AND id = %s
            RETURNING {self._columns}
        """
        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [start_time, end_time, note, employee_id, shift_id],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._to_work_shift(cast(tuple[Any, ...], row))

    def partial_update(
        self,
        employee_id: int,
        shift_id: int,
        changes: Mapping[str, object],
    ) -> WorkShift | None:
        allowed_fields = ("start_time", "end_time", "note")
        assignments: list[str] = []
        parameters: list[Any] = []

        for field in allowed_fields:
            if field in changes:
                assignments.append(f"{field} = %s")
                parameters.append(changes[field])

        if not assignments:
            return self.get_by_id(employee_id, shift_id)

        assignments.append("updated_at = CURRENT_TIMESTAMP")
        parameters.extend([employee_id, shift_id])
        sql = f"""
            UPDATE employee_work_shift
            SET {", ".join(assignments)}
            WHERE employee_id = %s AND id = %s
            RETURNING {self._columns}
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            row = cursor.fetchone()
        if row is None:
            return None
        return self._to_work_shift(cast(tuple[Any, ...], row))

    def delete(self, employee_id: int, shift_id: int) -> bool:
        sql = """
            DELETE FROM employee_work_shift
            WHERE employee_id = %s AND id = %s
            RETURNING id
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id, shift_id])
            row = cursor.fetchone()
        return row is not None

    def overlap_exists(
        self,
        employee_id: int,
        start_time: datetime,
        end_time: datetime,
        excluded_shift_id: int | None = None,
    ) -> bool:
        sql = """
            SELECT EXISTS (
                SELECT 1
                FROM employee_work_shift
                WHERE employee_id = %s
                  AND start_time < %s
                  AND end_time > %s
        """
        parameters: list[Any] = [employee_id, end_time, start_time]

        if excluded_shift_id is not None:
            sql += " AND id <> %s"
            parameters.append(excluded_shift_id)

        sql += ")"
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            row = cursor.fetchone()
        return bool(row and row[0])

    def employee_summary(self, employee_id: int) -> tuple[int, float]:
        sql = """
            SELECT
                COUNT(*),
                COALESCE(
                    SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 3600.0),
                    0
                )
            FROM employee_work_shift
            WHERE employee_id = %s
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id])
            row = cursor.fetchone()
        if row is None:
            return 0, 0.0
        return int(row[0]), self._number_to_float(row[1])

    def global_statistics(self) -> tuple[int, int, float]:
        sql = """
            SELECT
                (SELECT COUNT(*) FROM employee),
                COUNT(*),
                COALESCE(
                    SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 3600.0),
                    0
                )
            FROM employee_work_shift
        """
        with connection.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()
        if row is None:
            return 0, 0, 0.0
        return int(row[0]), int(row[1]), self._number_to_float(row[2])

    @staticmethod
    def _number_to_float(value: object) -> float:
        if isinstance(value, Decimal):
            return round(float(value), 2)
        if isinstance(value, (int, float)):
            return round(float(value), 2)
        return 0.0

    @staticmethod
    def _to_work_shift(row: tuple[Any, ...]) -> WorkShift:
        return WorkShift(
            id=cast(int, row[0]),
            employee_id=cast(int, row[1]),
            start_time=row[2],
            end_time=row[3],
            note=cast(str, row[4]),
            created_at=row[5],
            updated_at=row[6],
        )
