from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QMessageBox,
    QStyledItemDelegate,
    QStyle,
    QToolButton,
)

from . import main_window_core as _main_window_core
from . import scheduler as _scheduler
from .dialogs import PlanDialog as _BasePlanDialog
from .dialogs import RecurringScheduleDialog
from .main_window import (
    ITEM_TYPE_MONTH_SEPARATOR,
    ITEM_TYPE_WEEK_SEPARATOR,
    MONTH_COLOR,
    WEEK_COLOR,
    PlanningMainWindow as _PlanningMainWindow,
)
from .main_window_core import DAY_ROLE, ITEM_TYPE_ROLE, NODE_ROLE
from .scheduler import RECURRENCE_ONE_TIME, normalize_run_time


TODAY_HEADER_COLOR = "#C2185B"
TODAY_HEADER_TEXT_COLOR = "#FFFFFF"
DAY_SEPARATOR_COLOR = "#7B1FA2"
DAY_SEPARATOR_HEIGHT = 1.0
MONTH_SEPARATOR_COLOR = "#F69A61"
WEEK_SEPARATOR_COLOR = "#F6CC61"


class _OptionalDurationPlanDialog(_BasePlanDialog):
    """Daily-plan dialog whose duration can be genuinely empty/zero.

    The old QSpinBox had a minimum of one minute and rendered ``min`` inside
    the editor. Zero now means an untimed scheduled action, and the unit is
    no longer embedded in the editable text.
    """

    def __init__(
        self,
        database,
        *,
        dialog_title: str,
        initial_day: date,
        initial_title: str = "",
        initial_node_id: Optional[str] = None,
        initial_run_time: Optional[str] = None,
        initial_reminders: Optional[list[str]] = None,
        initial_duration_seconds: int = 30 * 60,
        parent=None,
    ) -> None:
        duration_seconds = max(0, int(initial_duration_seconds or 0))

        if initial_node_id:
            if str(dialog_title).casefold().startswith("edit"):
                try:
                    target_time = str(initial_run_time or "").strip()
                    target_title = str(initial_title or "").strip()
                    for row in database.plans_for_day(initial_day):
                        if str(row["node_id"] or "") != str(initial_node_id):
                            continue
                        if str(row["run_time"] or "").strip() != target_time:
                            continue
                        if target_title and str(row["action_name"] or "").strip() != target_title:
                            continue
                        duration_seconds = max(0, int(row["duration_seconds"] or 0))
                        break
                except Exception:
                    pass
            elif database.default_planned_seconds(str(initial_node_id)) is None:
                duration_seconds = 0

        super().__init__(
            database,
            dialog_title=dialog_title,
            initial_day=initial_day,
            initial_title=initial_title,
            initial_node_id=initial_node_id,
            initial_run_time=initial_run_time,
            initial_reminders=initial_reminders,
            initial_duration_seconds=duration_seconds,
            parent=parent,
        )

        self.duration_spin.setRange(0, 24 * 60)
        self.duration_spin.setSuffix("")
        self.duration_spin.setSpecialValueText(" ")
        self.duration_spin.setValue(max(0, int(round(duration_seconds / 60))))
        self.duration_spin.setToolTip("Duration in minutes; blank = no duration")


_main_window_core.PlanDialog = _OptionalDurationPlanDialog


def _materialize_recurring_with_optional_duration(
    self,
    through_day: Optional[date] = None,
    *,
    emit_change: bool = True,
) -> None:
    """Materialize recurring plans without inventing a 30-minute duration."""
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
                _scheduler._MATERIALIZED_OCCURRENCES.get(recurrence, 4)
            )
            try:
                horizon = date(min(9999, today.year + 100), 12, 31)
            except ValueError:
                horizon = date.max
        else:
            occurrence_limit = None
            horizon = max(today, through_day)

        occurrence_count = 0
        for occurrence in _scheduler.iter_occurrences(rule, today, horizon):
            occurrence_count += 1
            if not self.database.plan_exists_for_action_day(node_id, occurrence):
                default_duration = self.database.default_planned_seconds(node_id)
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
                        else 0 if default_duration is None
                        else int(default_duration)
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


