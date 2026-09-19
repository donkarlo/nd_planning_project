package com.ndplanning.android.data

import android.content.ContentValues
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import com.ndplanning.android.util.TimeUtil
import org.json.JSONArray
import java.time.Duration
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.temporal.ChronoUnit
import java.util.UUID
import kotlin.math.abs

/** Canonical data access boundary shared by Android UI, runtime, scheduler and sync. */
class PlanningRepository(private val database: PlanningDatabase) {
    private fun db(): SQLiteDatabase = database.writableDatabase

    fun actionTypes(includeArchived: Boolean = false): List<ActionType> {
        val where = if (includeArchived) "" else "WHERE archived=0"
        return db().rawQuery(
            "SELECT id_action_types,id,parent_id,title,duration_seconds,planned_duration_seconds,position,archived,created_at,updated_at FROM action_types $where ORDER BY parent_id,position,title",
            null,
        ).use { c -> buildList { while (c.moveToNext()) add(c.actionType()) } }
    }

    fun actionTree(filter: String = ""): List<ActionNode> {
        val rows = actionTypes(false)
        val byParent = rows.groupBy { it.parentId }
        fun build(parent: String?, depth: Int): List<ActionNode> = byParent[parent].orEmpty()
            .sortedBy { it.position }
            .map { action -> ActionNode(action, build(action.id, depth + 1), depth) }
        val roots = build(null, 0)
        if (filter.isBlank()) return roots
        val needle = filter.trim().lowercase()
        fun prune(node: ActionNode): ActionNode? {
            val selfMatches =
                needle in node.action.title.lowercase()

            // If the parent itself matches, keep its complete subtree.
            // Example: searching "phd" shows Phd and ALL its children.
            if (selfMatches) return node

            // Otherwise preserve only branches leading to a match.
            val children =
                node.children.mapNotNull(::prune)

            return if (children.isNotEmpty()) {
                node.copy(children = children)
            } else {
                null
            }
        }
        return roots.mapNotNull(::prune)
    }

    fun action(idOrCanonical: String): ActionType? = db().rawQuery(
        "SELECT id_action_types,id,parent_id,title,duration_seconds,planned_duration_seconds,position,archived,created_at,updated_at FROM action_types WHERE id=? OR id_action_types=? LIMIT 1",
        arrayOf(idOrCanonical, idOrCanonical),
    ).use { if (it.moveToFirst()) it.actionType() else null }

    fun addActionType(name: String, parentId: String?, durationSeconds: Int?): ActionType {
        require(name.trim().isNotEmpty()) { "Action Type name cannot be empty" }
        val canonical = UUID.randomUUID().toString().replace("-", "")
        val stableParent = parentId?.let { action(it)?.id ?: error("Unknown parent") }
        val stamp = TimeUtil.nowText()
        db().insertOrThrow("action_types", null, ContentValues().apply {
            put("id_action_types", canonical)
            put("id", canonical)
            if (stableParent == null) putNull("parent_id") else put("parent_id", stableParent)
            put("title", name.trim())
            put("duration_seconds", durationSeconds ?: 0)
            if (durationSeconds == null) putNull("planned_duration_seconds") else put("planned_duration_seconds", durationSeconds)
            put("position", nextPosition("action_types", "parent_id", stableParent))
            put("archived", 0)
            put("created_at", stamp)
            put("updated_at", stamp)
        })
        return action(canonical)!!
    }

    fun updateActionType(id: String, name: String, durationSeconds: Int?) {
        require(name.trim().isNotEmpty()) { "Action Type name cannot be empty" }
        val canonical = action(id)?.idActionTypes ?: return
        db().update("action_types", ContentValues().apply {
            put("title", name.trim())
            put("duration_seconds", durationSeconds ?: 0)
            if (durationSeconds == null) putNull("planned_duration_seconds") else put("planned_duration_seconds", durationSeconds)
            put("updated_at", TimeUtil.nowText())
        }, "id_action_types=?", arrayOf(canonical))
    }

    fun deleteActionType(id: String) {
        val canonical = action(id)?.idActionTypes ?: return
        db().delete("action_types", "id_action_types=?", arrayOf(canonical))
    }

    fun moveActionType(id: String, newParentId: String?, newPosition: Int) {
        val row = action(id) ?: return
        val target = newParentId?.let { action(it) }
        require(row.idActionTypes != target?.idActionTypes) { "An action cannot be its own parent" }
        require(target == null || target.idActionTypes !in subtreeIds(row.idActionTypes).toSet()) {
            "Cannot move an action into its own subtree"
        }
        val stableParent = target?.id
        db().beginTransaction()
        try {
            val oldParent = row.parentId
            db().update("action_types", ContentValues().apply {
                if (stableParent == null) putNull("parent_id") else put("parent_id", stableParent)
                put("updated_at", TimeUtil.nowText())
            }, "id_action_types=?", arrayOf(row.idActionTypes))
            normalizeActionPositions(oldParent)
            val siblings = actionTypes(false).filter { it.parentId == stableParent && it.idActionTypes != row.idActionTypes }
                .sortedBy { it.position }.map { it.idActionTypes }.toMutableList()
            siblings.add(newPosition.coerceIn(0, siblings.size), row.idActionTypes)
            siblings.forEachIndexed { index, canonical ->
                db().update("action_types", ContentValues().apply {
                    put("position", index); put("updated_at", TimeUtil.nowText())
                }, "id_action_types=?", arrayOf(canonical))
            }
            db().setTransactionSuccessful()
        } finally { db().endTransaction() }
    }

    private fun normalizeActionPositions(parentStable: String?) {
        val rows = actionTypes(false).filter { it.parentId == parentStable }.sortedBy { it.position }
        rows.forEachIndexed { index, row ->
            if (row.position != index) db().update("action_types", ContentValues().apply {
                put("position", index); put("updated_at", TimeUtil.nowText())
            }, "id_action_types=?", arrayOf(row.idActionTypes))
        }
    }

    fun subtreeIds(id: String): List<String> {
        val start = action(id) ?: return emptyList()
        val rows = actionTypes(true)
        val byParent = rows.groupBy { it.parentId }
        val result = mutableListOf<String>()
        fun visit(current: ActionType) {
            result += current.idActionTypes
            byParent[current.id].orEmpty().sortedBy { it.position }.forEach(::visit)
        }
        visit(start)
        return result
    }

