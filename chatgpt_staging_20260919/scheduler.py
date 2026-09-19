from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from .database import PlanningDatabase
from .runtime import PlanningRuntime

_TIME_PATTERN = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")
_REMINDER_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*"
    r"(days?|d|hours?|hrs?|hr|h|minutes?|mins?|min|m)\s*"
    r"befor(?:e)?\s*$",
    re.IGNORECASE,
)

RECURRENCE_ONE_TIME = "one_time"
RECURRENCE_WEEKLY = "weekly"
RECURRENCE_MONTHLY = "monthly"
RECURRENCE_YEARLY = "yearly"
RECURRENCE_EVERY_N_DAYS = "every_n_days"
RECURRENCE_EVERY_N_WEEKS = "every_n_weeks"

# Recurring rules are the source of truth. Only a small rolling set of concrete
# plans is materialized so long-running schedules do not grow the plans table
# by hundreds or thousands of rows at once.
_MATERIALIZED_OCCURRENCES = {
    RECURRENCE_EVERY_N_DAYS: 14,
    RECURRENCE_WEEKLY: 8,
    RECURRENCE_EVERY_N_WEEKS: 8,
    RECURRENCE_MONTHLY: 6,
    RECURRENCE_YEARLY: 2,
}


def normalize_run_time(value: Optional[str]) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    if not text or text.casefold() in {"pending", "pernding", "unplanned"}:
        return None
    match = _TIME_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError("Time must be HH:MM, for example 09:30")
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"


def reminder_delta(value: str) -> timedelta:
    match = _REMINDER_PATTERN.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(
            f'Invalid reminder "{value}". Examples: 1 day before, 2 hours before, 10 mins before'
        )
    amount = float(match.group(1))
    unit = match.group(2).lower()
    seconds = amount * (86400 if unit.startswith("d") else 3600 if unit.startswith("h") else 60)
    if seconds <= 0:
        raise ValueError("Reminder duration must be greater than zero")
    return timedelta(seconds=seconds)


def validate_recurrence(
    recurrence_type: str,
    interval_value: int,
    weekday: Optional[int],
    day_of_month: Optional[int],
    month_of_year: Optional[int],
    day_of_year_month: Optional[int],
) -> None:
    valid = {
        RECURRENCE_WEEKLY,
        RECURRENCE_MONTHLY,
        RECURRENCE_YEARLY,
        RECURRENCE_EVERY_N_DAYS,
        RECURRENCE_EVERY_N_WEEKS,
    }
    if recurrence_type not in valid:
        raise ValueError("Unsupported recurrence type")
    if recurrence_type in {RECURRENCE_EVERY_N_DAYS, RECURRENCE_EVERY_N_WEEKS}:
        if int(interval_value) < 1:
            raise ValueError("Recurrence interval must be at least 1")
    if recurrence_type == RECURRENCE_WEEKLY:
        if weekday is None or not 0 <= int(weekday) <= 6:
            raise ValueError("Choose a weekday")
    if recurrence_type == RECURRENCE_MONTHLY:
        if day_of_month is None or not 1 <= int(day_of_month) <= 31:
            raise ValueError("Choose a day of month")
    if recurrence_type == RECURRENCE_YEARLY:
        if month_of_year is None or not 1 <= int(month_of_year) <= 12:
            raise ValueError("Choose a month")
        if day_of_year_month is None or not 1 <= int(day_of_year_month) <= 31:
            raise ValueError("Choose a day")
        try:
            date(2024, int(month_of_year), int(day_of_year_month))
        except ValueError as error:
            raise ValueError("Choose a valid yearly date") from error


def _month_candidate(year: int, month: int, day_value: int) -> Optional[date]:
    if not 1 <= int(month) <= 12:
        return None
    if not 1 <= int(day_value) <= monthrange(year, month)[1]:
        return None
    return date(year, month, int(day_value))


