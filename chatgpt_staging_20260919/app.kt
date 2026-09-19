package com.ndplanning.android.ui

// ND_MOBILE_PARITY_PATCH_V1

import android.content.ClipData
import android.content.ClipDescription
import android.media.RingtoneManager
import android.view.View
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.draganddrop.dragAndDropSource
import androidx.compose.foundation.draganddrop.dragAndDropTarget
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Divider
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draganddrop.DragAndDropEvent
import androidx.compose.ui.draganddrop.DragAndDropTarget
import androidx.compose.ui.draganddrop.DragAndDropTransferData
import androidx.compose.ui.draganddrop.mimeTypes
import androidx.compose.ui.draganddrop.toAndroidDragEvent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ndplanning.android.data.ActionNode
import com.ndplanning.android.data.ActionPanelTodo
import com.ndplanning.android.data.ActionTodo
import com.ndplanning.android.data.DayPlan
import com.ndplanning.android.data.PlanAction
import com.ndplanning.android.data.PlanActionNote
import com.ndplanning.android.data.PlanActionTodo
import com.ndplanning.android.data.PlanNote
import com.ndplanning.android.data.RecurringRule
import com.ndplanning.android.data.RuntimeState
import com.ndplanning.android.data.TimeInterval
import com.ndplanning.android.util.TimeUtil
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import java.time.Duration
import java.time.LocalDate
import java.time.ZoneId
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.IsoFields

private val dayColors = listOf(
    Color(0xFFF2D6E7), Color(0xFFD8E8F7), Color(0xFFDDF0DF), Color(0xFFF5E3C7),
    Color(0xFFE7DDF5), Color(0xFFD9EFEF), Color(0xFFF5DCD7),
)
private val statisticColors = listOf(
    Color(0xFF7DA7D9),
    Color(0xFF78C6B0),
    Color(0xFFE5B56B),
    Color(0xFFD98FA6),
    Color(0xFF9B8CC7),
    Color(0xFF7FC3D4),
    Color(0xFFA6C873),
    Color(0xFFD69A73),
)
private val runningColor = Color(0xFFD14E5C)
private val pausedColor = Color(0xFFE0A84D)
private val monthColor = Color(0xFFF7A36F)
private val weekColor = Color(0xFFF7D06F)
private val todoOrange = Color(0xFFB45309)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlanningApp(vm: PlanningViewModel = viewModel()) {
    val message by vm.message.collectAsState()
    var tab by remember { mutableIntStateOf(vm.initialTab) }
    var showSettings by remember { mutableStateOf(false) }
    val tabs = listOf("Daily Plans", "Action types", "To plan", "Recurring", "Timers")

    Scaffold(topBar = {
        TopAppBar(title = { Text("ND Planning") }, actions = {
            SyncButton(vm)
            TextButton(onClick = { showSettings = true }) { Text("Settings") }
        })
    }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            TabRow(selectedTabIndex = tab) {
                tabs.forEachIndexed { index, label ->
                    Tab(selected = tab == index, onClick = { tab = index; vm.rememberTab(index) }, text = { Text(label) })
                }
            }
            ActiveRuntimeSection(vm)
            when (tab) {
                0 -> DailyPlansScreen(vm, Modifier.weight(1f))
                1 -> ActionTypesScreen(vm, Modifier.weight(1f))
                2 -> ToPlanScreen(vm, Modifier.weight(1f))
                3 -> RecurringScreen(vm, Modifier.weight(1f))
                else -> TimersScreen(Modifier.weight(1f))
            }
        }
    }

    if (showSettings) SettingsDialog(vm) { showSettings = false }
    message?.let {
        AlertDialog(
            onDismissRequest = vm::clearMessage,
            title = { Text("ND Planning") },
            text = { Text(it) },
            confirmButton = { TextButton(onClick = vm::clearMessage) { Text("OK") } },
        )
    }
}

@Composable
private fun SyncButton(vm: PlanningViewModel) {
    val sync by vm.sync.collectAsState()
    TextButton(onClick = vm::syncNow, enabled = sync.authenticated && !sync.running) {
        Text(if (sync.running) "Syncing…" else "Sync")
    }
}

@Composable
private fun ActiveRuntimeSection(vm: PlanningViewModel) {
    val runtime by vm.runtime.state.collectAsState()
    val runtimeTitle by vm.runtimeTitle.collectAsState()
    var showAddRuntimeTime by remember { mutableStateOf(false) }

    if (runtime.active && runtime.currentNodeId != null) {
        val title = runtimeTitle.ifBlank {
            runtime.rootNodeId?.let { "Action $it" } ?: "Running action"
        }
        ActiveRuntimeBar(
            title = title,
            runtime = runtime,
            onPauseResume = { if (runtime.paused) vm.resumeRuntime() else vm.pauseRuntime() },
            onRestart = { runtime.currentNodeId?.let(vm::restartAction) },
            onAddTime = { showAddRuntimeTime = true },
            onStop = vm::stopRuntime,
        )
    }
    if (showAddRuntimeTime) {
        AddRuntimeTimeDialog(
            onDismiss = { showAddRuntimeTime = false },
            onAdd = { seconds -> vm.addRuntimeTime(seconds); showAddRuntimeTime = false },
        )
    }
}

@Composable
private fun ActiveRuntimeBar(
    title: String,
    runtime: RuntimeState,
    onPauseResume: () -> Unit,
    onRestart: () -> Unit,
    onAddTime: () -> Unit,
    onStop: () -> Unit,
) {
    val bg = if (runtime.paused) pausedColor else runningColor
    val fg = if (runtime.paused) Color(0xFF3F2D12) else Color.White
    Surface(color = bg, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 7.dp)) {
            Text(title, color = fg, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val details = buildList {
                add(if (runtime.paused) "Paused" else "Running")
                add("elapsed ${TimeUtil.compactDuration(runtime.elapsedSeconds.toLong())}")
                if (runtime.remainingSeconds > 0) add("left ${TimeUtil.compactDuration(runtime.remainingSeconds.toLong())}")
            }.joinToString(" · ")
            Text(details, color = fg.copy(alpha = 0.9f), style = MaterialTheme.typography.bodySmall)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onPauseResume) { Text(if (runtime.paused) "Resume" else "Pause", color = fg) }
                TextButton(onClick = onRestart) { Text("Restart", color = fg) }
                TextButton(onClick = onAddTime) { Text("+ Time", color = fg) }
                TextButton(onClick = onStop) { Text("Stop", color = fg) }
            }
        }
    }
}

