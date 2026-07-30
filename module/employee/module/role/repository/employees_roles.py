from typing import Any, Mapping, cast

from django.db import connection

from module.employee.module.role.model.employee_role import EmployeeRole


class EmployeesRolesRepository:
    _columns = "id, employee_id, role_name, created_at, updated_at"

    def list_roles_by_employee_id(
            self,
            employee_id: int,
    ) -> list[EmployeeRole]:
        sql = f"""
            SELECT {self._columns}
            FROM employees_roles
            WHERE employee_id = %s
            ORDER BY role_name
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id])
            rows = cursor.fetchall()

        return [
            self._to_employee_role(cast(tuple[Any, ...], row))
            for row in rows
        ]

    def get_employees_by_role_name(
            self,
            role_name: str,
    ) -> list[EmployeeRole]:
        sql = f"""
            SELECT {self._columns}
            FROM employees_roles
            WHERE role_name = %s
            ORDER BY employee_id
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [role_name])
            rows = cursor.fetchall()

        return [
            self._to_employee_role(cast(tuple[Any, ...], row))
            for row in rows
        ]

    def get_by_employee_id_and_role_name(
            self,
            employee_id: int,
            role_name: str,
    ) -> EmployeeRole | None:
        sql = f"""
            SELECT {self._columns}
            FROM employees_roles
            WHERE employee_id = %s
              AND role_name = %s
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id, role_name])
            row = cursor.fetchone()

        if row is None:
            return None

        return self._to_employee_role(cast(tuple[Any, ...], row))

    def create(
            self,
            employee_id: int,
            role_name: str,
    ) -> EmployeeRole:
        sql = f"""
            INSERT INTO employees_roles (
                employee_id,
                role_name
            )
            VALUES (%s, %s)
            RETURNING {self._columns}
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id, role_name])
            row = cursor.fetchone()

        if row is None:
            raise RuntimeError("Employee role insert returned no row.")

        return self._to_employee_role(cast(tuple[Any, ...], row))

    def replace(
            self,
            employee_id: int,
            old_role_name: str,
            new_role_name: str,
    ) -> EmployeeRole | None:
        sql = f"""
            UPDATE employees_roles
            SET role_name = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE employee_id = %s
              AND role_name = %s
            RETURNING {self._columns}
        """

        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [new_role_name, employee_id, old_role_name],
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return self._to_employee_role(cast(tuple[Any, ...], row))

    def partial_update(
            self,
            employee_id: int,
            role_name: str,
            changes: Mapping[str, object],
    ) -> EmployeeRole | None:
        if "role_name" not in changes:
            return self.get_by_employee_id_and_role_name(
                employee_id,
                role_name,
            )

        new_role_name = str(changes["role_name"])

        sql = f"""
            UPDATE employees_roles
            SET role_name = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE employee_id = %s
              AND role_name = %s
            RETURNING {self._columns}
        """

        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [new_role_name, employee_id, role_name],
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return self._to_employee_role(cast(tuple[Any, ...], row))

    def delete_role_for_employee_by_role_name(
            self,
            employee_id: int,
            role_name: str,
    ) -> bool:
        sql = """
            DELETE FROM employees_roles
            WHERE employee_id = %s
              AND role_name = %s
            RETURNING id
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, [employee_id, role_name])
            row = cursor.fetchone()

        return row is not None

    @staticmethod
    def _to_employee_role(row: tuple[Any, ...]) -> EmployeeRole:
        return EmployeeRole(
            id=cast(int, row[0]),
            employee_id=cast(int, row[1]),
            role_name=cast(str, row[2]),
            created_at=row[3],
            updated_at=row[4],
        )