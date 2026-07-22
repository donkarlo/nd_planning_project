"""
This file is created so that Django by running it insert the arbitrary data in it for testing
"""

from typing import Final, TypeAlias

from django.core.management.base import BaseCommand
from django.db import connection, transaction

EmployeeRow: TypeAlias = tuple[str, str, str]
ShiftRow: TypeAlias = tuple[str, str, str, str]

EMPLOYEES: Final[tuple[EmployeeRow, ...]] = (
    (
        "Anna",
        "Muster",
        "anna@example.com",
    ),
    (
        "Mohammad",
        "Rahmani",
        "mohammad.rahmani.xyz@gmal.com",
    ),
    (
        "Mani",
        "Rad",
        "mani.rad@somewhere.com",
    ),
    (
        "Ali",
        "Zamni",
        "ali.zamni@somehow.com",
    ),
)

SHIFTS: Final[tuple[ShiftRow, ...]] = (
    (
        "anna@example.com",
        "2026-07-23T08:00:00+02:00",
        "2026-07-23T16:00:00+02:00",
        "Morning shift",
    ),
    (
        "anna@example.com",
        "2026-07-24T09:00:00+02:00",
        "2026-07-24T17:00:00+02:00",
        "Office shift",
    ),
    (
        "anna@example.com",
        "2026-07-25T07:00:00+02:00",
        "2026-07-25T15:00:00+02:00",
        "Early shift",
    ),
    (
        "mohammad.rahmani.xyz@gmal.com",
        "2026-07-23T08:30:00+02:00",
        "2026-07-23T16:30:00+02:00",
        "Morning shift",
    ),
    (
        "mohammad.rahmani.xyz@gmal.com",
        "2026-07-24T10:00:00+02:00",
        "2026-07-24T18:00:00+02:00",
        "Day shift",
    ),
    (
        "mohammad.rahmani.xyz@gmal.com",
        "2026-07-25T12:00:00+02:00",
        "2026-07-25T20:00:00+02:00",
        "Late shift",
    ),
    (
        "mani.rad@somewhere.com",
        "2026-07-23T06:00:00+02:00",
        "2026-07-23T14:00:00+02:00",
        "Early shift",
    ),
    (
        "mani.rad@somewhere.com",
        "2026-07-24T08:00:00+02:00",
        "2026-07-24T14:00:00+02:00",
        "Short shift",
    ),
    (
        "mani.rad@somewhere.com",
        "2026-07-25T14:00:00+02:00",
        "2026-07-25T22:00:00+02:00",
        "Evening shift",
    ),
    (
        "ali.zamni@somehow.com",
        "2026-07-23T07:30:00+02:00",
        "2026-07-23T15:30:00+02:00",
        "Regular shift",
    ),
    (
        "ali.zamni@somehow.com",
        "2026-07-24T11:00:00+02:00",
        "2026-07-24T19:00:00+02:00",
        "Late shift",
    ),
    (
        "ali.zamni@somehow.com",
        "2026-07-25T09:00:00+02:00",
        "2026-07-25T17:30:00+02:00",
        "Office shift",
    ),
)


class Command(BaseCommand):
    help = "Create idempotent demo employees and work shifts."

    def handle(
            self,
            *args: object,
            **options: object,
    ) -> None:
        employee_ids: dict[str, int] = {}

        with transaction.atomic():
            with connection.cursor() as cursor:
                for first_name, last_name, email in EMPLOYEES:
                    cursor.execute(
                        """
                        INSERT INTO employee (
                            first_name,
                            last_name,
                            email,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            NOW(),
                            NOW()
                        )
                        ON CONFLICT (email)
                        DO UPDATE SET
                            first_name = EXCLUDED.first_name,
                            last_name = EXCLUDED.last_name,
                            updated_at = NOW()
                        RETURNING id;
                        """,
                        [
                            first_name,
                            last_name,
                            email,
                        ],
                    )

                    result = cursor.fetchone()

                    if result is None:
                        raise RuntimeError(
                            f"Employee ID was not returned for {email}."
                        )

                    employee_ids[email] = int(result[0])

                for email, start_time, end_time, note in SHIFTS:
                    employee_id = employee_ids[email]

                    cursor.execute(
                        """
                        INSERT INTO employee_work_shift (
                            employee_id,
                            start_time,
                            end_time,
                            note,
                            created_at,
                            updated_at
                        )
                        SELECT
                            %s,
                            %s::timestamptz,
                            %s::timestamptz,
                            %s,
                            NOW(),
                            NOW()
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM employee_work_shift
                            WHERE employee_id = %s
                              AND start_time = %s::timestamptz
                              AND end_time = %s::timestamptz
                        );
                        """,
                        [
                            employee_id,
                            start_time,
                            end_time,
                            note,
                            employee_id,
                            start_time,
                            end_time,
                        ],
                    )

        self.stdout.write(
            self.style.SUCCESS(
                "Demo employees and work shifts are ready."
            )
        )
