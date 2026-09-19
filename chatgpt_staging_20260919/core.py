from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .database import PlanningDatabase
from .dialogs import (
    ActionStatisticsDialog,
    ActionTypeDialog,
    IntervalEditDialog,
    PlanDialog,
    RecurringScheduleDialog,
    TimeIntervalsDialog,
    TodosDialog,
    compact_duration,
    duration_text,
)
from .runtime import PlanningRuntime
from .scheduler import RECURRENCE_ONE_TIME, ScheduleService

NODE_ROLE = Qt.ItemDataRole.UserRole + 9001
DAY_ROLE = Qt.ItemDataRole.UserRole + 9002
PLAN_ID_ROLE = Qt.ItemDataRole.UserRole + 9003
ITEM_TYPE_ROLE = Qt.ItemDataRole.UserRole + 9005
PLAN_NOTE_ID_ROLE = Qt.ItemDataRole.UserRole + 9006
PLAN_ACTION_NOTE_ID_ROLE = Qt.ItemDataRole.UserRole + 9007
PLAN_ACTION_TODO_ID_ROLE = Qt.ItemDataRole.UserRole + 9008

ITEM_TYPE_DAY_HEADER = "day_header"
ITEM_TYPE_PLAN = "plan"
ITEM_TYPE_HISTORY = "history"
ITEM_TYPE_PLAN_NOTE = "plan_note"
ITEM_TYPE_PLAN_ACTION_NOTE = "plan_action_note"
ITEM_TYPE_ACTION_PANEL_TODO = "action_panel_todo"


