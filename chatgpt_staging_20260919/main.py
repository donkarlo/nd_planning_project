from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .dialogs import compact_duration, parse_duration
from .main_window_core import (
    DAY_ROLE,
    ITEM_TYPE_DAY_HEADER,
    ITEM_TYPE_ROLE,
    NODE_ROLE,
    PlanningMainWindow as CorePlanningMainWindow,
)
from .scheduler import next_occurrence

ITEM_TYPE_MONTH_SEPARATOR = "month_separator"
ITEM_TYPE_WEEK_SEPARATOR = "week_separator"

# Stable separators for the entire year.
MONTH_COLOR = "#F7A36F"
WEEK_COLOR = "#F7D06F"

# Monday .. Sunday. These colors are intentionally stable across every week.
DAY_COLORS = (
    "#F2D6E7",  # Monday - rose
    "#D8E8F7",  # Tuesday - blue
    "#DDF0DF",  # Wednesday - green
    "#F5E3C7",  # Thursday - apricot
    "#E7DDF5",  # Friday - lavender
    "#D9EFEF",  # Saturday - aqua
    "#F5DCD7",  # Sunday - coral
)

# Matching action shades. Every second action row uses the lighter shade.
DAY_ACTION_COLORS = (
    ("#FAEDF5", "#FDF6FA"),
    ("#EEF6FD", "#F7FBFE"),
    ("#EEF8EF", "#F7FBF7"),
    ("#FBF2E4", "#FDF8F0"),
    ("#F4EFFB", "#FAF7FD"),
    ("#EDF8F8", "#F7FCFC"),
    ("#FBEFEB", "#FDF7F5"),
)

RUNNING_COLOR = "#D14E5C"
RUNNING_TEXT_COLOR = "#FFFFFF"
PAUSED_COLOR = "#E0A84D"
PAUSED_TEXT_COLOR = "#3F2D12"
NORMAL_TEXT_COLOR = "#342F36"