    fun executionSequence(id: String): List<String> {
        val row = action(id) ?: return emptyList()
        val children = actionTypes(false).filter { it.parentId == row.id }.sortedBy { it.position }
        return if (children.isEmpty()) listOf(row.idActionTypes) else children.flatMap { executionSequence(it.idActionTypes) }
    }

    fun topRootId(id: String): String? {
        var row = action(id) ?: return null
        val seen = mutableSetOf<String>()
        while (row.parentId != null && seen.add(row.idActionTypes)) {
            row = action(row.parentId!!) ?: break
        }
        return row.idActionTypes
    }

    fun continuationSequence(id: String): Pair<String?, List<String>> {
        val clicked = action(id) ?: return null to emptyList()
        val root = topRootId(clicked.idActionTypes) ?: return null to emptyList()
        val queue = executionSequence(root)
        if (queue.isEmpty()) return root to listOf(clicked.idActionTypes)
        val clickedSubtree = subtreeIds(clicked.idActionTypes).toSet()
        val start = queue.indexOfFirst { it in clickedSubtree }.takeIf { it >= 0 } ?: 0
        return root to queue.drop(start)
    }

    fun todos(actionId: String): List<ActionTodo> {
        val canonical = action(actionId)?.idActionTypes ?: actionId
        return db().rawQuery(
            "SELECT id_action_types_todos,id_action_types,todo,is_done,created_at,updated_at FROM action_types_todos WHERE id_action_types=? ORDER BY is_done,id_action_types_todos",
            arrayOf(canonical),
        ).use { c -> buildList { while (c.moveToNext()) add(c.todo()) } }
    }

