from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec='microseconds')

def _quoted(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'

class PlanningDatabase:
    """Canonical persistence boundary for ND Planning.

    The application uses ``action_types``, ``action_types_todos`` and ``plans``
    as the canonical tables. Older schemas are migrated transactionally.
    Runtime/history tables keep the historical node id strings so previously
    recorded intervals continue to resolve.
    """

    def __init__(self, file_path: Path) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.file_path), timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout=15000')
        connection.execute('PRAGMA foreign_keys=ON')
        return connection

    @staticmethod
    def _object_type(connection: sqlite3.Connection, name: str) -> Optional[str]:
        row = connection.execute('SELECT type FROM sqlite_master WHERE name=?', (str(name),)).fetchone()
        return None if row is None else str(row['type'])

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
        return {str(row['name']): row for row in connection.execute(f'PRAGMA table_info({_quoted(table)})')}

    @staticmethod
    def _foreign_key_targets(connection: sqlite3.Connection, table: str) -> set[str]:
        try:
            return {str(row['table']) for row in connection.execute(f'PRAGMA foreign_key_list({_quoted(table)})')}
        except sqlite3.DatabaseError:
            return set()

    @classmethod
    def _add_column(cls, connection: sqlite3.Connection, table: str, name: str, sql: str) -> None:
        if name not in cls._columns(connection, table):
            connection.execute(f'ALTER TABLE {_quoted(table)} ADD COLUMN {_quoted(name)} {sql}')

    def initialize_schema(self) -> None:
        with self.connect() as connection:
            connection.execute('PRAGMA foreign_keys=OFF')
            self._ensure_action_types(connection)
            self._ensure_history_tables(connection)
            self._ensure_runtime_tables(connection)
            self._ensure_todos(connection)
            self._ensure_plans(connection)
            self._ensure_recurring(connection)
            self._add_column(
                connection,
                'recurring_schedule_rules',
                'duration_seconds',
                'INTEGER',
            )
            connection.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            connection.execute("INSERT INTO meta(key,value) VALUES('clean_schema_version','3') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
            connection.commit()
            connection.execute('PRAGMA foreign_keys=ON')

    def _action_types_are_canonical(self, connection: sqlite3.Connection) -> bool:
        if self._object_type(connection, 'action_types') != 'table':
            return False
        columns = self._columns(connection, 'action_types')
        required = {'id_action_types', 'id', 'parent_id', 'title', 'duration_seconds', 'planned_duration_seconds', 'position', 'archived', 'created_at', 'updated_at'}
        if not required.issubset(columns):
            return False
        return int(columns['id_action_types']['pk'] or 0) == 1

    @staticmethod
    def _action_types_sql(table_name: str) -> str:
        return f'''
            CREATE TABLE {_quoted(table_name)}(
                id_action_types TEXT PRIMARY KEY,
                id TEXT NOT NULL UNIQUE,
                parent_id TEXT,
                title TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                planned_duration_seconds INTEGER,
                position INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(parent_id) REFERENCES {_quoted(table_name)}(id) ON DELETE CASCADE
            )
        '''

    def _ensure_action_types(self, connection: sqlite3.Connection) -> None:
        source_table: Optional[str] = None
        if self._object_type(connection, 'action_types') == 'table':
            source_table = 'action_types'
        elif self._object_type(connection, 'nodes') == 'table':
            source_table = 'nodes'
        if source_table == 'action_types' and self._action_types_are_canonical(connection):
            connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_action_types_id ON action_types(id)')
            connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_action_types_canonical ON action_types(id_action_types)')
            connection.execute('CREATE INDEX IF NOT EXISTS idx_action_types_parent_position ON action_types(parent_id, position)')
            return
        connection.execute('DROP TABLE IF EXISTS action_types__clean_new')
        connection.execute(self._action_types_sql('action_types__clean_new'))
        if source_table is not None:
            columns = self._columns(connection, source_table)
            rows = connection.execute(f'SELECT * FROM {_quoted(source_table)} ORDER BY rowid').fetchall()
            stamp = _now_text()
            for row in rows:
                old_id = str(row['id']) if 'id' in columns and row['id'] is not None and str(row['id']).strip() else None
                canonical = str(row['id_action_types']) if 'id_action_types' in columns and row['id_action_types'] is not None and str(row['id_action_types']).strip() else old_id
                if canonical is None:
                    canonical = uuid.uuid4().hex
                if old_id is None:
                    old_id = canonical
                duration = max(0, int(row['duration_seconds'] or 0)) if 'duration_seconds' in columns else 0
                planned = row['planned_duration_seconds'] if 'planned_duration_seconds' in columns else duration if duration > 0 else None
                connection.execute('''
                    INSERT OR IGNORE INTO action_types__clean_new(
                        id_action_types,id,parent_id,title,duration_seconds,
                        planned_duration_seconds,position,archived,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ''', (canonical, old_id, row['parent_id'] if 'parent_id' in columns else None, str(row['title'] or 'Action') if 'title' in columns else 'Action', duration, None if planned is None else max(1, int(planned)), int(row['position'] or 0) if 'position' in columns else 0, int(row['archived'] or 0) if 'archived' in columns else 0, str(row['created_at'] or stamp) if 'created_at' in columns else stamp, str(row['updated_at'] or stamp) if 'updated_at' in columns else stamp))
        if self._object_type(connection, 'action_types') == 'table':
            connection.execute('DROP TABLE action_types')
        if self._object_type(connection, 'nodes') == 'table':
            connection.execute('DROP TABLE nodes')
        connection.execute('ALTER TABLE action_types__clean_new RENAME TO action_types')
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_action_types_id ON action_types(id)')
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_action_types_canonical ON action_types(id_action_types)')
        connection.execute('CREATE INDEX IF NOT EXISTS idx_action_types_parent_position ON action_types(parent_id, position)')

    def _ensure_history_tables(self, connection: sqlite3.Connection) -> None:
        interval_rebuild = self._object_type(connection, 'intervals') == 'table' and 'nodes' in self._foreign_key_targets(connection, 'intervals')
        if interval_rebuild:
            connection.execute('ALTER TABLE intervals RENAME TO intervals__legacy_clean')
        event_rebuild = self._object_type(connection, 'events') == 'table' and 'nodes' in self._foreign_key_targets(connection, 'events')
        if event_rebuild:
            connection.execute('ALTER TABLE events RENAME TO events__legacy_clean')
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS intervals(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_seconds INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_intervals_node_started
                ON intervals(node_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_intervals_started_ended
                ON intervals(started_at, ended_at);

            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                node_id TEXT,
                event TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_node_time
                ON events(node_id, occurred_at);
            ''')
        if interval_rebuild:
            connection.execute('''
                INSERT INTO intervals(id,node_id,started_at,ended_at,duration_seconds)
                SELECT id,node_id,started_at,ended_at,duration_seconds
                FROM intervals__legacy_clean
                ''')
            connection.execute('DROP TABLE intervals__legacy_clean')
        if event_rebuild:
            connection.execute('''
                INSERT INTO events(id,occurred_at,node_id,event)
                SELECT id,occurred_at,node_id,event FROM events__legacy_clean
                ''')
            connection.execute('DROP TABLE events__legacy_clean')

    def _ensure_runtime_tables(self, connection: sqlite3.Connection) -> None:
        paused_rebuild = self._object_type(connection, 'paused_runs') == 'table' and 'nodes' in self._foreign_key_targets(connection, 'paused_runs')
        if paused_rebuild:
            connection.execute('ALTER TABLE paused_runs RENAME TO paused_runs__legacy_clean')
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS runtime_state(
                id INTEGER PRIMARY KEY CHECK(id=1),
                active INTEGER NOT NULL DEFAULT 0,
                root_node_id TEXT,
                queue_json TEXT NOT NULL DEFAULT '[]',
                queue_index INTEGER NOT NULL DEFAULT 0,
                remaining_seconds INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                paused INTEGER NOT NULL DEFAULT 0,
                last_heartbeat TEXT
            );
            INSERT OR IGNORE INTO runtime_state(id, active) VALUES(1, 0);

            CREATE TABLE IF NOT EXISTS paused_runs(
                root_node_id TEXT PRIMARY KEY,
                queue_json TEXT NOT NULL,
                queue_index INTEGER NOT NULL,
                remaining_seconds INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                saved_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_time_extensions(
                root_node_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                extra_seconds INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(root_node_id, node_id)
            );
            """)
        self._add_column(connection, 'runtime_state', 'elapsed_seconds', 'INTEGER NOT NULL DEFAULT 0')
        self._add_column(connection, 'runtime_state', 'last_heartbeat', 'TEXT')
        self._add_column(connection, 'paused_runs', 'elapsed_seconds', 'INTEGER NOT NULL DEFAULT 0')
        if paused_rebuild:
            columns = self._columns(connection, 'paused_runs__legacy_clean')
            elapsed_expression = 'elapsed_seconds' if 'elapsed_seconds' in columns else '0'
            connection.execute(f'''
                INSERT OR REPLACE INTO paused_runs(
                    root_node_id,queue_json,queue_index,remaining_seconds,elapsed_seconds,saved_at
                )
                SELECT root_node_id,queue_json,queue_index,remaining_seconds,
                       {elapsed_expression},saved_at
                FROM paused_runs__legacy_clean
                ''')
            connection.execute('DROP TABLE paused_runs__legacy_clean')

    def _ensure_todos(self, connection: sqlite3.Connection) -> None:
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS action_types_todos(
                id_action_types_todos INTEGER PRIMARY KEY AUTOINCREMENT,
                id_action_types TEXT NOT NULL,
                todo TEXT NOT NULL,
                is_done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(id_action_types)
                    REFERENCES action_types(id_action_types) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_action_types_todos_action_done
                ON action_types_todos(id_action_types, is_done, id_action_types_todos);
            ''')

    @staticmethod
    def _plans_sql(table_name: str) -> str:
        return f'''
            CREATE TABLE {_quoted(table_name)}(
                id_plans INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        '''

    @staticmethod
    def _plan_action_types_sql(table_name: str) -> str:
        return f'''
            CREATE TABLE {_quoted(table_name)}(
                id_plan_action_types INTEGER PRIMARY KEY AUTOINCREMENT,
                id_plans INTEGER NOT NULL,
                id_action_types TEXT NOT NULL,
                action_name TEXT NOT NULL DEFAULT '',
                run_time TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                last_run_at TEXT,
                handled_at TEXT,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(id_plans) REFERENCES plans(id_plans) ON DELETE CASCADE,
                FOREIGN KEY(id_action_types)
                    REFERENCES action_types(id_action_types) ON DELETE CASCADE
            )
        '''

    def _plans_are_canonical(self, connection: sqlite3.Connection) -> bool:
        if self._object_type(connection, 'plans') != 'table':
            return False
        columns = self._columns(connection, 'plans')
        if not {'id_plans', 'day', 'created_at', 'updated_at'}.issubset(columns):
            return False
        return 'id_action_types' not in columns

    def _plan_actions_are_canonical(self, connection: sqlite3.Connection) -> bool:
        if self._object_type(connection, 'plan_action_types') != 'table':
            return False
        columns = self._columns(connection, 'plan_action_types')
        required = {'id_plan_action_types', 'id_plans', 'id_action_types', 'action_name', 'run_time', 'duration_seconds', 'last_run_at', 'handled_at', 'position', 'created_at', 'updated_at'}
        return required.issubset(columns) and int(columns['id_plan_action_types']['pk'] or 0) == 1

    @staticmethod
    def _json_list(value) -> list:
        try:
            parsed = json.loads(str(value or '[]'))
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []

    def _snapshot_legacy_plan_rows(self, connection: sqlite3.Connection) -> list[dict]:
        rows: list[dict] = []
        daily_kind = self._object_type(connection, 'daily_time_plan_actions')
        if daily_kind in {'table', 'view'}:
            columns = self._columns(connection, 'daily_time_plan_actions')
            if {'day', 'id_action_types'}.issubset(columns):
                expressions = {'legacy_id': 'id_daily_time_plan_actions' if 'id_daily_time_plan_actions' in columns else 'NULL', 'id_action_types': 'id_action_types', 'action_name': 'action_name' if 'action_name' in columns else "''", 'day': 'day', 'run_time': 'run_time' if 'run_time' in columns else 'NULL', 'duration_seconds': 'duration_seconds' if 'duration_seconds' in columns else '0', 'last_run_at': 'last_run_at' if 'last_run_at' in columns else 'NULL', 'handled_at': 'handled_at' if 'handled_at' in columns else 'NULL', 'position': 'position' if 'position' in columns else '0', 'created_at': 'created_at' if 'created_at' in columns else 'NULL', 'updated_at': 'updated_at' if 'updated_at' in columns else 'NULL', 'reminders_json': 'reminders_json' if 'reminders_json' in columns else "'[]'", 'fired_reminders_json': 'fired_reminders_json' if 'fired_reminders_json' in columns else "'[]'"}
                sql = 'SELECT ' + ','.join((f'{expr} AS {name}' for name, expr in expressions.items())) + ' FROM daily_time_plan_actions ORDER BY day,position'
                for row in connection.execute(sql).fetchall():
                    rows.append(dict(row))
                if rows:
                    return rows
        if self._object_type(connection, 'plans') == 'table':
            columns = self._columns(connection, 'plans')
            if {'day', 'id_action_types'}.issubset(columns):
                for row in connection.execute('SELECT * FROM plans ORDER BY day,position').fetchall():
                    canonical = row['id_action_types']
                    title = ''
                    if canonical is not None:
                        action = connection.execute('SELECT title FROM action_types WHERE id_action_types=?', (str(canonical),)).fetchone()
                        title = '' if action is None else str(action['title'] or '')
                    rows.append({'legacy_id': None, 'id_action_types': canonical, 'action_name': title, 'day': str(row['day']), 'run_time': None, 'duration_seconds': 0, 'last_run_at': None, 'handled_at': None, 'position': int(row['position'] or 0), 'created_at': row['created_at'] if 'created_at' in columns else None, 'updated_at': row['created_at'] if 'created_at' in columns else None, 'reminders_json': '[]', 'fired_reminders_json': '[]'})
        return rows

    def _ensure_plans(self, connection: sqlite3.Connection) -> None:
        if self._plans_are_canonical(connection) and self._plan_actions_are_canonical(connection):
            self._ensure_plan_auxiliary_tables(connection)
            self._create_plan_indexes(connection)
            return
        legacy_rows = self._snapshot_legacy_plan_rows(connection)
        normalized_rows: list[dict] = []
        if self._plans_are_canonical(connection) and self._object_type(connection, 'plan_action_types') == 'table':
            try:
                for row in connection.execute('''
                    SELECT pa.id_plan_action_types AS legacy_id,pa.id_action_types,pa.action_name,
                           p.day,pa.run_time,pa.duration_seconds,pa.last_run_at,pa.handled_at,
                           pa.position,pa.created_at,pa.updated_at,'[]' AS reminders_json,
                           '[]' AS fired_reminders_json
                    FROM plan_action_types pa JOIN plans p ON p.id_plans=pa.id_plans
                    ORDER BY p.day,pa.position,pa.id_plan_action_types
                    ''').fetchall():
                    normalized_rows.append(dict(row))
            except sqlite3.DatabaseError:
                pass
        if normalized_rows:
            legacy_rows = normalized_rows
        for trigger in ('trg_daily_plan_insert', 'trg_daily_plan_update', 'trg_daily_plan_delete'):
            connection.execute(f'DROP TRIGGER IF EXISTS {trigger}')
        if self._object_type(connection, 'daily_time_plan_actions') == 'view':
            connection.execute('DROP VIEW daily_time_plan_actions')
        elif self._object_type(connection, 'daily_time_plan_actions') == 'table':
            connection.execute('DROP TABLE daily_time_plan_actions')
        for table in ('plan_action_notes', 'plan_action_type_reminders', 'plan_notes', 'plan_action_types'):
            if self._object_type(connection, table) == 'table':
                connection.execute(f'DROP TABLE {_quoted(table)}')
        if self._object_type(connection, 'plans') == 'view':
            connection.execute('DROP VIEW plans')
        elif self._object_type(connection, 'plans') == 'table':
            connection.execute('DROP TABLE plans')
        connection.execute(self._plans_sql('plans'))
        connection.execute(self._plan_action_types_sql('plan_action_types'))
        self._ensure_plan_auxiliary_tables(connection)
        plan_ids: dict[str, int] = {}
        for value in legacy_rows:
            canonical = value.get('id_action_types')
            if canonical is None:
                title = str(value.get('action_name') or '').strip()
                action = connection.execute('SELECT id_action_types FROM action_types WHERE title=? AND archived=0 ORDER BY position LIMIT 1', (title,)).fetchone()
                if action is None:
                    continue
                canonical = str(action['id_action_types'])
            canonical = str(canonical)
            if connection.execute('SELECT 1 FROM action_types WHERE id_action_types=? AND archived=0', (canonical,)).fetchone() is None:
                continue
            day_text = str(value.get('day') or '').strip()
            try:
                date.fromisoformat(day_text)
            except ValueError:
                continue
            stamp = str(value.get('created_at') or _now_text())
            if day_text not in plan_ids:
                connection.execute('INSERT OR IGNORE INTO plans(day,created_at,updated_at) VALUES(?,?,?)', (day_text, stamp, str(value.get('updated_at') or stamp)))
                plan_row = connection.execute('SELECT id_plans FROM plans WHERE day=?', (day_text,)).fetchone()
                if plan_row is None:
                    continue
                plan_ids[day_text] = int(plan_row['id_plans'])
            occurrence_id = value.get('legacy_id')
            params = (plan_ids[day_text], canonical, str(value.get('action_name') or ''), value.get('run_time'), max(0, int(value.get('duration_seconds') or 0)), value.get('last_run_at'), value.get('handled_at'), int(value.get('position') or 0), stamp, str(value.get('updated_at') or stamp))
            if occurrence_id is None:
                cursor = connection.execute('''INSERT INTO plan_action_types(
                        id_plans,id_action_types,action_name,run_time,duration_seconds,last_run_at,
                        handled_at,position,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)''', params)
                occurrence_id = int(cursor.lastrowid)
            else:
                connection.execute('''INSERT OR IGNORE INTO plan_action_types(
                        id_plan_action_types,id_plans,id_action_types,action_name,run_time,duration_seconds,last_run_at,
                        handled_at,position,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (int(occurrence_id), *params))
                occurrence_id = int(occurrence_id)
            reminders = self._json_list(value.get('reminders_json'))
            fired = {int(x) for x in self._json_list(value.get('fired_reminders_json')) if str(x).lstrip('-').isdigit()}
            for position, reminder in enumerate(reminders):
                text = str(reminder).strip()
                if not text:
                    continue
                connection.execute('''INSERT INTO plan_action_type_reminders(
                        id_plan_action_types,reminder_spec,position,fired_at,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?)''', (occurrence_id, text, position, str(value.get('updated_at') or stamp) if position in fired else None, stamp, str(value.get('updated_at') or stamp)))
        self._create_plan_indexes(connection)

    @staticmethod
    def _ensure_plan_auxiliary_tables(connection: sqlite3.Connection) -> None:
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS plan_action_type_reminders(
                id_plan_action_type_reminders INTEGER PRIMARY KEY AUTOINCREMENT,
                id_plan_action_types INTEGER NOT NULL,
                reminder_spec TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                fired_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(id_plan_action_types)
                    REFERENCES plan_action_types(id_plan_action_types) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS plan_notes(
                id_plan_notes INTEGER PRIMARY KEY AUTOINCREMENT,
                id_plans INTEGER NOT NULL,
                note TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(id_plans) REFERENCES plans(id_plans) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS plan_action_notes(
                id_plan_action_notes INTEGER PRIMARY KEY AUTOINCREMENT,
                id_plan_action_types INTEGER NOT NULL,
                note TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(id_plan_action_types)
                    REFERENCES plan_action_types(id_plan_action_types) ON DELETE CASCADE
            );
            ''')

    @staticmethod
    def _create_plan_indexes(connection: sqlite3.Connection) -> None:
        connection.executescript('''
            CREATE INDEX IF NOT EXISTS idx_plan_action_types_plan_position
                ON plan_action_types(id_plans,position,id_plan_action_types);
            CREATE INDEX IF NOT EXISTS idx_plan_action_types_action
                ON plan_action_types(id_action_types,id_plans);
            CREATE INDEX IF NOT EXISTS idx_plan_action_types_due
                ON plan_action_types(run_time,handled_at,last_run_at);
            CREATE INDEX IF NOT EXISTS idx_plan_action_type_reminders_parent
                ON plan_action_type_reminders(id_plan_action_types,position,id_plan_action_type_reminders);
            CREATE INDEX IF NOT EXISTS idx_plan_notes_plan_position
                ON plan_notes(id_plans,position,id_plan_notes);
            CREATE INDEX IF NOT EXISTS idx_plan_action_notes_parent_position
                ON plan_action_notes(id_plan_action_types,position,id_plan_action_notes);
            ''')

    def _ensure_recurring(self, connection: sqlite3.Connection) -> None:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS recurring_schedule_rules(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                start_day TEXT NOT NULL,
                run_time TEXT NOT NULL,
                recurrence_type TEXT NOT NULL,
                interval_value INTEGER NOT NULL DEFAULT 1,
                weekday INTEGER,
                day_of_month INTEGER,
                month_of_year INTEGER,
                day_of_year_month INTEGER,
                reminders_json TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_recurring_schedule_rules_enabled
                ON recurring_schedule_rules(enabled, start_day);
            CREATE INDEX IF NOT EXISTS idx_recurring_schedule_rules_node
                ON recurring_schedule_rules(node_id, enabled);
            """)

    def action_types(self, include_archived: bool=False) -> list[sqlite3.Row]:
        where = '' if include_archived else 'WHERE COALESCE(archived,0)=0'
        with self.connect() as connection:
            return connection.execute(f'''
                SELECT id_action_types,id,parent_id,title,duration_seconds,
                       planned_duration_seconds,position,archived,created_at,updated_at
                FROM action_types {where}
                ORDER BY CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END,
                         parent_id,position,title
                ''').fetchall()

    def action_type(self, node_id: str, include_archived: bool=False) -> Optional[sqlite3.Row]:
        archived = '' if include_archived else 'AND COALESCE(archived,0)=0'
        with self.connect() as connection:
            return connection.execute(f'''
                SELECT id_action_types,id,parent_id,title,duration_seconds,
                       planned_duration_seconds,position,archived,created_at,updated_at
                FROM action_types WHERE (id=? OR id_action_types=?) {archived} LIMIT 1
                ''', (str(node_id), str(node_id))).fetchone()

    def find_action_type_by_title(self, title: str) -> Optional[sqlite3.Row]:
        cleaned = str(title).strip()
        if not cleaned:
            return None
        with self.connect() as connection:
            return connection.execute('SELECT * FROM action_types WHERE title=? AND archived=0 ORDER BY CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, position LIMIT 1', (cleaned,)).fetchone()

    def action_type_by_canonical(self, canonical_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('SELECT * FROM action_types WHERE id_action_types=? AND COALESCE(archived,0)=0 LIMIT 1', (str(canonical_id),)).fetchone()

    def roots(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('SELECT * FROM action_types WHERE parent_id IS NULL AND COALESCE(archived,0)=0 ORDER BY position,title').fetchall()

    def children(self, parent_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('SELECT * FROM action_types WHERE parent_id=? AND COALESCE(archived,0)=0 ORDER BY position,title', (str(parent_id),)).fetchall()

    @staticmethod
    def _tree_maps(rows: list[sqlite3.Row]) -> tuple[dict[str, sqlite3.Row], dict[Optional[str], list[sqlite3.Row]]]:
        by_id: dict[str, sqlite3.Row] = {}
        by_parent: dict[Optional[str], list[sqlite3.Row]] = {}
        for row in rows:
            stable = str(row['id'])
            canonical = str(row['id_action_types'])
            by_id[stable] = row
            by_id[canonical] = row
            parent = None if row['parent_id'] is None else str(row['parent_id'])
            by_parent.setdefault(parent, []).append(row)
        for values in by_parent.values():
            values.sort(key=lambda row: (int(row['position'] or 0), str(row['title']).casefold()))
        return by_id, by_parent

    def parent_id(self, node_id: str) -> Optional[str]:
        rows = self.action_types()
        by_id, _ = self._tree_maps(rows)
        row = by_id.get(str(node_id))
        if row is None or row['parent_id'] is None:
            return None
        return str(row['parent_id'])

    def top_root_id(self, node_id: str) -> Optional[str]:
        rows = self.action_types()
        by_id, _ = self._tree_maps(rows)
        row = by_id.get(str(node_id))
        if row is None:
            return None
        current = str(row['id'])
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            current_row = by_id.get(current)
            if current_row is None:
                return None
            parent = current_row['parent_id']
            if parent is None or not str(parent):
                return current
            current = str(parent)
        return None

    def action_path(self, node_id: str) -> list[sqlite3.Row]:
        rows = self.action_types()
        by_id, _ = self._tree_maps(rows)
        current_row = by_id.get(str(node_id))
        result: list[sqlite3.Row] = []
        seen: set[str] = set()
        while current_row is not None:
            stable = str(current_row['id'])
            if stable in seen:
                break
            seen.add(stable)
            result.append(current_row)
            parent = current_row['parent_id']
            current_row = None if parent is None else by_id.get(str(parent))
        result.reverse()
        return result

    def path_title(self, node_id: str) -> str:
        rows = self.action_path(node_id)
        return ' > '.join((str(row['title']) for row in rows)) if rows else str(node_id)

    def subtree_ids(self, node_id: str) -> list[str]:
        action = self.action_type(str(node_id))
        if action is None:
            return []
        stable_id = str(action['id'])
        with self.connect() as connection:
            rows = connection.execute('''
                WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM action_types
                    WHERE id=? AND COALESCE(archived,0)=0
                    UNION ALL
                    SELECT child.id
                    FROM action_types AS child
                    JOIN subtree ON child.parent_id=subtree.id
                    WHERE COALESCE(child.archived,0)=0
                )
                SELECT id FROM subtree
                ''', (stable_id,)).fetchall()
        return [str(row['id']) for row in rows]

    def execution_sequence(self, node_id: str) -> list[str]:
        rows = self.action_types()
        by_id, by_parent = self._tree_maps(rows)
        start = by_id.get(str(node_id))
        if start is None:
            return []
        result: list[str] = []
        def visit(row: sqlite3.Row) -> None:
            stable = str(row['id'])
            children = by_parent.get(stable, [])
            if children:
                for child in children:
                    visit(child)
            else:
                result.append(stable)
        visit(start)
        return result

    def continuation_sequence(self, clicked_node_id: str) -> tuple[Optional[str], list[str]]:
        rows = self.action_types()
        by_id, by_parent = self._tree_maps(rows)
        clicked_row = by_id.get(str(clicked_node_id))
        if clicked_row is None:
            return (None, [])
        clicked = str(clicked_row['id'])
        root = clicked
        seen: set[str] = set()
        while root not in seen:
            seen.add(root)
            row = by_id.get(root)
            if row is None:
                return (None, [])
            parent = row['parent_id']
            if parent is None or not str(parent):
                break
            root = str(parent)

        def sequence(start_id: str) -> list[str]:
            start = by_id.get(start_id)
            if start is None:
                return []
            result: list[str] = []
            def visit(row: sqlite3.Row) -> None:
                stable = str(row['id'])
                children = by_parent.get(stable, [])
                if children:
                    for child in children:
                        visit(child)
                else:
                    result.append(stable)
            visit(start)
            return result

        full = sequence(root)
        if clicked == root:
            return (root, full)
        clicked_queue = sequence(clicked)
        if not clicked_queue:
            return (root, full)
        try:
            index = full.index(clicked_queue[0])
        except ValueError:
            index = 0
        return (root, full[index:])

    def default_planned_seconds(self, node_id: str) -> Optional[int]:
        row = self.action_type(node_id)
        if row is None:
            return None
        value = row['planned_duration_seconds']
        if value is not None:
            return max(1, int(value))
        legacy = max(0, int(row['duration_seconds'] or 0))
        return legacy if legacy > 0 else None

    def create_action_type(self, title: str, parent_id: Optional[str]=None, planned_duration_seconds: Optional[int]=None, *, node_id: Optional[str]=None) -> str:
        cleaned = str(title).strip()
        if not cleaned:
            raise ValueError('Action Type name cannot be empty')
        if parent_id is not None and self.action_type(str(parent_id)) is None:
            raise ValueError('Parent Action Type no longer exists')
        node_id = str(node_id or uuid.uuid4().hex)
        planned = None if planned_duration_seconds is None else max(1, int(planned_duration_seconds))
        stamp = _now_text()
        with self.connect() as connection:
            row = connection.execute('SELECT COALESCE(MAX(position),-1)+1 AS p FROM action_types WHERE parent_id IS ?', (None if parent_id is None else str(parent_id),)).fetchone()
            position = int(row['p'] if row else 0)
            connection.execute('''
                INSERT INTO action_types(
                    id_action_types,id,parent_id,title,duration_seconds,
                    planned_duration_seconds,position,archived,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,0,?,?)
                ''', (node_id, node_id, None if parent_id is None else str(parent_id), cleaned, 0 if planned is None else planned, planned, position, stamp, stamp))
        return node_id

    def update_action_type(self, node_id: str, title: str, planned_duration_seconds: Optional[int]) -> None:
        cleaned = str(title).strip()
        if not cleaned:
            raise ValueError('Action Type name cannot be empty')
        planned = None if planned_duration_seconds is None else max(1, int(planned_duration_seconds))
        action = self.action_type(node_id)
        if action is None:
            raise ValueError('Action Type no longer exists')
        with self.connect() as connection:
            cursor = connection.execute('''
                UPDATE action_types SET title=?,duration_seconds=?,
                    planned_duration_seconds=?,updated_at=? WHERE id_action_types=?
                ''', (cleaned, 0 if planned is None else planned, planned, _now_text(), str(action['id_action_types'])))
            if cursor.rowcount <= 0:
                raise ValueError('Action Type no longer exists')

    def archive_action_type(self, node_id: str) -> None:
        ids = self.subtree_ids(node_id)
        if not ids:
            return
        placeholders = ','.join(('?' for _ in ids))
        with self.connect() as connection:
            connection.execute(f'UPDATE action_types SET archived=1,updated_at=? WHERE id IN ({placeholders})', (_now_text(), *ids))

    def save_tree_layout(self, rows: list[tuple[str, Optional[str], int]]) -> None:
        stamp = _now_text()
        with self.connect() as connection:
            for node_id, parent_id, position in rows:
                connection.execute('UPDATE action_types SET parent_id=?,position=?,updated_at=? WHERE id=?', (parent_id, int(position), stamp, str(node_id)))

    def todos(self, node_id: str) -> list[sqlite3.Row]:
        row = self.action_type(node_id)
        if row is None:
            return []
        with self.connect() as connection:
            return connection.execute('''
                SELECT id_action_types_todos,todo,is_done,created_at,updated_at
                FROM action_types_todos WHERE id_action_types=?
                ORDER BY is_done,id_action_types_todos
                ''', (str(row['id_action_types']),)).fetchall()

    def add_todo(self, node_id: str, text: str) -> int:
        action = self.action_type(node_id)
        cleaned = str(text).strip()
        if action is None:
            raise ValueError('Action Type no longer exists')
        if not cleaned:
            raise ValueError('Todo cannot be empty')
        stamp = _now_text()
        with self.connect() as connection:
            cursor = connection.execute('INSERT INTO action_types_todos(id_action_types,todo,is_done,created_at,updated_at) VALUES(?,?,0,?,?)', (str(action['id_action_types']), cleaned, stamp, stamp))
            return int(cursor.lastrowid)

    def update_todo(self, todo_id: int, text: str) -> None:
        cleaned = str(text).strip()
        if not cleaned:
            raise ValueError('Todo cannot be empty')
        with self.connect() as connection:
            connection.execute('UPDATE action_types_todos SET todo=?,updated_at=? WHERE id_action_types_todos=?', (cleaned, _now_text(), int(todo_id)))

    def set_todo_done(self, todo_id: int, done: bool) -> None:
        with self.connect() as connection:
            connection.execute('UPDATE action_types_todos SET is_done=?,updated_at=? WHERE id_action_types_todos=?', (1 if done else 0, _now_text(), int(todo_id)))

    def delete_todo(self, todo_id: int) -> None:
        with self.connect() as connection:
            connection.execute('DELETE FROM action_types_todos WHERE id_action_types_todos=?', (int(todo_id),))

    def action_panel_todos(self) -> list[sqlite3.Row]:
        """TODOs shown under Action Types, from both supported TODO sources."""
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT id_action_types,todo_source,todo_id,todo,is_done,day,run_time
                FROM (
                    SELECT
                        t.id_action_types AS id_action_types,
                        'action_type' AS todo_source,
                        t.id_action_types_todos AS todo_id,
                        t.todo AS todo,
                        t.is_done AS is_done,
                        NULL AS day,
                        NULL AS run_time
                    FROM action_types_todos t

                    UNION ALL

                    SELECT
                        pa.id_action_types AS id_action_types,
                        'plan_action' AS todo_source,
                        pat.id_plan_action_type_todos AS todo_id,
                        pat.todo AS todo,
                        pat.is_done AS is_done,
                        p.day AS day,
                        pa.run_time AS run_time
                    FROM plan_action_type_todos pat
                    JOIN plan_action_types pa
                      ON pa.id_plan_action_types=pat.id_plan_action_types
                    JOIN plans p
                      ON p.id_plans=pa.id_plans
                )
                ORDER BY
                    id_action_types,
                    CASE WHEN day IS NULL THEN 0 ELSE 1 END,
                    day,
                    run_time,
                    todo_id
                """
            ).fetchall()

    @staticmethod
    def _plan_projection() -> str:
        return '''
            pa.id_plan_action_types,
            pa.id_plan_action_types AS id_plans_action,
            pa.id_plans,
            pa.id_action_types,
            pa.action_name,
            p.day,
            pa.run_time,
            pa.duration_seconds,
            pa.last_run_at,
            pa.handled_at,
            pa.position,
            pa.created_at,
            pa.updated_at,
            a.id AS node_id,
            a.title AS current_action_name,
            COALESCE((
                SELECT json_group_array(x.reminder_spec)
                FROM (
                    SELECT r.reminder_spec
                    FROM plan_action_type_reminders r
                    WHERE r.id_plan_action_types=pa.id_plan_action_types
                    ORDER BY r.position,r.id_plan_action_type_reminders
                ) x
            ),'[]') AS reminders_json,
            COALESCE((
                SELECT json_group_array(x.position)
                FROM (
                    SELECT r.position
                    FROM plan_action_type_reminders r
                    WHERE r.id_plan_action_types=pa.id_plan_action_types AND r.fired_at IS NOT NULL
                    ORDER BY r.position,r.id_plan_action_type_reminders
                ) x
            ),'[]') AS fired_reminders_json
        '''

    def plan_days(self) -> list[date]:
        values: set[date] = set()
        with self.connect() as connection:
            for row in connection.execute('SELECT day FROM plans ORDER BY day'):
                try:
                    values.add(date.fromisoformat(str(row['day'])))
                except ValueError:
                    pass
        return sorted(values)

    def plan(self, plan_action_id: int) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(f'''SELECT {self._plan_projection()}
                FROM plan_action_types pa
                JOIN plans p ON p.id_plans=pa.id_plans
                JOIN action_types a ON a.id_action_types=pa.id_action_types
                WHERE pa.id_plan_action_types=? LIMIT 1''', (int(plan_action_id),)).fetchone()

    def plans_for_day(self, day_value: date) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(f'''SELECT {self._plan_projection()}
                FROM plan_action_types pa
                JOIN plans p ON p.id_plans=pa.id_plans
                JOIN action_types a ON a.id_action_types=pa.id_action_types
                WHERE p.day=? ORDER BY pa.position,pa.id_plan_action_types''', (day_value.isoformat(),)).fetchall()

    def plans_between(self, first_day: date, last_day: date) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(f'''SELECT {self._plan_projection()}
                FROM plan_action_types pa
                JOIN plans p ON p.id_plans=pa.id_plans
                JOIN action_types a ON a.id_action_types=pa.id_action_types
                WHERE p.day>=? AND p.day<=?
                ORDER BY p.day,pa.position,pa.id_plan_action_types''', (first_day.isoformat(), last_day.isoformat())).fetchall()

    def _plan_container_id(self, connection: sqlite3.Connection, day_value: date) -> int:
        stamp = _now_text()
        connection.execute('INSERT OR IGNORE INTO plans(day,created_at,updated_at) VALUES(?,?,?)', (day_value.isoformat(), stamp, stamp))
        row = connection.execute('SELECT id_plans FROM plans WHERE day=?', (day_value.isoformat(),)).fetchone()
        if row is None:
            raise RuntimeError('Could not create Daily Plan')
        return int(row['id_plans'])

    def _replace_plan_reminders(self, connection: sqlite3.Connection, plan_action_id: int, reminders: Iterable[str]) -> None:
        connection.execute('DELETE FROM plan_action_type_reminders WHERE id_plan_action_types=?', (int(plan_action_id),))
        stamp = _now_text()
        for position, value in enumerate(reminders):
            text = str(value).strip()
            if not text:
                continue
            connection.execute('''INSERT INTO plan_action_type_reminders(
                    id_plan_action_types,reminder_spec,position,fired_at,created_at,updated_at
                ) VALUES(?,?,?,NULL,?,?)''', (int(plan_action_id), text, position, stamp, stamp))

    def add_plan(
        self,
        *,
        day_value: date,
        action_name: str,
        node_id: Optional[str],
        run_time: Optional[str],
        reminders: Iterable[str],
        duration_seconds: int,
    ) -> int:
        if not node_id:
            raise ValueError("Select an Action Type")

        action = self.action_type(str(node_id))
        if action is None:
            raise ValueError(
                "Action Type no longer exists"
            )

        canonical = str(
            action["id_action_types"]
        )

        title = (
            str(action_name or "").strip()
            or str(action["title"])
        )

        normalized_time = (
            None
            if run_time is None
            or not str(run_time).strip()
            else str(run_time).strip()
        )

        stamp = _now_text()

        with self.connect() as connection:
            plan_id = self._plan_container_id(
                connection,
                day_value,
            )

            existing = connection.execute(
                """
                SELECT id_plan_action_types
                FROM plan_action_types
                WHERE id_plans=?
                  AND id_action_types=?
                  AND COALESCE(run_time,'')=?
                ORDER BY updated_at DESC,
                         id_plan_action_types
                LIMIT 1
                """,
                (
                    plan_id,
                    canonical,
                    normalized_time or "",
                ),
            ).fetchone()

            if existing is not None:
                action_id = int(
                    existing[
                        "id_plan_action_types"
                    ]
                )

                connection.execute(
                    """
                    UPDATE plan_action_types
                    SET action_name=?,
                        run_time=?,
                        duration_seconds=?,
                        last_run_at=NULL,
                        handled_at=NULL,
                        updated_at=?
                    WHERE id_plan_action_types=?
                    """,
                    (
                        title,
                        normalized_time,
                        max(
                            0,
                            int(duration_seconds),
                        ),
                        stamp,
                        action_id,
                    ),
                )

                self._replace_plan_reminders(
                    connection,
                    action_id,
                    reminders,
                )

                return action_id

            row = connection.execute(
                """
                SELECT
                    COALESCE(MAX(position),-1)+1
                    AS p
                FROM plan_action_types
                WHERE id_plans=?
                """,
                (plan_id,),
            ).fetchone()

            position = int(
                row["p"] if row else 0
            )

            cursor = connection.execute(
                """
                INSERT INTO plan_action_types(
                    id_plans,
                    id_action_types,
                    action_name,
                    run_time,
                    duration_seconds,
                    last_run_at,
                    handled_at,
                    position,
                    created_at,
                    updated_at
                )
                VALUES(
                    ?,?,?,?,?,
                    NULL,NULL,?,?,?
                )
                """,
                (
                    plan_id,
                    canonical,
                    title,
                    normalized_time,
                    max(
                        0,
                        int(duration_seconds),
                    ),
                    position,
                    stamp,
                    stamp,
                ),
            )

            action_id = int(
                cursor.lastrowid
            )

            self._replace_plan_reminders(
                connection,
                action_id,
                reminders,
            )

            return action_id

    def update_plan(self, plan_id: int, *, day_value: date, action_name: str, node_id: Optional[str], run_time: Optional[str], reminders: Iterable[str], duration_seconds: int) -> None:
        old = self.plan(plan_id)
        if old is None:
            raise ValueError('Daily Plan action no longer exists')
        if not node_id:
            raise ValueError('Select an Action Type')
        action = self.action_type(str(node_id))
        if action is None:
            raise ValueError('Action Type no longer exists')
        canonical = str(action['id_action_types'])
        title = str(action_name or '').strip() or str(action['title'])
        stamp = _now_text()
        with self.connect() as connection:
            old_container = int(old['id_plans'])
            new_container = self._plan_container_id(connection, day_value)
            position = int(old['position'] or 0)
            if new_container != old_container:
                row = connection.execute('SELECT COALESCE(MAX(position),-1)+1 AS p FROM plan_action_types WHERE id_plans=?', (new_container,)).fetchone()
                position = int(row['p'] if row else 0)
            connection.execute('''UPDATE plan_action_types SET
                    id_plans=?,id_action_types=?,action_name=?,run_time=?,duration_seconds=?,
                    last_run_at=NULL,handled_at=NULL,position=?,updated_at=?
                WHERE id_plan_action_types=?''', (new_container, canonical, title, run_time, max(0, int(duration_seconds)), position, stamp, int(plan_id)))
            self._replace_plan_reminders(connection, int(plan_id), reminders)
            self._delete_empty_plan_container(connection, old_container)

    @staticmethod
    def _delete_empty_plan_container(connection: sqlite3.Connection, plan_container_id: int) -> None:
        row = connection.execute('SELECT 1 FROM plan_action_types WHERE id_plans=? LIMIT 1', (int(plan_container_id),)).fetchone()
        note = connection.execute('SELECT 1 FROM plan_notes WHERE id_plans=? LIMIT 1', (int(plan_container_id),)).fetchone()
        if row is None and note is None:
            connection.execute('DELETE FROM plans WHERE id_plans=?', (int(plan_container_id),))

    def delete_plan(self, plan_id: int) -> None:
        row = self.plan(plan_id)
        if row is None:
            return
        container_id = int(row['id_plans'])
        with self.connect() as connection:
            connection.execute('DELETE FROM plan_action_types WHERE id_plan_action_types=?', (int(plan_id),))
            self._delete_empty_plan_container(connection, container_id)

    def delete_all_plans_for_action(self, node_id: str) -> int:
        action = self.action_type(node_id, include_archived=True)
        if action is None:
            return 0
        canonical = str(action['id_action_types'])
        with self.connect() as connection:
            cursor = connection.execute('DELETE FROM plan_action_types WHERE id_action_types=?', (canonical,))
            connection.execute('DELETE FROM recurring_schedule_rules WHERE node_id=?', (str(action['id']),))
            connection.execute('DELETE FROM plans WHERE NOT EXISTS(SELECT 1 FROM plan_action_types pa WHERE pa.id_plans=plans.id_plans) AND NOT EXISTS(SELECT 1 FROM plan_notes pn WHERE pn.id_plans=plans.id_plans)')
            return max(0, int(cursor.rowcount))

    def move_plan(self, plan_id: int, target_day: date, target_index: Optional[int]=None) -> None:
        row = self.plan(plan_id)
        if row is None:
            return
        source_container = int(row['id_plans'])
        with self.connect() as connection:
            target_container = self._plan_container_id(connection, target_day)
            source_ids = [int(r['id_plan_action_types']) for r in connection.execute('SELECT id_plan_action_types FROM plan_action_types WHERE id_plans=? ORDER BY position,id_plan_action_types', (source_container,)) if int(r['id_plan_action_types']) != int(plan_id)]
            target_ids = source_ids if source_container == target_container else [int(r['id_plan_action_types']) for r in connection.execute('SELECT id_plan_action_types FROM plan_action_types WHERE id_plans=? ORDER BY position,id_plan_action_types', (target_container,)) if int(r['id_plan_action_types']) != int(plan_id)]
            index = len(target_ids) if target_index is None else max(0, min(int(target_index), len(target_ids)))
            target_ids.insert(index, int(plan_id))
            connection.execute('UPDATE plan_action_types SET id_plans=?,updated_at=? WHERE id_plan_action_types=?', (target_container, _now_text(), int(plan_id)))
            for pos, pid in enumerate(target_ids):
                connection.execute('UPDATE plan_action_types SET position=? WHERE id_plan_action_types=?', (pos, pid))
            if source_container != target_container:
                for pos, pid in enumerate(source_ids):
                    connection.execute('UPDATE plan_action_types SET position=? WHERE id_plan_action_types=?', (pos, pid))
                self._delete_empty_plan_container(connection, source_container)

    def mark_plan_handled(self, plan_id: int, *, ran: bool) -> None:
        stamp = _now_text()
        with self.connect() as connection:
            connection.execute('UPDATE plan_action_types SET handled_at=?,last_run_at=?,updated_at=? WHERE id_plan_action_types=?', (stamp, stamp if ran else None, stamp, int(plan_id)))

    def reset_plan_schedule(self, plan_id: int) -> None:
        with self.connect() as connection:
            connection.execute('UPDATE plan_action_types SET last_run_at=NULL,handled_at=NULL,updated_at=? WHERE id_plan_action_types=?', (_now_text(), int(plan_id)))
            connection.execute('UPDATE plan_action_type_reminders SET fired_at=NULL,updated_at=? WHERE id_plan_action_types=?', (_now_text(), int(plan_id)))

    def mark_plan_reminder_fired(self, plan_id: int, index: int) -> None:
        with self.connect() as connection:
            row = connection.execute('''SELECT id_plan_action_type_reminders FROM plan_action_type_reminders
                WHERE id_plan_action_types=? AND position=? ORDER BY id_plan_action_type_reminders LIMIT 1''', (int(plan_id), int(index))).fetchone()
            if row is not None:
                connection.execute('UPDATE plan_action_type_reminders SET fired_at=?,updated_at=? WHERE id_plan_action_type_reminders=?', (_now_text(), _now_text(), int(row['id_plan_action_type_reminders'])))

    def plan_notes(self, day_value: date) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('''SELECT pn.id_plan_notes,pn.note,pn.position FROM plan_notes pn
                JOIN plans p ON p.id_plans=pn.id_plans WHERE p.day=?
                ORDER BY pn.position,pn.id_plan_notes''', (day_value.isoformat(),)).fetchall()

    def add_plan_note(self, day_value: date, text: str) -> int:
        text = str(text).strip()
        if not text:
            raise ValueError('Note cannot be empty')
        with self.connect() as connection:
            plan_id = self._plan_container_id(connection, day_value)
            row = connection.execute('SELECT COALESCE(MAX(position),-1)+1 AS p FROM plan_notes WHERE id_plans=?', (plan_id,)).fetchone()
            stamp = _now_text()
            cursor = connection.execute('INSERT INTO plan_notes(id_plans,note,position,created_at,updated_at) VALUES(?,?,?,?,?)', (plan_id, text, int(row['p'] if row else 0), stamp, stamp))
            return int(cursor.lastrowid)

    def update_plan_note(self, note_id: int, text: str) -> None:
        text = str(text).strip()
        if not text:
            raise ValueError('Note cannot be empty')
        with self.connect() as connection:
            connection.execute('UPDATE plan_notes SET note=?,updated_at=? WHERE id_plan_notes=?', (text, _now_text(), int(note_id)))

    def delete_plan_note(self, note_id: int) -> None:
        with self.connect() as connection:
            row = connection.execute('SELECT id_plans FROM plan_notes WHERE id_plan_notes=?', (int(note_id),)).fetchone()
            connection.execute('DELETE FROM plan_notes WHERE id_plan_notes=?', (int(note_id),))
            if row is not None:
                self._delete_empty_plan_container(connection, int(row['id_plans']))

    def plan_action_notes(self, plan_action_id: int) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('SELECT id_plan_action_notes,note,position FROM plan_action_notes WHERE id_plan_action_types=? ORDER BY position,id_plan_action_notes', (int(plan_action_id),)).fetchall()

    def add_plan_action_note(self, plan_action_id: int, text: str) -> int:
        text = str(text).strip()
        if not text:
            raise ValueError('Note cannot be empty')
        with self.connect() as connection:
            row = connection.execute('SELECT COALESCE(MAX(position),-1)+1 AS p FROM plan_action_notes WHERE id_plan_action_types=?', (int(plan_action_id),)).fetchone()
            stamp = _now_text()
            cursor = connection.execute('INSERT INTO plan_action_notes(id_plan_action_types,note,position,created_at,updated_at) VALUES(?,?,?,?,?)', (int(plan_action_id), text, int(row['p'] if row else 0), stamp, stamp))
            return int(cursor.lastrowid)

    def update_plan_action_note(self, note_id: int, text: str) -> None:
        text = str(text).strip()
        if not text:
            raise ValueError('Note cannot be empty')
        with self.connect() as connection:
            connection.execute('UPDATE plan_action_notes SET note=?,updated_at=? WHERE id_plan_action_notes=?', (text, _now_text(), int(note_id)))

    def delete_plan_action_note(self, note_id: int) -> None:
        with self.connect() as connection:
            connection.execute('DELETE FROM plan_action_notes WHERE id_plan_action_notes=?', (int(note_id),))

    def plan_exists_for_action_day(self, node_id: str, day_value: date) -> bool:
        action = self.action_type(node_id)
        if action is None:
            return False
        with self.connect() as connection:
            row = connection.execute('''SELECT 1 FROM plan_action_types pa JOIN plans p ON p.id_plans=pa.id_plans
                WHERE pa.id_action_types=? AND p.day=? LIMIT 1''', (str(action['id_action_types']), day_value.isoformat())).fetchone()
        return row is not None

    def record_manual_start(self, node_id: str, at: Optional[datetime]=None) -> int:
        at = at or datetime.now().astimezone()
        action = self.action_type(node_id)
        if action is None:
            raise ValueError('Action Type no longer exists')
        duration = self.default_planned_seconds(node_id)
        if duration is None:
            duration = 30 * 60
        return self.add_plan(day_value=at.date(), action_name=str(action['title']), node_id=str(action['id']), run_time=at.strftime('%H:%M'), reminders=[], duration_seconds=max(0, int(duration)))

    def start_interval(
        self,
        node_id: str,
        started_at: datetime,
    ) -> int:
        node_id = str(node_id)
        started_at = started_at.astimezone()
        stamp = started_at.isoformat(
            timespec='microseconds'
        )

        with self.connect() as connection:
            # Reusing the same already-open Action prevents a second
            # interval when the same runtime is seen twice.
            existing = connection.execute(
                """
                SELECT id
                FROM intervals
                WHERE node_id=?
                  AND ended_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (node_id,),
            ).fetchone()

            if existing is not None:
                return int(existing['id'])

            # Planning has exactly one global running Action.
            # Starting another one atomically closes any stale open row.
            open_rows = connection.execute(
                """
                SELECT id,started_at
                FROM intervals
                WHERE ended_at IS NULL
                """
            ).fetchall()

            for row in open_rows:
                try:
                    old_start = datetime.fromisoformat(
                        str(row['started_at'])
                    ).astimezone()

                    seconds = max(
                        0,
                        int(
                            (
                                started_at
                                - old_start
                            ).total_seconds()
                        ),
                    )
                except Exception:
                    seconds = 0

                connection.execute(
                    """
                    UPDATE intervals
                    SET ended_at=?,
                        duration_seconds=?
                    WHERE id=?
                    """,
                    (
                        stamp,
                        seconds,
                        int(row['id']),
                    ),
                )

            cursor = connection.execute(
                """
                INSERT INTO intervals(
                    node_id,
                    started_at,
                    ended_at,
                    duration_seconds
                )
                VALUES(?,?,NULL,NULL)
                """,
                (
                    node_id,
                    stamp,
                ),
            )

            return int(cursor.lastrowid)

    def close_interval(self, interval_id: int, ended_at: datetime) -> None:
        with self.connect() as connection:
            row = connection.execute('SELECT started_at FROM intervals WHERE id=? AND ended_at IS NULL', (int(interval_id),)).fetchone()
            if row is None:
                return
            try:
                started = datetime.fromisoformat(str(row['started_at'])).astimezone()
            except Exception:
                started = ended_at
            seconds = max(0, int(round((ended_at - started).total_seconds())))
            connection.execute('UPDATE intervals SET ended_at=?,duration_seconds=? WHERE id=?', (ended_at.isoformat(timespec='microseconds'), seconds, int(interval_id)))

    def add_completed_interval(self, node_id: str, started_at: datetime, ended_at: datetime) -> int:
        if ended_at <= started_at:
            raise ValueError('End must be later than Start')
        seconds = max(1, int(round((ended_at - started_at).total_seconds())))
        with self.connect() as connection:
            cursor = connection.execute('INSERT INTO intervals(node_id,started_at,ended_at,duration_seconds) VALUES(?,?,?,?)', (str(node_id), started_at.isoformat(timespec='microseconds'), ended_at.isoformat(timespec='microseconds'), seconds))
            return int(cursor.lastrowid)

    def interval(self, interval_id: int) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('SELECT * FROM intervals WHERE id=?', (int(interval_id),)).fetchone()

    def update_interval(self, interval_id: int, started_at: datetime, ended_at: datetime) -> None:
        if ended_at <= started_at:
            raise ValueError('End must be later than Start')
        seconds = max(1, int(round((ended_at - started_at).total_seconds())))
        with self.connect() as connection:
            connection.execute('UPDATE intervals SET started_at=?,ended_at=?,duration_seconds=? WHERE id=?', (started_at.isoformat(timespec='microseconds'), ended_at.isoformat(timespec='microseconds'), seconds, int(interval_id)))

    def delete_interval(self, interval_id: int) -> None:
        with self.connect() as connection:
            connection.execute('DELETE FROM intervals WHERE id=?', (int(interval_id),))

    def intervals_for_nodes(self, node_ids: Iterable[str]) -> list[sqlite3.Row]:
        values = [str(value) for value in node_ids]
        if not values:
            return []
        placeholders = ','.join(('?' for _ in values))
        with self.connect() as connection:
            return connection.execute(f'SELECT * FROM intervals WHERE node_id IN ({placeholders}) ORDER BY started_at', tuple(values)).fetchall()

    def interval_rows_overlapping(self, started_at: datetime, ended_at: datetime) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('''
                SELECT id,node_id,started_at,ended_at,duration_seconds
                FROM intervals
                WHERE started_at < ? AND (ended_at IS NULL OR ended_at > ?)
                ORDER BY started_at
                ''', (ended_at.isoformat(timespec='microseconds'), started_at.isoformat(timespec='microseconds'))).fetchall()

    def previous_overlapping_interval(self, target_node_id: str, started_at: datetime, ended_at: datetime, *, exclude_node_id: Optional[str]=None) -> Optional[dict[str, object]]:
        excluded = {str(target_node_id)}
        if exclude_node_id:
            excluded.add(str(exclude_node_id))
        placeholders = ','.join(('?' for _ in excluded))
        params: list[object] = list(excluded)
        params.extend([ended_at.isoformat(timespec='microseconds'), started_at.isoformat(timespec='microseconds')])
        with self.connect() as connection:
            row = connection.execute(f'''
                SELECT id,node_id,started_at,ended_at,duration_seconds
                FROM intervals
                WHERE node_id NOT IN ({placeholders})
                  AND ended_at IS NOT NULL
                  AND started_at < ?
                  AND ended_at > ?
                ORDER BY ended_at DESC,id DESC
                LIMIT 1
                ''', tuple(params)).fetchone()
        if row is None:
            return None
        try:
            previous_start = datetime.fromisoformat(str(row['started_at'])).astimezone()
            previous_end = datetime.fromisoformat(str(row['ended_at'])).astimezone()
        except Exception:
            return None
        overlap_start = max(started_at, previous_start)
        overlap_end = min(ended_at, previous_end)
        if overlap_end <= overlap_start:
            return None
        return {'id': int(row['id']), 'node_id': str(row['node_id']), 'started_at': previous_start, 'ended_at': previous_end, 'overlap_seconds': max(0, int(round((overlap_end - overlap_start).total_seconds())))}

    def subtract_interval_overlap(self, interval_id: int, started_at: datetime, ended_at: datetime) -> tuple[str, int]:
        row = self.interval(int(interval_id))
        if row is None or not row['ended_at']:
            return ('', 0)
        try:
            previous_start = datetime.fromisoformat(str(row['started_at'])).astimezone()
            previous_end = datetime.fromisoformat(str(row['ended_at'])).astimezone()
        except Exception:
            return ('', 0)
        overlap_start = max(started_at, previous_start)
        overlap_end = min(ended_at, previous_end)
        if overlap_end <= overlap_start:
            return (str(row['node_id']), 0)
        removed = max(0, int(round((overlap_end - overlap_start).total_seconds())))
        if removed <= 0:
            return (str(row['node_id']), 0)
        node_id = str(row['node_id'])
        left_seconds = max(0, int(round((overlap_start - previous_start).total_seconds())))
        right_seconds = max(0, int(round((previous_end - overlap_end).total_seconds())))
        with self.connect() as connection:
            if overlap_start <= previous_start and overlap_end >= previous_end:
                connection.execute('DELETE FROM intervals WHERE id=?', (int(interval_id),))
            elif overlap_start <= previous_start:
                connection.execute('UPDATE intervals SET started_at=?,duration_seconds=? WHERE id=?', (overlap_end.isoformat(timespec='microseconds'), right_seconds, int(interval_id)))
            elif overlap_end >= previous_end:
                connection.execute('UPDATE intervals SET ended_at=?,duration_seconds=? WHERE id=?', (overlap_start.isoformat(timespec='microseconds'), left_seconds, int(interval_id)))
            else:
                connection.execute('UPDATE intervals SET ended_at=?,duration_seconds=? WHERE id=?', (overlap_start.isoformat(timespec='microseconds'), left_seconds, int(interval_id)))
                connection.execute('''
                    INSERT INTO intervals(node_id,started_at,ended_at,duration_seconds)
                    VALUES(?,?,?,?)
                    ''', (node_id, overlap_end.isoformat(timespec='microseconds'), previous_end.isoformat(timespec='microseconds'), right_seconds))
        return (node_id, removed)

    def canonical_interval_segments(
        self,
        started_at: datetime,
        ended_at: datetime,
    ) -> list[dict]:
        if ended_at <= started_at:
            return []

        now = datetime.now().astimezone()

        parsed: list[dict] = []

        for row in self.interval_rows_overlapping(
            started_at,
            ended_at,
        ):
            try:
                begin = datetime.fromisoformat(
                    str(row['started_at'])
                ).astimezone()

                finish = (
                    now
                    if not row['ended_at']
                    else datetime.fromisoformat(
                        str(row['ended_at'])
                    ).astimezone()
                )
            except Exception:
                continue

            begin = max(
                begin,
                started_at,
            )

            finish = min(
                finish,
                ended_at,
                now,
            )

            if finish <= begin:
                continue

            parsed.append({
                'id': int(row['id']),
                'node_id': str(row['node_id']),
                'started_at': begin,
                'ended_at': finish,
            })

        parsed.sort(
            key=lambda value: (
                value['started_at'],
                value['id'],
            )
        )

        # Two devices can report the same logical start a few seconds
        # apart.  Keep one segment and use the earlier ending.
        merged: list[dict] = []

        for segment in parsed:
            previous = (
                merged[-1]
                if merged
                else None
            )

            duplicate = (
                previous is not None
                and previous['node_id']
                    == segment['node_id']
                and abs(
                    (
                        segment['started_at']
                        - previous['started_at']
                    ).total_seconds()
                ) <= 5
                and segment['started_at']
                    < previous['ended_at']
            )

            if duplicate:
                previous['ended_at'] = min(
                    previous['ended_at'],
                    segment['ended_at'],
                )
                continue

            merged.append(segment)

        # A new Action start ends the previous globally-running Action.
        canonical: list[dict] = []

        for index, segment in enumerate(
            merged
        ):
            finish = segment['ended_at']

            if index + 1 < len(merged):
                finish = min(
                    finish,
                    merged[index + 1][
                        'started_at'
                    ],
                )

            if finish <= segment['started_at']:
                continue

            canonical.append({
                'id': segment['id'],
                'node_id': segment[
                    'node_id'
                ],
                'started_at': segment[
                    'started_at'
                ],
                'ended_at': finish,
            })

        return canonical

    def time_spent_seconds(
        self,
        node_id: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> int:
        ids = set(
            self.subtree_ids(node_id)
        )

        if (
            not ids
            or ended_at <= started_at
        ):
            return 0

        total = 0.0

        for segment in (
            self.canonical_interval_segments(
                started_at,
                ended_at,
            )
        ):
            if (
                segment['node_id']
                not in ids
            ):
                continue

            total += (
                segment['ended_at']
                - segment['started_at']
            ).total_seconds()

        return max(
            0,
            int(round(total)),
        )

    def activity_days(self) -> list[date]:
        values: set[date] = set(self.plan_days())
        with self.connect() as connection:
            rows = connection.execute('SELECT started_at FROM intervals ORDER BY started_at').fetchall()
        for row in rows:
            try:
                values.add(datetime.fromisoformat(str(row['started_at'])).astimezone().date())
            except Exception:
                pass
        return sorted(values)

    def day_node_stats(self, day_value: date) -> dict[str, dict[str, object]]:
        now = datetime.now().astimezone()
        timezone = now.tzinfo
        start = datetime(day_value.year, day_value.month, day_value.day, tzinfo=timezone)
        end = now if day_value == now.date() else start + timedelta(hours=23, minutes=50)
        if end <= start:
            return {}
        action_rows = self.action_types(include_archived=True)
        parent = {str(row['id']): None if row['parent_id'] is None else str(row['parent_id']) for row in action_rows}
        stats: dict[str, dict[str, object]] = {}
        for row in self.interval_rows_overlapping(start, end):
            node_id = str(row['node_id'] or '')
            if not node_id:
                continue
            try:
                interval_start = datetime.fromisoformat(str(row['started_at'])).astimezone()
                interval_end = now if not row['ended_at'] else datetime.fromisoformat(str(row['ended_at'])).astimezone()
            except Exception:
                continue
            overlap_start = max(start, interval_start)
            overlap_end = min(end, interval_end, now)
            if overlap_end <= overlap_start:
                continue
            seconds = max(0, int((overlap_end - overlap_start).total_seconds()))
            chain: list[str] = []
            current: Optional[str] = node_id
            seen: set[str] = set()
            while current is not None and current not in seen:
                seen.add(current)
                chain.append(current)
                current = parent.get(current)
            for ancestor in chain:
                stat = stats.setdefault(ancestor, {'seconds': 0, 'first': None, 'last': None, 'open': False})
                stat['seconds'] = int(stat['seconds']) + seconds
                first = stat['first']
                last = stat['last']
                stat['first'] = overlap_start if first is None else min(first, overlap_start)
                stat['last'] = overlap_end if last is None else max(last, overlap_end)
                if not row['ended_at']:
                    stat['open'] = True
        return stats

    def log_event(self, node_id: Optional[str], event: str) -> None:
        with self.connect() as connection:
            connection.execute('INSERT INTO events(occurred_at,node_id,event) VALUES(?,?,?)', (_now_text(), None if node_id is None else str(node_id), str(event)))

    def save_runtime(self, *, active: bool, root_node_id: Optional[str], queue: list[str], queue_index: int, remaining_seconds: int, elapsed_seconds: int, paused: bool) -> None:
        with self.connect() as connection:
            connection.execute('''
                UPDATE runtime_state SET active=?,root_node_id=?,queue_json=?,
                    queue_index=?,remaining_seconds=?,elapsed_seconds=?,paused=?,last_heartbeat=?
                WHERE id=1
                ''', (1 if active else 0, root_node_id, json.dumps(queue, ensure_ascii=False), int(queue_index), max(0, int(remaining_seconds)), max(0, int(elapsed_seconds)), 1 if paused else 0, _now_text()))

    def load_runtime(self) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM runtime_state WHERE id=1').fetchone()
        if row is None or not bool(row['active']):
            return None
        try:
            queue = [str(value) for value in json.loads(str(row['queue_json'] or '[]'))]
        except Exception:
            queue = []
        return {'root_node_id': str(row['root_node_id'] or ''), 'queue': queue, 'queue_index': int(row['queue_index'] or 0), 'remaining_seconds': max(0, int(row['remaining_seconds'] or 0)), 'elapsed_seconds': max(0, int(row['elapsed_seconds'] or 0)), 'paused': bool(row['paused']), 'last_heartbeat': row['last_heartbeat']}

    def save_paused_run(self, root_node_id: str, queue: list[str], queue_index: int, remaining_seconds: int, elapsed_seconds: int) -> None:
        with self.connect() as connection:
            connection.execute('''
                INSERT INTO paused_runs(
                    root_node_id,queue_json,queue_index,remaining_seconds,
                    elapsed_seconds,saved_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(root_node_id) DO UPDATE SET
                    queue_json=excluded.queue_json,
                    queue_index=excluded.queue_index,
                    remaining_seconds=excluded.remaining_seconds,
                    elapsed_seconds=excluded.elapsed_seconds,
                    saved_at=excluded.saved_at
                ''', (str(root_node_id), json.dumps(queue, ensure_ascii=False), int(queue_index), max(0, int(remaining_seconds)), max(0, int(elapsed_seconds)), _now_text()))

    def paused_runs(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('SELECT * FROM paused_runs ORDER BY saved_at DESC').fetchall()

    def load_paused_run(self, root_node_id: str) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM paused_runs WHERE root_node_id=?', (str(root_node_id),)).fetchone()
        if row is None:
            return None
        try:
            queue = [str(value) for value in json.loads(str(row['queue_json'] or '[]'))]
        except Exception:
            queue = []
        return {'queue': queue, 'queue_index': int(row['queue_index'] or 0), 'remaining_seconds': max(0, int(row['remaining_seconds'] or 0)), 'elapsed_seconds': max(0, int(row['elapsed_seconds'] or 0)), 'saved_at': row['saved_at']}

    def add_paused_remaining(self, root_node_id: str, seconds: int) -> bool:
        value = max(0, int(seconds))
        if value <= 0:
            return False
        with self.connect() as connection:
            cursor = connection.execute('UPDATE paused_runs SET remaining_seconds=remaining_seconds+?,saved_at=? WHERE root_node_id=?', (value, _now_text(), str(root_node_id)))
            return int(cursor.rowcount or 0) > 0

    def delete_paused_run(self, root_node_id: str) -> None:
        with self.connect() as connection:
            connection.execute('DELETE FROM paused_runs WHERE root_node_id=?', (str(root_node_id),))

    def add_run_extension(self, root_node_id: str, node_id: str, seconds: int) -> None:
        value = max(1, int(seconds))
        with self.connect() as connection:
            connection.execute('''
                INSERT INTO run_time_extensions(root_node_id,node_id,extra_seconds,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(root_node_id,node_id) DO UPDATE SET
                    extra_seconds=run_time_extensions.extra_seconds+excluded.extra_seconds,
                    updated_at=excluded.updated_at
                ''', (str(root_node_id), str(node_id), value, _now_text()))

    def extension_seconds(self, root_node_id: str, node_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute('SELECT extra_seconds FROM run_time_extensions WHERE root_node_id=? AND node_id=?', (str(root_node_id), str(node_id))).fetchone()
        return 0 if row is None else max(0, int(row['extra_seconds'] or 0))

    def clear_run_extensions(self, root_node_id: str) -> None:
        with self.connect() as connection:
            connection.execute('DELETE FROM run_time_extensions WHERE root_node_id=?', (str(root_node_id),))

    def recover_open_intervals(self) -> None:
        runtime = self.load_runtime()
        if runtime is not None:
            return
        stamp = datetime.now().astimezone()
        with self.connect() as connection:
            rows = connection.execute('SELECT id,started_at FROM intervals WHERE ended_at IS NULL').fetchall()
            for row in rows:
                try:
                    started = datetime.fromisoformat(str(row['started_at'])).astimezone()
                    seconds = max(0, int((stamp - started).total_seconds()))
                except Exception:
                    seconds = 0
                connection.execute('UPDATE intervals SET ended_at=?,duration_seconds=? WHERE id=?', (stamp.isoformat(timespec='microseconds'), seconds, int(row['id'])))

    def open_interval_for_node(self, node_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute('SELECT * FROM intervals WHERE node_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1', (str(node_id),)).fetchone()

    def create_recurring_rule(self, *, node_id: str, start_day: date, run_time: str, recurrence_type: str, interval_value: int, weekday: Optional[int], day_of_month: Optional[int], month_of_year: Optional[int], day_of_year_month: Optional[int], reminders: Iterable[str]) -> int:
        action = self.action_type(node_id)
        if action is None:
            raise ValueError('Action Type no longer exists')
        stable_id = str(action['id'])
        stamp = _now_text()
        with self.connect() as connection:
            cursor = connection.execute('''
                INSERT INTO recurring_schedule_rules(
                    node_id,start_day,run_time,recurrence_type,interval_value,
                    weekday,day_of_month,month_of_year,day_of_year_month,
                    reminders_json,enabled,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)
                ''', (stable_id, start_day.isoformat(), str(run_time), str(recurrence_type), max(1, int(interval_value)), weekday, day_of_month, month_of_year, day_of_year_month, json.dumps([str(v).strip() for v in reminders if str(v).strip()], ensure_ascii=False), stamp, stamp))
            return int(cursor.lastrowid)

    def recurring_rules(self, enabled_only: bool=True) -> list[sqlite3.Row]:
        where = 'WHERE enabled=1' if enabled_only else ''
        with self.connect() as connection:
            return connection.execute(f'SELECT * FROM recurring_schedule_rules {where} ORDER BY id').fetchall()

    def delete_recurring_for_node(self, node_id: str) -> None:
        action = self.action_type(node_id, include_archived=True)
        stable = str(action['id']) if action is not None else str(node_id)
        with self.connect() as connection:
            connection.execute('DELETE FROM recurring_schedule_rules WHERE node_id=?', (stable,))

