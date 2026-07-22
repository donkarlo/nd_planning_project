from typing import Any, Mapping, cast

from django.db import connection

from module.employee.models.employee import Employee


class EmployeeRepository:
    """
    Responsible for handeling communication with database
    """
    _columns = "id, first_name, last_name, email, created_at, updated_at"

    def list_all(self) -> list[Employee]:
        sql = f"""
            SELECT {self._columns}
            FROM employee
            ORDER BY last_name, first_name, id
        """
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
        return [self._to_employee(cast(tuple[Any, ...], row)) for row in rows]

    def get_by_id(self, employee_id: int) -> Employee | None:
        sql = f"""
            SELECT {self._columns}
            FROM employee
            WHERE id = %s
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id])
            row = cursor.fetchone()
        if row is None:
            return None
        return self._to_employee(cast(tuple[Any, ...], row))

    def create(self, first_name: str, last_name: str, email: str) -> Employee:
        sql = f"""
            INSERT INTO employee (first_name, last_name, email)
            VALUES (%s, %s, %s)
            RETURNING {self._columns}
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [first_name, last_name, email])
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Employee insert returned no row.")
        return self._to_employee(cast(tuple[Any, ...], row))

    def replace(
        self,
        employee_id: int,
        first_name: str,
        last_name: str,
        email: str,
    ) -> Employee | None:
        sql = f"""
            UPDATE employee
            SET first_name = %s,
                last_name = %s,
                email = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING {self._columns}
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [first_name, last_name, email, employee_id])
            row = cursor.fetchone()
        if row is None:
            return None
        return self._to_employee(cast(tuple[Any, ...], row))

    def partial_update(
        self,
        employee_id: int,
        changes: Mapping[str, object],
    ) -> Employee | None:
        allowed_fields = ("first_name", "last_name", "email")
        assignments: list[str] = []
        parameters: list[Any] = []

        for field in allowed_fields:
            if field in changes:
                assignments.append(f"{field} = %s")
                parameters.append(changes[field])

        if not assignments:
            return self.get_by_id(employee_id)

        assignments.append("updated_at = CURRENT_TIMESTAMP")
        parameters.append(employee_id)
        sql = f"""
            UPDATE employee
            SET {", ".join(assignments)}
            WHERE id = %s
            RETURNING {self._columns}
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            row = cursor.fetchone()
        if row is None:
            return None
        return self._to_employee(cast(tuple[Any, ...], row))

    def delete(self, employee_id: int) -> bool:
        sql = """
            DELETE FROM employee
            WHERE id = %s
            RETURNING id
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id])
            row = cursor.fetchone()
        return row is not None

    @staticmethod
    def _to_employee(row: tuple[Any, ...]) -> Employee:
        return Employee(
            id=cast(int, row[0]),
            first_name=cast(str, row[1]),
            last_name=cast(str, row[2]),
            email=cast(str, row[3]),
            created_at=row[4],
            updated_at=row[5],
        )