def _prompt_due_with_optional_duration(self, row, scheduled_at: datetime) -> None:
    """Start due zero-duration plans as untimed actions instead of 30 min."""
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

    seconds = max(0, int(row["duration_seconds"] or 0))
    if seconds > 0:
        self.runtime.prepare_plan_duration(plan_id, node_id, seconds)
    else:
        self.runtime.clear_plan_duration()
        self.runtime.set_plan_id(plan_id)

    started = self.runtime.start_node(node_id, speak=False)
    if started:
        self.database.mark_plan_handled(plan_id, ran=True)
    else:
        self.runtime.clear_plan_duration()
    self.plan_changed.emit()


_scheduler.ScheduleService.materialize_recurring = _materialize_recurring_with_optional_duration
_scheduler.ScheduleService._prompt_due = _prompt_due_with_optional_duration


class _DayHeaderSeparatorDelegate(QStyledItemDelegate):
    """Paint a true thin full-width separator on top of every day header."""

    def __init__(self, tree) -> None:
        super().__init__(tree)
        self._tree = tree

    def paint(self, painter, option, index) -> None:
        viewport_rect = self._tree.viewport().rect()

        if index.column() == 0:
            item_type = index.data(ITEM_TYPE_ROLE)
            if item_type == ITEM_TYPE_MONTH_SEPARATOR:
                painter.fillRect(
                    QRectF(
                        float(viewport_rect.left()),
                        float(option.rect.top()),
                        float(viewport_rect.width()),
                        float(option.rect.height()),
                    ),
                    QColor(MONTH_SEPARATOR_COLOR),
                )
            elif item_type == ITEM_TYPE_WEEK_SEPARATOR:
                painter.fillRect(
                    QRectF(
                        float(viewport_rect.left()),
                        float(option.rect.top()),
                        float(viewport_rect.width()),
                        float(option.rect.height()),
                    ),
                    QColor(WEEK_SEPARATOR_COLOR),
                )

        super().paint(painter, option, index)

        if index.column() != 0:
            return
        day_text = index.data(DAY_ROLE)
        if not isinstance(day_text, str) or not day_text:
            return

        painter.fillRect(
            QRectF(
                float(viewport_rect.left()),
                float(option.rect.top()),
                float(viewport_rect.width()),
                DAY_SEPARATOR_HEIGHT,
            ),
            QColor(DAY_SEPARATOR_COLOR),
        )