@Composable
private fun AddRuntimeTimeDialog(onDismiss: () -> Unit, onAdd: (Int) -> Unit) {
    var text by remember { mutableStateOf("5 min") }
    var error by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add runtime") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(text, { text = it }, label = { Text("Duration") }, singleLine = true)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = {
            Button(onClick = {
                val seconds = try {
                    TimeUtil.parseDuration(text)
                } catch (e: Exception) {
                    error = e.message ?: "Invalid duration"
                    null
                }
                if (seconds == null || seconds <= 0) {
                    if (error == null) error = "Enter a duration, for example 5 min."
                } else {
                    onAdd(seconds)
                }
            }) { Text("Add") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private fun dailyListIndexFor(days: List<LocalDate>, target: LocalDate): Int {
    var index = 0
    var previousMonth: String? = null
    var previousWeek: Int? = null
    for (day in days) {
        val month = day.format(DateTimeFormatter.ofPattern("MMMM yyyy"))
        val week = day.get(IsoFields.WEEK_OF_WEEK_BASED_YEAR)
        if (month != previousMonth) {
            index += 1
            previousMonth = month
            previousWeek = null
        }
        if (week != previousWeek) {
            index += 1
            previousWeek = week
        }
        if (day == target) return index
        index += 1
    }
    return 0
}

@Composable
private fun DailyPlansScreen(vm: PlanningViewModel, modifier: Modifier) {
    val plans by vm.plans.collectAsState()
    val before by vm.daysBefore.collectAsState()
    val after by vm.daysAfter.collectAsState()
    val runtime by vm.runtimeControl.collectAsState()
    val runtimeTitle by vm.runtimeTitle.collectAsState()
    val today = LocalDate.now(ZoneId.of("Europe/Vienna"))
    val byDay = remember(plans) { plans.associateBy { it.day } }
    val days = remember(before, after, today) {
        (after downTo -before).map { today.plusDays(it.toLong()) }
    }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val todayIndex = remember(days, today) { dailyListIndexFor(days, today) }

    LaunchedEffect(todayIndex) {
        listState.scrollToItem(todayIndex)
    }

    var addForDay by remember { mutableStateOf<LocalDate?>(null) }
    var editPlan by remember { mutableStateOf<Pair<LocalDate, PlanAction>?>(null) }
    var notesFor by remember { mutableStateOf<DayPlan?>(null) }
    var actionDetailsFor by remember { mutableStateOf<PlanAction?>(null) }
    var pendingStart by remember { mutableStateOf<PlanAction?>(null) }

    Column(modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(
                onClick = {
                    scope.launch {
                        listState.scrollToItem(todayIndex)
                    }
                }
            ) {
                Text("⌖ Today")
            }
        }
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth().padding(horizontal = 8.dp),
            state = listState,
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            var previousMonth: String? = null
            var previousWeek: Int? = null
            days.forEach { day ->
                val month = day.format(DateTimeFormatter.ofPattern("MMMM yyyy"))
                val week = day.get(IsoFields.WEEK_OF_WEEK_BASED_YEAR)
                if (month != previousMonth) {
                    item("month-$month") { Separator(month, monthColor) }
                    previousMonth = month
                    previousWeek = null
                }
                if (week != previousWeek) {
                    item("week-separator-$day") { Separator("Week $week", weekColor) }
                    previousWeek = week
                }
                item("day-$day") {
                    DayCard(
                        day = day,
                        plan = byDay[day.toString()],
                        runtime = runtime,
                        runtimeTitle = runtimeTitle,
                        vm = vm,
                        onAdd = { addForDay = day },
                        onNotes = { notesFor = it },
                        onPlanDrop = { id, position -> vm.movePlan(id, day, position) },
                        onActionDrop = { id -> vm.addPlan(day, id, null, "") },
                        onEdit = { editPlan = day to it },
                        onDetails = { actionDetailsFor = it },
                        onDelete = vm::deletePlan,
                        onStart = { pendingStart = it },
                    )
                }
            }
        }
    }

    addForDay?.let { day -> PlanEditorDialog(vm, day = day, onDismiss = { addForDay = null }) }
    editPlan?.let { (day, action) -> PlanEditorDialog(vm, day, action) { editPlan = null } }
    notesFor?.let { DayNotesDialog(vm, it) { notesFor = null } }
    actionDetailsFor?.let { PlanActionDetailsDialog(vm, it) { actionDetailsFor = null } }
    pendingStart?.let { action ->
        StartActionDialog(runtime, action.actionName, onCancel = { pendingStart = null }) { stopPrevious ->
            vm.startAction(action.idActionTypes, action.durationSeconds.takeIf { it > 0 }, stopPrevious)
            pendingStart = null
        }
    }
}

@Composable
private fun Separator(text: String, color: Color) {
    Surface(color = color, shape = RoundedCornerShape(5.dp), modifier = Modifier.fillMaxWidth().padding(top = 4.dp)) {
        Text(text, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp))
    }
}

@Composable
private fun DayCard(
    day: LocalDate,
    plan: DayPlan?,
    runtime: RuntimeControlState,
    runtimeTitle: String,
    vm: PlanningViewModel,
    onAdd: () -> Unit,
    onNotes: (DayPlan) -> Unit,
    onPlanDrop: (Long, Int) -> Unit,
    onActionDrop: (String) -> Unit,
    onEdit: (PlanAction) -> Unit,
    onDetails: (PlanAction) -> Unit,
    onDelete: (Long) -> Unit,
    onStart: (PlanAction) -> Unit,
) {
    val outerTarget = remember(day, plan?.actions?.size) { textDropTarget { payload ->
        when {
            payload.startsWith("plan:") -> payload.removePrefix("plan:").toLongOrNull()?.let { onPlanDrop(it, plan?.actions?.size ?: 0); true } ?: false
            payload.startsWith("action:") -> payload.removePrefix("action:").takeIf(String::isNotBlank)?.let { onActionDrop(it); true } ?: false
            else -> false
        }
    } }
    val bg = if (day == LocalDate.now(ZoneId.of("Europe/Vienna"))) Color(0xFFE24D66) else dayColors[day.dayOfWeek.value - 1]
    val fg = if (day == LocalDate.now(ZoneId.of("Europe/Vienna"))) Color.White else Color(0xFF342F36)
    Card(
        modifier = Modifier.fillMaxWidth().dragAndDropTarget(
            shouldStartDragAndDrop = { it.mimeTypes().contains(ClipDescription.MIMETYPE_TEXT_PLAIN) },
            target = outerTarget,
        ),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFFFBFE)),
    ) {
        Row(Modifier.fillMaxWidth().background(bg).padding(horizontal = 10.dp, vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(day.format(DateTimeFormatter.ofPattern("EEE, dd MMM yyyy")), color = fg, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            plan?.let { TextButton(onClick = { onNotes(it) }) { Text("Notes", color = fg) } }
            TextButton(onClick = onAdd) { Text("Add", color = fg) }
        }
        if (
            day == LocalDate.now(
                ZoneId.of("Europe/Vienna")
            ) &&
            runtime.active
        ) {
            RunningNowPlanRow(
                vm = vm,
                title = runtimeTitle,
            )
        }

        val displayedActions =
            plan?.actions.orEmpty()

        displayedActions.forEachIndexed { index, action ->
            PlanDropZone(day, index, onPlanDrop)
            val isCurrent = false
            val rowColor = when { isCurrent && runtime.paused -> pausedColor; isCurrent -> runningColor; else -> Color.Transparent }
            val textColor = if (isCurrent && !runtime.paused) Color.White else MaterialTheme.colorScheme.onSurface
            Row(
                Modifier.fillMaxWidth().background(rowColor)
                    .dragAndDropSource { _ -> dragData("plan:${action.idPlanActionTypes}") }
                    .clickable { onEdit(action) }.padding(horizontal = 8.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("☷", color = textColor, modifier = Modifier.padding(end = 6.dp))
                Column(Modifier.weight(1f)) {
                    Text(action.actionName, color = textColor, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    val details = buildList {
                        action.runTime?.let(::add)
                        if (action.durationSeconds > 0) add(TimeUtil.compactDuration(action.durationSeconds.toLong())) else add("untimed")
                        if (isCurrent) add(if (runtime.paused) "Paused" else "Running")
                    }.joinToString(" · ")
                    Text(details, color = textColor.copy(alpha = 0.85f), style = MaterialTheme.typography.bodySmall)
                }
                TextButton(onClick = { onStart(action) }) { Text("Run", color = textColor) }
                PlanActionMenu(onEdit = { onEdit(action) }, onDetails = { onDetails(action) }, onDelete = { onDelete(action.idPlanActionTypes) }, textColor = textColor)
            }
            Divider()
        }
        plan?.let { PlanDropZone(day, it.actions.size, onPlanDrop) }
    }
}

@Composable
private fun RunningNowPlanRow(
    vm: PlanningViewModel,
    title: String,
) {
    val state by vm.runtime.state.collectAsState()

    if (!state.active) return

    val bg =
        if (state.paused) pausedColor
        else runningColor

    val fg =
        if (state.paused) Color(0xFF3F2D12)
        else Color.White

    Surface(
        color = bg,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(
                    horizontal = 10.dp,
                    vertical = 8.dp,
                )
        ) {
            Text(
                text = title.ifBlank {
                    "Running action"
                },
                color = fg,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )

            val details = buildList {
                add(
                    if (state.paused) {
                        "Paused"
                    } else {
                        "Running now"
                    }
                )

                add(
                    "elapsed ${
                        TimeUtil.compactDuration(
                            state.elapsedSeconds.toLong()
                        )
                    }"
                )

                if (state.remainingSeconds > 0) {
                    add(
                        "left ${
                            TimeUtil.compactDuration(
                                state.remainingSeconds.toLong()
                            )
                        }"
                    )
                }
            }.joinToString(" · ")

            Text(
                details,
                color = fg.copy(alpha = 0.9f),
                style =
                    MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun PlanDropZone(day: LocalDate, position: Int, onDrop: (Long, Int) -> Unit) {
    val target = remember(day, position) { textDropTarget { payload ->
        payload.removePrefix("plan:").takeIf { payload.startsWith("plan:") }?.toLongOrNull()?.let { onDrop(it, position); true } ?: false
    } }
    Box(Modifier.fillMaxWidth().height(5.dp).dragAndDropTarget({ it.mimeTypes().contains(ClipDescription.MIMETYPE_TEXT_PLAIN) }, target))
}

@Composable
private fun PlanActionMenu(onEdit: () -> Unit, onDetails: () -> Unit, onDelete: () -> Unit, textColor: Color) {
    var open by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { open = true }) { Text("⋮", color = textColor) }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("Edit") }, onClick = { open = false; onEdit() })
            DropdownMenuItem(text = { Text("TODOs") }, onClick = { open = false; onDetails() })
            DropdownMenuItem(text = { Text("Delete") }, onClick = { open = false; onDelete() })
        }
    }
}

