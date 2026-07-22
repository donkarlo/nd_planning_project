-- Employee CREATE
INSERT INTO employee (first_name, last_name, email)
VALUES (%s, %s, %s)
RETURNING id, first_name, last_name, email, created_at, updated_at;

-- Employee READ: list
SELECT id, first_name, last_name, email, created_at, updated_at
FROM employee
ORDER BY last_name, first_name, id;

-- Employee READ: detail
SELECT id, first_name, last_name, email, created_at, updated_at
FROM employee
WHERE id = %s;

-- Employee UPDATE: complete replacement
UPDATE employee
SET first_name = %s,
    last_name = %s,
    email = %s,
    updated_at = CURRENT_TIMESTAMP
WHERE id = %s
RETURNING id, first_name, last_name, email, created_at, updated_at;

-- Employee PATCH is generated only from this safe whitelist:
-- first_name, last_name, email
UPDATE employee
SET last_name = %s,
    updated_at = CURRENT_TIMESTAMP
WHERE id = %s
RETURNING id, first_name, last_name, email, created_at, updated_at;

-- Employee DELETE
DELETE FROM employee
WHERE id = %s
RETURNING id;

-- Work-shift CREATE
INSERT INTO employee_work_shift (employee_id, start_time, end_time, note)
VALUES (%s, %s, %s, %s)
RETURNING id, employee_id, start_time, end_time, note, created_at, updated_at;

-- Work-shift READ: list for one employee
SELECT id, employee_id, start_time, end_time, note, created_at, updated_at
FROM employee_work_shift
WHERE employee_id = %s
ORDER BY start_time, id;

-- Work-shift READ: detail
SELECT id, employee_id, start_time, end_time, note, created_at, updated_at
FROM employee_work_shift
WHERE employee_id = %s AND id = %s;

-- Work-shift UPDATE: complete replacement
UPDATE employee_work_shift
SET start_time = %s,
    end_time = %s,
    note = %s,
    updated_at = CURRENT_TIMESTAMP
WHERE employee_id = %s AND id = %s
RETURNING id, employee_id, start_time, end_time, note, created_at, updated_at;

-- Work-shift PATCH is generated only from this safe whitelist:
-- start_time, end_time, note
UPDATE employee_work_shift
SET note = %s,
    updated_at = CURRENT_TIMESTAMP
WHERE employee_id = %s AND id = %s
RETURNING id, employee_id, start_time, end_time, note, created_at, updated_at;

-- Work-shift DELETE
DELETE FROM employee_work_shift
WHERE employee_id = %s AND id = %s
RETURNING id;

-- Overlap validation for half-open intervals [start_time, end_time)
SELECT EXISTS (
    SELECT 1
    FROM employee_work_shift
    WHERE employee_id = %s
      AND start_time < %s
      AND end_time > %s
);

-- Employee summary
SELECT
    COUNT(*),
    COALESCE(SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 3600.0), 0)
FROM employee_work_shift
WHERE employee_id = %s;

-- Global statistics
SELECT
    (SELECT COUNT(*) FROM employee),
    COUNT(*),
    COALESCE(SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 3600.0), 0)
FROM employee_work_shift;
