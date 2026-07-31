from django.db import migrations

ADD_CONSTRAINT_SQL = """
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE employee_work_shift
ADD CONSTRAINT employee_work_shift_no_overlap
EXCLUDE USING GIST (
    employee_id WITH =,
    tstzrange(start_time, end_time, '[)') WITH &&
);
"""

DROP_CONSTRAINT_SQL = """
ALTER TABLE employee_work_shift
DROP CONSTRAINT IF EXISTS employee_work_shift_no_overlap;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("employee", "0002_employee_role"),
    ]

    operations = [
        migrations.RunSQL(
            sql=ADD_CONSTRAINT_SQL,
            reverse_sql=DROP_CONSTRAINT_SQL,
        ),
    ]