def _spent(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "0m"
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def _bar_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    if 0 < seconds < 60:
        return "<1m"
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"
    return f"{minutes}m"


class ActionTreeWidget(QTreeWidget):
    layout_changed = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setIndentation(18)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.header().setStretchLastSection(True)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        rows: list[tuple[str, Optional[str], int]] = []

        def visit(parent_item: Optional[QTreeWidgetItem], parent_id: Optional[str]) -> None:
            count = self.topLevelItemCount() if parent_item is None else parent_item.childCount()
            for position in range(count):
                item = self.topLevelItem(position) if parent_item is None else parent_item.child(position)
                node_id = item.data(0, NODE_ROLE)
                if isinstance(node_id, str) and node_id:
                    rows.append((node_id, parent_id, position))
                    visit(item, node_id)

        visit(None, None)
        self.layout_changed.emit(rows)


class PlanTreeWidget(QTreeWidget):
    plan_moved = Signal(int, str, int)
    action_type_dropped = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Plan / Action", "Spent", "Schedule"])
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, self.header().ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, self.header().ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(2, self.header().ResizeMode.ResizeToContents)

    @staticmethod
    def day_header(item: Optional[QTreeWidgetItem]) -> Optional[QTreeWidgetItem]:
        current = item
        while current is not None:
            if current.data(0, ITEM_TYPE_ROLE) == ITEM_TYPE_DAY_HEADER:
                return current
            current = current.parent()
        return None

    def _action_type_drop_data(self, event) -> Optional[tuple[str, str]]:
        source = event.source()
        if not isinstance(source, ActionTreeWidget):
            return None
        source_item = source.currentItem()
        if source_item is None:
            return None
        node_id = source_item.data(0, NODE_ROLE)
        if not isinstance(node_id, str) or not node_id:
            return None
        target_item = self.itemAt(event.position().toPoint())
        header = self.day_header(target_item)
        if header is None:
            return None
        day_text = header.data(0, DAY_ROLE)
        if not isinstance(day_text, str) or not day_text:
            return None
        return node_id, day_text

    def dragEnterEvent(self, event) -> None:
        if isinstance(event.source(), ActionTreeWidget):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._action_type_drop_data(event) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        action_drop = self._action_type_drop_data(event)
        if action_drop is not None:
            node_id, day_text = action_drop
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.action_type_dropped.emit(node_id, day_text)
            return

        selected = self.currentItem()
        plan_id = None if selected is None else selected.data(0, PLAN_ID_ROLE)
        if plan_id is None:
            event.ignore()
            return
        target_item = self.itemAt(event.position().toPoint())
        header = self.day_header(target_item)
        if header is None:
            event.ignore()
            return
        day_text = header.data(0, DAY_ROLE)
        if not isinstance(day_text, str):
            event.ignore()
            return
        target_index = header.childCount()
        if target_item is not None and target_item.parent() is header:
            target_index = header.indexOfChild(target_item)
            if event.position().toPoint().y() > self.visualItemRect(target_item).center().y():
                target_index += 1
        self.plan_moved.emit(int(plan_id), day_text, target_index)
        event.acceptProposedAction()


class PlanActionTypeTodosDialog(QDialog):
    """Todos belonging to one Daily Plan action, independent of Action Type todos."""

    TABLE_NAME = "plan_action_type_todos"

    @staticmethod
    def ensure_schema(database: PlanningDatabase) -> None:
        with database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS plan_action_type_todos(
                    id_plan_action_type_todos INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_plan_action_types INTEGER NOT NULL,
                    todo TEXT NOT NULL,
                    is_done INTEGER NOT NULL DEFAULT 0,
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(id_plan_action_types)
                        REFERENCES plan_action_types(id_plan_action_types) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_plan_action_type_todos_plan_done
                    ON plan_action_type_todos(
                        id_plan_action_types,
                        is_done,
                        position,
                        id_plan_action_type_todos
                    );
                """
            )

    def __init__(self, database: PlanningDatabase, plan_action_id: int, parent=None) -> None:
        super().__init__(parent)
        self.database = database
        self.plan_action_id = int(plan_action_id)
        self.ensure_schema(database)
        self.setWindowTitle("Plan action todos")
        self.resize(620, 430)

        root = QVBoxLayout(self)
        plan = self.database.plan(self.plan_action_id)
        title = "Daily Plan action"
        if plan is not None:
            title = str(plan["action_name"] or plan["current_action_name"] or "Daily Plan action")
        root.addWidget(QLabel(f"Action: {title}", self))

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Done", "Todo"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        add = QPushButton("Add...", self)
        edit = QPushButton("Edit...", self)
        delete = QPushButton("Delete", self)
        buttons.addWidget(add)
        buttons.addWidget(edit)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        close = QPushButton("Close", self)
        buttons.addWidget(close)
        root.addLayout(buttons)

        add.clicked.connect(self._add)
        edit.clicked.connect(self._edit)
        delete.clicked.connect(self._delete)
        close.clicked.connect(self.accept)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit())
        self.refresh()

    @staticmethod
    def _now_text() -> str:
        return datetime.now().astimezone().isoformat(timespec="microseconds")

    def _rows(self):
        with self.database.connect() as connection:
            return connection.execute(
                """
                SELECT id_plan_action_type_todos,todo,is_done,position
                FROM plan_action_type_todos
                WHERE id_plan_action_types=?
                ORDER BY position,id_plan_action_type_todos
                """,
                (self.plan_action_id,),
            ).fetchall()

    def refresh(self) -> None:
        rows = self._rows()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            done_item = QTableWidgetItem("")
            done_item.setData(PLAN_ACTION_TODO_ID_ROLE, int(row["id_plan_action_type_todos"]))
            done_item.setFlags(
                (done_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                & ~Qt.ItemFlag.ItemIsEditable
            )
            done_item.setCheckState(
                Qt.CheckState.Checked if row["is_done"] else Qt.CheckState.Unchecked
            )
            todo_item = QTableWidgetItem(str(row["todo"]))
            todo_item.setData(PLAN_ACTION_TODO_ID_ROLE, int(row["id_plan_action_type_todos"]))
            todo_item.setFlags(todo_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(index, 0, done_item)
            self.table.setItem(index, 1, todo_item)
        self.table.blockSignals(False)
        self.table.resizeColumnToContents(0)

    def _selected(self) -> Optional[tuple[int, str]]:
        row_index = self.table.currentRow()
        if row_index < 0:
            return None
        id_item = self.table.item(row_index, 0)
        text_item = self.table.item(row_index, 1)
        if id_item is None or text_item is None:
            return None
        todo_id = id_item.data(PLAN_ACTION_TODO_ID_ROLE)
        if todo_id is None:
            return None
        return int(todo_id), text_item.text()

    def _add(self) -> None:
        text, accepted = QInputDialog.getText(self, "Add plan action todo", "Todo")
        text = str(text).strip()
        if not accepted or not text:
            return
        stamp = self._now_text()
        with self.database.connect() as connection:
            position_row = connection.execute(
                "SELECT COALESCE(MAX(position),-1)+1 AS p "
                "FROM plan_action_type_todos WHERE id_plan_action_types=?",
                (self.plan_action_id,),
            ).fetchone()
            position = int(position_row["p"] if position_row is not None else 0)
            connection.execute(
                """
                INSERT INTO plan_action_type_todos(
                    id_plan_action_types,todo,is_done,position,created_at,updated_at
                ) VALUES(?,?,0,?,?,?)
                """,
                (self.plan_action_id, text, position, stamp, stamp),
            )
        self.refresh()

    def _edit(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        todo_id, current_text = selected
        text, accepted = QInputDialog.getText(
            self,
            "Edit plan action todo",
            "Todo",
            text=current_text,
        )
        text = str(text).strip()
        if not accepted or not text:
            return
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plan_action_type_todos SET todo=?,updated_at=? "
                "WHERE id_plan_action_type_todos=?",
                (text, self._now_text(), todo_id),
            )
        self.refresh()

    def _delete(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        todo_id, _current_text = selected
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM plan_action_type_todos WHERE id_plan_action_type_todos=?",
                (todo_id,),
            )
        self.refresh()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        todo_id = item.data(PLAN_ACTION_TODO_ID_ROLE)
        if todo_id is None:
            return
        is_done = item.checkState() == Qt.CheckState.Checked
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE plan_action_type_todos SET is_done=?,updated_at=? "
                "WHERE id_plan_action_type_todos=?",
                (1 if is_done else 0, self._now_text(), int(todo_id)),
            )


class PlanningMainWindow(QMainWindow):
    def __init__(
        self,
        database: PlanningDatabase,
        runtime: PlanningRuntime,
        schedules: ScheduleService,
        *,
        yaml_action_kinds_file_path: Optional[str],
        yaml_plan_by_date_time_file_path: Optional[str],
        yaml_to_plan_file_path: Optional[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.runtime = runtime
        self.schedules = schedules
        self.yaml_action_kinds_file_path = yaml_action_kinds_file_path
        self.yaml_plan_by_date_time_file_path = yaml_plan_by_date_time_file_path
        self.yaml_to_plan_file_path = yaml_to_plan_file_path
        self.settings = QSettings("nd_planning_project", "planning")
        PlanActionTypeTodosDialog.ensure_schema(self.database)
        self._action_items: dict[str, QTreeWidgetItem] = {}
        self._remaining_labels: dict[str, QLabel] = {}
        self._panel_actions: dict[str, QAction] = {}
        self.setWindowTitle("ND Planning")
        self.resize(1240, 760)
        self._build_ui()
        self._connect_signals()
        self._restore_window_state()
        self.refresh_all()
        self.schedules.start()
        self._plan_refresh_timer = QTimer(self)
        self._plan_refresh_timer.setInterval(60_000)
        self._plan_refresh_timer.timeout.connect(self.refresh_plans)
        self._plan_refresh_timer.start()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)

        self.active_bar_host = QWidget(root)
        host_layout = QHBoxLayout(self.active_bar_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        self.active_bar = QFrame(self.active_bar_host)
        self.active_bar.setObjectName("activeActionBar")
        bar = QHBoxLayout(self.active_bar)
        bar.setContentsMargins(8, 3, 8, 3)
        bar.setSpacing(6)
        self.active_title = QLabel("", self.active_bar)
        self.active_title.setStyleSheet("font-weight:700;")
        self.active_pause = QToolButton(self.active_bar)
        self.active_restart = QToolButton(self.active_bar)
        self.active_stop = QToolButton(self.active_bar)
        for button in (self.active_pause, self.active_restart, self.active_stop):
            button.setAutoRaise(True)
            button.setFixedSize(22, 22)
            button.setIconSize(QSize(14, 14))
        self.active_restart.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.active_restart.setToolTip("Restart current action")
        self.active_stop.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )
        self.active_stop.setToolTip("End current action")
        self.active_time = QLabel("", self.active_bar)
        self.active_time.setStyleSheet("font-weight:700;")
        bar.addWidget(self.active_title, 1)
        bar.addWidget(self.active_pause)
        bar.addWidget(self.active_restart)
        bar.addWidget(self.active_stop)
        bar.addWidget(self.active_time)
        host_layout.addWidget(self.active_bar, 1)
        layout.addWidget(self.active_bar_host)
        self.active_bar_host.hide()

        self.splitter = QSplitter(Qt.Orientation.Horizontal, root)
        self.left_box = self._build_left_box()
        self.middle_box = self._build_middle_box()
        self.right_box = self._build_right_box()
        for box in (self.left_box, self.middle_box, self.right_box):
            self.splitter.addWidget(box)
        self.splitter.setSizes([470, 445, 375])
        for index in range(3):
            self.splitter.setStretchFactor(index, 1)
        layout.addWidget(self.splitter, 1)
        self.statusBar().showMessage("Ready")
        self._build_menu()

    def _build_left_box(self) -> QGroupBox:
        box = QGroupBox("plans", self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(5, 7, 5, 5)
        controls = QHBoxLayout()
        add = QPushButton("Add...", box)
        statistics = QPushButton("Statistics...", box)
        refresh = QPushButton("Refresh", box)
        controls.addWidget(add)
        controls.addWidget(statistics)
        controls.addStretch(1)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.plan_tree = PlanTreeWidget(box)
        self.plan_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.plan_tree, 1)
        add.clicked.connect(lambda: self._add_plan(date.today()))
        statistics.clicked.connect(
            lambda: ActionStatisticsDialog(self.database, None, self).exec()
        )
        refresh.clicked.connect(self.refresh_plans)
        self.plan_tree.customContextMenuRequested.connect(self._plan_context_menu)
        self.plan_tree.itemDoubleClicked.connect(self._plan_double_clicked)
        self.plan_tree.plan_moved.connect(self._move_plan)
        self.plan_tree.action_type_dropped.connect(self._add_dropped_action_type_to_plan)
        return box

    def _build_middle_box(self) -> QGroupBox:
        box = QGroupBox("action_types", self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(5, 7, 5, 5)
        controls = QHBoxLayout()
        self.action_filter = QLineEdit(box)
        self.action_filter.setPlaceholderText("Filter action types...")
        self.action_filter.setClearButtonEnabled(True)
        controls.addWidget(self.action_filter, 1)
        self.show_todos_checkbox = QCheckBox("TODOs", box)
        self.show_todos_checkbox.setToolTip(
            "Show only Action Type branches containing TODOs, including Daily Plan TODOs"
        )
        controls.addWidget(self.show_todos_checkbox)
        self.action_actions_button = QPushButton("Root statistics...", box)
        self.action_actions_button.setEnabled(True)
        controls.addWidget(self.action_actions_button)
        layout.addLayout(controls)

        self.action_tree = ActionTreeWidget(box)
        self.action_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.action_tree, 1)

        bottom = QHBoxLayout()
        self.add_root_button = QPushButton("New root...", box)
        self.add_child_button = QPushButton("New child...", box)
        self.edit_action_button = QPushButton("Edit...", box)
        self.add_child_button.setEnabled(False)
        self.edit_action_button.setEnabled(False)
        bottom.addWidget(self.add_root_button)
        bottom.addWidget(self.add_child_button)
        bottom.addWidget(self.edit_action_button)
        layout.addLayout(bottom)

        self.action_filter.textChanged.connect(self._filter_actions)
        self.show_todos_checkbox.toggled.connect(
            lambda _checked=False: self.refresh_actions()
        )
        self.action_tree.itemSelectionChanged.connect(self._action_selection_changed)
        self.action_tree.customContextMenuRequested.connect(self._action_context_menu)
        self.action_tree.layout_changed.connect(self._save_action_layout)
        self.action_actions_button.clicked.connect(
            lambda: ActionStatisticsDialog(self.database, None, self).exec()
        )
        self.add_root_button.clicked.connect(lambda: self._add_action_type(None))
        self.add_child_button.clicked.connect(
            lambda: self._add_action_type(self._selected_node_id())
        )
        self.edit_action_button.clicked.connect(
            lambda: self._edit_action_type(self._selected_node_id())
            if self._selected_node_id()
            else None
        )
        return box

    def _build_right_box(self) -> QGroupBox:
        box = QGroupBox("to_plan", self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(5, 7, 5, 5)
        self.to_plan_filter = QLineEdit(box)
        self.to_plan_filter.setPlaceholderText("Filter unscheduled actions...")
        self.to_plan_filter.setClearButtonEnabled(True)
        layout.addWidget(self.to_plan_filter)
        self.to_plan_tree = QTreeWidget(box)
        self.to_plan_tree.setColumnCount(1)
        self.to_plan_tree.setHeaderLabels(["Not in today's plan"])
        self.to_plan_tree.setRootIsDecorated(False)
        self.to_plan_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.to_plan_tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(self.to_plan_tree, 1)
        buttons = QHBoxLayout()
        self.add_today_button = QPushButton("Add today", box)
        self.add_any_day_button = QPushButton("Add...", box)
        buttons.addWidget(self.add_today_button)
        buttons.addWidget(self.add_any_day_button)
        layout.addLayout(buttons)
        self.to_plan_filter.textChanged.connect(lambda _text: self.refresh_to_plan())
        self.to_plan_tree.itemSelectionChanged.connect(self._to_plan_selection_changed)
        self.to_plan_tree.itemDoubleClicked.connect(self._to_plan_activated)
        self.add_today_button.clicked.connect(
            lambda: self._add_selected_to_plan(today=True)
        )
        self.add_any_day_button.clicked.connect(
            lambda: self._add_selected_to_plan(today=False)
        )
        return box

    def _build_menu(self) -> None:
        view_menu = self.menuBar().addMenu("View")
        for key, title, panel in (
            ("plans", "Plans", self.left_box),
            ("action_types", "Action Types", self.middle_box),
            ("to_plan", "To Plan", self.right_box),
        ):
            action = QAction(title, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(panel.setVisible)
            self._panel_actions[key] = action
            view_menu.addAction(action)
        tools = self.menuBar().addMenu("Tools")
        statistics = QAction("Action type time graphâ¦", self)
        statistics.triggered.connect(
            lambda: ActionStatisticsDialog(self.database, None, self).exec()
        )
        tools.addAction(statistics)
        reload_action = QAction("Refresh", self)
        reload_action.triggered.connect(self.refresh_all)
        tools.addAction(reload_action)

    def _connect_signals(self) -> None:
        self.runtime.state_changed.connect(self._runtime_changed)
        self.runtime.ticked.connect(self._runtime_ticked)
        self.runtime.finished.connect(self._runtime_finished)
        self.schedules.plan_changed.connect(self.refresh_plans)
        self.splitter.splitterMoved.connect(lambda *_: self._save_window_state())
        self.active_pause.clicked.connect(self._toggle_active_pause)
        self.active_restart.clicked.connect(self._restart_active)
        self.active_stop.clicked.connect(
            lambda: self.runtime.stop(announce_finished=False)
        )

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass
        sizes = self.settings.value("splitter_sizes")
        if isinstance(sizes, list) and len(sizes) == 3:
            try:
                self.splitter.setSizes([int(value) for value in sizes])
            except Exception:
                pass
        for key, panel in (
            ("plans", self.left_box),
            ("action_types", self.middle_box),
            ("to_plan", self.right_box),
        ):
            raw = self.settings.value(f"panel_{key}")
            if raw is not None:
                visible = str(raw).lower() not in {"0", "false", "no"}
                panel.setVisible(visible)
                self._panel_actions[key].setChecked(visible)

    def _save_window_state(self) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter_sizes", self.splitter.sizes())
        self.settings.setValue("panel_plans", self.left_box.isVisible())
        self.settings.setValue("panel_action_types", self.middle_box.isVisible())
        self.settings.setValue("panel_to_plan", self.right_box.isVisible())
        self.settings.sync()

    def closeEvent(self, event) -> None:
        self._save_window_state()
        super().closeEvent(event)

    def refresh_all(self) -> None:
        self.refresh_plans()
        self.refresh_actions()
        self.refresh_to_plan()
        self._refresh_active_bar()

    def _capture_expanded_actions(self) -> set[str]:
        result: set[str] = set()

        def visit(item: QTreeWidgetItem) -> None:
            node_id = item.data(0, NODE_ROLE)
            if item.isExpanded() and isinstance(node_id, str):
                result.add(node_id)
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self.action_tree.topLevelItemCount()):
            visit(self.action_tree.topLevelItem(index))
        return result

    def refresh_actions(self) -> None:
        selected = self._selected_node_id()
        expanded = self._capture_expanded_actions()
        self.action_tree.blockSignals(True)
        self.action_tree.clear()
        self._action_items.clear()
        self._remaining_labels.clear()
        rows = self.database.action_types()
        by_parent: dict[Optional[str], list] = {}
        for row in rows:
            parent = None if row["parent_id"] is None else str(row["parent_id"])
            by_parent.setdefault(parent, []).append(row)
        for values in by_parent.values():
            values.sort(
                key=lambda row: (
                    int(row["position"] or 0),
                    str(row["title"]).casefold(),
                )
            )

        show_todos = bool(self.show_todos_checkbox.isChecked())
        todos_by_action: dict[str, list] = {}
        todo_branch_ids: set[str] = set()
        if show_todos:
            for todo_row in self.database.action_panel_todos():
                todos_by_action.setdefault(
                    str(todo_row["id_action_types"]),
                    [],
                ).append(todo_row)

            row_by_stable = {str(row["id"]): row for row in rows}
            stable_by_canonical = {
                str(row["id_action_types"]): str(row["id"])
                for row in rows
            }
            for canonical_id in todos_by_action:
                stable_id = stable_by_canonical.get(canonical_id)
                seen: set[str] = set()
                while stable_id and stable_id not in seen:
                    seen.add(stable_id)
                    todo_branch_ids.add(stable_id)
                    parent_value = row_by_stable.get(stable_id)
                    if parent_value is None or parent_value["parent_id"] is None:
                        stable_id = None
                    else:
                        stable_id = str(parent_value["parent_id"])

            # The tree is intentionally incomplete in TODO mode. Do not allow
            # drag/drop to persist a partial hierarchy back into action_types.
            self.action_tree.setDragDropMode(
                QAbstractItemView.DragDropMode.NoDragDrop
            )
        else:
            self.action_tree.setDragDropMode(
                QAbstractItemView.DragDropMode.InternalMove
            )

        active = self.runtime.state()
        paused = self.runtime.paused_snapshots()
        self._refresh_active_bar()

        def add(parent_item: Optional[QTreeWidgetItem], row) -> None:
            node_id = str(row["id"])
            if show_todos and node_id not in todo_branch_ids:
                return
            item = QTreeWidgetItem([""])
            item.setData(0, NODE_ROLE, node_id)
            if parent_item is None:
                self.action_tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            self._action_items[node_id] = item
            item.setExpanded(show_todos or node_id in expanded)
            if selected == node_id:
                self.action_tree.setCurrentItem(item)

            container = QWidget(self.action_tree)
            line = QHBoxLayout(container)
            line.setContentsMargins(2, 0, 4, 0)
            line.setSpacing(4)
            title = QLabel(str(row["title"]), container)
            title.setStyleSheet(
                "font-weight:600;background:transparent;"
                if parent_item is None
                else "background:transparent;"
            )
            line.addWidget(title)

            play_pause = QToolButton(container)
            stop = QToolButton(container)
            restart = QToolButton(container)
            todos = QToolButton(container)
            for button in (play_pause, stop, restart, todos):
                button.setAutoRaise(True)
                button.setFixedSize(22, 22)
                button.setIconSize(QSize(14, 14))

            node_is_current = active is not None and active.current_node_id == node_id
            paused_snapshot = None
            for snapshot in paused.values():
                if snapshot.get("current_node_id") == node_id:
                    paused_snapshot = snapshot
                    break

            if node_is_current and active is not None and not active.paused:
                play_pause.setIcon(self.active_pause.icon())
                play_pause.setIconSize(self.active_pause.iconSize())
                play_pause.setToolTip("Pause")
                play_pause.clicked.connect(self.runtime.pause)
            elif node_is_current and active is not None and active.paused:
                play_pause.setIcon(self.active_pause.icon())
                play_pause.setIconSize(self.active_pause.iconSize())
                play_pause.setToolTip("Continue")
                play_pause.clicked.connect(self.runtime.resume)
            elif paused_snapshot is not None:
                play_pause.setIcon(
                    self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
                )
                play_pause.setToolTip("Continue paused action")
                play_pause.clicked.connect(
                    lambda _checked=False, nid=node_id: self._start_action_type_manually(nid)
                )
            else:
                play_pause.setIcon(
                    self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
                )
                play_pause.setToolTip("Start")
                play_pause.clicked.connect(
                    lambda _checked=False, nid=node_id: self._start_action_type_manually(nid)
                )

            stop.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
            )
            stop.setToolTip("Stop")
            stop.setStyleSheet(
                "QToolButton{background:#D14E5C;border-radius:4px;}"
                "QToolButton:hover{background:#BE4250;}"
            )
            if node_is_current and active is not None:
                stop.clicked.connect(
                    lambda _checked=False: self.runtime.stop(announce_finished=False)
                )
                stop.show()
            elif paused_snapshot is not None:
                paused_root = str(paused_snapshot.get("root_node_id") or "")
                if paused_root:
                    stop.clicked.connect(
                        lambda _checked=False, rid=paused_root: self.runtime.end_paused_run(rid)
                    )
                    stop.show()
                else:
                    stop.hide()
            else:
                stop.hide()

            restart.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
            )
            restart.setToolTip("Restart")
            restart.clicked.connect(
                lambda _checked=False, nid=node_id: self.runtime.restart_node(
                    nid,
                    speak=False,
                )
            )
            todos.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            )
            todos.setToolTip("Todos")
            todos.clicked.connect(
                lambda _checked=False, nid=node_id: self._open_action_todos(nid)
            )

            line.addWidget(play_pause)
            line.addWidget(stop)
            line.addWidget(restart)
            line.addWidget(todos)

            remaining = QLabel("", container)
            remaining.setStyleSheet(
                "color:#c62828;font-weight:700;background:transparent;padding-left:4px;"
            )
            self._remaining_labels[node_id] = remaining
            if node_is_current and active is not None:
                if active.planned_duration_seconds is None:
                    remaining.setText("elapsed " + compact_duration(active.elapsed_seconds))
                else:
                    remaining.setText(compact_duration(active.remaining_seconds))
            elif paused_snapshot is not None:
                remaining.setText(
                    "â¸ E "
                    + compact_duration(int(paused_snapshot.get("elapsed_seconds", 0)))
                    + " Â· R "
                    + compact_duration(int(paused_snapshot.get("remaining_seconds", 0)))
                )
            line.addWidget(remaining)
            line.addStretch(1)

            if node_is_current and active is not None and not active.paused:
                container.setStyleSheet("background-color:rgb(255,246,184);")
            elif (
                node_is_current
                and active is not None
                and active.paused
            ) or paused_snapshot is not None:
                container.setStyleSheet("background-color:rgb(255,243,205);")
            else:
                container.setStyleSheet("background:transparent;")

            self.action_tree.setItemWidget(item, 0, container)
            item.setSizeHint(0, QSize(0, 25))

            if show_todos:
                canonical_id = str(row["id_action_types"])
                for todo_row in todos_by_action.get(canonical_id, []):
                    day_text = str(todo_row["day"] or "").strip()
                    time_text = str(todo_row["run_time"] or "").strip()
                    schedule_text = " ".join(
                        value for value in (day_text, time_text) if value
                    )
                    status = "[x]" if int(todo_row["is_done"] or 0) else "[ ]"
                    todo_text = f"{status} {todo_row['todo']}"
                    if schedule_text:
                        todo_text = f"{schedule_text} · {todo_text}"

                    todo_item = QTreeWidgetItem([todo_text])
                    todo_item.setData(
                        0,
                        ITEM_TYPE_ROLE,
                        ITEM_TYPE_ACTION_PANEL_TODO,
                    )
                    todo_item.setForeground(0, QBrush(QColor("#B45309")))
                    todo_item.setFlags(
                        todo_item.flags()
                        & ~Qt.ItemFlag.ItemIsDragEnabled
                        & ~Qt.ItemFlag.ItemIsDropEnabled
                    )
                    todo_item.setSizeHint(0, QSize(0, 23))
                    item.addChild(todo_item)

            for child in by_parent.get(node_id, []):
                add(item, child)

        for row in by_parent.get(None, []):
            add(None, row)
        self.action_tree.blockSignals(False)
        self._filter_actions(self.action_filter.text())
        self._action_selection_changed()

    def _capture_expanded_days(self) -> set[str]:
        result: set[str] = set()
        for index in range(self.plan_tree.topLevelItemCount()):
            item = self.plan_tree.topLevelItem(index)
            value = item.data(0, DAY_ROLE)
            if item.isExpanded() and isinstance(value, str):
                result.add(value)
        return result

    def refresh_plans(self) -> None:
        expanded = self._capture_expanded_days()
        selected_plan_id = None
        current_item = self.plan_tree.currentItem()
        if current_item is not None:
            selected_plan_id = current_item.data(0, PLAN_ID_ROLE)

        self.plan_tree.blockSignals(True)
        self.plan_tree.clear()
        today = datetime.now().astimezone().date()
        days = set(self.database.activity_days())
        days.update(self.database.plan_days())
        days.add(today)
        action_rows = self.database.action_types(include_archived=True)
        title_by_id = {
            str(row["id"]): str(row["title"] or "Action")
            for row in action_rows
        }
        parent_by_id = {
            str(row["id"]): None
            if row["parent_id"] is None
            else str(row["parent_id"])
            for row in action_rows
        }
        position_by_id = {
            str(row["id"]): int(row["position"] or 0)
            for row in action_rows
        }

        for day_value in sorted(days, reverse=True):
            header = QTreeWidgetItem(
                [day_value.strftime("%A Â· %d %B %Y"), "", ""]
            )
            header.setData(0, ITEM_TYPE_ROLE, ITEM_TYPE_DAY_HEADER)
            header.setData(0, DAY_ROLE, day_value.isoformat())
            self.plan_tree.addTopLevelItem(header)
            header.setExpanded(
                day_value.isoformat() in expanded or day_value == today
            )

            plans = self.database.plans_for_day(day_value)
            stats = self.database.day_node_stats(day_value) if day_value <= today else {}
            plan_by_node: dict[str, list] = {}
            for row in plans:
                node_id = str(row["node_id"])
                plan_by_node.setdefault(node_id, []).append(row)

            visible: set[str] = set(plan_by_node)
            visible.update(
                node_id
                for node_id, stat in stats.items()
                if int(stat.get("seconds", 0) or 0) > 0
            )
            for node_id in list(visible):
                parent_id = parent_by_id.get(node_id)
                seen: set[str] = set()
                while parent_id and parent_id not in seen:
                    seen.add(parent_id)
                    visible.add(parent_id)
                    parent_id = parent_by_id.get(parent_id)

            children: dict[Optional[str], list[str]] = {}
            for node_id in visible:
                parent_id = parent_by_id.get(node_id)
                if parent_id not in visible:
                    parent_id = None
                children.setdefault(parent_id, []).append(node_id)
            for values in children.values():
                values.sort(
                    key=lambda nid: (
                        position_by_id.get(nid, 0),
                        title_by_id.get(nid, "").casefold(),
                    )
                )

            represented: set[int] = set()

            def add_node(parent_item: QTreeWidgetItem, node_id: str) -> None:
                stat = stats.get(node_id, {"seconds": 0})
                node_plans = plan_by_node.get(node_id, [])
                schedules: list[str] = []
                for row in node_plans:
                    represented.add(int(row["id_plan_action_types"]))
                    raw = str(row["run_time"] or "").strip()
                    if raw and raw not in schedules:
                        schedules.append(raw)

                title = title_by_id.get(node_id, "Action")
                if len(node_plans) == 1:
                    custom = str(node_plans[0]["action_name"] or "").strip()
                    if custom and custom != title:
                        title = custom

                item = QTreeWidgetItem(
                    [
                        title,
                        _spent(int(stat.get("seconds", 0) or 0)),
                        ", ".join(schedules),
                    ]
                )
                item.setData(0, ITEM_TYPE_ROLE, ITEM_TYPE_HISTORY)
                item.setData(0, NODE_ROLE, node_id)
                if node_plans:
                    item.setData(
                        0,
                        PLAN_ID_ROLE,
                        int(node_plans[0]["id_plan_action_types"]),
                    )
                parent_item.addChild(item)
                item.setExpanded(True)
                if (
                    selected_plan_id is not None
                    and item.data(0, PLAN_ID_ROLE) == selected_plan_id
                ):
                    self.plan_tree.setCurrentItem(item)

                for row in node_plans:
                    plan_id = int(row["id_plan_action_types"])
                    for note in self.database.plan_action_notes(plan_id):
                        note_item = QTreeWidgetItem(
                            [f"note: {note['note']}", "", ""]
                        )
                        note_item.setData(
                            0,
                            ITEM_TYPE_ROLE,
                            ITEM_TYPE_PLAN_ACTION_NOTE,
                        )
                        note_item.setData(
                            0,
                            PLAN_ACTION_NOTE_ID_ROLE,
                            int(note["id_plan_action_notes"]),
                        )
                        item.addChild(note_item)

                for child_id in children.get(node_id, []):
                    add_node(item, child_id)

            for root_id in children.get(None, []):
                add_node(header, root_id)

            for row in plans:
                plan_id = int(row["id_plan_action_types"])
                if plan_id in represented:
                    continue
                title = str(
                    row["action_name"]
                    or row["current_action_name"]
                    or "Action"
                )
                item = QTreeWidgetItem(
                    [
                        title,
                        "0m" if day_value <= today else "",
                        str(row["run_time"] or ""),
                    ]
                )
                item.setData(0, ITEM_TYPE_ROLE, ITEM_TYPE_PLAN)
                item.setData(0, PLAN_ID_ROLE, plan_id)
                item.setData(0, NODE_ROLE, str(row["node_id"]))
                header.addChild(item)

            for note in self.database.plan_notes(day_value):
                note_item = QTreeWidgetItem(
                    [f"note: {note['note']}", "", ""]
                )
                note_item.setData(0, ITEM_TYPE_ROLE, ITEM_TYPE_PLAN_NOTE)
                note_item.setData(
                    0,
                    PLAN_NOTE_ID_ROLE,
                    int(note["id_plan_notes"]),
                )
                header.addChild(note_item)

            if day_value.isocalendar().week % 2 == 0:
                brush = QBrush(QColor(239, 245, 255))
                for column in range(3):
                    header.setBackground(column, brush)

        self.plan_tree.blockSignals(False)
        self.plan_tree.resizeColumnToContents(1)
        self.plan_tree.resizeColumnToContents(2)

    def refresh_to_plan(self) -> None:
        selected_node = self._selected_to_plan_node_id()
        self.to_plan_tree.clear()
        query = str(self.to_plan_filter.text() or "").strip().casefold()
        today = datetime.now().astimezone().date()
        planned_today = {
            str(row["node_id"])
            for row in self.database.plans_for_day(today)
            if row["node_id"] is not None
        }
        rows = self.database.action_types()
        child_count: dict[str, int] = {}
        for row in rows:
            if row["parent_id"] is not None:
                parent = str(row["parent_id"])
                child_count[parent] = child_count.get(parent, 0) + 1

        candidates = []
        for row in rows:
            node_id = str(row["id"])
            if node_id in planned_today or child_count.get(node_id, 0) > 0:
                continue
            path = " > ".join(
                str(path_row["title"])
                for path_row in self.database.action_path(node_id)
            )
            if query and query not in path.casefold():
                continue
            candidates.append((path, node_id))

        for path, node_id in sorted(candidates, key=lambda value: value[0].casefold()):
            item = QTreeWidgetItem([path])
            item.setData(0, NODE_ROLE, node_id)
            self.to_plan_tree.addTopLevelItem(item)
            if node_id == selected_node:
                self.to_plan_tree.setCurrentItem(item)
        self._to_plan_selection_changed()

    def _refresh_active_bar(self) -> None:
        active = self.runtime.state()
        if active is None:
            self.active_bar_host.hide()
            self.statusBar().showMessage("MindWandering")
            return

        self.active_bar_host.show()
        root = self.database.action_type(active.root_node_id, include_archived=True)
        current = self.database.action_type(active.current_node_id, include_archived=True)
        root_title = str(
            root["title"] if root is not None else active.root_node_id
        )
        current_title = str(
            current["title"] if current is not None else active.current_node_id
        )
        prefix = "Paused" if active.paused else "Running"
        title = f"{prefix} Â· {root_title}"
        if active.current_node_id != active.root_node_id:
            title += f" âº {current_title}"
        self.active_title.setText(title)

        if active.paused:
            self.active_pause.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
            )
            self.active_pause.setToolTip("Continue")
            background, border = "#fff3cd", "#d6b656"
        else:
            self.active_pause.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
            )
            self.active_pause.setToolTip("Pause")
            background, border = "#dff4e3", "#75b784"

        self.active_bar.setStyleSheet(
            f"QFrame#activeActionBar {{background:{background};"
            f"border:1px solid {border};border-radius:7px;}}"
        )

        if active.planned_duration_seconds is None:
            self.active_time.setText(
                "Elapsed " + compact_duration(active.elapsed_seconds)
            )
        else:
            self.active_time.setText(
                "Remaining "
                + _bar_remaining(active.remaining_seconds)
                + " Â· Elapsed "
                + compact_duration(active.elapsed_seconds)
            )

    def _runtime_ticked(self) -> None:
        active = self.runtime.state()
        if active is not None:
            label = self._remaining_labels.get(active.current_node_id)
            if label is not None:
                if active.planned_duration_seconds is None:
                    label.setText(
                        "elapsed " + compact_duration(active.elapsed_seconds)
                    )
                else:
                    label.setText(compact_duration(active.remaining_seconds))
        self._refresh_active_bar()

    def _runtime_changed(self) -> None:
        self.refresh_actions()
        self.refresh_plans()
        self.refresh_to_plan()
        self._refresh_active_bar()

    def _runtime_finished(self, node_id: str) -> None:
        temporary = self.runtime.temporary_node_id()
        if temporary and temporary == str(node_id):
            self.database.archive_action_type(temporary)
            self.runtime.set_temporary_node(None)
        self.refresh_all()

    def _toggle_active_pause(self) -> None:
        active = self.runtime.state()
        if active is not None:
            self.runtime.resume() if active.paused else self.runtime.pause()

    def _restart_active(self) -> None:
        active = self.runtime.state()
        if active is not None:
            self.runtime.restart_node(active.current_node_id, speak=False)

    def _selected_node_id(self) -> Optional[str]:
        item = self.action_tree.currentItem()
        if item is None:
            return None
        value = item.data(0, NODE_ROLE)
        return value if isinstance(value, str) and value else None

    def _action_selection_changed(self) -> None:
        selected = self._selected_node_id() is not None
        self.action_actions_button.setEnabled(True)
        self.add_child_button.setEnabled(selected)
        self.edit_action_button.setEnabled(selected)

    def _filter_actions(self, text: str) -> None:
        query = str(text).strip().casefold()

        def show_subtree(item: QTreeWidgetItem) -> None:
            item.setHidden(False)
            if query:
                item.setExpanded(True)
            for index in range(item.childCount()):
                show_subtree(item.child(index))

        def visit(item: QTreeWidgetItem) -> bool:
            node_id = item.data(0, NODE_ROLE)
            row = (
                self.database.action_type(node_id)
                if isinstance(node_id, str)
                else None
            )
            own = (
                bool(row and query in str(row["title"]).casefold())
                if query
                else True
            )
            if query and own:
                show_subtree(item)
                return True

            child_match = False
            for index in range(item.childCount()):
                child_match = visit(item.child(index)) or child_match
            visible = own or child_match
            item.setHidden(not visible)
            if query and child_match:
                item.setExpanded(True)
            return visible

        for index in range(self.action_tree.topLevelItemCount()):
            visit(self.action_tree.topLevelItem(index))

    def _save_action_layout(self, rows: list) -> None:
        try:
            self.database.save_tree_layout(rows)
        except Exception as error:
            QMessageBox.warning(self, "Move action", str(error))
        self.refresh_actions()

    def _add_action_type(self, parent_id: Optional[str]) -> None:
        dialog = ActionTypeDialog(title="Add Action Type", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.database.create_action_type(
                dialog.entered_name(),
                parent_id,
                dialog.entered_duration_seconds(),
            )
        except Exception as error:
            QMessageBox.warning(self, "Add Action Type", str(error))
            return
        self.refresh_actions()

    def _edit_action_type(self, node_id: str) -> None:
        row = self.database.action_type(node_id)
        if row is None:
            return
        dialog = ActionTypeDialog(
            title="Edit Action Type",
            initial_name=str(row["title"]),
            initial_duration_seconds=self.database.default_planned_seconds(node_id),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.database.update_action_type(
                node_id,
                dialog.entered_name(),
                dialog.entered_duration_seconds(),
            )
        except Exception as error:
            QMessageBox.warning(self, "Edit Action Type", str(error))
            return
        self.refresh_all()

    def _delete_action_type(self, node_id: str) -> None:
        title = self.database.path_title(node_id)
        answer = QMessageBox.question(
            self,
            "Delete Action Type",
            f'Archive "{title}" and its sub-actions? Recorded time history is kept.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            active = self.runtime.state()
            if active and node_id in self.database.subtree_ids(active.root_node_id):
                self.runtime.stop(announce_finished=False)
            self.database.archive_action_type(node_id)
            self.refresh_all()

    def _action_context_menu(self, position) -> None:
        item = self.action_tree.itemAt(position)
        if item is None:
            return
        node_id = item.data(0, NODE_ROLE)
        if isinstance(node_id, str):
            self._show_action_menu(
                node_id,
                self.action_tree.viewport().mapToGlobal(position),
            )

    def _selected_action_menu(self) -> None:
        node_id = self._selected_node_id()
        if node_id:
            self._show_action_menu(
                node_id,
                self.action_actions_button.mapToGlobal(
                    self.action_actions_button.rect().bottomLeft()
                ),
            )

    def _open_action_todos(self, node_id: str) -> None:
        TodosDialog(self.database, node_id, self).exec()
        if self.show_todos_checkbox.isChecked():
            self.refresh_actions()

    def _show_action_menu(self, node_id: str, global_position) -> None:
        menu = QMenu(self)
        active = self.runtime.state()
        node_is_current = active is not None and active.current_node_id == node_id
        start_action = menu.addAction("Start")
        if node_is_current and active is not None:
            start_action.setText("Continue" if active.paused else "Pause")
        menu.addSeparator()
        add_more = menu.addAction("Add more time...")
        add_more.setEnabled(
            node_is_current
            and active is not None
            and active.planned_duration_seconds is not None
        )
        add_time = menu.addAction("Add time...")
        intervals = menu.addAction("Time intervals...")
        schedule = menu.addAction("Schedule...")
        todos = menu.addAction("Todos...")
        statistics = menu.addAction("Statistics...")
        menu.addSeparator()
        add_child = menu.addAction("Add sub-action")
        edit = menu.addAction("Edit")
        delete = menu.addAction("Delete")
        selected = menu.exec(global_position)

        if selected is start_action:
            if node_is_current and active is not None:
                self.runtime.resume() if active.paused else self.runtime.pause()
            else:
                self._start_action_type_manually(node_id)
        elif selected is add_more:
            self._add_more_time()
        elif selected is add_time:
            self._add_completed_time(node_id)
        elif selected is intervals:
            TimeIntervalsDialog(self.database, node_id, self).exec()
        elif selected is schedule:
            self._schedule_action(node_id)
        elif selected is todos:
            self._open_action_todos(node_id)
        elif selected is statistics:
            ActionStatisticsDialog(self.database, node_id, self).exec()
        elif selected is add_child:
            self._add_action_type(node_id)
        elif selected is edit:
            self._edit_action_type(node_id)
        elif selected is delete:
            self._delete_action_type(node_id)

    def _start_action_type_manually(self, node_id: str) -> None:
        try:
            started = self.runtime.start_node(node_id, speak=False)
            if not started:
                return
            plan_id = self.database.record_manual_start(node_id)
            self.database.mark_plan_handled(plan_id, ran=True)
            self.runtime.set_plan_id(plan_id)
            self.statusBar().showMessage(
                f"Started: {self.database.path_title(node_id)} | "
                "added to today's Daily Plan",
                5000,
            )
        except Exception as error:
            QMessageBox.warning(self, "Start Action Type", str(error))
            return
        self.refresh_all()

    def _add_more_time(self) -> None:
        minutes, accepted = QInputDialog.getInt(
            self,
            "Add more time",
            "Minutes",
            10,
            1,
            24 * 60,
            1,
        )
        if accepted:
            try:
                self.runtime.add_more_time(minutes * 60)
            except Exception as error:
                QMessageBox.warning(self, "Add more time", str(error))

    def _add_completed_time(self, node_id: str) -> None:
        dialog = IntervalEditDialog(title="Add completed time", parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            started, ended = dialog.interval()
        except Exception as error:
            QMessageBox.warning(self, "Add time", str(error))
            return

        target_node_id = str(node_id)
        active = self.runtime.state()
        active_node_id = (
            str(active.current_node_id)
            if active is not None and not active.paused
            else None
        )
        transfer_running = False
        if active_node_id and active_node_id != target_node_id:
            overlap = self.runtime.running_overlap_seconds(started, ended)
            if overlap > 0:
                answer = QMessageBox.question(
                    self,
                    "Move time from running action",
                    f'This added time overlaps "{self.database.path_title(active_node_id)}" '
                    f"by {duration_text(overlap)}.\n\n"
                    "Move that time to this action and return it to the remaining "
                    "time of the running action?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                transfer_running = answer == QMessageBox.StandardButton.Yes

        previous = self.database.previous_overlapping_interval(
            target_node_id,
            started,
            ended,
            exclude_node_id=active_node_id,
        )
        transfer_previous = False
        if previous is not None:
            answer = QMessageBox.question(
                self,
                "Move time from previous action",
                f'This added time overlaps "{self.database.path_title(str(previous["node_id"]))}" '
                f'by {duration_text(int(previous["overlap_seconds"]))}.\n\n'
                "Move that time to this action?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            transfer_previous = answer == QMessageBox.StandardButton.Yes

        try:
            self.database.add_completed_interval(
                target_node_id,
                started,
                ended,
            )
            if transfer_running and active_node_id:
                self.runtime.subtract_running_overlap(started, ended)
            if transfer_previous and previous is not None:
                old_node, removed = self.database.subtract_interval_overlap(
                    int(previous["id"]),
                    started,
                    ended,
                )
                if removed > 0:
                    self.runtime.restore_remaining_time(old_node, removed)
        except Exception as error:
            QMessageBox.warning(self, "Add time", str(error))
            return

        self.refresh_plans()
        self.refresh_actions()

    def _schedule_action(self, node_id: str) -> None:
        dialog = RecurringScheduleDialog(
            action_title=self.database.path_title(node_id),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            recurrence = dialog.recurrence_type()
            if recurrence == RECURRENCE_ONE_TIME:
                action = self.database.action_type(node_id)
                self.database.add_plan(
                    day_value=dialog.selected_date(),
                    action_name=""
                    if action is None
                    else str(action["title"]),
                    node_id=node_id,
                    run_time=dialog.selected_time(),
                    reminders=dialog.reminders(),
                    duration_seconds=self.database.default_planned_seconds(node_id)
                    or 30 * 60,
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

    def _add_dropped_action_type_to_plan(self, node_id: str, day_text: str) -> None:
        try:
            target_day = date.fromisoformat(str(day_text))
        except ValueError:
            return
        if self.database.action_type(str(node_id)) is None:
            return
        self._add_plan(target_day, initial_node_id=str(node_id))

    def _add_plan(
        self,
        day_value: date,
        initial_node_id: Optional[str] = None,
    ) -> None:
        if initial_node_id:
            initial_duration = (
                self.database.default_planned_seconds(initial_node_id)
                or 30 * 60
            )
        else:
            initial_duration = 30 * 60
        dialog = PlanDialog(
            self.database,
            dialog_title="Add Daily Plan",
            initial_day=day_value,
            initial_node_id=initial_node_id,
            initial_duration_seconds=initial_duration,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            node_id = dialog.selected_node_id()
            title = dialog.entered_title()
            if not title and node_id:
                title = self.database.path_title(node_id).split(" > ")[-1]
            self.database.add_plan(
                day_value=dialog.selected_day(),
                action_name=title,
                node_id=node_id,
                run_time=dialog.run_time(),
                reminders=dialog.reminders(),
                duration_seconds=dialog.duration_seconds(),
            )
        except Exception as error:
            QMessageBox.warning(self, "Add Daily Plan", str(error))
            return
        self.refresh_all()

    def _edit_plan(self, plan_id: int) -> None:
        row = self.database.plan(plan_id)
        if row is None:
            return
        try:
            reminders = [
                str(value)
                for value in json.loads(str(row["reminders_json"] or "[]"))
            ]
        except Exception:
            reminders = []
        dialog = PlanDialog(
            self.database,
            dialog_title="Edit Daily Plan",
            initial_day=date.fromisoformat(str(row["day"])),
            initial_title=str(row["action_name"] or ""),
            initial_node_id=None
            if row["node_id"] is None
            else str(row["node_id"]),
            initial_run_time=row["run_time"],
            initial_reminders=reminders,
            initial_duration_seconds=max(
                60,
                int(row["duration_seconds"] or 30 * 60),
            ),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            node_id = dialog.selected_node_id()
            title = dialog.entered_title()
            if not title and node_id:
                title = self.database.path_title(node_id).split(" > ")[-1]
            self.database.update_plan(
                plan_id,
                day_value=dialog.selected_day(),
                action_name=title,
                node_id=node_id,
                run_time=dialog.run_time(),
                reminders=dialog.reminders(),
                duration_seconds=dialog.duration_seconds(),
            )
        except Exception as error:
            QMessageBox.warning(self, "Edit Daily Plan", str(error))
            return
        self.refresh_all()

    def _plan_double_clicked(self, item, _column) -> None:
        item_type = item.data(0, ITEM_TYPE_ROLE)
        if item_type == ITEM_TYPE_PLAN_NOTE:
            note_id = item.data(0, PLAN_NOTE_ID_ROLE)
            if note_id is not None:
                self._edit_plan_note(
                    int(note_id),
                    item.text(0).removeprefix("note: "),
                )
            return
        if item_type == ITEM_TYPE_PLAN_ACTION_NOTE:
            note_id = item.data(0, PLAN_ACTION_NOTE_ID_ROLE)
            if note_id is not None:
                self._edit_plan_action_note(
                    int(note_id),
                    item.text(0).removeprefix("note: "),
                )
            return
        plan_id = item.data(0, PLAN_ID_ROLE)
        if plan_id is not None:
            self._start_plan(int(plan_id))

    def _start_plan(self, plan_id: int) -> None:
        row = self.database.plan(plan_id)
        if row is None:
            return
        node_id = str(row["node_id"])
        self.runtime.prepare_plan_duration(
            plan_id,
            node_id,
            max(60, int(row["duration_seconds"] or 30 * 60)),
        )
        started = self.runtime.start_node(node_id, speak=False)
        if started:
            self.database.mark_plan_handled(plan_id, ran=True)
        else:
            self.runtime.clear_plan_duration()
        self.refresh_all()

    def _plan_context_menu(self, position) -> None:
        item = self.plan_tree.itemAt(position)
        header = PlanTreeWidget.day_header(item)
        target_day = datetime.now().astimezone().date()
        if header is not None:
            try:
                target_day = date.fromisoformat(str(header.data(0, DAY_ROLE)))
            except ValueError:
                pass

        item_type = None if item is None else item.data(0, ITEM_TYPE_ROLE)
        if item_type in {ITEM_TYPE_PLAN_NOTE, ITEM_TYPE_PLAN_ACTION_NOTE}:
            note_id = (
                item.data(0, PLAN_NOTE_ID_ROLE)
                if item_type == ITEM_TYPE_PLAN_NOTE
                else item.data(0, PLAN_ACTION_NOTE_ID_ROLE)
            )
            menu = QMenu(self.plan_tree)
            edit = menu.addAction("Edit note...")
            delete = menu.addAction("Delete note")
            selected = menu.exec(
                self.plan_tree.viewport().mapToGlobal(position)
            )
            if note_id is None:
                return
            current_text = item.text(0).removeprefix("note: ")
            if selected is edit:
                if item_type == ITEM_TYPE_PLAN_NOTE:
                    self._edit_plan_note(int(note_id), current_text)
                else:
                    self._edit_plan_action_note(int(note_id), current_text)
            elif selected is delete:
                if item_type == ITEM_TYPE_PLAN_NOTE:
                    self.database.delete_plan_note(int(note_id))
                else:
                    self.database.delete_plan_action_note(int(note_id))
                self.refresh_plans()
            return

        menu = QMenu(self.plan_tree)
        add = menu.addAction("Add...")
        add_day_note = menu.addAction("Add day note...")
        plan_id = None if item is None else item.data(0, PLAN_ID_ROLE)
        start_action = None
        edit_action = None
        notes_action = None
        todos_action = None
        remove_action = None
        remove_all_action = None
        if plan_id is not None:
            menu.addSeparator()
            start_action = menu.addAction("Start")
            edit_action = menu.addAction("Edit...")
            notes_action = menu.addAction("Notes...")
            todos_action = menu.addAction("TODOs")
            remove_action = menu.addAction("Remove")
            remove_all_action = menu.addAction(
                "Remove all instances of this Action Type"
            )

        selected = menu.exec(self.plan_tree.viewport().mapToGlobal(position))
        if selected is add:
            self._add_plan(target_day)
        elif selected is add_day_note:
            text, accepted = QInputDialog.getMultiLineText(
                self,
                "Add Daily Plan note",
                f"Note for {target_day.isoformat()}:",
                "",
            )
            if accepted and str(text).strip():
                self.database.add_plan_note(target_day, str(text).strip())
                self.refresh_plans()
        elif start_action is not None and selected is start_action:
            self._start_plan(int(plan_id))
        elif edit_action is not None and selected is edit_action:
            self._edit_plan(int(plan_id))
        elif notes_action is not None and selected is notes_action:
            self._add_plan_action_note(int(plan_id))
        elif todos_action is not None and selected is todos_action:
            PlanActionTypeTodosDialog(
                self.database,
                int(plan_id),
                self,
            ).exec()
            if self.show_todos_checkbox.isChecked():
                self.refresh_actions()
        elif remove_action is not None and selected is remove_action:
            self.database.delete_plan(int(plan_id))
            self.refresh_all()
        elif remove_all_action is not None and selected is remove_all_action:
            row = self.database.plan(int(plan_id))
            if row is not None:
                count = self.database.delete_all_plans_for_action(
                    str(row["node_id"])
                )
                self.statusBar().showMessage(
                    f"Removed {count} planned instance(s)",
                    5000,
                )
                self.refresh_all()

    def _add_plan_action_note(self, plan_id: int) -> None:
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Add note",
            "Note:",
            "",
        )
        if accepted and str(text).strip():
            self.database.add_plan_action_note(plan_id, str(text).strip())
            self.refresh_plans()

    def _edit_plan_note(self, note_id: int, current_text: str) -> None:
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Edit Daily Plan note",
            "Note:",
            current_text,
        )
        if accepted and str(text).strip():
            self.database.update_plan_note(note_id, str(text).strip())
            self.refresh_plans()

    def _edit_plan_action_note(self, note_id: int, current_text: str) -> None:
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Edit note",
            "Note:",
            current_text,
        )
        if accepted and str(text).strip():
            self.database.update_plan_action_note(
                note_id,
                str(text).strip(),
            )
            self.refresh_plans()

    def _move_plan(
        self,
        plan_id: int,
        target_day_text: str,
        target_index: int,
    ) -> None:
        try:
            self.database.move_plan(
                plan_id,
                date.fromisoformat(target_day_text),
                target_index,
            )
        except Exception as error:
            QMessageBox.warning(self, "Move Daily Plan", str(error))
        self.refresh_plans()

    def _to_plan_selection_changed(self) -> None:
        selected = self.to_plan_tree.currentItem() is not None
        self.add_today_button.setEnabled(selected)
        self.add_any_day_button.setEnabled(selected)

    def _selected_to_plan_node_id(self) -> Optional[str]:
        item = self.to_plan_tree.currentItem()
        if item is None:
            return None
        value = item.data(0, NODE_ROLE)
        return value if isinstance(value, str) and value else None

    def _add_selected_to_plan(self, *, today: bool) -> None:
        node_id = self._selected_to_plan_node_id()
        if not node_id:
            return
        if today:
            row = self.database.action_type(node_id)
            if row is None:
                return
            duration = (
                self.database.default_planned_seconds(node_id)
                or 30 * 60
            )
            try:
                self.database.add_plan(
                    day_value=datetime.now().astimezone().date(),
                    action_name=str(row["title"]),
                    node_id=node_id,
                    run_time=None,
                    reminders=[],
                    duration_seconds=max(60, int(duration)),
                )
            except Exception as error:
                QMessageBox.warning(self, "Add to plan", str(error))
                return
            self.refresh_all()
        else:
            self._add_plan(
                datetime.now().astimezone().date(),
                initial_node_id=node_id,
            )

    def _to_plan_activated(
        self,
        item: QTreeWidgetItem,
        _column: int,
    ) -> None:
        node_id = item.data(0, NODE_ROLE)
        if isinstance(node_id, str) and node_id:
            self._add_selected_to_plan(today=True)

    @staticmethod
    def _open_file(file_path: Optional[str]) -> None:
        if not file_path:
            return
        path = Path(file_path)
        if not path.exists():
            return
        for command in (("pycharm", str(path)), ("xdg-open", str(path))):
            try:
                subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except OSError:
                pass