class PlanningMainWindow(_PlanningMainWindow):
    """Performance-focused wrapper around the regular planning window."""

    def __init__(self, *args, **kwargs) -> None:
        self._suspend_runtime_refresh = 0
        super().__init__(*args, **kwargs)

    def _recurring_rule_for_plan(self, row):
        try:
            day_value = date.fromisoformat(
                str(row["day"])
            )
        except (TypeError, ValueError):
            return None

        node_id = row["node_id"]
        if node_id is None:
            return None

        target_action = self.database.action_type(
            str(node_id)
        )
        if target_action is None:
            return None

        target_canonical = str(
            target_action["id_action_types"]
        )

        candidates = []

        for rule in self.database.recurring_rules(
            enabled_only=True
        ):
            rule_action = self.database.action_type(
                str(rule["node_id"])
            )
            if rule_action is None:
                continue

            if (
                str(rule_action["id_action_types"])
                != target_canonical
            ):
                continue

            if not list(
                _scheduler.iter_occurrences(
                    rule,
                    day_value,
                    day_value,
                )
            ):
                continue

            candidates.append(rule)

        if not candidates:
            return None

        try:
            current_time = (
                normalize_run_time(
                    row["run_time"]
                )
                or ""
            )
        except ValueError:
            current_time = str(
                row["run_time"] or ""
            )

        for rule in candidates:
            try:
                rule_time = (
                    normalize_run_time(
                        rule["run_time"]
                    )
                    or ""
                )
            except ValueError:
                rule_time = str(
                    rule["run_time"] or ""
                )

            if rule_time == current_time:
                return rule

        return (
            candidates[0]
            if len(candidates) == 1
            else None
        )

    def _edit_recurring_future(
        self,
        plan_id: int,
        row,
        rule,
    ) -> None:
        try:
            reminders = [
                str(value).strip()
                for value in json.loads(
                    str(
                        row["reminders_json"]
                        or "[]"
                    )
                )
                if str(value).strip()
            ]
        except Exception:
            reminders = []

        old_day = date.fromisoformat(
            str(row["day"])
        )

        dialog = _OptionalDurationPlanDialog(
            self.database,
            dialog_title="Edit Daily Plan",
            initial_day=old_day,
            initial_title=str(
                row["action_name"] or ""
            ),
            initial_node_id=(
                None
                if row["node_id"] is None
                else str(row["node_id"])
            ),
            initial_run_time=row["run_time"],
            initial_reminders=reminders,
            initial_duration_seconds=max(
                0,
                int(
                    row["duration_seconds"]
                    or 0
                ),
            ),
            parent=self,
        )

        if (
            dialog.exec()
            != QDialog.DialogCode.Accepted
        ):
            return

        try:
            node_id = dialog.selected_node_id()

            if not node_id:
                raise ValueError(
                    "Select an Action Type"
                )

            new_action = self.database.action_type(
                str(node_id)
            )

            if new_action is None:
                raise ValueError(
                    "Action Type no longer exists"
                )

            new_time = dialog.run_time()

            if new_time is None:
                raise ValueError(
                    "A run time is required for recurring schedules"
                )

            new_day = dialog.selected_day()

            title = dialog.entered_title()
            if not title:
                title = str(
                    new_action["title"]
                )

            new_reminders = dialog.reminders()
            new_duration = max(
                0,
                int(
                    dialog.duration_seconds()
                    or 0
                ),
            )

            old_action = self.database.action_type(
                str(row["node_id"])
            )

            if old_action is None:
                raise ValueError(
                    "Original Action Type no longer exists"
                )

            old_canonical = str(
                old_action[
                    "id_action_types"
                ]
            )

            try:
                old_time = (
                    normalize_run_time(
                        rule["run_time"]
                    )
                    or ""
                )
            except ValueError:
                old_time = str(
                    rule["run_time"]
                    or ""
                )

            threshold = max(
                old_day,
                datetime.now()
                    .astimezone()
                    .date(),
            )

            with self.database.connect() as connection:
                future_rows = connection.execute(
                    """
                    SELECT
                        pa.id_plan_action_types,
                        p.day,
                        COALESCE(
                            pa.run_time,''
                        ) AS run_time
                    FROM plan_action_types pa
                    JOIN plans p
                      ON p.id_plans=pa.id_plans
                    WHERE pa.id_action_types=?
                      AND p.day>=?
                    ORDER BY
                        p.day,
                        pa.id_plan_action_types
                    """,
                    (
                        old_canonical,
                        threshold.isoformat(),
                    ),
                ).fetchall()

            if future_rows:
                max_day = max(
                    date.fromisoformat(
                        str(value["day"])
                    )
                    for value in future_rows
                )

                old_occurrences = set(
                    _scheduler.iter_occurrences(
                        rule,
                        threshold,
                        max_day,
                    )
                )
            else:
                old_occurrences = set()

            delete_ids = []

            for value in future_rows:
                candidate_id = int(
                    value[
                        "id_plan_action_types"
                    ]
                )

                if candidate_id == plan_id:
                    continue

                candidate_day = date.fromisoformat(
                    str(value["day"])
                )

                if (
                    candidate_day
                    in old_occurrences
                    and str(
                        value["run_time"] or ""
                    ) == old_time
                ):
                    delete_ids.append(
                        candidate_id
                    )

            for candidate_id in delete_ids:
                self.database.delete_plan(
                    candidate_id
                )

            self.database.update_plan(
                plan_id,
                day_value=new_day,
                action_name=title,
                node_id=node_id,
                run_time=new_time,
                reminders=new_reminders,
                duration_seconds=new_duration,
            )

            recurrence = str(
                rule["recurrence_type"]
            )

            start_day = str(
                rule["start_day"]
            )

            weekday = rule["weekday"]
            day_of_month = rule[
                "day_of_month"
            ]
            month_of_year = rule[
                "month_of_year"
            ]
            day_of_year_month = rule[
                "day_of_year_month"
            ]

            if new_day != old_day:
                start_day = (
                    new_day.isoformat()
                )

                if (
                    recurrence
                    == _scheduler
                    .RECURRENCE_WEEKLY
                ):
                    weekday = (
                        new_day.weekday()
                    )

                elif (
                    recurrence
                    == _scheduler
                    .RECURRENCE_MONTHLY
                ):
                    day_of_month = (
                        new_day.day
                    )

                elif (
                    recurrence
                    == _scheduler
                    .RECURRENCE_YEARLY
                ):
                    month_of_year = (
                        new_day.month
                    )
                    day_of_year_month = (
                        new_day.day
                    )

            stamp = (
                datetime.now()
                .astimezone()
                .isoformat(
                    timespec="microseconds"
                )
            )

            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE recurring_schedule_rules
                    SET
                        node_id=?,
                        start_day=?,
                        run_time=?,
                        weekday=?,
                        day_of_month=?,
                        month_of_year=?,
                        day_of_year_month=?,
                        reminders_json=?,
                        duration_seconds=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        str(new_action["id"]),
                        start_day,
                        new_time,
                        weekday,
                        day_of_month,
                        month_of_year,
                        day_of_year_month,
                        json.dumps(
                            new_reminders,
                            ensure_ascii=False,
                        ),
                        new_duration,
                        stamp,
                        int(rule["id"]),
                    ),
                )

            self.schedules.materialize_recurring()
            self.refresh_all()

        except Exception as error:
            QMessageBox.warning(
                self,
                "Edit recurring Daily Plan",
                str(error),
            )

    def _edit_plan(
        self,
        plan_id: int,
    ) -> None:
        row = self.database.plan(plan_id)

        if row is None:
            return

        rule = self._recurring_rule_for_plan(
            row
        )

        if rule is None:
            super()._edit_plan(plan_id)
            return

        choice = QMessageBox(self)
        choice.setIcon(
            QMessageBox.Icon.Question
        )
        choice.setWindowTitle(
            "Edit recurring Daily Plan"
        )
        choice.setText(
            "This Daily Plan item is recurring."
        )
        choice.setInformativeText(
            "Which occurrences should be changed?"
        )

        only_this = choice.addButton(
            "Only this occurrence",
            QMessageBox.ButtonRole.AcceptRole,
        )

        future = choice.addButton(
            "This and future occurrences",
            QMessageBox.ButtonRole.ActionRole,
        )

        choice.addButton(
            QMessageBox.StandardButton.Cancel
        )

        choice.exec()

        clicked = choice.clickedButton()

        if clicked is only_this:
            super()._edit_plan(plan_id)
            return

        if clicked is future:
            self._edit_recurring_future(
                plan_id,
                row,
                rule,
            )

    def _separator(self, text, color, height, point_delta, item_type):
        if item_type == ITEM_TYPE_MONTH_SEPARATOR:
            color = MONTH_SEPARATOR_COLOR
        elif item_type == ITEM_TYPE_WEEK_SEPARATOR:
            color = WEEK_SEPARATOR_COLOR
        return super()._separator(text, color, height, point_delta, item_type)

    def _build_left_box(self):
        box = super()._build_left_box()
        controls = box.layout().itemAt(0).layout()

        self.today_crosshair_button = QToolButton(box)
        self.today_crosshair_button.setText("â")
        self.today_crosshair_button.setToolTip("Jump to today")
        self.today_crosshair_button.setAutoRaise(True)
        self.today_crosshair_button.setFixedSize(30, 30)
        font = QFont(self.today_crosshair_button.font())
        font.setPointSize(max(15, font.pointSize() + 4))
        font.setBold(True)
        self.today_crosshair_button.setFont(font)
        self.today_crosshair_button.clicked.connect(self._jump_to_today)
        controls.insertWidget(0, self.today_crosshair_button)

        self._day_header_separator_delegate = _DayHeaderSeparatorDelegate(self.plan_tree)
        self.plan_tree.setItemDelegate(self._day_header_separator_delegate)
        return box

    def _jump_to_today(self) -> None:
        item = getattr(self, "_today_header_item", None)
        if item is None:
            self.refresh_plans()
            item = getattr(self, "_today_header_item", None)
        if item is None:
            return
        self.plan_tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    @staticmethod
    def _rollup_duration_text(seconds: int) -> str:
        seconds = max(0, int(seconds))
        if seconds <= 0:
            return ""
        minutes = (seconds + 59) // 60
        hours, minutes = divmod(minutes, 60)
        if hours and minutes:
            return f"{hours}h{minutes:02d}m"
        if hours:
            return f"{hours}h"
        return f"{minutes}m"

    def _apply_descendant_schedule_rollups(self) -> None:
        """Aggregate descendant schedules without subtree queries per widget."""
        action_rows = self.database.action_types()
        parent_by_id: dict[str, Optional[str]] = {
            str(row["id"]): None if row["parent_id"] is None else str(row["parent_id"])
            for row in action_rows
        }
        ancestor_cache: dict[str, tuple[str, ...]] = {}

        def ancestors(node_id: str) -> tuple[str, ...]:
            cached = ancestor_cache.get(node_id)
            if cached is not None:
                return cached
            result: list[str] = []
            current = parent_by_id.get(node_id)
            seen: set[str] = set()
            while current and current not in seen:
                seen.add(current)
                result.append(current)
                current = parent_by_id.get(current)
            value = tuple(result)
            ancestor_cache[node_id] = value
            return value

        # One bulk query replaces plans_for_day() for every visible day.
        day_values: list[date] = []
        headers: dict[str, object] = {}
        for top_index in range(self.plan_tree.topLevelItemCount()):
            header = self.plan_tree.topLevelItem(top_index)
            day_text = header.data(0, DAY_ROLE)
            if not isinstance(day_text, str) or not day_text:
                continue
            try:
                day_value = date.fromisoformat(day_text)
            except ValueError:
                continue
            day_values.append(day_value)
            headers[day_text] = header
        if not day_values:
            return
        first_day = min(day_values)
        last_day = max(day_values)
        rows_by_day: dict[str, list] = {}
        for row in self.database.plans_between(first_day, last_day):
            rows_by_day.setdefault(str(row["day"]), []).append(row)

        for day_text, header in headers.items():
            rollups: dict[str, list[object]] = {}
            for row in rows_by_day.get(day_text, []):
                node_id = str(row["node_id"] or "").strip()
                if not node_id:
                    continue
                try:
                    run_time = normalize_run_time(row["run_time"])
                except ValueError:
                    continue
                if run_time is None:
                    continue
                duration = max(0, int(row["duration_seconds"] or 0))
                for ancestor_id in ancestors(node_id):
                    current = rollups.get(ancestor_id)
                    if current is None:
                        rollups[ancestor_id] = [run_time, duration]
                    else:
                        if run_time < str(current[0]):
                            current[0] = run_time
                        current[1] = int(current[1]) + duration
            if not rollups:
                continue

            def visit(item) -> None:
                node_id = item.data(0, NODE_ROLE)
                if isinstance(node_id, str) and node_id and not item.text(2).strip():
                    value = rollups.get(node_id)
                    if value is not None:
                        earliest = str(value[0])
                        duration_text = self._rollup_duration_text(int(value[1]))
                        item.setText(2, earliest if not duration_text else f"{earliest} Â· {duration_text}")
                for child_index in range(item.childCount()):
                    visit(item.child(child_index))

            for child_index in range(header.childCount()):
                visit(header.child(child_index))

    def _apply_today_marker(self) -> None:
        header = getattr(self, "_today_header_item", None)
        if header is None:
            return
        today_background = QBrush(QColor(TODAY_HEADER_COLOR))
        foreground = QBrush(QColor(TODAY_HEADER_TEXT_COLOR))
        for column in range(self.plan_tree.columnCount()):
            header.setData(column, Qt.ItemDataRole.BackgroundRole, today_background)
            header.setData(column, Qt.ItemDataRole.ForegroundRole, foreground)
        font = QFont(header.font(0))
        font.setBold(True)
        header.setFont(0, font)

    def refresh_plans(self) -> None:
        before_spin = getattr(self, "days_before_spin", None)
        after_spin = getattr(self, "days_after_spin", None)
        if before_spin is None or after_spin is None:
            super().refresh_plans()
            self._apply_descendant_schedule_rollups()
            self._apply_today_marker()
            return

        today = datetime.now().astimezone().date()
        first_day = today - timedelta(days=int(before_spin.value()))
        last_day = today + timedelta(days=int(after_spin.value()))
        anchor_days = self._recurring_anchor_days(last_day + timedelta(days=1))
        original_activity_days = self.database.activity_days
        original_plan_days = self.database.plan_days
        activity_days = [day for day in original_activity_days() if first_day <= day <= last_day]
        plan_days = [day for day in original_plan_days() if first_day <= day <= last_day or day in anchor_days]
        self.database.activity_days = lambda: list(activity_days)
        self.database.plan_days = lambda: list(plan_days)
        try:
            super().refresh_plans()
        finally:
            self.database.__dict__.pop("activity_days", None)
            self.database.__dict__.pop("plan_days", None)
        self._apply_descendant_schedule_rollups()
        self._apply_today_marker()

    def _schedule_action(self, node_id: str) -> None:
        dialog = RecurringScheduleDialog(action_title=self.database.path_title(node_id), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            recurrence = dialog.recurrence_type()
            if recurrence == RECURRENCE_ONE_TIME:
                action = self.database.action_type(node_id)
                default_duration = self.database.default_planned_seconds(node_id)
                self.database.add_plan(
                    day_value=dialog.selected_date(),
                    action_name="" if action is None else str(action["title"]),
                    node_id=node_id,
                    run_time=dialog.selected_time(),
                    reminders=dialog.reminders(),
                    duration_seconds=0 if default_duration is None else int(default_duration),
                )
            else:
                self.schedules.schedule_recurring(
                    node_id=node_id,
                    start_day=dialog.selected_date(),
                    run_time=dialog.selected_time(),
                    recurrence_type=recurrence,
                    interval_value=dialog.interval_value(),
                    weekday=dialog.selected_weekday(),
                    day_of_month=dialog.day_of_month(),
                    month_of_year=dialog.month_of_year(),
                    day_of_year_month=dialog.day_of_year_month(),
                    reminders=dialog.reminders(),
                )
        except Exception as error:
            QMessageBox.warning(self, "Schedule", str(error))
            return
        self.refresh_plans()

    def _update_runtime_controls(self) -> None:
        """Update existing action widgets in place; never rebuild whole trees."""
        active = self.runtime.state()
        paused = self.runtime.paused_snapshots()
        self._refresh_active_bar()

        for node_id, item in tuple(self._action_items.items()):
            container = self.action_tree.itemWidget(item, 0)
            if container is None or container.layout() is None:
                continue
            layout = container.layout()
            play = layout.itemAt(1).widget() if layout.count() > 1 else None
            stop = layout.itemAt(2).widget() if layout.count() > 2 else None
            remaining = self._remaining_labels.get(node_id)
            node_is_current = active is not None and active.current_node_id == node_id
            paused_snapshot = next((x for x in paused.values() if x.get("current_node_id") == node_id), None)

            if isinstance(play, QToolButton):
                try:
                    play.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
                if node_is_current and active is not None:
                    play.setIcon(self.active_pause.icon())
                    play.setIconSize(self.active_pause.iconSize())
                    if active.paused:
                        play.setToolTip("Continue")
                        play.clicked.connect(self.runtime.resume)
                    else:
                        play.setToolTip("Pause")
                        play.clicked.connect(self.runtime.pause)
                else:
                    play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                    play.setToolTip("Continue paused action" if paused_snapshot is not None else "Start")
                    play.clicked.connect(lambda _checked=False, nid=node_id: self._start_action_type_manually(nid))

            if isinstance(stop, QToolButton):
                try:
                    stop.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
                if node_is_current and active is not None:
                    stop.clicked.connect(lambda _checked=False: self.runtime.stop(announce_finished=False))
                    stop.show()
                elif paused_snapshot is not None and paused_snapshot.get("root_node_id"):
                    root = str(paused_snapshot["root_node_id"])
                    stop.clicked.connect(lambda _checked=False, rid=root: self.runtime.end_paused_run(rid))
                    stop.show()
                else:
                    stop.hide()

            if remaining is not None:
                if node_is_current and active is not None:
                    if active.planned_duration_seconds is None:
                        from .dialogs import compact_duration
                        remaining.setText("elapsed " + compact_duration(active.elapsed_seconds))
                    else:
                        from .dialogs import compact_duration
                        remaining.setText(compact_duration(active.remaining_seconds))
                elif paused_snapshot is not None:
                    from .dialogs import compact_duration
                    remaining.setText(
                        "â¸ E " + compact_duration(int(paused_snapshot.get("elapsed_seconds", 0)))
                        + " Â· R " + compact_duration(int(paused_snapshot.get("remaining_seconds", 0)))
                    )
                else:
                    remaining.clear()

            if node_is_current and active is not None and not active.paused:
                container.setStyleSheet("background-color:rgb(255,246,184);")
            elif (node_is_current and active is not None and active.paused) or paused_snapshot is not None:
                container.setStyleSheet("background-color:rgb(255,243,205);")
            else:
                container.setStyleSheet("background:transparent;")

    def _start_plan(self, plan_id: int) -> None:
        row = self.database.plan(plan_id)
        if row is None:
            return
        node_id = str(row["node_id"])
        seconds = max(0, int(row["duration_seconds"] or 0))
        self._suspend_runtime_refresh += 1
        try:
            if seconds > 0:
                self.runtime.prepare_plan_duration(plan_id, node_id, seconds)
            else:
                self.runtime.clear_plan_duration()
                self.runtime.set_plan_id(plan_id)
            started = self.runtime.start_node(node_id, speak=False)
            if started:
                self.database.mark_plan_handled(plan_id, ran=True)
            else:
                self.runtime.clear_plan_duration()
        finally:
            self._suspend_runtime_refresh = max(0, self._suspend_runtime_refresh - 1)
        self._update_runtime_controls()
        # Plan data changed only for handled/time state; a deferred refresh keeps
        # the click path instant and lets Qt paint the new runtime state first.
        QTimer.singleShot(250, self.refresh_plans)

    def _runtime_changed(self) -> None:
        if self._suspend_runtime_refresh:
            return
        self._update_runtime_controls()

    def _start_action_type_manually(self, node_id: str) -> None:
        started = False
        self._suspend_runtime_refresh += 1
        try:
            started = self.runtime.start_node(node_id, speak=False)
            if started:
                plan_id = self.database.record_manual_start(node_id)
                self.database.mark_plan_handled(plan_id, ran=True)
                self.runtime.set_plan_id(plan_id)
                self.statusBar().showMessage(
                    f"Started: {self.database.path_title(node_id)} | added to today's Daily Plan",
                    5000,
                )
        except Exception as error:
            QMessageBox.warning(self, "Start Action Type", str(error))
        finally:
            self._suspend_runtime_refresh = max(0, self._suspend_runtime_refresh - 1)

        if started:
            self._update_runtime_controls()
            QTimer.singleShot(250, self.refresh_plans)
            QTimer.singleShot(350, self.refresh_to_plan)