@Composable
private fun ActionTypesScreen(vm: PlanningViewModel, modifier: Modifier) {
    val tree by vm.actions.collectAsState()
    val filter by vm.filter.collectAsState()
    val runtime by vm.runtimeControl.collectAsState()
    val panelTodos by vm.actionPanelTodos.collectAsState()
    val flat = remember(tree) { flatten(tree) }
    val activePathIds = remember(flat, runtime.currentNodeId) {
        val byStable = flat.associateBy { it.action.id }
        val currentId = runtime.currentNodeId
        var current = flat.firstOrNull { node -> currentId != null && (node.action.idActionTypes == currentId || node.action.id == currentId) }
        buildSet {
            val seen = mutableSetOf<String>()
            while (current != null && seen.add(current!!.action.id)) {
                add(current!!.action.idActionTypes)
                current = current!!.action.parentId?.let(byStable::get)
            }
        }
    }
    var addParent by remember { mutableStateOf<String?>(null) }
    var edit by remember { mutableStateOf<ActionNode?>(null) }
    var todosFor by remember { mutableStateOf<ActionNode?>(null) }
    var statsFor by remember { mutableStateOf<ActionNode?>(null) }
    var showOverallStats by remember { mutableStateOf(false) }
    var scheduleFor by remember { mutableStateOf<ActionNode?>(null) }
    var pendingStart by remember { mutableStateOf<ActionNode?>(null) }
    var showTodos by remember { mutableStateOf(false) }

    val todosByAction =
        remember(panelTodos) {
            panelTodos.groupBy {
                it.idActionTypes
            }
        }

    val todoBranchIds =
        remember(flat, panelTodos) {
            val byStable =
                flat.associateBy {
                    it.action.id
                }
            val byCanonical =
                flat.associateBy {
                    it.action.idActionTypes
                }

            buildSet {
                panelTodos.forEach { todo ->
                    var node =
                        byCanonical[
                            todo.idActionTypes
                        ]
                    val seen =
                        mutableSetOf<String>()

                    while (
                        node != null &&
                        seen.add(
                            node.action.idActionTypes
                        )
                    ) {
                        add(
                            node.action.idActionTypes
                        )
                        node =
                            node.action.parentId
                                ?.let(
                                    byStable::get
                                )
                    }
                }
            }
        }

    val displayedFlat =
        remember(
            flat,
            showTodos,
            todoBranchIds,
        ) {
            if (showTodos) {
                flat.filter {
                    it.action.idActionTypes in
                        todoBranchIds
                }
            } else {
                flat
            }
        }

    val rootTarget = remember { textDropTarget { payload ->
        payload.removePrefix("action:").takeIf { payload.startsWith("action:") }?.let { vm.moveAction(it, null); true } ?: false
    } }

    Column(modifier.fillMaxSize().padding(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                filter,
                vm::setFilter,
                label = { Text("Search action types") },
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(4.dp))
            Row(
                verticalAlignment =
                    Alignment.CenterVertically
            ) {
                Checkbox(
                    checked = showTodos,
                    onCheckedChange = {
                        showTodos = it
                    },
                )
                Text(
                    "TODOs",
                    color = todoOrange,
                    fontWeight =
                        FontWeight.SemiBold,
                )
            }
            Spacer(Modifier.width(6.dp))
            OutlinedButton(
                onClick = { showOverallStats = true }
            ) {
                Text("Statistics")
            }
            Spacer(Modifier.width(6.dp))
            Button(
                onClick = { addParent = "" }
            ) {
                Text("Add")
            }
        }
        if (!showTodos) {
            Surface(
                modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp).dragAndDropTarget(
                    { it.mimeTypes().contains(ClipDescription.MIMETYPE_TEXT_PLAIN) }, rootTarget,
                ),
                color = MaterialTheme.colorScheme.surfaceVariant,
                shape = RoundedCornerShape(7.dp),
            ) { Text("Drop here to make an Action Type a root item", modifier = Modifier.padding(7.dp)) }
        }
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            items(displayedFlat, key = { it.action.idActionTypes }) { node ->
                if (!showTodos) {
                    ActionSiblingDropZone(node, vm)
                }
                ActionRow(
                    node, runtime, activePathIds,
                    dragEnabled = !showTodos,
                    onRun = { pendingStart = node },
                    onAddChild = { addParent = node.action.id },
                    onEdit = { edit = node },
                    onTodos = { todosFor = node },
                    onStats = { statsFor = node },
                    onSchedule = { scheduleFor = node },
                    onDelete = { vm.deleteAction(node.action.idActionTypes) },
                    onDropChild = { moving -> vm.moveAction(moving, node.action.id) },
                )

                if (showTodos) {
                    todosByAction[
                        node.action.idActionTypes
                    ].orEmpty().forEach { todo ->
                        ActionPanelTodoRow(
                            node = node,
                            todo = todo,
                        )
                    }
                }
            }
        }
    }

    if (addParent != null) ActionEditorDialog("Add Action Type", onDismiss = { addParent = null }) { name, duration ->
        vm.addAction(name, addParent!!.takeIf(String::isNotBlank), duration); addParent = null
    }
    edit?.let { node -> ActionEditorDialog(
        "Edit Action Type",
        node.action.title,
        node.action.plannedDurationSeconds?.let { TimeUtil.durationEditorText(it) }.orEmpty(),
        onDismiss = { edit = null },
    ) { name, duration -> vm.editAction(node.action.idActionTypes, name, duration); edit = null } }
    todosFor?.let { TodosDialog(vm, it) { todosFor = null } }
    statsFor?.let {
        StatisticsDialog(vm, it) {
            statsFor = null
        }
    }

    if (showOverallStats) {
        OverallStatisticsDialog(
            vm = vm,
            roots = tree,
            onDismiss = {
                showOverallStats = false
            },
        )
    }

    scheduleFor?.let { node -> RecurringDialog(vm, null, onDismiss = { scheduleFor = null }, initialActionId = node.action.idActionTypes, initialType = "one_time") }
    pendingStart?.let { node ->
        StartActionDialog(runtime, node.action.title, onCancel = { pendingStart = null }) { stopPrevious ->
            vm.startAction(node.action.idActionTypes, null, stopPrevious); pendingStart = null
        }
    }
}

@Composable
private fun ActionSiblingDropZone(node: ActionNode, vm: PlanningViewModel) {
    val target = remember(node.action.idActionTypes, node.action.parentId, node.action.position) { textDropTarget { payload ->
        payload.removePrefix("action:").takeIf { payload.startsWith("action:") }?.let {
            vm.moveAction(it, node.action.parentId, node.action.position); true
        } ?: false
    } }
    Box(Modifier.fillMaxWidth().padding(start = (node.depth * 16).dp).height(5.dp).dragAndDropTarget(
        { it.mimeTypes().contains(ClipDescription.MIMETYPE_TEXT_PLAIN) }, target,
    ))
}

@Composable
private fun RuntimeBar(runtime: RuntimeState, vm: PlanningViewModel) {
    if (!runtime.active) return
    Surface(
        color = if (runtime.paused) pausedColor else runningColor,
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
    ) {
        Row(Modifier.padding(7.dp), verticalAlignment = Alignment.CenterVertically) {
            val fg = if (runtime.paused) Color.Black else Color.White
            Text(
                "Active: ${runtime.currentNodeId.orEmpty()} · ${TimeUtil.compactDuration(runtime.elapsedSeconds.toLong())}" +
                    if (runtime.remainingSeconds > 0) " · left ${TimeUtil.compactDuration(runtime.remainingSeconds.toLong())}" else "",
                color = fg,
                modifier = Modifier.weight(1f),
            )
            if (runtime.remainingSeconds > 0) TextButton(onClick = { vm.addRuntimeTime(5 * 60) }) { Text("+5m", color = fg) }
            TextButton(onClick = { if (runtime.paused) vm.resumeRuntime() else vm.pauseRuntime() }) { Text(if (runtime.paused) "Continue" else "Pause", color = fg) }
            TextButton(onClick = vm::stopRuntime) { Text("Stop", color = fg) }
        }
    }
}