def iter_occurrences(rule, first_day: date, last_day: date):
    try:
        start = date.fromisoformat(str(rule["start_day"]))
    except ValueError:
        return
    if last_day < start:
        return

    recurrence = str(rule["recurrence_type"])
    lower = max(first_day, start)

    if recurrence == RECURRENCE_WEEKLY:
        weekday = int(rule["weekday"] if rule["weekday"] is not None else start.weekday())
        first = start + timedelta(days=(weekday - start.weekday()) % 7)
        if first < lower:
            delta = (lower - first).days
            first += timedelta(days=((delta + 6) // 7) * 7)
        current = first
        while current <= last_day:
            yield current
            current += timedelta(days=7)
        return

    if recurrence == RECURRENCE_EVERY_N_DAYS:
        step_days = max(1, int(rule["interval_value"] or 1))
        first = start
        if first < lower:
            delta = (lower - first).days
            first += timedelta(days=((delta + step_days - 1) // step_days) * step_days)
        current = first
        while current <= last_day:
            yield current
            current += timedelta(days=step_days)
        return

    if recurrence == RECURRENCE_EVERY_N_WEEKS:
        step_days = max(1, int(rule["interval_value"] or 1)) * 7
        first = start
        if first < lower:
            delta = (lower - first).days
            first += timedelta(days=((delta + step_days - 1) // step_days) * step_days)
        current = first
        while current <= last_day:
            yield current
            current += timedelta(days=step_days)
        return

    if recurrence == RECURRENCE_MONTHLY:
        target_day = int(rule["day_of_month"] or start.day)
        year, month = start.year, start.month
        while True:
            candidate = _month_candidate(year, month, target_day)
            if candidate is not None and candidate >= start:
                if candidate > last_day:
                    return
                if candidate >= lower:
                    yield candidate
            month += 1
            if month > 12:
                month = 1
                year += 1
        return

    if recurrence == RECURRENCE_YEARLY:
        target_month = int(rule["month_of_year"] or start.month)
        target_day = int(rule["day_of_year_month"] or start.day)
        year = start.year
        while True:
            candidate = _month_candidate(year, target_month, target_day)
            if candidate is not None and candidate >= start:
                if candidate > last_day:
                    return
                if candidate >= lower:
                    yield candidate
            year += 1


def next_occurrence(rule, first_day: date) -> Optional[date]:
    """Return the first occurrence on or after first_day without materializing it."""
    # The UI limits interval controls to 365 units. A 100-year search therefore
    # covers even very sparse Every-N-Weeks rules while iter_occurrences jumps
    # directly to the first candidate instead of walking day by day.
    try:
        horizon = date(min(9999, first_day.year + 100), 12, 31)
    except ValueError:
        horizon = date.max
    return next(iter_occurrences(rule, first_day, horizon), None)


class ScheduleService(QObject):
    plan_changed = Signal()
    reminder_fired = Signal(int)

    def __init__(self, database: PlanningDatabase, runtime: PlanningRuntime, speech) -> None:
        super().__init__()
        self.database = database
        self.runtime = runtime
        self.speech = speech
        self._prompting: set[int] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.check_due)
        self._materialize_timer = QTimer(self)
        self._materialize_timer.setInterval(30 * 60 * 1000)
        self._materialize_timer.timeout.connect(self.materialize_recurring)

    def start(self) -> None:
        self.materialize_recurring()
        self.check_due()
        self._timer.start()
        self._materialize_timer.start()

    def schedule_recurring(
        self,
        *,
        node_id: str,
        start_day: date,
        run_time: str,
        recurrence_type: str,
        interval_value: int,
        weekday: Optional[int],
        day_of_month: Optional[int],
        month_of_year: Optional[int],
        day_of_year_month: Optional[int],
        reminders: list[str],
    ) -> int:
        normalized = normalize_run_time(run_time)
        if normalized is None:
            raise ValueError("A run time is required for recurring schedules")
        for value in reminders:
            reminder_delta(value)
        validate_recurrence(
            recurrence_type,
            interval_value,
            weekday,
            day_of_month,
            month_of_year,
            day_of_year_month,
        )
        rule_id = self.database.create_recurring_rule(
            node_id=node_id,
            start_day=start_day,
            run_time=normalized,
            recurrence_type=recurrence_type,
            interval_value=interval_value,
            weekday=weekday,
            day_of_month=day_of_month,
            month_of_year=month_of_year,
            day_of_year_month=day_of_year_month,
            reminders=reminders,
        )
        self.materialize_recurring()
        return rule_id

    def materialize_recurring(
        self,
        through_day: Optional[date] = None,
        *,
        emit_change: bool = True,
    ) -> None:
        today = datetime.now().astimezone().date()
        changed = False
        for rule in self.database.recurring_rules(enabled_only=True):
            node_id = str(rule["node_id"])
            action = self.database.action_type(node_id)
            if action is None:
                continue
            try:
                reminders = [
                    str(value).strip()
                    for value in json.loads(str(rule["reminders_json"] or "[]"))
                    if str(value).strip()
                ]
            except Exception:
                reminders = []

            recurrence = str(rule["recurrence_type"])
            if through_day is None:
                occurrence_limit: Optional[int] = int(
                    _MATERIALIZED_OCCURRENCES.get(recurrence, 4)
                )
                try:
                    horizon = date(min(9999, today.year + 100), 12, 31)
                except ValueError:
                    horizon = date.max
            else:
                occurrence_limit = None
                horizon = max(today, through_day)

            occurrence_count = 0
            for occurrence in iter_occurrences(rule, today, horizon):
                occurrence_count += 1
                if not self.database.plan_exists_for_action_day(node_id, occurrence):
                    rule_duration = (
                        rule["duration_seconds"]
                        if "duration_seconds" in rule.keys()
                        else None
                    )
                    self.database.add_plan(
                        day_value=occurrence,
                        action_name=str(action["title"]),
                        node_id=node_id,
                        run_time=str(rule["run_time"]),
                        reminders=reminders,
                        duration_seconds=(
                            max(0, int(rule_duration))
                            if rule_duration is not None
                            else self.database.default_planned_seconds(node_id)
                            or 30 * 60
                        ),
                    )
                    changed = True
                if (
                    occurrence_limit is not None
                    and occurrence_count >= occurrence_limit
                ):
                    break
        if changed and emit_change:
            self.plan_changed.emit()

    def check_due(self) -> None:
        now = datetime.now().astimezone()
        rows = self.database.plans_for_day(now.date())
        for row in rows:
            run_time = normalize_run_time(row["run_time"])
            if run_time is None:
                continue
            try:
                hour, minute = (int(part) for part in run_time.split(":", 1))
                scheduled_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except Exception:
                continue
            self._check_reminders(row, scheduled_at, now)
            if row["handled_at"] is not None or row["last_run_at"] is not None:
                continue
            if now < scheduled_at:
                continue
            plan_id = int(row["id_plan_action_types"])
            if plan_id in self._prompting:
                continue
            self._prompting.add(plan_id)
            try:
                self._prompt_due(row, scheduled_at)
            finally:
                self._prompting.discard(plan_id)

    def _check_reminders(self, row, scheduled_at: datetime, now: datetime) -> None:
        try:
            reminders = [str(value) for value in json.loads(str(row["reminders_json"] or "[]"))]
        except Exception:
            reminders = []
        try:
            fired = {int(value) for value in json.loads(str(row["fired_reminders_json"] or "[]"))}
        except Exception:
            fired = set()
        title = self._row_title(row)
        for index, reminder in enumerate(reminders):
            if index in fired:
                continue
            try:
                due_at = scheduled_at - reminder_delta(reminder)
            except ValueError:
                continue
            if now < due_at:
                continue
            self.speech.speak(title)
            self.database.mark_plan_reminder_fired(int(row["id_plan_action_types"]), index)
            self.reminder_fired.emit(int(row["id_plan_action_types"]))

    def _prompt_due(self, row, scheduled_at: datetime) -> None:
        plan_id = int(row["id_plan_action_types"])
        title = self._row_title(row)
        self.speech.speak(title)
        answer = QMessageBox.question(
            None,
            "Scheduled task",
            f'{title}\n\nScheduled for {scheduled_at.strftime("%H:%M")}.\n\nStart this task now?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.database.mark_plan_handled(plan_id, ran=False)
            self.plan_changed.emit()
            return
        node_id = row["node_id"]
        if node_id is None:
            self.database.mark_plan_handled(plan_id, ran=False)
            self.plan_changed.emit()
            return
        node_id = str(node_id)
        active = self.runtime.state()
        target_root = self.database.top_root_id(node_id)
        if active is not None and target_root == active.root_node_id:
            if active.paused:
                self.runtime.resume()
            self.database.mark_plan_handled(plan_id, ran=True)
            self.plan_changed.emit()
            return

        seconds = max(60, int(row["duration_seconds"] or 30 * 60))
        self.runtime.prepare_plan_duration(plan_id, node_id, seconds)
        started = self.runtime.start_node(node_id, speak=False)
        if started:
            self.database.mark_plan_handled(plan_id, ran=True)
        else:
            self.runtime.clear_plan_duration()
            # The switch dialog was cancelled or the action could not start.
            # Treat this occurrence as handled so the 5-second scheduler does
            # not immediately show the same popup again.
            self.database.mark_plan_handled(plan_id, ran=False)
        self.plan_changed.emit()

    @staticmethod
    def _row_title(row) -> str:
        custom = str(row["action_name"] or "").strip()
        current = str(row["current_action_name"] or "").strip()
        return custom or current or "Action"

