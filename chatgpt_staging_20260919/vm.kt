package com.ndplanning.android.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ndplanning.android.BuildConfig
import com.ndplanning.android.PlanningApplication
import com.ndplanning.android.data.ActionNode
import com.ndplanning.android.data.ActionPanelTodo
import com.ndplanning.android.data.ActionStatistics
import com.ndplanning.android.data.ActionTodo
import com.ndplanning.android.data.DayPlan
import com.ndplanning.android.data.PlanAction
import com.ndplanning.android.data.PlanActionNote
import com.ndplanning.android.data.PlanActionTodo
import com.ndplanning.android.data.PlanNote
import com.ndplanning.android.data.RecurringRule
import com.ndplanning.android.data.TimeInterval
import com.ndplanning.android.runtime.PlanningRuntime
import com.ndplanning.android.sync.SyncStatus
import com.ndplanning.android.util.TimeUtil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import java.time.LocalDate
import java.time.ZoneId

data class RuntimeControlState(
    val active: Boolean = false,
    val currentNodeId: String? = null,
    val rootNodeId: String? = null,
    val paused: Boolean = false,
)

class PlanningViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as PlanningApplication
    private val repo = app.repository
    val runtime: PlanningRuntime = app.runtime

    private val prefs = app.getSharedPreferences("nd_planning_ui", 0)
    private val _actions = MutableStateFlow<List<ActionNode>>(emptyList())
    val actions = _actions.asStateFlow()
    private val _actionPanelTodos = MutableStateFlow<List<ActionPanelTodo>>(emptyList())
    val actionPanelTodos = _actionPanelTodos.asStateFlow()
    private val _plans = MutableStateFlow<List<DayPlan>>(emptyList())
    val plans = _plans.asStateFlow()
    private val _recurringRules = MutableStateFlow<List<RecurringRule>>(emptyList())
    val recurringRules = _recurringRules.asStateFlow()
    private val _sync = MutableStateFlow(SyncStatus(app.dropbox.isAuthenticated()))
    val sync = _sync.asStateFlow()
    private val _filter = MutableStateFlow("")
    val filter = _filter.asStateFlow()
    private val _daysBefore = MutableStateFlow(prefs.getInt("days_before", 14))
    val daysBefore = _daysBefore.asStateFlow()
    private val _daysAfter = MutableStateFlow(prefs.getInt("days_after", 14))
    val daysAfter = _daysAfter.asStateFlow()
    private val _message = MutableStateFlow<String?>(null)
    val message = _message.asStateFlow()
    private val _runtimeControl = MutableStateFlow(RuntimeControlState())
    val runtimeControl = _runtimeControl.asStateFlow()

    private val _runtimeTitle = MutableStateFlow("")
    val runtimeTitle = _runtimeTitle.asStateFlow()

    // When Dropbox is connected, never trust an old local runtime until the
    // first successful remote sync has hydrated it.
    private var runtimeHydrated = !app.dropbox.isAuthenticated()
    private var scheduleHydrated = !app.dropbox.isAuthenticated()
    private var wasAuthenticated = app.dropbox.isAuthenticated()
    @Volatile private var lastScheduleRefreshAt = 0L

    val initialTab: Int get() = prefs.getInt("selected_tab", 0).coerceIn(0, 4)
    fun rememberTab(index: Int) { prefs.edit().putInt("selected_tab", index.coerceIn(0, 4)).apply() }

    init {
        refresh()
        viewModelScope.launch {
            runtime.state.collect { state ->
                val nextControl = RuntimeControlState(
                    active = state.active,
                    currentNodeId = state.currentNodeId,
                    rootNodeId = state.rootNodeId,
                    paused = state.paused,
                )

                val semanticChanged = nextControl != _runtimeControl.value
                _runtimeControl.value = nextControl

                if (semanticChanged) {
                    _runtimeTitle.value =
                        if (!state.active) {
                            ""
                        } else {
                            withContext(Dispatchers.IO) {
                                resolveRuntimeTitle(
                                    state.currentNodeId,
                                    state.rootNodeId,
                                )
                            }
                        }
                }
            }
        }
        if (app.dropbox.isAuthenticated()) syncNow()
        viewModelScope.launch {
            while (true) {
                delay(2_000)
                if (app.dropbox.isAuthenticated()) syncNow()
            }
        }
    }

    private fun resolveRuntimeTitle(
        currentNodeId: String?,
        rootNodeId: String?,
    ): String {
        var row = currentNodeId?.let(repo::action)
            ?: rootNodeId?.let(repo::action)
            ?: return ""

        val parts = mutableListOf<String>()
        val seen = mutableSetOf<String>()

        while (seen.add(row.idActionTypes)) {
            parts += row.title
            val parent = row.parentId ?: break
            row = repo.action(parent) ?: break
        }

        return parts.asReversed().joinToString(" › ")
    }

    fun refresh() {
        viewModelScope.launch(Dispatchers.IO) {
            val today = LocalDate.now(ZoneId.of("Europe/Vienna"))
            app.scheduleEngine.materializeThrough(_daysAfter.value.toLong())
            _actions.value = repo.actionTree(_filter.value)
            _actionPanelTodos.value = repo.actionPanelTodos()
            _plans.value = repo.plansBetween(today.minusDays(_daysBefore.value.toLong()), today.plusDays(_daysAfter.value.toLong()))
            _recurringRules.value = repo.recurringRules()
            _sync.value = _sync.value.copy(authenticated = app.dropbox.isAuthenticated())
        }
    }

    fun setFilter(value: String) { _filter.value = value; refresh() }

    fun setRange(before: Int, after: Int) {
        _daysBefore.value = before.coerceIn(0, 3650)
        _daysAfter.value = after.coerceIn(0, 3650)
        prefs.edit().putInt("days_before", _daysBefore.value).putInt("days_after", _daysAfter.value).apply()
        refresh()
    }

    fun connectDropbox() {
        if (BuildConfig.DROPBOX_APP_KEY.isBlank() || BuildConfig.DROPBOX_APP_KEY == "missing_dropbox_app_key") {
            _message.value = "Set DROPBOX_APP_KEY in local.properties first."
            return
        }
        app.dropbox.startAuthentication()
    }

    fun disconnectDropbox() {
        app.dropbox.signOut()
        _sync.value = SyncStatus(false)
        wasAuthenticated = false
        runtimeHydrated = true
        scheduleHydrated = true
        viewModelScope.launch(Dispatchers.IO) { app.runtime.reloadFromDatabase() }
    }

    fun syncNow() {
        val authenticated = app.dropbox.isAuthenticated()
        if (!authenticated || _sync.value.running) return
        if (!wasAuthenticated) {
            wasAuthenticated = true
            runtimeHydrated = false
            scheduleHydrated = false
        }
        viewModelScope.launch {
            _sync.value = _sync.value.copy(authenticated = true, running = true, lastError = null)
            val firstRuntimeHydration = !runtimeHydrated
            val result = app.syncNowSerialized()

            if (result.lastError == null) {
                if (firstRuntimeHydration) {
                    withContext(Dispatchers.IO) {
                        app.runtime.reloadFromDatabase()
                    }
                    runtimeHydrated = true
                } else {
                    // Do not depend on result.runtimeChanged here.
                    // A background Worker may already have applied the
                    // runtime version to SQLite, making the next foreground
                    // sync report runtimeChanged=false while RAM is stale.
                    withContext(Dispatchers.IO) {
                        app.runtime.reloadFromDatabaseIfControlChanged()
                    }
                }

                if (!scheduleHydrated) {
                    scheduleHydrated = true
                    scheduleRefreshAsync(force = true)
                } else if (result.pulled > 0) {
                    scheduleRefreshAsync(force = false)
                }
            }

            _sync.value = result
            if (result.pulled > 0 || firstRuntimeHydration) refresh()
        }
    }

    fun clearMessage() { _message.value = null }

    fun addAction(name: String, parentId: String?, durationText: String) = mutate {
        repo.addActionType(name, parentId, TimeUtil.parseDuration(durationText))
    }

    fun editAction(id: String, name: String, durationText: String) = mutate {
        repo.updateActionType(id, name, TimeUtil.parseDuration(durationText))
    }

    fun deleteAction(id: String) = mutate { repo.deleteActionType(id) }

    fun moveAction(id: String, targetParent: String?, position: Int = Int.MAX_VALUE) = mutate {
        val stableParent = targetParent?.let { repo.action(it)?.id }
        val siblings = repo.actionTypes().count { it.parentId == stableParent && it.idActionTypes != id }
        repo.moveActionType(id, stableParent, if (position == Int.MAX_VALUE) siblings else position)
    }

    fun addPlan(day: LocalDate, actionId: String, runTime: String?, durationText: String, remindersText: String = "") =
        mutate(refreshSchedule = true) {
            repo.addPlanAction(day, actionId, runTime, TimeUtil.parseDuration(durationText), parseReminders(remindersText))
        }

    fun isRecurringOccurrence(
        day: LocalDate,
        action: PlanAction,
    ): Boolean =
        repo.recurringRuleForOccurrence(
            day,
            action,
        ) != null

    fun editPlan(
        id: Long,
        day: LocalDate,
        runTime: String?,
        durationText: String,
        remindersText: String? = null,
        applyToFuture: Boolean = false,
    ) =
        mutate(refreshSchedule = true) {
            val duration =
                TimeUtil.parseDuration(
                    durationText
                )

            val reminderValues =
                remindersText?.let(
                    ::parseReminders
                ) ?: repo.reminders(id)

            val updatedFuture =
                applyToFuture &&
                    repo.updateRecurringOccurrenceAndFuture(
                        id,
                        day,
                        runTime,
                        duration,
                        reminderValues,
                    )

            if (!updatedFuture) {
                repo.updatePlanAction(
                    id,
                    day,
                    runTime,
                    duration,
                )

                remindersText?.let {
                    repo.replaceReminders(
                        id,
                        reminderValues,
                    )
                }
            }
        }

    fun deletePlan(id: Long) = mutate(refreshSchedule = true) { repo.deletePlanAction(id) }

    fun movePlan(id: Long, day: LocalDate, position: Int = Int.MAX_VALUE) = mutate(refreshSchedule = true) {
        val plan = repo.dayPlan(day)
        val size = plan?.actions?.count { it.idPlanActionTypes != id } ?: 0
        repo.movePlanAction(id, day, if (position == Int.MAX_VALUE) size else position.coerceIn(0, size))
    }

    fun reminders(planId: Long): String = repo.reminders(planId).joinToString("; ")
    fun addReminder(planId: Long, text: String) = mutate(refreshSchedule = true) { repo.addReminder(planId, text) }

    fun todos(actionId: String): List<ActionTodo> = repo.todos(actionId)
    fun addTodo(actionId: String, text: String) = mutate { if (text.isNotBlank()) repo.addTodo(actionId, text) }
    fun setTodo(todo: ActionTodo, done: Boolean) = mutate { repo.updateTodo(todo.idActionTypesTodos, todo.todo, done) }
    fun updateTodo(todo: ActionTodo, text: String) = mutate { repo.updateTodo(todo.idActionTypesTodos, text, null) }
    fun deleteTodo(id: Long) = mutate { repo.deleteTodo(id) }

    fun planNotes(idPlans: Long): List<PlanNote> = repo.planNotes(idPlans)
    fun addPlanNote(idPlans: Long, text: String) = mutate { repo.addPlanNote(idPlans, text) }
    fun updatePlanNote(id: Long, text: String) = mutate { repo.updatePlanNote(id, text) }
    fun deletePlanNote(id: Long) = mutate { repo.deletePlanNote(id) }

    fun planActionNotes(id: Long): List<PlanActionNote> = repo.planActionNotes(id)
    fun addPlanActionNote(id: Long, text: String) = mutate { repo.addPlanActionNote(id, text) }
    fun updatePlanActionNote(id: Long, text: String) = mutate { repo.updatePlanActionNote(id, text) }
    fun deletePlanActionNote(id: Long) = mutate { repo.deletePlanActionNote(id) }

    fun planActionTodos(id: Long): List<PlanActionTodo> = repo.planActionTodos(id)
    fun addPlanActionTodo(id: Long, text: String) = mutate { repo.addPlanActionTodo(id, text) }
    fun setPlanActionTodoDone(todo: PlanActionTodo, done: Boolean) = mutate { repo.setPlanActionTodoDone(todo.idPlanActionTypeTodos, done) }
    fun updatePlanActionTodo(todo: PlanActionTodo, text: String) = mutate { repo.updatePlanActionTodo(todo.idPlanActionTypeTodos, text) }
    fun deletePlanActionTodo(id: Long) = mutate { repo.deletePlanActionTodo(id) }

    suspend fun allIntervalsForStatistics(): List<TimeInterval> =
        withContext(Dispatchers.IO) {
            repo.allIntervalsForStatistics()
        }

    fun intervals(actionId: String): List<TimeInterval> = repo.intervals(actionId)
    fun statistics(actionId: String): ActionStatistics = repo.statistics(actionId)
    fun addInterval(actionId: String, startedAt: String, endedAt: String) = mutate { repo.addCompletedInterval(actionId, startedAt, endedAt) }
    fun updateInterval(id: Long, startedAt: String, endedAt: String) = mutate { repo.updateCompletedInterval(id, startedAt, endedAt) }
    fun deleteInterval(id: Long) = mutate { repo.deleteInterval(id) }

    fun saveRecurring(rule: RecurringRule) = mutate(refreshSchedule = true) {
        if (rule.recurrenceType == "one_time") {
            require(rule.runTime.isNotBlank()) { "A run time is required for schedules" }
            com.ndplanning.android.data.PlanningRepository.normalizeRunTime(rule.runTime)
            val day = LocalDate.parse(rule.startDay)
            val reminderArray = JSONArray(rule.remindersJson)
            val reminders = (0 until reminderArray.length()).map { reminderArray.getString(it) }
            repo.addPlanAction(day, rule.nodeId, rule.runTime, null, reminders)
        } else {
            validateRecurring(rule)
            if (rule.id == 0L) repo.addRecurringRule(rule) else repo.updateRecurringRule(rule.id, rule)
        }
    }

    fun deleteRecurring(id: Long) = mutate(refreshSchedule = true) { repo.deleteRecurringRule(id) }

    private fun runtimeMutated() {
        // UI state changes immediately; network work never runs on the click path.
        if (app.dropbox.isAuthenticated()) syncNow()
    }

    private fun mutateRuntime(block: () -> Unit) {
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { block() }
                runtimeMutated()
            } catch (error: Exception) {
                _message.value = error.message ?: error.javaClass.simpleName
            }
        }
    }

    fun startAction(actionId: String, planSeconds: Int? = null, stopPrevious: Boolean = false) = mutateRuntime {
        runtime.start(actionId, planSeconds, stopPrevious)
    }

    fun pauseRuntime() = mutateRuntime { runtime.pause() }
    fun resumeRuntime() = mutateRuntime { runtime.resume() }
    fun stopRuntime() = mutateRuntime { runtime.stop() }
    fun restartAction(actionId: String) = mutateRuntime { runtime.restart(actionId) }
    fun addRuntimeTime(seconds: Int) = mutateRuntime { runtime.addTime(seconds) }

    private fun parseReminders(text: String): List<String> = text
        .split(';', '\n', ',')
        .map(String::trim)
        .filter(String::isNotBlank)

    private fun validateRecurring(rule: RecurringRule) {
        require(rule.runTime.isNotBlank()) { "A run time is required for recurring schedules" }
        LocalDate.parse(rule.startDay)
        com.ndplanning.android.data.PlanningRepository.normalizeRunTime(rule.runTime)
        require(rule.intervalValue >= 1) { "Recurrence interval must be at least 1" }
        when (rule.recurrenceType) {
            "weekly" -> require(rule.weekday != null && rule.weekday in 0..6) { "Choose a weekday" }
            "monthly" -> require(rule.dayOfMonth != null && rule.dayOfMonth in 1..31) { "Choose a day of month" }
            "yearly" -> {
                require(rule.monthOfYear != null && rule.monthOfYear in 1..12) { "Choose a month" }
                require(rule.dayOfYearMonth != null && rule.dayOfYearMonth in 1..31) { "Choose a day" }
            }
        }
        runCatching { JSONArray(rule.remindersJson) }.getOrElse { throw IllegalArgumentException("Invalid reminders") }
    }

    private fun scheduleRefreshAsync(force: Boolean) {
        val now = System.currentTimeMillis()
        if (!force && now - lastScheduleRefreshAt < 60_000L) return
        lastScheduleRefreshAt = now
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { app.scheduleEngine.refresh() }
        }
    }

    private fun mutate(refreshSchedule: Boolean = false, block: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { block() }
                refresh()
                if (refreshSchedule) scheduleRefreshAsync(force = true)
                if (app.dropbox.isAuthenticated()) syncNow()
            } catch (error: Exception) {
                _message.value = error.message ?: error.javaClass.simpleName
            }
        }
    }
}