@Composable
private fun ActionRow(
    node: ActionNode,
    runtime: RuntimeControlState,
    activePathIds: Set<String>,
    dragEnabled: Boolean,
    onRun: () -> Unit,
    onAddChild: () -> Unit,
    onEdit: () -> Unit,
    onTodos: () -> Unit,
    onStats: () -> Unit,
    onSchedule: () -> Unit,
    onDelete: () -> Unit,
    onDropChild: (String) -> Unit,
) {
    val target = remember(node.action.id) { textDropTarget { payload ->
        if (!payload.startsWith("action:")) false else { onDropChild(payload.removePrefix("action:")); true }
    } }
    val current = runtime.active && (runtime.currentNodeId == node.action.idActionTypes || runtime.currentNodeId == node.action.id)
    val inActiveBranch = node.action.idActionTypes in activePathIds
    var rowModifier =
        Modifier
            .fillMaxWidth()
            .padding(
                start =
                    (node.depth * 16).dp
            )
    if (dragEnabled) {
        rowModifier =
            rowModifier
                .dragAndDropSource { _ ->
                    dragData(
                        "action:${node.action.idActionTypes}"
                    )
                }
                .dragAndDropTarget(
                    {
                        it.mimeTypes().contains(
                            ClipDescription.MIMETYPE_TEXT_PLAIN
                        )
                    },
                    target,
                )
    }
    Surface(
        modifier = rowModifier,
        color = when {
            current && runtime.paused -> pausedColor
            current -> runningColor
            inActiveBranch -> runningColor.copy(alpha = 0.14f)
            else -> MaterialTheme.colorScheme.surface
        },
        tonalElevation = 1.dp,
        shape = RoundedCornerShape(6.dp),
    ) {
        Row(Modifier.padding(horizontal = 8.dp, vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("☷", modifier = Modifier.padding(end = 8.dp))
            Column(Modifier.weight(1f)) {
                val fg = if (current && !runtime.paused) Color.White else MaterialTheme.colorScheme.onSurface
                Text(node.action.title, fontWeight = FontWeight.SemiBold, color = fg)
                Text(node.action.plannedDurationSeconds?.let { TimeUtil.compactDuration(it.toLong()) } ?: "elapsed only", style = MaterialTheme.typography.bodySmall, color = fg.copy(alpha = .8f))
            }
            TextButton(onClick = onRun) { Text("Run") }
            ActionMenu(onAddChild, onEdit, onTodos, onStats, onSchedule, onDelete)
        }
    }
}

@Composable
private fun ActionPanelTodoRow(
    node: ActionNode,
    todo: ActionPanelTodo,
) {
    val schedule =
        listOfNotNull(
            todo.day
                ?.takeIf(String::isNotBlank),
            todo.runTime
                ?.takeIf(String::isNotBlank),
        ).joinToString(" ")

    val status =
        if (todo.isDone) {
            "[x]"
        } else {
            "[ ]"
        }

    val text =
        buildString {
            if (schedule.isNotBlank()) {
                append(schedule)
                append(" · ")
            }
            append(status)
            append(" ")
            append(todo.todo)
        }

    Text(
        text = text,
        color = todoOrange,
        fontWeight = FontWeight.Medium,
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(
                    start =
                        ((node.depth + 1) * 16).dp,
                    end = 8.dp,
                    top = 2.dp,
                    bottom = 3.dp,
                ),
        maxLines = 3,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun ActionMenu(onAddChild: () -> Unit, onEdit: () -> Unit, onTodos: () -> Unit, onStats: () -> Unit, onSchedule: () -> Unit, onDelete: () -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { open = true }) { Text("⋮") }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            listOf("Add child" to onAddChild, "Edit" to onEdit, "Todos" to onTodos, "Intervals / Statistics" to onStats, "Schedule..." to onSchedule, "Delete" to onDelete)
                .forEach { (label, action) -> DropdownMenuItem(text = { Text(label) }, onClick = { open = false; action() }) }
        }
    }
}

@Composable
private fun ToPlanScreen(vm: PlanningViewModel, modifier: Modifier) {
    val tree by vm.actions.collectAsState()
    var day by remember { mutableStateOf(LocalDate.now(ZoneId.of("Europe/Vienna"))) }
    Column(modifier.fillMaxSize().padding(8.dp)) {
        Text("Quickly add an Action Type to a Daily Plan", style = MaterialTheme.typography.titleMedium)
        DateStepper(day) { day = it }
        LazyColumn(Modifier.weight(1f)) {
            items(flatten(tree), key = { it.action.idActionTypes }) { node ->
                Row(Modifier.fillMaxWidth().padding(start = (node.depth * 14).dp, top = 3.dp, bottom = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(node.action.title, modifier = Modifier.weight(1f))
                    Button(onClick = { vm.addPlan(day, node.action.idActionTypes, null, "") }) { Text("Plan") }
                }
            }
        }
    }
}

@Composable
private fun RecurringScreen(vm: PlanningViewModel, modifier: Modifier) {
    val rules by vm.recurringRules.collectAsState()
    val actions by vm.actions.collectAsState()
    var edit by remember { mutableStateOf<RecurringRule?>(null) }
    var adding by remember { mutableStateOf(false) }
    val titles = remember(actions) { flatten(actions).associate { it.action.idActionTypes to it.action.title } }
    Column(modifier.fillMaxSize().padding(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Recurring schedules", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            Button(onClick = { adding = true }) { Text("Add") }
        }
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            items(rules, key = { it.id }) { rule ->
                Card(Modifier.fillMaxWidth().clickable { edit = rule }) {
                    Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(titles[rule.nodeId] ?: rule.nodeId, fontWeight = FontWeight.Bold)
                            Text("${rule.recurrenceType.replace('_', ' ')} · ${rule.runTime} · from ${rule.startDay}" + if (!rule.enabled) " · disabled" else "", style = MaterialTheme.typography.bodySmall)
                        }
                        TextButton(onClick = { vm.deleteRecurring(rule.id) }) { Text("Delete") }
                    }
                }
            }
        }
    }
    if (adding) RecurringDialog(vm, null, onDismiss = { adding = false })
    edit?.let { RecurringDialog(vm, it, onDismiss = { edit = null }) }
}