def _play_timer_alarm() -> None:
    """Play a system completion sound without adding audio assets to the project."""
    player = shutil.which("canberra-gtk-play")
    if player:
        for sound_id in ("complete", "bell", "message"):
            try:
                subprocess.Popen(
                    [player, "-i", sound_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return
            except OSError:
                continue
    QApplication.beep()
    QTimer.singleShot(180, QApplication.beep)


class CountdownTimerRow(QFrame):
    """A standalone countdown timer unrelated to plans, actions, runtime, or the database."""

    def __init__(self, *, title: str, duration_seconds: int, speech=None, parent=None) -> None:
        super().__init__(parent)
        self._title = str(title)
        self._speech = speech
        self._duration_seconds = max(1, int(duration_seconds))
        self._elapsed_base = 0.0
        self._segment_started: Optional[float] = time.monotonic()
        self._running = True
        self._alarm_played = False

        self.setObjectName("standaloneTimerCard")
        self.setStyleSheet(
            "QFrame#standaloneTimerCard{background:#F7F8FC;border:1px solid #D7DCE8;border-radius:10px;}"
            "QLabel#timerTitle{font-weight:700;font-size:14px;color:#343A4A;}"
            "QLabel#timerClock{font-weight:800;font-size:19px;color:#344A78;}"
            "QLabel#timerDetails{color:#626A78;font-size:12px;}"
            "QPushButton{min-height:28px;padding:3px 10px;border-radius:6px;border:1px solid #CBD2DF;background:#FFFFFF;}"
            "QPushButton:hover{background:#F0F3F9;}"
            "QPushButton#deleteTimer{color:#A33A45;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(5)

        top = QHBoxLayout()
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("timerTitle")
        self.clock_label = QLabel("", self)
        self.clock_label.setObjectName("timerClock")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.title_label, 1)
        top.addWidget(self.clock_label)
        root.addLayout(top)

        self.details_label = QLabel("", self)
        self.details_label.setObjectName("timerDetails")
        root.addWidget(self.details_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.run_pause_button = QPushButton("Run", self)
        self.delete_button = QPushButton("Delete", self)
        self.delete_button.setObjectName("deleteTimer")
        buttons.addWidget(self.run_pause_button)
        buttons.addWidget(self.delete_button)
        root.addLayout(buttons)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(200)
        self._tick_timer.timeout.connect(self._update_display)
        self._tick_timer.start()
        self.run_pause_button.clicked.connect(self.toggle_running)
        self.delete_button.clicked.connect(self._delete_self)
        self._update_display()

    def _elapsed_seconds(self) -> float:
        elapsed = max(0.0, float(self._elapsed_base))
        if self._running and self._segment_started is not None:
            elapsed += max(0.0, time.monotonic() - self._segment_started)
        return elapsed

    def toggle_running(self) -> None:
        if self._running:
            self._elapsed_base = self._elapsed_seconds()
            self._segment_started = None
            self._running = False
        else:
            self._segment_started = time.monotonic()
            self._running = True
        self._update_display()

    def _delete_self(self) -> None:
        self._tick_timer.stop()
        self.setParent(None)
        self.deleteLater()

    def _update_display(self) -> None:
        elapsed_float = self._elapsed_seconds()
        elapsed = max(0, int(elapsed_float))
        difference = self._duration_seconds - elapsed_float

        if difference > 0:
            self.clock_label.setText(f"Remaining {compact_duration(int(difference + 0.999))}")
            self.clock_label.setStyleSheet("font-weight:800;font-size:19px;color:#344A78;")
        else:
            overdue = max(0, int(-difference))
            self.clock_label.setText(f"Over +{compact_duration(overdue)}")
            self.clock_label.setStyleSheet("font-weight:800;font-size:19px;color:#B54855;")
            if not self._alarm_played:
                self._alarm_played = True
                if self._speech is not None:
                    try:
                        self._speech.speak(f"Time {self._title} finished")
                    except Exception:
                        _play_timer_alarm()
                else:
                    _play_timer_alarm()

        state = "Running" if self._running else "Paused"
        self.details_label.setText(
            f"Initial {compact_duration(self._duration_seconds)}  ·  "
            f"Elapsed {compact_duration(elapsed)}  ·  {state}"
        )
        self.run_pause_button.setText("Pause" if self._running else "Run")


class StandaloneTimerDialog(QDialog):
    """Independent multi-timer tool; it never reads or writes plan/action state."""

    def __init__(self, parent=None, *, speech=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Timers")
        self.resize(620, 480)
        self._timer_number = 0
        self._speech = speech

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(9)

        heading = QLabel("Standalone timers", self)
        heading.setStyleSheet("font-size:17px;font-weight:800;color:#343A4A;")
        root.addWidget(heading)

        note = QLabel("These timers are independent from Plans and Action types.", self)
        note.setStyleSheet("color:#697181;")
        root.addWidget(note)

        add_row = QHBoxLayout()
        self.label_input = QLineEdit(self)
        self.label_input.setPlaceholderText("Label (optional)")
        self.duration_input = QLineEdit(self)
        self.duration_input.setPlaceholderText("Duration: 5 min, 1 h, 10:30")
        self.duration_input.setMinimumHeight(35)
        self.add_button = QPushButton("Add timer", self)
        self.add_button.setMinimumHeight(35)
        add_row.addWidget(self.label_input, 1)
        add_row.addWidget(self.duration_input, 1)
        add_row.addWidget(self.add_button)
        root.addLayout(add_row)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color:#A33A45;")
        self.error_label.hide()
        root.addWidget(self.error_label)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget(scroll)
        self.timer_layout = QVBoxLayout(container)
        self.timer_layout.setContentsMargins(0, 0, 0, 0)
        self.timer_layout.setSpacing(8)
        self.timer_layout.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        self.add_button.clicked.connect(self._add_timer)
        self.duration_input.returnPressed.connect(self._add_timer)

    def _add_timer(self) -> None:
        try:
            duration = parse_duration(self.duration_input.text())
        except ValueError as error:
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        if duration is None:
            self.error_label.setText("Enter a duration, for example 5 min or 10:30.")
            self.error_label.show()
            return

        self.error_label.hide()
        self._timer_number += 1
        title = self.label_input.text().strip() or f"Timer {self._timer_number}"
        timer = CountdownTimerRow(
            title=title,
            duration_seconds=duration,
            speech=self._speech,
            parent=self,
        )
        self.timer_layout.insertWidget(self.timer_layout.count() - 1, timer)
        self.label_input.clear()
        self.duration_input.clear()
        self.duration_input.setFocus()


class PlanningMainWindow(CorePlanningMainWindow):
    """Daily Plans presentation and persistent UI state."""

    DEFAULT_DAYS_BEFORE = 14
    DEFAULT_DAYS_AFTER = 14

    def __init__(self, *args, **kwargs) -> None:
        self._ui_state_path = Path(__file__).resolve().parents[3] / "data" / "nd_planning" / "ui_state.json"
        self._restoring_ui_state = False
        self._today_header_item: Optional[QTreeWidgetItem] = None
        self._daily_active_items: list[QTreeWidgetItem] = []
        self._state_save_timer: Optional[QTimer] = None
        self._plans_initialized = False
        self._timer_window: Optional[StandaloneTimerDialog] = None
        super().__init__(*args, **kwargs)
        self._state_save_timer = QTimer(self)
        self._state_save_timer.setSingleShot(True)
        self._state_save_timer.setInterval(350)
        self._state_save_timer.timeout.connect(self._save_window_state)

    def _build_ui(self) -> None:
        super()._build_ui()
        self._apply_pastel_style()
        self.plan_tree.itemCollapsed.connect(self._plan_item_collapsed)

    def _build_left_box(self) -> QGroupBox:
        box = super()._build_left_box()
        controls = box.layout().itemAt(0).layout()

        statistics_index = 1
        refresh_widget = None
        for index in range(controls.count()):
            widget = controls.itemAt(index).widget()
            if isinstance(widget, QPushButton):
                if widget.text() == "Statistics...":
                    statistics_index = index
                elif widget.text() == "Refresh":
                    refresh_widget = widget
        if refresh_widget is not None:
            controls.removeWidget(refresh_widget)
            refresh_widget.deleteLater()

        self.timer_button = QPushButton("Time...", box)
        controls.insertWidget(statistics_index + 1, self.timer_button)
        self.timer_button.clicked.connect(self._show_timer_window)

        future_label = QLabel("Future", box)
        past_label = QLabel("Past", box)
        self.days_after_spin = QSpinBox(box)
        self.days_before_spin = QSpinBox(box)
        for spin in (self.days_after_spin, self.days_before_spin):
            spin.setRange(0, 3650)
            spin.setSuffix(" d")
            spin.setFixedWidth(76)
        self.days_after_spin.setValue(self.DEFAULT_DAYS_AFTER)
        self.days_before_spin.setValue(self.DEFAULT_DAYS_BEFORE)
        self.days_after_spin.setToolTip("Future days shown above today")
        self.days_before_spin.setToolTip("Past days shown below today")
        controls.addSpacing(8)
        controls.addWidget(future_label)
        controls.addWidget(self.days_after_spin)
        controls.addWidget(past_label)
        controls.addWidget(self.days_before_spin)
        self.days_after_spin.valueChanged.connect(self._daily_range_changed)
        self.days_before_spin.valueChanged.connect(self._daily_range_changed)
        return box

    def _build_middle_box(self) -> QGroupBox:
        box = super()._build_middle_box()
        box.setTitle("Action types")
        self.action_filter.setMinimumHeight(38)
        font = QFont(self.action_filter.font())
        font.setPointSize(max(11, font.pointSize() + 1))
        self.action_filter.setFont(font)
        self.action_filter.setStyleSheet(
            "QLineEdit{background:#FFFDFE;border:1px solid #CFC5D4;border-radius:8px;"
            "padding:6px 10px;color:#37313A;}"
            "QLineEdit:focus{border:1px solid #8C7AA0;background:#FFFFFF;}"
        )
        return box

    def _show_timer_window(self) -> None:
        if self._timer_window is None:
            self._timer_window = StandaloneTimerDialog(parent=self, speech=self.runtime.speech)
        self._timer_window.show()
        self._timer_window.raise_()
        self._timer_window.activateWindow()

    def refresh_actions(self) -> None:
        super().refresh_actions()
        self._match_action_stop_buttons_to_active_bar()

    def _match_action_stop_buttons_to_active_bar(self) -> None:
        """Use the same plain red stop icon as the top active-action bar."""

        def visit(item: QTreeWidgetItem) -> None:
            container = self.action_tree.itemWidget(item, 0)
            if container is not None:
                for button in container.findChildren(QToolButton):
                    if button.toolTip() == "Stop":
                        button.setStyleSheet("")
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self.action_tree.topLevelItemCount()):
            visit(self.action_tree.topLevelItem(index))

    def _apply_pastel_style(self) -> None:
        self.left_box.setStyleSheet(
            "QGroupBox{background:#FFFDFB;border:1px solid #DED6DF;border-radius:11px;margin-top:8px;font-weight:600;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;color:#514955;}"
            "QPushButton{background:#F4EDF7;border:1px solid #D9CEDF;border-radius:7px;padding:5px 10px;color:#49404E;}"
            "QPushButton:hover{background:#EDE2F2;border-color:#CDBFD5;}"
            "QSpinBox{background:#FFFDFE;border:1px solid #D8CEDB;border-radius:6px;padding:3px 5px;color:#454047;}"
        )
        self.plan_tree.setStyleSheet(
            "QTreeWidget{background:#FFFDFC;border:1px solid #E3DAE3;border-radius:9px;outline:0;padding:3px;}"
            "QHeaderView::section{background:#EEE6F1;color:#4B4350;border:0;border-right:1px solid #DDD2E0;"
            "border-bottom:1px solid #D7CDD9;padding:6px 8px;font-weight:700;}"
        )
        self.plan_tree.setAnimated(True)
        self.plan_tree.setUniformRowHeights(False)

    def _daily_range_changed(self, _value: int) -> None:
        if self._restoring_ui_state:
            return
        self._save_window_state()
        self.refresh_plans()

    def _load_ui_state(self) -> dict:
        try:
            data = json.loads(self._ui_state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _restore_window_state(self) -> None:
        self._restoring_ui_state = True
        try:
            state = self._load_ui_state()
            self.days_before_spin.blockSignals(True)
            self.days_after_spin.blockSignals(True)
            self.days_before_spin.setValue(max(0, int(state.get("days_before_today", self.DEFAULT_DAYS_BEFORE))))
            self.days_after_spin.setValue(max(0, int(state.get("days_after_today", self.DEFAULT_DAYS_AFTER))))
            self.days_before_spin.blockSignals(False)
            self.days_after_spin.blockSignals(False)
            window = state.get("window", {})
            if isinstance(window, dict):
                geometry = window.get("geometry_base64")
                if isinstance(geometry, str) and geometry:
                    try:
                        self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
                    except Exception:
                        pass
                else:
                    try:
                        self.resize(
                            max(500, int(window.get("width", self.width()))),
                            max(400, int(window.get("height", self.height()))),
                        )
                        self.move(int(window.get("x", self.x())), int(window.get("y", self.y())))
                    except (TypeError, ValueError):
                        pass
            sizes = state.get("splitter_sizes")
            if isinstance(sizes, list) and len(sizes) == 3:
                try:
                    self.splitter.setSizes([max(1, int(value)) for value in sizes])
                except (TypeError, ValueError):
                    pass
            panels = state.get("panels", {})
            if isinstance(panels, dict):
                panel_values = {
                    "plans": bool(panels.get("plans", True)),
                    "action_types": bool(
                        panels.get("action_types", True)
                    ),
                    "to_plan": bool(panels.get("to_plan", True)),
                }

                # Never restore an unusable completely blank workspace.
                if not any(panel_values.values()):
                    panel_values = {
                        key: True
                        for key in panel_values
                    }

                for key, panel in (
                    ("plans", self.left_box),
                    ("action_types", self.middle_box),
                    ("to_plan", self.right_box),
                ):
                    visible = panel_values[key]
                    panel.setVisible(visible)
                    self._panel_actions[key].setChecked(visible)
        finally:
            self._restoring_ui_state = False

    def _save_window_state(self) -> None:
        if self._restoring_ui_state:
            return
        try:
            self._ui_state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "version": 1,
                "days_before_today": int(self.days_before_spin.value()),
                "days_after_today": int(self.days_after_spin.value()),
                "window": {
                    "x": int(self.x()),
                    "y": int(self.y()),
                    "width": int(self.width()),
                    "height": int(self.height()),
                    "maximized": bool(self.isMaximized()),
                    "geometry_base64": bytes(self.saveGeometry().toBase64()).decode("ascii"),
                },
                "splitter_sizes": [int(value) for value in self.splitter.sizes()],
                "panels": {
                    # isHidden() reflects an explicit user hide/show choice.
                    # isVisible() becomes False for every child while the
                    # parent window is closing and corrupted the next startup.
                    "plans": not self.left_box.isHidden(),
                    "action_types": not self.middle_box.isHidden(),
                    "to_plan": not self.right_box.isHidden(),
                },
            }
            self._ui_state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def _queue_window_state_save(self) -> None:
        if not self._restoring_ui_state and self._state_save_timer is not None:
            self._state_save_timer.start()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._queue_window_state_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._queue_window_state_save()

    @staticmethod
    def _set_row_style(item: QTreeWidgetItem, background: str, foreground: str = NORMAL_TEXT_COLOR) -> None:
        background_brush = QBrush(QColor(background))
        foreground_brush = QBrush(QColor(foreground))
        for column in range(3):
            item.setData(column, Qt.ItemDataRole.BackgroundRole, background_brush)
            item.setData(column, Qt.ItemDataRole.ForegroundRole, foreground_brush)

    def _separator(self, text: str, color: str, height: int, point_delta: int, item_type: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text, "", ""])
        item.setData(0, ITEM_TYPE_ROLE, item_type)
        item.setFlags(
            item.flags()
            & ~Qt.ItemFlag.ItemIsSelectable
            & ~Qt.ItemFlag.ItemIsDragEnabled
            & ~Qt.ItemFlag.ItemIsDropEnabled
        )
        item.setTextAlignment(0, Qt.AlignmentFlag.AlignCenter)
        font = QFont(item.font(0))
        font.setBold(True)
        font.setPointSize(max(9, font.pointSize() + point_delta))
        item.setFont(0, font)
        item.setSizeHint(0, QSize(0, height))
        self._set_row_style(item, color, "#FFFFFF")
        return item

    def _style_day(self, header: QTreeWidgetItem, day_value: date, today: date) -> None:
        weekday_index = day_value.weekday()
        self._set_row_style(header, DAY_COLORS[weekday_index])
        font = QFont(header.font(0))
        font.setBold(True)
        header.setFont(0, font)
        header.setSizeHint(0, QSize(0, 31 if day_value == today else 29))

        row_index = 0

        def visit(item: QTreeWidgetItem) -> None:
            nonlocal row_index
            shade_index = row_index % 2
            self._set_row_style(item, DAY_ACTION_COLORS[weekday_index][shade_index])
            item.setSizeHint(0, QSize(0, 27))
            row_index += 1
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(header.childCount()):
            visit(header.child(index))

    def _recurring_anchor_days(self, first_day: date) -> set[date]:
        """Show one next occurrence per recurring rule even outside the normal range."""
        anchors: set[date] = set()
        for rule in self.database.recurring_rules(enabled_only=True):
            occurrence = next_occurrence(rule, first_day)
            if occurrence is not None:
                anchors.add(occurrence)
        return anchors

    def refresh_plans(self) -> None:
        previous_scroll_value = None
        if self._plans_initialized:
            previous_scroll_value = int(self.plan_tree.verticalScrollBar().value())

        today = datetime.now().astimezone().date()
        first_day = today - timedelta(days=int(self.days_before_spin.value()))
        last_day = today + timedelta(days=int(self.days_after_spin.value()))
        self.schedules.materialize_recurring(
            through_day=last_day,
            emit_change=False,
        )
        super().refresh_plans()
        populated_days = set(self.database.activity_days())
        populated_days.update(self.database.plan_days())

        headers: dict[date, QTreeWidgetItem] = {}
        while self.plan_tree.topLevelItemCount():
            item = self.plan_tree.takeTopLevelItem(0)
            raw_day = item.data(0, DAY_ROLE)
            if isinstance(raw_day, str):
                try:
                    headers[date.fromisoformat(raw_day)] = item
                except ValueError:
                    pass

        self._today_header_item = None
        self._daily_active_items = []
        active = self.runtime.state()
        current_node_id = None if active is None else str(active.current_node_id)
        last_month: Optional[tuple[int, int]] = None
        last_week: Optional[tuple[int, int]] = None

        display_days: set[date] = set()
        day_value = first_day
        while day_value <= last_day:
            display_days.add(day_value)
            day_value += timedelta(days=1)
        display_days.update(self._recurring_anchor_days(last_day + timedelta(days=1)))

        for day_value in sorted(display_days, reverse=True):
            month_key = (day_value.year, day_value.month)
            if month_key != last_month:
                month = self._separator(
                    day_value.strftime("%B %Y"),
                    MONTH_COLOR,
                    37,
                    2,
                    ITEM_TYPE_MONTH_SEPARATOR,
                )
                self.plan_tree.addTopLevelItem(month)
                month.setFirstColumnSpanned(True)
                last_month = month_key
                last_week = None

            iso = day_value.isocalendar()
            week_key = (iso.year, iso.week)
            if week_key != last_week:
                week = self._separator(
                    f"Week {iso.week:02d}",
                    WEEK_COLOR,
                    28,
                    0,
                    ITEM_TYPE_WEEK_SEPARATOR,
                )
                self.plan_tree.addTopLevelItem(week)
                week.setFirstColumnSpanned(True)
                last_week = week_key

            header = headers.get(day_value)
            if header is None:
                header = QTreeWidgetItem(["", "", ""])
                header.setData(0, ITEM_TYPE_ROLE, ITEM_TYPE_DAY_HEADER)
                header.setData(0, DAY_ROLE, day_value.isoformat())
            header.setText(0, day_value.strftime("%d %A %B %Y"))
            header.setText(1, "")
            header.setText(2, "")
            self.plan_tree.addTopLevelItem(header)
            header.setFirstColumnSpanned(True)
            self._style_day(header, day_value, today)

            if day_value == today:
                self._today_header_item = header
                if active is not None:
                    self._collect_active_items(header, current_node_id)

            header.setExpanded(day_value == today or day_value in populated_days or header.childCount() > 0)

        self.plan_tree.resizeColumnToContents(1)
        self.plan_tree.resizeColumnToContents(2)
        self._refresh_daily_active_display()
        if previous_scroll_value is None:
            if self._today_header_item is not None:
                self.plan_tree.scrollToItem(
                    self._today_header_item,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
        else:
            QTimer.singleShot(0, lambda value=previous_scroll_value: self._restore_plan_scroll(value))
        self._plans_initialized = True

    def _restore_plan_scroll(self, value: int) -> None:
        scroll_bar = self.plan_tree.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), min(int(value), scroll_bar.maximum())))

    def _collect_active_items(self, parent: QTreeWidgetItem, node_id: Optional[str]) -> None:
        if not node_id:
            return
        for index in range(parent.childCount()):
            item = parent.child(index)
            if str(item.data(0, NODE_ROLE) or "") == node_id:
                self._daily_active_items.append(item)
            self._collect_active_items(item, node_id)

    def _expand_active_branch(self) -> None:
        """Keep every ancestor of the running Daily Plan action expanded."""
        for active_item in self._daily_active_items:
            item: Optional[QTreeWidgetItem] = active_item
            while item is not None:
                if item.childCount() > 0 or item is not active_item:
                    item.setExpanded(True)
                item = item.parent()

    def _plan_item_collapsed(self, collapsed_item: QTreeWidgetItem) -> None:
        """Prevent the branch containing the running action from staying collapsed."""
        if self.runtime.state() is None:
            return
        for active_item in self._daily_active_items:
            item: Optional[QTreeWidgetItem] = active_item
            while item is not None:
                if item is collapsed_item:
                    QTimer.singleShot(0, self._expand_active_branch)
                    return
                item = item.parent()

    @staticmethod
    def _live_text(active) -> str:
        icon = "⏸" if active.paused else "▶"
        elapsed = compact_duration(active.elapsed_seconds)
        if active.planned_duration_seconds is None:
            return f"{icon} Elapsed {elapsed}"
        return f"{icon} Remaining {compact_duration(active.remaining_seconds)} · Elapsed {elapsed}"

    def _refresh_daily_active_display(self) -> None:
        active = self.runtime.state()
        if active is None:
            self.plan_tree.viewport().update()
            return

        text = self._live_text(active)
        background = PAUSED_COLOR if active.paused else RUNNING_COLOR
        foreground = PAUSED_TEXT_COLOR if active.paused else RUNNING_TEXT_COLOR
        for item in self._daily_active_items:
            item.setText(1, text)
            font = QFont(item.font(0))
            font.setBold(True)
            item.setFont(0, font)
            self._set_row_style(item, background, foreground)

        self._expand_active_branch()
        self.plan_tree.viewport().update()

    def _runtime_ticked(self) -> None:
        super()._runtime_ticked()
        self._refresh_daily_active_display()

