package com.ndplanning.android.data

data class ActionType(
    val idActionTypes: String,
    val id: String,
    val parentId: String?,
    val title: String,
    val durationSeconds: Int,
    val plannedDurationSeconds: Int?,
    val position: Int,
    val archived: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

data class ActionNode(
    val action: ActionType,
    val children: List<ActionNode> = emptyList(),
    val depth: Int = 0,
)

data class ActionTodo(
    val idActionTypesTodos: Long,
    val idActionTypes: String,
    val todo: String,
    val isDone: Boolean,
    val createdAt: String,
    val updatedAt: String,
)

data class ActionPanelTodo(
    val idActionTypes: String,
    val todoSource: String,
    val todoId: Long,
    val todo: String,
    val isDone: Boolean,
    val day: String?,
    val runTime: String?,
)

data class PlanAction(
    val idPlanActionTypes: Long,
    val idPlans: Long,
    val idActionTypes: String,
    val actionName: String,
    val runTime: String?,
    val durationSeconds: Int,
    val lastRunAt: String?,
    val handledAt: String?,
    val position: Int,
    val createdAt: String,
    val updatedAt: String,
)

data class DayPlan(
    val idPlans: Long,
    val day: String,
    val createdAt: String,
    val updatedAt: String,
    val actions: List<PlanAction>,
)

data class TimeInterval(
    val id: Long,
    val nodeId: String,
    val startedAt: String,
    val endedAt: String?,
    val durationSeconds: Int?,
)

data class RuntimeState(
    val active: Boolean,
    val rootNodeId: String?,
    val queue: List<String>,
    val queueIndex: Int,
    val remainingSeconds: Int,
    val elapsedSeconds: Int,
    val paused: Boolean,
    val lastHeartbeat: String?,
) {
    val currentNodeId: String?
        get() = queue.getOrNull(queueIndex)
}

data class ActionStatistics(
    val actionId: String,
    val totalSeconds: Long,
    val intervalCount: Int,
    val lastStartedAt: String?,
)

data class RecurringRule(
    val id: Long,
    val nodeId: String,
    val startDay: String,
    val runTime: String,
    val recurrenceType: String,
    val intervalValue: Int,
    val weekday: Int?,
    val dayOfMonth: Int?,
    val monthOfYear: Int?,
    val dayOfYearMonth: Int?,
    val remindersJson: String,
    val enabled: Boolean,
    val createdAt: String,
    val updatedAt: String,
    val durationSeconds: Int? = null,
)

data class PlanReminder(
    val idPlanActionTypeReminders: Long,
    val idPlanActionTypes: Long,
    val reminderSpec: String,
    val position: Int,
    val firedAt: String?,
    val createdAt: String,
    val updatedAt: String,
)

data class PlanNote(
    val idPlanNotes: Long,
    val idPlans: Long,
    val note: String,
    val position: Int,
    val createdAt: String,
    val updatedAt: String,
)

data class PlanActionNote(
    val idPlanActionNotes: Long,
    val idPlanActionTypes: Long,
    val note: String,
    val position: Int,
    val createdAt: String,
    val updatedAt: String,
)

data class PlanActionTodo(
    val idPlanActionTypeTodos: Long,
    val idPlanActionTypes: Long,
    val todo: String,
    val isDone: Boolean,
    val position: Int,
    val createdAt: String,
    val updatedAt: String,
)

data class PausedRun(
    val rootNodeId: String,
    val queue: List<String>,
    val queueIndex: Int,
    val remainingSeconds: Int,
    val elapsedSeconds: Int,
    val savedAt: String,
)