    fun actionPanelTodos(): List<ActionPanelTodo> = db().rawQuery(
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
        """.trimIndent(),
        null,
    ).use { cursor ->
        buildList {
            while (cursor.moveToNext()) {
                add(cursor.actionPanelTodo())
            }
        }
    }

    fun addTodo(actionId: String, text: String): Long {
        require(text.trim().isNotEmpty()) { "Todo cannot be empty" }
        val canonical = action(actionId)?.idActionTypes ?: error("Unknown action")
        val id = nextNegativeId("action_types_todos", "id_action_types_todos")
        val stamp = TimeUtil.nowText()
        db().insertOrThrow("action_types_todos", null, ContentValues().apply {
            put("id_action_types_todos", id); put("id_action_types", canonical); put("todo", text.trim())
            put("is_done", 0); put("created_at", stamp); put("updated_at", stamp)
        })
        return id
    }

    fun updateTodo(id: Long, text: String, done: Boolean? = null) {
        require(text.trim().isNotEmpty()) { "Todo cannot be empty" }
        db().update("action_types_todos", ContentValues().apply {
            put("todo", text.trim()); done?.let { put("is_done", if (it) 1 else 0) }; put("updated_at", TimeUtil.nowText())
        }, "id_action_types_todos=?", arrayOf(id.toString()))
    }

    fun deleteTodo(id: Long) { db().delete("action_types_todos", "id_action_types_todos=?", arrayOf(id.toString())) }

    fun plansBetween(firstDay: LocalDate, lastDay: LocalDate): List<DayPlan> = db().rawQuery(
        "SELECT id_plans,day,created_at,updated_at FROM plans WHERE day BETWEEN ? AND ? ORDER BY day",
        arrayOf(firstDay.toString(), lastDay.toString()),
    ).use { c -> buildList {
        while (c.moveToNext()) {
            val id = c.getLong(0)
            add(DayPlan(id, c.getString(1), c.getString(2), c.getString(3), planActions(id)))
        }
    } }

    fun dayPlan(day: LocalDate): DayPlan? = db().rawQuery(
        "SELECT id_plans,day,created_at,updated_at FROM plans WHERE day=? LIMIT 1", arrayOf(day.toString()),
    ).use { c -> if (!c.moveToFirst()) null else {
        val id = c.getLong(0); DayPlan(id, c.getString(1), c.getString(2), c.getString(3), planActions(id))
    } }

    fun planActions(idPlans: Long): List<PlanAction> = db().rawQuery(
        "SELECT id_plan_action_types,id_plans,id_action_types,action_name,run_time,duration_seconds,last_run_at,handled_at,position,created_at,updated_at FROM plan_action_types WHERE id_plans=? ORDER BY position,id_plan_action_types",
        arrayOf(idPlans.toString()),
    ).use { c -> buildList { while (c.moveToNext()) add(c.planAction()) } }

    fun addPlanAction(
        day: LocalDate,
        actionId: String,
        runTime: String?,
        durationSeconds: Int?,
        reminders: List<String> = emptyList(),
    ): Long {
        val action =
            action(actionId)
                ?: error("Unknown action")

        val stamp = TimeUtil.nowText()

        val normalizedRunTime =
            runTime
                ?.takeIf { it.isNotBlank() }
                ?.let(::normalizeRunTime)

        db().beginTransaction()

        try {
            val idPlans =
                ensurePlanDay(day, stamp)

            // One scheduled occurrence has one logical identity:
            // day + Action Type + run time.
            val existingId =
                db().rawQuery(
                    """
                    SELECT id_plan_action_types
                    FROM plan_action_types
                    WHERE id_plans=?
                      AND id_action_types=?
                      AND COALESCE(run_time,'')=?
                    ORDER BY updated_at DESC,
                             id_plan_action_types
                    LIMIT 1
                    """.trimIndent(),
                    arrayOf(
                        idPlans.toString(),
                        action.idActionTypes,
                        normalizedRunTime ?: "",
                    ),
                ).use { cursor ->
                    if (cursor.moveToFirst()) {
                        cursor.getLong(0)
                    } else {
                        null
                    }
                }

            if (existingId != null) {
                db().update(
                    "plan_action_types",
                    ContentValues().apply {
                        put("action_name", action.title)

                        if (normalizedRunTime == null) {
                            putNull("run_time")
                        } else {
                            put(
                                "run_time",
                                normalizedRunTime,
                            )
                        }

                        put(
                            "duration_seconds",
                            durationSeconds
                                ?: action
                                    .plannedDurationSeconds
                                ?: 0,
                        )

                        // Re-adding the same occurrence means updating
                        // that occurrence, not creating another one.
                        putNull("last_run_at")
                        putNull("handled_at")
                        put("updated_at", stamp)
                    },
                    "id_plan_action_types=?",
                    arrayOf(existingId.toString()),
                )

                db().delete(
                    "plan_action_type_reminders",
                    "id_plan_action_types=?",
                    arrayOf(existingId.toString()),
                )

                reminders
                    .map(String::trim)
                    .filter(String::isNotEmpty)
                    .forEach {
                        addReminderInternal(
                            existingId,
                            it,
                        )
                    }

                db().setTransactionSuccessful()
                return existingId
            }

            val id =
                nextNegativeId(
                    "plan_action_types",
                    "id_plan_action_types",
                )

            db().insertOrThrow(
                "plan_action_types",
                null,
                ContentValues().apply {
                    put(
                        "id_plan_action_types",
                        id,
                    )
                    put("id_plans", idPlans)
                    put(
                        "id_action_types",
                        action.idActionTypes,
                    )
                    put(
                        "action_name",
                        action.title,
                    )

                    if (normalizedRunTime == null) {
                        putNull("run_time")
                    } else {
                        put(
                            "run_time",
                            normalizedRunTime,
                        )
                    }

                    put(
                        "duration_seconds",
                        durationSeconds
                            ?: action
                                .plannedDurationSeconds
                            ?: 0,
                    )

                    putNull("last_run_at")
                    putNull("handled_at")

                    put(
                        "position",
                        nextPosition(
                            "plan_action_types",
                            "id_plans",
                            idPlans.toString(),
                        ),
                    )

                    put("created_at", stamp)
                    put("updated_at", stamp)
                },
            )

            reminders
                .map(String::trim)
                .filter(String::isNotEmpty)
                .forEach {
                    addReminderInternal(id, it)
                }

            db().setTransactionSuccessful()
            return id

        } finally {
            db().endTransaction()
        }
    }

    fun updatePlanAction(id: Long, day: LocalDate, runTime: String?, durationSeconds: Int?) {
        val existing = planAction(id) ?: return
        val stamp = TimeUtil.nowText()
        val oldPlan = existing.idPlans
        val targetPlan = ensurePlanDay(day, stamp)
        db().beginTransaction()
        try {
            db().update("plan_action_types", ContentValues().apply {
                put("id_plans", targetPlan)
                if (runTime.isNullOrBlank()) putNull("run_time") else put("run_time", normalizeRunTime(runTime))
                put("duration_seconds", durationSeconds ?: 0)
                put("updated_at", stamp)
            }, "id_plan_action_types=?", arrayOf(id.toString()))
            normalizePlanPositions(oldPlan)
            normalizePlanPositions(targetPlan)
            removeEmptyPlans()
            db().setTransactionSuccessful()
        } finally { db().endTransaction() }
    }

    fun movePlanAction(id: Long, day: LocalDate, newPosition: Int) {
        val row = planAction(id) ?: return
        val target = ensurePlanDay(day, TimeUtil.nowText())
        db().beginTransaction()
        try {
            db().update("plan_action_types", ContentValues().apply {
                put("id_plans", target); put("updated_at", TimeUtil.nowText())
            }, "id_plan_action_types=?", arrayOf(id.toString()))
            normalizePlanPositions(row.idPlans)
            val siblings = planActions(target).filter { it.idPlanActionTypes != id }.map { it.idPlanActionTypes }.toMutableList()
            siblings.add(newPosition.coerceIn(0, siblings.size), id)
            siblings.forEachIndexed { index, value -> db().update("plan_action_types", ContentValues().apply {
                put("position", index); put("updated_at", TimeUtil.nowText())
            }, "id_plan_action_types=?", arrayOf(value.toString())) }
            removeEmptyPlans()
            db().setTransactionSuccessful()
        } finally { db().endTransaction() }
    }

    fun deletePlanAction(id: Long) {
        val planId = planAction(id)?.idPlans
        db().delete("plan_action_types", "id_plan_action_types=?", arrayOf(id.toString()))
        planId?.let(::normalizePlanPositions)
        removeEmptyPlans()
    }

    fun planAction(id: Long): PlanAction? = db().rawQuery(
        "SELECT id_plan_action_types,id_plans,id_action_types,action_name,run_time,duration_seconds,last_run_at,handled_at,position,created_at,updated_at FROM plan_action_types WHERE id_plan_action_types=?",
        arrayOf(id.toString()),
    ).use { if (it.moveToFirst()) it.planAction() else null }

    fun planExistsForActionDay(actionId: String, day: LocalDate): Boolean {
        val canonical = action(actionId)?.idActionTypes ?: actionId
        return db().rawQuery(
            "SELECT 1 FROM plan_action_types a JOIN plans p ON p.id_plans=a.id_plans WHERE a.id_action_types=? AND p.day=? LIMIT 1",
            arrayOf(canonical, day.toString()),
        ).use { it.moveToFirst() }
    }

    fun addReminder(planActionId: Long, spec: String): Long = addReminderInternal(planActionId, spec)

    private fun addReminderInternal(planActionId: Long, spec: String): Long {
        require(spec.trim().isNotEmpty()) { "Reminder cannot be empty" }
        require(planAction(planActionId) != null) { "Unknown plan action" }
        val id = nextNegativeId("plan_action_type_reminders", "id_plan_action_type_reminders")
        val stamp = TimeUtil.nowText()
        db().insertOrThrow("plan_action_type_reminders", null, ContentValues().apply {
            put("id_plan_action_type_reminders", id); put("id_plan_action_types", planActionId); put("reminder_spec", spec.trim())
            put("position", nextPosition("plan_action_type_reminders", "id_plan_action_types", planActionId.toString()))
            putNull("fired_at"); put("created_at", stamp); put("updated_at", stamp)
        })
        return id
    }

    fun replaceReminders(planActionId: Long, specs: List<String>) {
        db().beginTransaction()
        try {
            db().delete("plan_action_type_reminders", "id_plan_action_types=?", arrayOf(planActionId.toString()))
            specs.map(String::trim).filter(String::isNotEmpty).forEach { addReminderInternal(planActionId, it) }
            db().setTransactionSuccessful()
        } finally { db().endTransaction() }
    }

    fun reminders(planActionId: Long): List<String> = reminderRows(planActionId).map { it.reminderSpec }

    fun reminderRows(planActionId: Long): List<PlanReminder> = db().rawQuery(
        "SELECT id_plan_action_type_reminders,id_plan_action_types,reminder_spec,position,fired_at,created_at,updated_at FROM plan_action_type_reminders WHERE id_plan_action_types=? ORDER BY position,id_plan_action_type_reminders",
        arrayOf(planActionId.toString()),
    ).use { c -> buildList { while (c.moveToNext()) add(c.planReminder()) } }

    fun deleteReminder(id: Long) { db().delete("plan_action_type_reminders", "id_plan_action_type_reminders=?", arrayOf(id.toString())) }

    fun markReminderFired(id: Long) {
        db().update("plan_action_type_reminders", ContentValues().apply {
            put("fired_at", TimeUtil.nowText()); put("updated_at", TimeUtil.nowText())
        }, "id_plan_action_type_reminders=?", arrayOf(id.toString()))
    }

    fun markPlanHandled(id: Long, ran: Boolean) {
        db().update("plan_action_types", ContentValues().apply {
            put("handled_at", TimeUtil.nowText()); if (ran) put("last_run_at", TimeUtil.nowText()); put("updated_at", TimeUtil.nowText())
        }, "id_plan_action_types=?", arrayOf(id.toString()))
    }

    fun planNotes(idPlans: Long): List<PlanNote> = db().rawQuery(
        "SELECT id_plan_notes,id_plans,note,position,created_at,updated_at FROM plan_notes WHERE id_plans=? ORDER BY position,id_plan_notes",
        arrayOf(idPlans.toString()),
    ).use { c -> buildList { while (c.moveToNext()) add(c.planNote()) } }

    fun addPlanNote(idPlans: Long, text: String): Long {
        require(text.trim().isNotEmpty()) { "Note cannot be empty" }
        val id = nextNegativeId("plan_notes", "id_plan_notes"); val stamp = TimeUtil.nowText()
        db().insertOrThrow("plan_notes", null, ContentValues().apply {
            put("id_plan_notes", id); put("id_plans", idPlans); put("note", text.trim())
            put("position", nextPosition("plan_notes", "id_plans", idPlans.toString())); put("created_at", stamp); put("updated_at", stamp)
        }); return id
    }

    fun updatePlanNote(id: Long, text: String) {
        require(text.trim().isNotEmpty()) { "Note cannot be empty" }
        db().update("plan_notes", ContentValues().apply { put("note", text.trim()); put("updated_at", TimeUtil.nowText()) }, "id_plan_notes=?", arrayOf(id.toString()))
    }
    fun deletePlanNote(id: Long) { db().delete("plan_notes", "id_plan_notes=?", arrayOf(id.toString())); removeEmptyPlans() }

    fun planActionNotes(idPlanActionTypes: Long): List<PlanActionNote> = db().rawQuery(
        "SELECT id_plan_action_notes,id_plan_action_types,note,position,created_at,updated_at FROM plan_action_notes WHERE id_plan_action_types=? ORDER BY position,id_plan_action_notes",
        arrayOf(idPlanActionTypes.toString()),
    ).use { c -> buildList { while (c.moveToNext()) add(c.planActionNote()) } }

    fun addPlanActionNote(idPlanActionTypes: Long, text: String): Long {
        require(text.trim().isNotEmpty()) { "Note cannot be empty" }
        val id = nextNegativeId("plan_action_notes", "id_plan_action_notes"); val stamp = TimeUtil.nowText()
        db().insertOrThrow("plan_action_notes", null, ContentValues().apply {
            put("id_plan_action_notes", id); put("id_plan_action_types", idPlanActionTypes); put("note", text.trim())
            put("position", nextPosition("plan_action_notes", "id_plan_action_types", idPlanActionTypes.toString())); put("created_at", stamp); put("updated_at", stamp)
        }); return id
    }
    fun updatePlanActionNote(id: Long, text: String) {
        require(text.trim().isNotEmpty()) { "Note cannot be empty" }
        db().update("plan_action_notes", ContentValues().apply { put("note", text.trim()); put("updated_at", TimeUtil.nowText()) }, "id_plan_action_notes=?", arrayOf(id.toString()))
    }
    fun deletePlanActionNote(id: Long) { db().delete("plan_action_notes", "id_plan_action_notes=?", arrayOf(id.toString())) }

    fun planActionTodos(idPlanActionTypes: Long): List<PlanActionTodo> = db().rawQuery(
        "SELECT id_plan_action_type_todos,id_plan_action_types,todo,is_done,position,created_at,updated_at FROM plan_action_type_todos WHERE id_plan_action_types=? ORDER BY position,id_plan_action_type_todos",
        arrayOf(idPlanActionTypes.toString()),
    ).use { c -> buildList { while (c.moveToNext()) add(c.planActionTodo()) } }

    fun addPlanActionTodo(idPlanActionTypes: Long, text: String): Long {
        require(text.trim().isNotEmpty()) { "Todo cannot be empty" }
        val id = nextNegativeId("plan_action_type_todos", "id_plan_action_type_todos"); val stamp = TimeUtil.nowText()
        db().insertOrThrow("plan_action_type_todos", null, ContentValues().apply {
            put("id_plan_action_type_todos", id); put("id_plan_action_types", idPlanActionTypes); put("todo", text.trim()); put("is_done", 0)
            put("position", nextPosition("plan_action_type_todos", "id_plan_action_types", idPlanActionTypes.toString())); put("created_at", stamp); put("updated_at", stamp)
        }); return id
    }
    fun setPlanActionTodoDone(id: Long, done: Boolean) {
        db().update("plan_action_type_todos", ContentValues().apply { put("is_done", if (done) 1 else 0); put("updated_at", TimeUtil.nowText()) }, "id_plan_action_type_todos=?", arrayOf(id.toString()))
    }
    fun updatePlanActionTodo(id: Long, text: String) {
        require(text.trim().isNotEmpty()) { "Todo cannot be empty" }
        db().update("plan_action_type_todos", ContentValues().apply { put("todo", text.trim()); put("updated_at", TimeUtil.nowText()) }, "id_plan_action_type_todos=?", arrayOf(id.toString()))
    }
    fun deletePlanActionTodo(id: Long) { db().delete("plan_action_type_todos", "id_plan_action_type_todos=?", arrayOf(id.toString())) }

    private data class StatisticsSegment(
        val id: Long,
        val nodeId: String,
        val start: OffsetDateTime,
        var end: OffsetDateTime,
    )

    private fun canonicalStatisticsIntervals():
        List<TimeInterval> {

        val now =
            OffsetDateTime.now()

        val raw =
            db().rawQuery(
                """
                SELECT
                    id,
                    node_id,
                    started_at,
                    ended_at,
                    duration_seconds
                FROM intervals
                ORDER BY started_at,id
                """.trimIndent(),
                null,
            ).use { cursor ->
                buildList {
                    while (
                        cursor.moveToNext()
                    ) {
                        add(
                            cursor.interval()
                        )
                    }
                }
            }

        val parsed =
            raw.mapNotNull { item ->
                val start =
                    runCatching {
                        OffsetDateTime.parse(
                            item.startedAt
                        )
                    }.getOrNull()
                        ?: return@mapNotNull null

                val end =
                    if (
                        item.endedAt == null
                    ) {
                        now
                    } else {
                        runCatching {
                            OffsetDateTime.parse(
                                item.endedAt
                            )
                        }.getOrNull()
                            ?: return@mapNotNull null
                    }

                if (!end.isAfter(start)) {
                    return@mapNotNull null
                }

                StatisticsSegment(
                    item.id,
                    item.nodeId,
                    start,
                    end,
                )
            }.sortedWith(
                compareBy<StatisticsSegment> {
                    it.start
                }.thenBy {
                    it.id
                }
            )

        val merged =
            mutableListOf<
                StatisticsSegment
            >()

        parsed.forEach { segment ->
            val previous =
                merged.lastOrNull()

            val duplicate =
                previous != null &&
                    previous.nodeId ==
                        segment.nodeId &&
                    abs(
                        Duration.between(
                            previous.start,
                            segment.start,
                        ).seconds
                    ) <= 5L &&
                    segment.start
                        .isBefore(previous.end)

            if (duplicate) {
                if (
                    segment.end
                        .isBefore(previous.end)
                ) {
                    previous.end =
                        segment.end
                }
            } else {
                merged += segment
            }
        }

        return merged.mapIndexedNotNull {
                index,
                segment ->

            var end =
                segment.end

            if (
                index + 1 <
                    merged.size
            ) {
                val nextStart =
                    merged[
                        index + 1
                    ].start

                if (
                    nextStart
                        .isBefore(end)
                ) {
                    end =
                        nextStart
                }
            }

            if (
                !end.isAfter(
                    segment.start
                )
            ) {
                null
            } else {
                TimeInterval(
                    id = segment.id,
                    nodeId =
                        segment.nodeId,
                    startedAt =
                        segment.start
                            .toString(),
                    endedAt =
                        end.toString(),
                    durationSeconds =
                        Duration.between(
                            segment.start,
                            end,
                        ).seconds
                            .coerceAtMost(
                                Int.MAX_VALUE
                                    .toLong()
                            )
                            .toInt(),
                )
            }
        }
    }

    fun intervals(
        actionId: String,
    ): List<TimeInterval> {
        val ids =
            subtreeIds(actionId)
                .toSet()

        if (ids.isEmpty()) {
            return emptyList()
        }

        return canonicalStatisticsIntervals()
            .filter {
                it.nodeId in ids
            }
            .sortedByDescending {
                it.startedAt
            }
    }

    fun allIntervalsForStatistics():
        List<TimeInterval> =
        canonicalStatisticsIntervals()

    fun statistics(
        actionId: String,
    ): ActionStatistics {
        val values =
            intervals(actionId)

        return ActionStatistics(
            actionId = actionId,
            totalSeconds =
                values.sumOf {
                    (
                        it.durationSeconds
                            ?: 0
                    ).toLong()
                },
            intervalCount =
                values.size,
            lastStartedAt =
                values.maxOfOrNull {
                    it.startedAt
                },
        )
    }

    fun addCompletedInterval(
        actionId: String,
        startedAt: String,
        endedAt: String,
    ): Long {
        val canonical =
            action(actionId)?.idActionTypes
                ?: error("Unknown Action Type")

        val start =
            OffsetDateTime.parse(startedAt)

        val end =
            OffsetDateTime.parse(endedAt)

        require(end.isAfter(start)) {
            "End time must be after start time"
        }

        val seconds =
            Duration.between(
                start,
                end,
            ).seconds
                .coerceAtLeast(0L)
                .coerceAtMost(
                    Int.MAX_VALUE.toLong()
                )
                .toInt()

        val id =
            nextNegativeId(
                "intervals",
                "id",
            )

        db().insertOrThrow(
            "intervals",
            null,
            ContentValues().apply {
                put("id", id)
                put(
                    "node_id",
                    canonical,
                )
                put(
                    "started_at",
                    startedAt,
                )
                put(
                    "ended_at",
                    endedAt,
                )
                put(
                    "duration_seconds",
                    seconds,
                )
            },
        )

        return id
    }

    fun updateCompletedInterval(
        id: Long,
        startedAt: String,
        endedAt: String,
    ) {
        val start =
            OffsetDateTime.parse(startedAt)

        val end =
            OffsetDateTime.parse(endedAt)

        require(end.isAfter(start)) {
            "End time must be after start time"
        }

        val seconds =
            Duration.between(
                start,
                end,
            ).seconds
                .coerceAtLeast(0L)
                .coerceAtMost(
                    Int.MAX_VALUE.toLong()
                )
                .toInt()

        db().update(
            "intervals",
            ContentValues().apply {
                put(
                    "started_at",
                    startedAt,
                )
                put(
                    "ended_at",
                    endedAt,
                )
                put(
                    "duration_seconds",
                    seconds,
                )
            },
            "id=?",
            arrayOf(id.toString()),
        )
    }

    fun deleteInterval(
        id: Long,
    ) {
        db().delete(
            "intervals",
            "id=?",
            arrayOf(id.toString()),
        )
    }

    fun recoverOpenIntervals() {
        val now = TimeUtil.nowText()
        db().rawQuery("SELECT id,started_at FROM intervals WHERE ended_at IS NULL", null).use { c ->
            while (c.moveToNext()) {
                val seconds = TimeUtil.elapsedSeconds(c.getString(1), now).coerceAtLeast(0)
                db().update("intervals", ContentValues().apply { put("ended_at", now); put("duration_seconds", seconds) }, "id=?", arrayOf(c.getLong(0).toString()))
            }
        }
    }

    fun runtimeState(): RuntimeState = db().rawQuery(
        "SELECT active,root_node_id,queue_json,queue_index,remaining_seconds,elapsed_seconds,paused,last_heartbeat FROM runtime_state WHERE id=1", null,
    ).use { c ->
        if (!c.moveToFirst()) RuntimeState(false, null, emptyList(), 0, 0, 0, false, null) else {
            val queue = runCatching { JSONArray(c.getString(2)).let { a -> (0 until a.length()).map { a.getString(it) } } }.getOrDefault(emptyList())
            RuntimeState(c.getInt(0) != 0, c.nullableString(1), queue, c.getInt(3), c.getInt(4), c.getInt(5), c.getInt(6) != 0, c.nullableString(7))
        }
    }

    fun saveRuntime(state: RuntimeState) {
        db().update("runtime_state", ContentValues().apply {
            put("active", if (state.active) 1 else 0); if (state.rootNodeId == null) putNull("root_node_id") else put("root_node_id", state.rootNodeId)
            put("queue_json", JSONArray(state.queue).toString()); put("queue_index", state.queueIndex); put("remaining_seconds", state.remainingSeconds)
            put("elapsed_seconds", state.elapsedSeconds); put("paused", if (state.paused) 1 else 0)
            if (state.lastHeartbeat == null) putNull("last_heartbeat") else put("last_heartbeat", state.lastHeartbeat)
        }, "id=1", null)
    }

    fun savePausedRun(state: RuntimeState) {
        val root = state.rootNodeId ?: return
        db().insertWithOnConflict("paused_runs", null, ContentValues().apply {
            put("root_node_id", root); put("queue_json", JSONArray(state.queue).toString()); put("queue_index", state.queueIndex)
            put("remaining_seconds", state.remainingSeconds); put("elapsed_seconds", state.elapsedSeconds); put("saved_at", TimeUtil.nowText())
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun pausedRun(rootId: String): PausedRun? = db().rawQuery(
        "SELECT root_node_id,queue_json,queue_index,remaining_seconds,elapsed_seconds,saved_at FROM paused_runs WHERE root_node_id=?",
        arrayOf(rootId),
    ).use { c -> if (!c.moveToFirst()) null else {
        val queue = runCatching { JSONArray(c.getString(1)).let { a -> (0 until a.length()).map { a.getString(it) } } }.getOrDefault(emptyList())
        PausedRun(c.getString(0), queue, c.getInt(2), c.getInt(3), c.getInt(4), c.getString(5))
    } }
    fun deletePausedRun(rootId: String) { db().delete("paused_runs", "root_node_id=?", arrayOf(rootId)) }

    fun logEvent(nodeId: String?, event: String) {
        val id = nextNegativeId("events", "id")
        db().insert("events", null, ContentValues().apply {
            put("id", id); put("occurred_at", TimeUtil.nowText()); if (nodeId == null) putNull("node_id") else put("node_id", nodeId); put("event", event)
        })
    }

    fun openInterval(
        nodeId: String,
    ): Long {
        val canonical =
            action(nodeId)?.idActionTypes
                ?: nodeId

        val stamp =
            TimeUtil.nowText()

        val database =
            db()

        database.beginTransaction()

        try {
            val existing =
                database.rawQuery(
                    """
                    SELECT id
                    FROM intervals
                    WHERE node_id=?
                      AND ended_at IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """.trimIndent(),
                    arrayOf(canonical),
                ).use {
                    if (it.moveToFirst()) {
                        it.getLong(0)
                    } else {
                        null
                    }
                }

            if (existing != null) {
                database.setTransactionSuccessful()
                return existing
            }

            // One global Planning runtime means one globally open interval.
            val openRows =
                database.rawQuery(
                    """
                    SELECT id,started_at
                    FROM intervals
                    WHERE ended_at IS NULL
                    """.trimIndent(),
                    null,
                ).use { cursor ->
                    buildList {
                        while (
                            cursor.moveToNext()
                        ) {
                            add(
                                cursor.getLong(0) to
                                    cursor.getString(1)
                            )
                        }
                    }
                }

            openRows.forEach {
                    (id, startedAt) ->

                val seconds =
                    TimeUtil.elapsedSeconds(
                        startedAt,
                        stamp,
                    ).coerceAtLeast(0)

                database.update(
                    "intervals",
                    ContentValues().apply {
                        put(
                            "ended_at",
                            stamp,
                        )
                        put(
                            "duration_seconds",
                            seconds,
                        )
                    },
                    "id=?",
                    arrayOf(id.toString()),
                )
            }

            val id =
                nextNegativeId(
                    "intervals",
                    "id",
                )

            database.insertOrThrow(
                "intervals",
                null,
                ContentValues().apply {
                    put("id", id)
                    put(
                        "node_id",
                        canonical,
                    )
                    put(
                        "started_at",
                        stamp,
                    )
                    putNull("ended_at")
                    putNull(
                        "duration_seconds"
                    )
                },
            )

            database.setTransactionSuccessful()
            return id

        } finally {
            database.endTransaction()
        }
    }

    fun closeInterval(id: Long) {
        val started = db().rawQuery("SELECT started_at FROM intervals WHERE id=?", arrayOf(id.toString())).use { if (it.moveToFirst()) it.getString(0) else null } ?: return
        val ended = TimeUtil.nowText()
        db().update("intervals", ContentValues().apply { put("ended_at", ended); put("duration_seconds", TimeUtil.elapsedSeconds(started, ended)) }, "id=?", arrayOf(id.toString()))
    }

    fun recurringRules(): List<RecurringRule> = db().rawQuery(
        "SELECT id,node_id,start_day,run_time,recurrence_type,interval_value,weekday,day_of_month,month_of_year,day_of_year_month,reminders_json,enabled,created_at,updated_at,duration_seconds FROM recurring_schedule_rules ORDER BY id",
        null,
    ).use { c -> buildList { while (c.moveToNext()) add(c.recurringRule()) } }

    private fun recurringMatches(
        rule: RecurringRule,
        day: LocalDate,
    ): Boolean {
        val start =
            runCatching {
                LocalDate.parse(rule.startDay)
            }.getOrNull() ?: return false

        if (day.isBefore(start)) return false

        return when (rule.recurrenceType) {
            "weekly" -> {
                val weekday =
                    rule.weekday
                        ?: (start.dayOfWeek.value - 1)

                day.dayOfWeek.value - 1 == weekday
            }

            "every_n_days" -> {
                val delta =
                    ChronoUnit.DAYS.between(
                        start,
                        day,
                    )

                delta >= 0 &&
                    delta %
                        rule.intervalValue
                            .coerceAtLeast(1) == 0L
            }

            "every_n_weeks" -> {
                val step =
                    rule.intervalValue
                        .coerceAtLeast(1) * 7L

                val delta =
                    ChronoUnit.DAYS.between(
                        start,
                        day,
                    )

                delta >= 0 &&
                    delta % step == 0L
            }

            "monthly" ->
                day.dayOfMonth ==
                    (rule.dayOfMonth
                        ?: start.dayOfMonth)

            "yearly" ->
                day.monthValue ==
                    (rule.monthOfYear
                        ?: start.monthValue) &&
                    day.dayOfMonth ==
                    (rule.dayOfYearMonth
                        ?: start.dayOfMonth)

            else -> false
        }
    }

    fun recurringRuleForOccurrence(
        day: LocalDate,
        planAction: PlanAction,
    ): RecurringRule? {
        val candidates =
            recurringRules().filter { rule ->
                if (!rule.enabled) {
                    false
                } else {
                    val canonical =
                        action(rule.nodeId)
                            ?.idActionTypes
                            ?: rule.nodeId

                    canonical ==
                        planAction.idActionTypes &&
                        recurringMatches(
                            rule,
                            day,
                        )
                }
            }

        if (candidates.isEmpty()) {
            return null
        }

        val currentTime =
            planAction.runTime
                ?.let {
                    runCatching {
                        normalizeRunTime(it)
                    }.getOrNull()
                }
                .orEmpty()

        candidates.firstOrNull { rule ->
            runCatching {
                normalizeRunTime(
                    rule.runTime
                )
            }.getOrNull().orEmpty() ==
                currentTime
        }?.let {
            return it
        }

        return candidates.singleOrNull()
    }

    fun updateRecurringOccurrenceAndFuture(
        planActionId: Long,
        day: LocalDate,
        runTime: String?,
        durationSeconds: Int?,
        reminders: List<String>,
    ): Boolean {
        val existing =
            planAction(planActionId)
                ?: return false

        val rule =
            recurringRuleForOccurrence(
                day,
                existing,
            ) ?: return false

        require(!runTime.isNullOrBlank()) {
            "A run time is required when editing future recurring occurrences"
        }

        val newTime =
            normalizeRunTime(runTime)
                ?: error(
                    "A run time is required for recurring schedules"
                )

        val oldTime =
            runCatching {
                normalizeRunTime(
                    rule.runTime
                )
            }.getOrNull().orEmpty()

        val stamp = TimeUtil.nowText()
        val duration =
            durationSeconds ?: 0

        val future =
            db().rawQuery(
                """
                SELECT
                    pa.id_plan_action_types,
                    p.day,
                    COALESCE(pa.run_time,'')
                FROM plan_action_types pa
                JOIN plans p
                  ON p.id_plans=pa.id_plans
                WHERE pa.id_action_types=?
                  AND p.day>=?
                ORDER BY p.day,
                         pa.id_plan_action_types
                """.trimIndent(),
                arrayOf(
                    existing.idActionTypes,
                    day.toString(),
                ),
            ).use { cursor ->
                buildList {
                    while (cursor.moveToNext()) {
                        add(
                            Triple(
                                cursor.getLong(0),
                                cursor.getString(1),
                                cursor.getString(2),
                            )
                        )
                    }
                }
            }

        val oldPlanId = existing.idPlans

        db().beginTransaction()

        try {
            val targetPlan =
                ensurePlanDay(day, stamp)

            future.forEach {
                    (id, dayText, rowTime) ->

                if (id == planActionId) {
                    return@forEach
                }

                val rowDay =
                    runCatching {
                        LocalDate.parse(dayText)
                    }.getOrNull()
                        ?: return@forEach

                if (
                    recurringMatches(
                        rule,
                        rowDay,
                    ) &&
                    rowTime == oldTime
                ) {
                    db().delete(
                        "plan_action_types",
                        "id_plan_action_types=?",
                        arrayOf(id.toString()),
                    )
                }
            }

            db().update(
                "plan_action_types",
                ContentValues().apply {
                    put(
                        "id_plans",
                        targetPlan,
                    )
                    put(
                        "run_time",
                        newTime,
                    )
                    put(
                        "duration_seconds",
                        duration,
                    )
                    putNull("last_run_at")
                    putNull("handled_at")
                    put(
                        "updated_at",
                        stamp,
                    )
                },
                "id_plan_action_types=?",
                arrayOf(
                    planActionId.toString()
                ),
            )

            db().delete(
                "plan_action_type_reminders",
                "id_plan_action_types=?",
                arrayOf(
                    planActionId.toString()
                ),
            )

            reminders
                .map(String::trim)
                .filter(String::isNotBlank)
                .forEach {
                    addReminderInternal(
                        planActionId,
                        it,
                    )
                }

            db().update(
                "recurring_schedule_rules",
                ContentValues().apply {
                    put(
                        "run_time",
                        newTime,
                    )
                    put(
                        "reminders_json",
                        JSONArray(
                            reminders
                                .map(String::trim)
                                .filter(String::isNotBlank)
                        ).toString(),
                    )
                    put(
                        "duration_seconds",
                        duration,
                    )
                    put(
                        "updated_at",
                        stamp,
                    )
                },
                "id=?",
                arrayOf(rule.id.toString()),
            )

            normalizePlanPositions(
                oldPlanId
            )

            normalizePlanPositions(
                targetPlan
            )

            removeEmptyPlans()
            db().setTransactionSuccessful()

        } finally {
            db().endTransaction()
        }

        return true
    }

    fun addRecurringRule(rule: RecurringRule): Long {
        val id = nextNegativeId("recurring_schedule_rules", "id"); val stamp = TimeUtil.nowText()
        db().insertOrThrow("recurring_schedule_rules", null, recurringValues(rule, stamp).apply { put("id", id); put("created_at", stamp) })
        return id
    }

    fun updateRecurringRule(id: Long, rule: RecurringRule) {
        db().update("recurring_schedule_rules", recurringValues(rule, TimeUtil.nowText()), "id=?", arrayOf(id.toString()))
    }

    fun deleteRecurringRule(id: Long) { db().delete("recurring_schedule_rules", "id=?", arrayOf(id.toString())) }

    private fun recurringValues(rule: RecurringRule, stamp: String) = ContentValues().apply {
        put("node_id", action(rule.nodeId)?.idActionTypes ?: rule.nodeId); put("start_day", rule.startDay); put("run_time", normalizeRunTime(rule.runTime)); put("recurrence_type", rule.recurrenceType)
        put("interval_value", rule.intervalValue.coerceAtLeast(1)); if (rule.weekday == null) putNull("weekday") else put("weekday", rule.weekday)
        if (rule.dayOfMonth == null) putNull("day_of_month") else put("day_of_month", rule.dayOfMonth)
        if (rule.monthOfYear == null) putNull("month_of_year") else put("month_of_year", rule.monthOfYear)
        if (rule.dayOfYearMonth == null) putNull("day_of_year_month") else put("day_of_year_month", rule.dayOfYearMonth)
        rule.durationSeconds?.let {
            put("duration_seconds", it.coerceAtLeast(0))
        }
        put("reminders_json", rule.remindersJson); put("enabled", if (rule.enabled) 1 else 0); put("updated_at", stamp)
    }

    fun syncDatabase(): SQLiteDatabase = db()
    fun databaseHelper(): PlanningDatabase = database

    private fun ensurePlanDay(day: LocalDate, stamp: String): Long {
        db().rawQuery("SELECT id_plans FROM plans WHERE day=?", arrayOf(day.toString())).use { if (it.moveToFirst()) return it.getLong(0) }
        val id = nextNegativeId("plans", "id_plans")
        db().insertOrThrow("plans", null, ContentValues().apply { put("id_plans", id); put("day", day.toString()); put("created_at", stamp); put("updated_at", stamp) })
        return id
    }

    private fun normalizePlanPositions(idPlans: Long) {
        planActions(idPlans).forEachIndexed { index, row -> if (row.position != index) db().update("plan_action_types", ContentValues().apply {
            put("position", index); put("updated_at", TimeUtil.nowText())
        }, "id_plan_action_types=?", arrayOf(row.idPlanActionTypes.toString())) }
    }

    private fun removeEmptyPlans() {
        db().execSQL("DELETE FROM plans WHERE NOT EXISTS(SELECT 1 FROM plan_action_types a WHERE a.id_plans=plans.id_plans) AND NOT EXISTS(SELECT 1 FROM plan_notes n WHERE n.id_plans=plans.id_plans)")
    }

    private fun nextNegativeId(table: String, column: String): Long = db().rawQuery("SELECT MIN($column) FROM $table", null).use { c ->
        c.moveToFirst(); val min = if (c.isNull(0)) 0L else c.getLong(0); if (min >= 0) -1L else min - 1L
    }

    private fun nextPosition(table: String, foreignColumn: String, foreignValue: String?): Int {
        val (where, args) = if (foreignValue == null) "$foreignColumn IS NULL" to null else "$foreignColumn=?" to arrayOf(foreignValue)
        return db().rawQuery("SELECT COALESCE(MAX(position),-1)+1 FROM $table WHERE $where", args).use { it.moveToFirst(); it.getInt(0) }
    }

    companion object {
        fun normalizeRunTime(value: String): String {
            val match = Regex("^\\s*([01]?\\d|2[0-3]):([0-5]\\d)\\s*$").matchEntire(value)
                ?: throw IllegalArgumentException("Time must be HH:MM, for example 09:30")
            return "%02d:%02d".format(match.groupValues[1].toInt(), match.groupValues[2].toInt())
        }
    }
}

private fun Cursor.actionType() = ActionType(getString(0), getString(1), nullableString(2), getString(3), getInt(4), nullableInt(5), getInt(6), getInt(7) != 0, getString(8), getString(9))
private fun Cursor.todo() = ActionTodo(getLong(0), getString(1), getString(2), getInt(3) != 0, getString(4), getString(5))
private fun Cursor.actionPanelTodo() = ActionPanelTodo(
    getString(0),
    getString(1),
    getLong(2),
    getString(3),
    getInt(4) != 0,
    nullableString(5),
    nullableString(6),
)
private fun Cursor.planAction() = PlanAction(getLong(0), getLong(1), getString(2), getString(3), nullableString(4), getInt(5), nullableString(6), nullableString(7), getInt(8), getString(9), getString(10))
private fun Cursor.planReminder() = PlanReminder(getLong(0), getLong(1), getString(2), getInt(3), nullableString(4), getString(5), getString(6))
private fun Cursor.planNote() = PlanNote(getLong(0), getLong(1), getString(2), getInt(3), getString(4), getString(5))
private fun Cursor.planActionNote() = PlanActionNote(getLong(0), getLong(1), getString(2), getInt(3), getString(4), getString(5))
private fun Cursor.planActionTodo() = PlanActionTodo(getLong(0), getLong(1), getString(2), getInt(3) != 0, getInt(4), getString(5), getString(6))
private fun Cursor.interval() = TimeInterval(getLong(0), getString(1), getString(2), nullableString(3), nullableInt(4))
private fun Cursor.recurringRule() = RecurringRule(getLong(0), getString(1), getString(2), getString(3), getString(4), getInt(5), nullableInt(6), nullableInt(7), nullableInt(8), nullableInt(9), getString(10), getInt(11) != 0, getString(12), getString(13), nullableInt(14))
private fun Cursor.nullableString(index: Int): String? = if (isNull(index)) null else getString(index)
private fun Cursor.nullableInt(index: Int): Int? = if (isNull(index)) null else getInt(index)