@Composable
private fun RecurringDialog(vm: PlanningViewModel, existing: RecurringRule?, onDismiss: () -> Unit, initialActionId: String? = null, initialType: String? = null) {
    val actions by vm.actions.collectAsState()
    val all = flatten(actions)
    var actionId by remember { mutableStateOf(existing?.nodeId ?: initialActionId ?: all.firstOrNull()?.action?.idActionTypes.orEmpty()) }
    var startDay by remember { mutableStateOf(existing?.startDay ?: LocalDate.now(ZoneId.of("Europe/Vienna")).toString()) }
    var runTime by remember { mutableStateOf(existing?.runTime ?: "09:00") }
    var type by remember { mutableStateOf(existing?.recurrenceType ?: initialType ?: "weekly") }
    var interval by remember { mutableStateOf((existing?.intervalValue ?: 1).toString()) }
    var weekday by remember { mutableStateOf(existing?.weekday?.toString().orEmpty()) }
    var dayOfMonth by remember { mutableStateOf(existing?.dayOfMonth?.toString().orEmpty()) }
    var monthOfYear by remember { mutableStateOf(existing?.monthOfYear?.toString().orEmpty()) }
    var dayOfYear by remember { mutableStateOf(existing?.dayOfYearMonth?.toString().orEmpty()) }
    var reminders by remember { mutableStateOf(existing?.remindersJson?.let(::jsonArrayToText).orEmpty()) }
    var enabled by remember { mutableStateOf(existing?.enabled ?: true) }
    var actionMenu by remember { mutableStateOf(false) }
    var typeMenu by remember { mutableStateOf(false) }
    val types = listOf("weekly", "monthly", "yearly", "every_n_days", "every_n_weeks")

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (existing == null && initialType == "one_time") "Schedule Action Type" else if (existing == null) "Add recurring schedule" else "Edit recurring schedule") },
        text = { LazyColumn(Modifier.height(470.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            item { Box {
                OutlinedButton(onClick = { actionMenu = true }) { Text(all.firstOrNull { it.action.idActionTypes == actionId }?.action?.title ?: "Choose Action Type") }
                DropdownMenu(actionMenu, { actionMenu = false }) { all.forEach { node -> DropdownMenuItem(text = { Text("  ".repeat(node.depth) + node.action.title) }, onClick = { actionId = node.action.idActionTypes; actionMenu = false }) } }
            } }
            item { OutlinedTextField(startDay, { startDay = it }, label = { Text("Start day YYYY-MM-DD") }) }
            item { OutlinedTextField(runTime, { runTime = it }, label = { Text("Run time HH:MM") }) }
            item { Box {
                OutlinedButton(onClick = { typeMenu = true }) { Text(type.replace('_', ' ')) }
                DropdownMenu(typeMenu, { typeMenu = false }) { types.forEach { value -> DropdownMenuItem(text = { Text(value.replace('_', ' ')) }, onClick = { type = value; typeMenu = false }) } }
            } }
            if (type == "every_n_days" || type == "every_n_weeks") item { OutlinedTextField(interval, { interval = it.filter(Char::isDigit) }, label = { Text("Interval") }) }
            if (type == "weekly") item { OutlinedTextField(weekday, { weekday = it.filter(Char::isDigit) }, label = { Text("Weekday 0=Mon ... 6=Sun") }) }
            if (type == "monthly") item { OutlinedTextField(dayOfMonth, { dayOfMonth = it.filter(Char::isDigit) }, label = { Text("Day of month") }) }
            if (type == "yearly") {
                item { OutlinedTextField(monthOfYear, { monthOfYear = it.filter(Char::isDigit) }, label = { Text("Month 1-12") }) }
                item { OutlinedTextField(dayOfYear, { dayOfYear = it.filter(Char::isDigit) }, label = { Text("Day") }) }
            }
            item { OutlinedTextField(reminders, { reminders = it }, label = { Text("Reminders ; separated") }, placeholder = { Text("1 day before; 10 min before") }) }
            item { Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(enabled, { enabled = it }); Text("Enabled") } }
        } },
        confirmButton = { Button(enabled = actionId.isNotBlank(), onClick = {
            val now = TimeUtil.nowText()
            vm.saveRecurring(RecurringRule(
                id = existing?.id ?: 0,
                nodeId = actionId,
                startDay = startDay,
                runTime = runTime,
                recurrenceType = type,
                intervalValue = interval.toIntOrNull() ?: 1,
                weekday = weekday.toIntOrNull(),
                dayOfMonth = dayOfMonth.toIntOrNull(),
                monthOfYear = monthOfYear.toIntOrNull(),
                dayOfYearMonth = dayOfYear.toIntOrNull(),
                remindersJson = JSONArray(splitMulti(reminders)).toString(),
                enabled = enabled,
                createdAt = existing?.createdAt ?: now,
                updatedAt = now,
            )); onDismiss()
        }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun PlanEditorDialog(vm: PlanningViewModel, day: LocalDate, existing: PlanAction? = null, onDismiss: () -> Unit) {
    val tree by vm.actions.collectAsState()
    val all = flatten(tree)
    var selected by remember { mutableStateOf(existing?.idActionTypes ?: all.firstOrNull()?.action?.idActionTypes.orEmpty()) }
    var time by remember { mutableStateOf(existing?.runTime.orEmpty()) }
    var duration by remember { mutableStateOf(existing?.durationSeconds?.takeIf { it > 0 }?.let { TimeUtil.durationEditorText(it) }.orEmpty()) }
    var reminders by remember(existing?.idPlanActionTypes) { mutableStateOf(existing?.let { vm.reminders(it.idPlanActionTypes) }.orEmpty()) }
    val recurringRules by vm.recurringRules.collectAsState()
    val isRecurring =
        remember(
            existing?.idPlanActionTypes,
            day,
            recurringRules,
        ) {
            existing != null &&
                vm.isRecurringOccurrence(
                    day,
                    existing,
                )
        }
    var applyToFuture by remember {
        mutableStateOf(false)
    }
    var actionMenu by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (existing == null) "Add plan" else "Edit plan") },
        text = { Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text(day.toString())
            if (existing == null) Box {
                OutlinedButton(onClick = { actionMenu = true }) { Text(all.firstOrNull { it.action.idActionTypes == selected }?.action?.title ?: "Choose Action Type") }
                DropdownMenu(actionMenu, { actionMenu = false }) { all.forEach { node -> DropdownMenuItem(text = { Text("  ".repeat(node.depth) + node.action.title) }, onClick = { selected = node.action.idActionTypes; actionMenu = false }) } }
            } else Text(existing.actionName, fontWeight = FontWeight.Bold)
            OutlinedTextField(time, { time = it }, label = { Text("Start time HH:MM (optional)") })
            OutlinedTextField(duration, { duration = it }, label = { Text("Duration (blank = untimed)") })
            OutlinedTextField(reminders, { reminders = it }, label = { Text("Reminders ; separated") }, placeholder = { Text("1 day before; 10 min before") })

            if (isRecurring) {
                Text(
                    "Apply changes to",
                    fontWeight =
                        FontWeight.SemiBold,
                )

                if (!applyToFuture) {
                    Button(
                        onClick = {
                            applyToFuture = false
                        },
                        modifier =
                            Modifier.fillMaxWidth(),
                    ) {
                        Text("Only this occurrence")
                    }
                } else {
                    OutlinedButton(
                        onClick = {
                            applyToFuture = false
                        },
                        modifier =
                            Modifier.fillMaxWidth(),
                    ) {
                        Text("Only this occurrence")
                    }
                }

                if (applyToFuture) {
                    Button(
                        onClick = {
                            applyToFuture = true
                        },
                        modifier =
                            Modifier.fillMaxWidth(),
                    ) {
                        Text("This and future occurrences")
                    }
                } else {
                    OutlinedButton(
                        onClick = {
                            applyToFuture = true
                        },
                        modifier =
                            Modifier.fillMaxWidth(),
                    ) {
                        Text("This and future occurrences")
                    }
                }
            }
        } },
        confirmButton = { Button(enabled = existing != null || selected.isNotBlank(), onClick = {
            if (existing == null) vm.addPlan(day, selected, time.ifBlank { null }, duration, reminders)
            else vm.editPlan(
                existing.idPlanActionTypes,
                day,
                time.ifBlank { null },
                duration,
                reminders,
                applyToFuture = applyToFuture,
            )
            onDismiss()
        }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun ActionEditorDialog(title: String, initialName: String = "", initialDuration: String = "", onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    var name by remember { mutableStateOf(initialName) }
    var duration by remember { mutableStateOf(initialDuration) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(name, { name = it }, label = { Text("Name") })
            OutlinedTextField(duration, { duration = it }, label = { Text("Duration") }, placeholder = { Text("optional: 20 min, 1 h; blank = elapsed only") })
        } },
        confirmButton = { Button(enabled = name.isNotBlank(), onClick = { onSave(name, duration) }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun TodosDialog(vm: PlanningViewModel, node: ActionNode, onDismiss: () -> Unit) {
    var revision by remember { mutableIntStateOf(0) }
    val todos = remember(revision) { vm.todos(node.action.idActionTypes) }
    var text by remember { mutableStateOf("") }
    var editing by remember { mutableStateOf<ActionTodo?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Todos — ${node.action.title}") },
        text = { Column {
            todos.forEach { todo -> Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(todo.isDone, { vm.setTodo(todo, it); revision++ })
                Text(todo.todo, modifier = Modifier.weight(1f).clickable { editing = todo })
                TextButton(onClick = { editing = todo }) { Text("Edit") }
                TextButton(onClick = { vm.deleteTodo(todo.idActionTypesTodos); revision++ }) { Text("×") }
            } }
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(text, { text = it }, modifier = Modifier.weight(1f), label = { Text("New todo") })
                TextButton(onClick = { if (text.isNotBlank()) { vm.addTodo(node.action.idActionTypes, text); text = ""; revision++ } }) { Text("Add") }
            }
        } },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
    editing?.let { todo -> TextEditDialog("Edit todo", todo.todo, onDismiss = { editing = null }) { value -> vm.updateTodo(todo, value); editing = null; revision++ } }
}

private data class OverallStatisticsSnapshot(
    val bars: List<Pair<ActionNode, Long>>,
    val total: Long,
    val maximum: Long,
)

@Composable
private fun OverallStatisticsDialog(
    vm: PlanningViewModel,
    roots: List<ActionNode>,
    onDismiss: () -> Unit,
) {
    var range by remember {
        mutableStateOf("Today")
    }

    var rangeOpen by remember {
        mutableStateOf(false)
    }

    val today =
        LocalDate.now(
            ZoneId.of("Europe/Vienna")
        )

    var customFrom by remember {
        mutableStateOf(
            today.minusDays(7).toString()
        )
    }

    var customTo by remember {
        mutableStateOf(today.toString())
    }

    var revision by remember {
        mutableIntStateOf(0)
    }

    var intervals by remember {
        mutableStateOf<List<TimeInterval>?>(null)
    }

    LaunchedEffect(revision) {
        intervals =
            vm.allIntervalsForStatistics()
    }

    val bounds =
        remember(
            range,
            customFrom,
            customTo,
        ) {
            statisticsBounds(
                range,
                customFrom,
                customTo,
            )
        }

    val snapshot =
        remember(
            roots,
            intervals,
            bounds,
        ) {
            val loaded = intervals
            val selectedBounds = bounds

            if (
                loaded == null ||
                selectedBounds == null
            ) {
                OverallStatisticsSnapshot(
                    emptyList(),
                    0L,
                    1L,
                )
            } else {
                val byNode =
                    loaded.groupBy {
                        it.nodeId
                    }

                val totals =
                    mutableMapOf<String, Long>()

                fun directSeconds(
                    node: ActionNode,
                ): Long {
                    val ids =
                        listOf(
                            node.action.idActionTypes,
                            node.action.id,
                        ).distinct()

                    return ids.sumOf { id ->
                        intervalSecondsInRange(
                            byNode[id].orEmpty(),
                            selectedBounds,
                        )
                    }
                }

                fun visit(
                    node: ActionNode,
                ): Long {
                    val total =
                        directSeconds(node) +
                            node.children.sumOf {
                                visit(it)
                            }

                    totals[
                        node.action.idActionTypes
                    ] = total

                    return total
                }

                val grandTotal =
                    roots.sumOf {
                        visit(it)
                    }

                val bars =
                    flatten(roots).map {
                        node ->
                        node to (
                            totals[
                                node.action.idActionTypes
                            ] ?: 0L
                        )
                    }

                OverallStatisticsSnapshot(
                    bars = bars,
                    total = grandTotal,
                    maximum =
                        bars.maxOfOrNull {
                            it.second
                        }?.coerceAtLeast(1L)
                            ?: 1L,
                )
            }
        }

    val expandedNodes =
        remember {
            mutableStateListOf<String>()
        }

    val visibleBars =
        remember(
            roots,
            snapshot.bars,
            expandedNodes.toList(),
        ) {
            val secondsById =
                snapshot.bars.associate {
                    it.first.action.idActionTypes to
                        it.second
                }

            buildList<Pair<ActionNode, Long>> {
                fun addVisible(
                    node: ActionNode,
                ) {
                    add(
                        node to
                            (
                                secondsById[
                                    node.action.idActionTypes
                                ] ?: 0L
                            )
                    )

                    if (
                        node.action.idActionTypes
                        in expandedNodes
                    ) {
                        node.children.forEach(
                            ::addVisible
                        )
                    }
                }

                roots.forEach(
                    ::addVisible
                )
            }
        }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                "Statistics — Action Types"
            )
        },
        text = {
            Column(
                verticalArrangement =
                    Arrangement.spacedBy(6.dp)
            ) {
                Box {
                    OutlinedButton(
                        onClick = {
                            rangeOpen = true
                        }
                    ) {
                        Text(
                            when (range) {
                                "Today" ->
                                    "Today 00:00 → now"

                                "24 h" ->
                                    "Last 24 hours"

                                else ->
                                    range
                            }
                        )
                    }

                    DropdownMenu(
                        expanded = rangeOpen,
                        onDismissRequest = {
                            rangeOpen = false
                        },
                    ) {
                        listOf(
                            "Today",
                            "24 h",
                            "Week",
                            "Month",
                            "Year",
                            "All",
                            "Custom",
                        ).forEach { option ->
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        when (option) {
                                            "Today" ->
                                                "Today (00:00 → now)"

                                            "24 h" ->
                                                "Last 24 hours"

                                            else ->
                                                option
                                        }
                                    )
                                },
                                onClick = {
                                    range = option
                                    rangeOpen = false
                                },
                            )
                        }
                    }
                }

                if (range == "Custom") {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement =
                            Arrangement.spacedBy(6.dp),
                    ) {
                        OutlinedTextField(
                            customFrom,
                            {
                                customFrom = it
                            },
                            label = {
                                Text(
                                    "From YYYY-MM-DD"
                                )
                            },
                            singleLine = true,
                            modifier =
                                Modifier.weight(1f),
                        )

                        OutlinedTextField(
                            customTo,
                            {
                                customTo = it
                            },
                            label = {
                                Text(
                                    "To YYYY-MM-DD"
                                )
                            },
                            singleLine = true,
                            modifier =
                                Modifier.weight(1f),
                        )
                    }
                }

                when {
                    intervals == null -> {
                        Text(
                            "Loading statistics…"
                        )
                    }

                    bounds == null -> {
                        Text(
                            "Invalid custom date range",
                            color =
                                MaterialTheme
                                    .colorScheme
                                    .error,
                        )
                    }

                    else -> {
                        Text(
                            "Total: ${
                                TimeUtil.compactDuration(
                                    snapshot.total
                                )
                            }",
                            fontWeight =
                                FontWeight.SemiBold,
                        )

                        Text(
                            "Bar plot",
                            style =
                                MaterialTheme
                                    .typography
                                    .labelLarge,
                        )

                        LazyColumn(
                            Modifier.height(330.dp)
                        ) {
                            items(
                                visibleBars,
                                key = {
                                    it.first
                                        .action
                                        .idActionTypes
                                },
                            ) {
                                (node, seconds) ->

                                StatisticBarRow(
                                    title =
                                        node.action.title,
                                    seconds = seconds,
                                    maximum =
                                        snapshot.maximum,
                                    depth = node.depth,
                                    expandable =
                                        node.children.isNotEmpty(),
                                    expanded =
                                        node.action.idActionTypes
                                            in expandedNodes,
                                    onToggle = {
                                        val id =
                                            node.action.idActionTypes

                                        if (id in expandedNodes) {
                                            expandedNodes.remove(id)
                                        } else {
                                            expandedNodes.add(id)
                                        }
                                    },
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            Row {
                TextButton(
                    onClick = {
                        revision++
                    }
                ) {
                    Text("Refresh")
                }

                TextButton(
                    onClick = onDismiss
                ) {
                    Text("Close")
                }
            }
        },
    )
}


@Composable
private fun StatisticsDialog(vm: PlanningViewModel, node: ActionNode, onDismiss: () -> Unit) {
    var revision by remember { mutableIntStateOf(0) }
    var range by remember { mutableStateOf("Today") }
    var rangeOpen by remember { mutableStateOf(false) }
    var customFrom by remember { mutableStateOf(LocalDate.now(ZoneId.of("Europe/Vienna")).minusDays(7).toString()) }
    var customTo by remember { mutableStateOf(LocalDate.now(ZoneId.of("Europe/Vienna")).toString()) }
    var add by remember { mutableStateOf(false) }
    var edit by remember { mutableStateOf<TimeInterval?>(null) }

    val intervals = remember(revision) { vm.intervals(node.action.idActionTypes).take(100) }
    val bounds = remember(range, customFrom, customTo, revision) { statisticsBounds(range, customFrom, customTo) }
    val barNodes = remember(node) { listOf(node) + flatten(node.children) }
    val bars = remember(revision, range, customFrom, customTo, node) {
        val b = statisticsBounds(range, customFrom, customTo)
        if (b == null) emptyList() else barNodes.map { item ->
            item to intervalSecondsInRange(vm.intervals(item.action.idActionTypes), b)
        }
    }
    val maximum = bars.maxOfOrNull { it.second }?.coerceAtLeast(1L) ?: 1L
    val selectedTotal = bars.firstOrNull()?.second ?: 0L

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Intervals / Statistics") },
        text = {
            Column {
                Text(node.action.title, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                Box {
                    OutlinedButton(onClick = { rangeOpen = true }) { Text("Range: $range") }
                    DropdownMenu(expanded = rangeOpen, onDismissRequest = { rangeOpen = false }) {
                        listOf("Today", "24 h", "Week", "Month", "Year", "All", "Custom").forEach { label ->
                            DropdownMenuItem(
                                text = { Text(label) },
                                onClick = { range = label; rangeOpen = false },
                            )
                        }
                    }
                }
                if (range == "Custom") {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedTextField(customFrom, { customFrom = it }, label = { Text("From YYYY-MM-DD") }, modifier = Modifier.weight(1f), singleLine = true)
                        OutlinedTextField(customTo, { customTo = it }, label = { Text("To YYYY-MM-DD") }, modifier = Modifier.weight(1f), singleLine = true)
                    }
                }
                if (bounds == null) {
                    Text("Invalid custom date range", color = MaterialTheme.colorScheme.error)
                } else {
                    Text("Total: ${TimeUtil.compactDuration(selectedTotal)}", fontWeight = FontWeight.SemiBold)
                    Text("Bar plot", style = MaterialTheme.typography.labelLarge)
                    LazyColumn(Modifier.height(190.dp)) {
                        items(bars, key = { it.first.action.idActionTypes }) { (barNode, seconds) ->
                            StatisticBarRow(
                                title = barNode.action.title,
                                seconds = seconds,
                                maximum = maximum,
                                depth = (barNode.depth - node.depth).coerceAtLeast(0),
                            )
                        }
                    }
                }
                Divider()
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("Intervals", fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    Button(onClick = { add = true }) { Text("Add interval") }
                }
                LazyColumn(Modifier.height(220.dp)) {
                    items(intervals, key = { it.id }) { item ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                "${item.startedAt} → ${item.endedAt ?: "running"}\n${item.durationSeconds?.let { TimeUtil.compactDuration(it.toLong()) }.orEmpty()}",
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.weight(1f).clickable { if (item.endedAt != null) edit = item },
                            )
                            if (item.endedAt != null) TextButton(onClick = { edit = item }) { Text("Edit") }
                            if (item.endedAt != null) TextButton(onClick = { vm.deleteInterval(item.id); revision++ }) { Text("×") }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
    if (add) IntervalDialog(null, onDismiss = { add = false }) { start, end ->
        vm.addInterval(node.action.idActionTypes, start, end)
        add = false
        revision++
    }
    edit?.let { item ->
        IntervalDialog(item, onDismiss = { edit = null }) { start, end ->
            vm.updateInterval(item.id, start, end)
            edit = null
            revision++
        }
    }
}

private fun statisticsBounds(
    range: String,
    customFrom: String,
    customTo: String,
): Pair<OffsetDateTime?, OffsetDateTime?>? {
    val now = OffsetDateTime.now()
    val offset = now.offset
    return try {
        when (range) {
            "Today" -> now.toLocalDate().atStartOfDay().atOffset(offset) to now
            "24 h" -> now.minusHours(24) to now
            "Week" -> now.toLocalDate().minusDays((now.dayOfWeek.value - 1).toLong()).atStartOfDay().atOffset(offset) to now
            "Month" -> now.toLocalDate().withDayOfMonth(1).atStartOfDay().atOffset(offset) to now
            "Year" -> now.toLocalDate().withDayOfYear(1).atStartOfDay().atOffset(offset) to now
            "All" -> null to null
            "Custom" -> {
                val start = LocalDate.parse(customFrom).atStartOfDay().atOffset(offset)
                val end = LocalDate.parse(customTo).plusDays(1).atStartOfDay().atOffset(offset)
                if (end.isAfter(start)) start to end else null
            }
            else -> null
        }
    } catch (_: Exception) {
        null
    }
}

private fun intervalSecondsInRange(
    intervals: List<TimeInterval>,
    bounds: Pair<OffsetDateTime?, OffsetDateTime?>,
): Long {
    val now = OffsetDateTime.now()

    return intervals.sumOf { item ->
        val started =
            runCatching {
                OffsetDateTime.parse(
                    item.startedAt
                )
            }.getOrNull()
                ?: return@sumOf 0L

        val ended =
            if (item.endedAt == null) {
                now
            } else {
                runCatching {
                    OffsetDateTime.parse(
                        item.endedAt
                    )
                }.getOrNull()
                    ?: return@sumOf 0L
            }

        val from =
            bounds.first?.let {
                if (started.isBefore(it)) {
                    it
                } else {
                    started
                }
            } ?: started

        val to =
            bounds.second?.let {
                if (ended.isAfter(it)) {
                    it
                } else {
                    ended
                }
            } ?: ended

        if (to.isAfter(from)) {
            Duration.between(
                from,
                to,
            ).seconds.coerceAtLeast(0L)
        } else {
            0L
        }
    }
}

@Composable
private fun StatisticBarRow(
    title: String,
    seconds: Long,
    maximum: Long,
    depth: Int,
    expandable: Boolean = false,
    expanded: Boolean = false,
    onToggle: (() -> Unit)? = null,
) {
    val fraction =
        (
            seconds.toFloat() /
                maximum.toFloat()
            ).coerceIn(0f, 1f)

    Row(
        Modifier
            .fillMaxWidth()
            .clickable(
                enabled = expandable,
            ) {
                onToggle?.invoke()
            }
            .padding(vertical = 3.dp),
        verticalAlignment =
            Alignment.CenterVertically,
    ) {
        val marker =
            when {
                !expandable -> "  "
                expanded -> "▾ "
                else -> "▸ "
            }

        Text(
            "  ".repeat(
                depth.coerceAtMost(6)
            ) + marker + title,
            style =
                MaterialTheme.typography
                    .bodySmall,
            maxLines = 1,
            overflow =
                TextOverflow.Ellipsis,
            modifier =
                Modifier.weight(0.46f),
        )

        Box(
            Modifier
                .weight(0.54f)
                .height(26.dp)
                .background(
                    MaterialTheme
                        .colorScheme
                        .surfaceVariant,
                    RoundedCornerShape(7.dp),
                ),
            contentAlignment =
                Alignment.Center,
        ) {
            if (fraction > 0f) {
                Box(
                    Modifier
                        .fillMaxWidth(
                            fraction
                        )
                        .height(26.dp)
                        .background(
                            statisticColors[
                                depth %
                                    statisticColors.size
                            ],
                            RoundedCornerShape(
                                7.dp
                            ),
                        ),
                )
            }

            Text(
                TimeUtil.compactDuration(
                    seconds
                ),
                style =
                    MaterialTheme.typography
                        .labelSmall,
                fontWeight =
                    FontWeight.Bold,
            )
        }
    }
}

@Composable
private fun IntervalDialog(existing: TimeInterval?, onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    val now = OffsetDateTime.now()
    var start by remember { mutableStateOf(existing?.startedAt ?: now.minusMinutes(30).toString()) }
    var end by remember { mutableStateOf(existing?.endedAt ?: now.toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (existing == null) "Add interval" else "Edit interval") },
        text = { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(start, { start = it }, label = { Text("From ISO date-time") })
            OutlinedTextField(end, { end = it }, label = { Text("To ISO date-time") })
        } },
        confirmButton = { Button(onClick = { onSave(start, end) }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun DayNotesDialog(vm: PlanningViewModel, plan: DayPlan, onDismiss: () -> Unit) {
    var revision by remember { mutableIntStateOf(0) }
    val notes = remember(revision) { vm.planNotes(plan.idPlans) }
    NotesEditor("Day notes — ${plan.day}", notes, { it.note },
        onAdd = { vm.addPlanNote(plan.idPlans, it); revision++ },
        onEdit = { note, text -> vm.updatePlanNote(note.idPlanNotes, text); revision++ },
        onDelete = { vm.deletePlanNote(it.idPlanNotes); revision++ },
        onDismiss = onDismiss)
}

@Composable
private fun PlanActionDetailsDialog(vm: PlanningViewModel, action: PlanAction, onDismiss: () -> Unit) {
    var revision by remember { mutableIntStateOf(0) }
    val notes = remember(revision) { vm.planActionNotes(action.idPlanActionTypes) }
    val todos = remember(revision) { vm.planActionTodos(action.idPlanActionTypes) }
    var noteText by remember { mutableStateOf("") }
    var todoText by remember { mutableStateOf("") }
    var editingNote by remember { mutableStateOf<PlanActionNote?>(null) }
    var editingTodo by remember { mutableStateOf<PlanActionTodo?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Plan details — ${action.actionName}") },
        text = { LazyColumn(Modifier.height(430.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            item { Text("Notes", fontWeight = FontWeight.Bold) }
            items(notes, key = { "n${it.idPlanActionNotes}" }) { note -> Row(verticalAlignment = Alignment.CenterVertically) {
                Text(note.note, modifier = Modifier.weight(1f).clickable { editingNote = note })
                TextButton(onClick = { editingNote = note }) { Text("Edit") }
                TextButton(onClick = { vm.deletePlanActionNote(note.idPlanActionNotes); revision++ }) { Text("×") }
            } }
            item { Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(noteText, { noteText = it }, modifier = Modifier.weight(1f), label = { Text("New note") })
                TextButton(onClick = { if (noteText.isNotBlank()) { vm.addPlanActionNote(action.idPlanActionTypes, noteText); noteText = ""; revision++ } }) { Text("Add") }
            } }
            item { Divider(); Text("Todos", fontWeight = FontWeight.Bold) }
            items(todos, key = { "t${it.idPlanActionTypeTodos}" }) { todo -> Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(todo.isDone, { vm.setPlanActionTodoDone(todo, it); revision++ })
                Text(todo.todo, modifier = Modifier.weight(1f).clickable { editingTodo = todo })
                TextButton(onClick = { editingTodo = todo }) { Text("Edit") }
                TextButton(onClick = { vm.deletePlanActionTodo(todo.idPlanActionTypeTodos); revision++ }) { Text("×") }
            } }
            item { Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(todoText, { todoText = it }, modifier = Modifier.weight(1f), label = { Text("New todo") })
                TextButton(onClick = { if (todoText.isNotBlank()) { vm.addPlanActionTodo(action.idPlanActionTypes, todoText); todoText = ""; revision++ } }) { Text("Add") }
            } }
        } },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
    editingNote?.let { note -> TextEditDialog("Edit note", note.note, { editingNote = null }) { vm.updatePlanActionNote(note.idPlanActionNotes, it); editingNote = null; revision++ } }
    editingTodo?.let { todo -> TextEditDialog("Edit todo", todo.todo, { editingTodo = null }) { vm.updatePlanActionTodo(todo, it); editingTodo = null; revision++ } }
}

@Composable
private fun <T> NotesEditor(
    title: String,
    notes: List<T>,
    textOf: (T) -> String,
    onAdd: (String) -> Unit,
    onEdit: (T, String) -> Unit,
    onDelete: (T) -> Unit,
    onDismiss: () -> Unit,
) {
    var text by remember { mutableStateOf("") }
    var editing by remember { mutableStateOf<T?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Column {
            notes.forEach { note -> Row(verticalAlignment = Alignment.CenterVertically) {
                Text(textOf(note), modifier = Modifier.weight(1f).clickable { editing = note })
                TextButton(onClick = { editing = note }) { Text("Edit") }
                TextButton(onClick = { onDelete(note) }) { Text("×") }
            } }
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(text, { text = it }, modifier = Modifier.weight(1f), label = { Text("New note") })
                TextButton(onClick = { if (text.isNotBlank()) { onAdd(text); text = "" } }) { Text("Add") }
            }
        } },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
    editing?.let { note -> TextEditDialog("Edit note", textOf(note), { editing = null }) { value -> onEdit(note, value); editing = null } }
}

@Composable
private fun TextEditDialog(title: String, initial: String, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var text by remember(initial) { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { OutlinedTextField(text, { text = it }, label = { Text("Text") }) },
        confirmButton = { Button(enabled = text.isNotBlank(), onClick = { onSave(text) }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun StartActionDialog(runtime: RuntimeControlState, title: String, onCancel: () -> Unit, onStart: (Boolean) -> Unit) {
    if (!runtime.active || runtime.currentNodeId == null) {
        LaunchedEffect(title) { onStart(false) }
        return
    }
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Switch action") },
        text = { Text("A task is already active. Before starting \"$title\", what should happen to the current action?") },
        confirmButton = { Button(onClick = { onStart(false) }) { Text("Pause previous") } },
        dismissButton = { Row {
            TextButton(onClick = { onStart(true) }) { Text("Stop previous") }
            TextButton(onClick = onCancel) { Text("Cancel") }
        } },
    )
}

@Composable
private fun SettingsDialog(vm: PlanningViewModel, onDismiss: () -> Unit) {
    val sync by vm.sync.collectAsState()
    val before by vm.daysBefore.collectAsState()
    val after by vm.daysAfter.collectAsState()
    var b by remember(before) { mutableStateOf(before.toString()) }
    var a by remember(after) { mutableStateOf(after.toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Settings") },
        text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(if (sync.authenticated) "Dropbox connected" else "Dropbox not connected")
            sync.lastSyncAt?.let { Text("Last sync: $it", style = MaterialTheme.typography.bodySmall) }
            sync.lastError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (!sync.authenticated) Button(onClick = vm::connectDropbox) { Text("Connect Dropbox") }
            else OutlinedButton(onClick = vm::disconnectDropbox) { Text("Disconnect") }
            OutlinedTextField(b, { b = it.filter(Char::isDigit) }, label = { Text("Past days") })
            OutlinedTextField(a, { a = it.filter(Char::isDigit) }, label = { Text("Future days") })
            Text("Record-level sync is used; Android and Desktop never overwrite the same live SQLite file.", style = MaterialTheme.typography.bodySmall)
        } },
        confirmButton = { Button(onClick = { vm.setRange(b.toIntOrNull() ?: before, a.toIntOrNull() ?: after); onDismiss() }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

private data class TimerModel(
    val id: Long,
    val label: String,
    val initialSeconds: Int,
    val startedAt: Long,
    val baseElapsed: Int = 0,
    val running: Boolean = true,
    val alarmed: Boolean = false,
)

@Composable
private fun TimersScreen(modifier: Modifier) {
    val context = LocalContext.current
    val timers = remember { mutableStateListOf<TimerModel>() }
    var label by remember { mutableStateOf("") }
    var duration by remember { mutableStateOf("") }
    var tick by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { tick = System.currentTimeMillis(); delay(250) } }
    Column(modifier.fillMaxSize().padding(10.dp)) {
        Text("Standalone timers", style = MaterialTheme.typography.titleMedium)
        Text("Independent from Plans, Action types and planning history.", style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(label, { label = it }, label = { Text("Label") }, modifier = Modifier.weight(1f))
            Spacer(Modifier.width(5.dp))
            OutlinedTextField(duration, { duration = it }, label = { Text("Duration") }, modifier = Modifier.weight(1f))
            Spacer(Modifier.width(5.dp))
            Button(onClick = {
                TimeUtil.parseDuration(duration)?.let { seconds ->
                    timers += TimerModel(System.nanoTime(), label.ifBlank { "Timer ${timers.size + 1}" }, seconds, System.currentTimeMillis())
                    label = ""; duration = ""
                }
            }) { Text("Add") }
        }
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            items(timers, key = { it.id }) { timer ->
                val elapsed = timer.baseElapsed + if (timer.running) ((tick - timer.startedAt) / 1000L).toInt().coerceAtLeast(0) else 0
                val remaining = timer.initialSeconds - elapsed
                LaunchedEffect(timer.id, remaining <= 0, timer.alarmed) {
                    if (remaining <= 0 && !timer.alarmed) {
                        runCatching { RingtoneManager.getRingtone(context, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION))?.play() }
                        val index = timers.indexOfFirst { it.id == timer.id }
                        if (index >= 0) timers[index] = timers[index].copy(alarmed = true)
                    }
                }
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(9.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(timer.label, fontWeight = FontWeight.Bold)
                            Text(if (remaining >= 0) "Remaining ${TimeUtil.compactDuration(remaining.toLong())}" else "Over +${TimeUtil.compactDuration((-remaining).toLong())}")
                            Text("Initial ${TimeUtil.compactDuration(timer.initialSeconds.toLong())} · Elapsed ${TimeUtil.compactDuration(elapsed.toLong())}", style = MaterialTheme.typography.bodySmall)
                        }
                        TextButton(onClick = {
                            val index = timers.indexOf(timer)
                            if (index >= 0) timers[index] = if (timer.running) timer.copy(baseElapsed = elapsed, running = false) else timer.copy(startedAt = System.currentTimeMillis(), running = true)
                        }) { Text(if (timer.running) "Pause" else "Run") }
                        TextButton(onClick = { timers.remove(timer) }) { Text("Delete") }
                    }
                }
            }
        }
    }
}

@Composable
private fun DateStepper(day: LocalDate, onChange: (LocalDate) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        TextButton(onClick = { onChange(day.minusDays(1)) }) { Text("‹") }
        Text(day.toString(), fontWeight = FontWeight.Bold)
        TextButton(onClick = { onChange(day.plusDays(1)) }) { Text("›") }
        TextButton(onClick = { onChange(LocalDate.now(ZoneId.of("Europe/Vienna"))) }) { Text("Today") }
    }
}

private fun flatten(nodes: List<ActionNode>): List<ActionNode> = buildList {
    fun visit(node: ActionNode) { add(node); node.children.forEach(::visit) }
    nodes.forEach(::visit)
}

private fun splitMulti(text: String): List<String> = text.split(';', '\n', ',').map(String::trim).filter(String::isNotBlank)
private fun jsonArrayToText(raw: String): String = runCatching { JSONArray(raw).let { a -> (0 until a.length()).joinToString("; ") { a.getString(it) } } }.getOrDefault("")

private fun dragData(text: String): DragAndDropTransferData = DragAndDropTransferData(
    clipData = ClipData.newPlainText("nd-planning", text), flags = View.DRAG_FLAG_GLOBAL,
)

private fun textDropTarget(onDropText: (String) -> Boolean): DragAndDropTarget = object : DragAndDropTarget {
    override fun onDrop(event: DragAndDropEvent): Boolean {
        val data = event.toAndroidDragEvent().clipData ?: return false
        if (data.itemCount == 0) return false
        return onDropText(data.getItemAt(0).text?.toString().orEmpty())
    }
}

