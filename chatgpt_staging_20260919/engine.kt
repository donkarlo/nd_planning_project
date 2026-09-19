package com.ndplanning.android.schedule

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.ndplanning.android.MainActivity
import com.ndplanning.android.PlanningApplication
import com.ndplanning.android.R
import com.ndplanning.android.data.PlanAction
import com.ndplanning.android.data.RecurringRule
import org.json.JSONArray
import java.time.Duration
import java.time.LocalDate
import java.time.LocalTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.temporal.ChronoUnit
import java.util.concurrent.TimeUnit

/** Materializes recurring rules and schedules Android notifications. */
class ScheduleEngine(private val context: Context) {
    fun refresh(daysAhead: Long = 120) {
        val app = context.applicationContext as PlanningApplication
        val horizonDays = daysAhead.coerceAtLeast(0)
        val today =
            LocalDate.now(
                ZoneId.of("Europe/Vienna")
            )
        materializeRecurring(app, today.plusDays(horizonDays))
        val manager = WorkManager.getInstance(context)
        manager.cancelAllWorkByTag(TAG)
        val plans = app.repository.plansBetween(today, today.plusDays(horizonDays)).flatMap { day ->
            day.actions.map { day.day to it }
        }
        plans.forEach { (day, action) ->
            scheduleAction(LocalDate.parse(day), action, app.repository.reminderRows(action.idPlanActionTypes))
        }
    }

    fun materializeThrough(daysAhead: Long) {
        val app = context.applicationContext as PlanningApplication
        val today =
            LocalDate.now(
                ZoneId.of("Europe/Vienna")
            )
        materializeRecurring(
            app,
            today.plusDays(daysAhead.coerceAtLeast(0)),
        )
    }

    private fun materializeRecurring(
        app: PlanningApplication,
        throughDay: LocalDate,
    ) {
        val today =
            LocalDate.now(
                ZoneId.of("Europe/Vienna")
            )

        app.repository.recurringRules().filter { it.enabled }.forEach { rule ->
            val action = app.repository.action(rule.nodeId) ?: return@forEach
            val reminders = runCatching {
                JSONArray(rule.remindersJson).let { array ->
                    (0 until array.length()).map { array.getString(it) }
                }
            }.getOrDefault(emptyList())

            occurrences(rule, today, throughDay).forEach { day ->
                if (!app.repository.planExistsForActionDay(action.idActionTypes, day)) {
                    app.repository.addPlanAction(
                        day = day,
                        actionId = action.idActionTypes,
                        runTime = rule.runTime,
                        durationSeconds =
                            rule.durationSeconds
                                ?: action.plannedDurationSeconds,
                        reminders = reminders,
                    )
                }
            }
        }
    }

    private fun occurrences(
        rule: RecurringRule,
        from: LocalDate,
        throughDay: LocalDate,
    ): List<LocalDate> {
        val start =
            runCatching {
                LocalDate.parse(rule.startDay)
            }.getOrNull() ?: return emptyList()

        val lower = maxOf(start, from)
        if (throughDay < lower) return emptyList()

        val result = mutableListOf<LocalDate>()

        when (rule.recurrenceType) {
            "weekly" -> {
                val weekday =
                    (rule.weekday ?: start.dayOfWeek.value - 1)
                        .coerceIn(0, 6) + 1
                var day =
                    start.plusDays(
                        ((weekday - start.dayOfWeek.value) + 7L) % 7L
                    )
                while (day < lower) {
                    day = day.plusWeeks(1)
                }
                while (day <= throughDay) {
                    result += day
                    day = day.plusWeeks(1)
                }
            }

            "every_n_days" -> {
                val step =
                    rule.intervalValue
                        .coerceAtLeast(1)
                        .toLong()
                var day = start
                if (day < lower) {
                    val delta =
                        ChronoUnit.DAYS.between(
                            day,
                            lower,
                        )
                    day =
                        day.plusDays(
                            ((delta + step - 1) / step) * step
                        )
                }
                while (day <= throughDay) {
                    result += day
                    day = day.plusDays(step)
                }
            }

            "every_n_weeks" -> {
                val step =
                    rule.intervalValue
                        .coerceAtLeast(1)
                        .toLong()
                var day = start
                if (day < lower) {
                    val deltaWeeks =
                        (
                            ChronoUnit.DAYS.between(
                                day,
                                lower,
                            ) + 6
                        ) / 7
                    day =
                        day.plusWeeks(
                            ((deltaWeeks + step - 1) / step) * step
                        )
                }
                while (day <= throughDay) {
                    result += day
                    day = day.plusWeeks(step)
                }
            }

            "monthly" -> {
                val target =
                    (rule.dayOfMonth ?: start.dayOfMonth)
                        .coerceIn(1, 31)
                var month = YearMonth.from(lower)
                val endMonth = YearMonth.from(throughDay)
                while (month <= endMonth) {
                    if (target <= month.lengthOfMonth()) {
                        val candidate = month.atDay(target)
                        if (
                            candidate >= lower &&
                            candidate >= start &&
                            candidate <= throughDay
                        ) {
                            result += candidate
                        }
                    }
                    month = month.plusMonths(1)
                }
            }

            "yearly" -> {
                val month =
                    (rule.monthOfYear ?: start.monthValue)
                        .coerceIn(1, 12)
                val dayOfMonth =
                    (rule.dayOfYearMonth ?: start.dayOfMonth)
                        .coerceIn(1, 31)
                var year = lower.year
                while (year <= throughDay.year) {
                    val candidate =
                        runCatching {
                            LocalDate.of(
                                year,
                                month,
                                dayOfMonth,
                            )
                        }.getOrNull()
                    if (
                        candidate != null &&
                        candidate >= lower &&
                        candidate >= start &&
                        candidate <= throughDay
                    ) {
                        result += candidate
                    }
                    year++
                }
            }
        }

        return result
    }

    private fun scheduleAction(day: LocalDate, action: PlanAction, reminders: List<com.ndplanning.android.data.PlanReminder>) {
        val runTime = action.runTime ?: return
        val time = runCatching { LocalTime.parse(runTime) }.getOrNull() ?: return
        val scheduled = ZonedDateTime.of(day, time, ZoneId.of("Europe/Vienna"))
        scheduleNotification(
            "due-${action.idPlanActionTypes}",
            scheduled,
            action.actionName,
            "Scheduled now",
            null,
            "action",
        )
        reminders.filter { it.firedAt == null }.forEach { reminder ->
            val seconds = parseReminderSeconds(reminder.reminderSpec) ?: return@forEach
            scheduleNotification(
                "reminder-${reminder.idPlanActionTypeReminders}",
                scheduled.minusSeconds(seconds),
                action.actionName,
                reminder.reminderSpec,
                reminder.idPlanActionTypeReminders,
                "reminder",
            )
        }
    }

    private fun scheduleNotification(
        name: String,
        whenAt: ZonedDateTime,
        title: String,
        message: String,
        reminderId: Long?,
        kind: String,
    ) {
        val delay =
            Duration.between(
                ZonedDateTime.now(
                    ZoneId.of("Europe/Vienna")
                ),
                whenAt,
            ).toMillis()

        if (delay <= 0) return

        val data =
            Data.Builder()
                .putString("title", title)
                .putString("message", message)
                .putString("kind", kind)
                .apply {
                    reminderId?.let {
                        putLong("reminder_id", it)
                    }
                }
                .build()
        val request = OneTimeWorkRequestBuilder<PlanningNotificationWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setInputData(data)
            .addTag(TAG)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(name, ExistingWorkPolicy.REPLACE, request)
    }

    private fun parseReminderSeconds(text: String): Long? {
        val match = Regex("^\\s*(\\d+(?:\\.\\d+)?)\\s*(days?|d|hours?|hrs?|hr|h|minutes?|mins?|min|m)\\s*befor(?:e)?\\s*$", RegexOption.IGNORE_CASE).matchEntire(text) ?: return null
        val amount = match.groupValues[1].toDouble()
        val unit = match.groupValues[2].lowercase()
        return (amount * when {
            unit.startsWith("d") -> 86400
            unit.startsWith("h") -> 3600
            else -> 60
        }).toLong().coerceAtLeast(1)
    }

    companion object { private const val TAG = "nd-planning-schedule" }
}

class PlanningNotificationWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val title =
            inputData.getString("title")
                ?: "ND Planning"

        val message =
            inputData.getString("message")
                ?: "Scheduled action"

        val kind =
            inputData.getString("kind")
                ?: "action"

        val reminderId =
            inputData.getLong(
                "reminder_id",
                Long.MIN_VALUE,
            )
        val app = applicationContext as PlanningApplication
        if (reminderId != Long.MIN_VALUE) app.repository.markReminderFired(reminderId)

        val manager =
            applicationContext.getSystemService(
                Context.NOTIFICATION_SERVICE
            ) as NotificationManager

        val vibration =
            longArrayOf(
                0L,
                250L,
                250L,
                250L,
                250L,
                250L,
            )

        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL,
                "Planning alerts",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description =
                    "Scheduled actions and reminders"

                lockscreenVisibility =
                    Notification.VISIBILITY_PUBLIC

                enableVibration(true)
                vibrationPattern = vibration

                // Vibration only; no notification sound.
                setSound(null, null)
            }
        )
        if (ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            val intent = Intent(applicationContext, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pending = PendingIntent.getActivity(applicationContext, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val text =
                if (kind == "reminder") {
                    "Reminder · $message"
                } else {
                    "Scheduled now"
                }

            val publicVersion =
                NotificationCompat.Builder(
                    applicationContext,
                    CHANNEL,
                )
                    .setSmallIcon(
                        R.drawable.ic_stat_nd_planning
                    )
                    .setContentTitle(title)
                    .setContentText(text)
                    .setPriority(
                        NotificationCompat.PRIORITY_MAX
                    )
                    .setVisibility(
                        NotificationCompat.VISIBILITY_PUBLIC
                    )
                    .build()

            val notification =
                NotificationCompat.Builder(
                    applicationContext,
                    CHANNEL,
                )
                    .setSmallIcon(
                        R.drawable.ic_stat_nd_planning
                    )
                    .setContentTitle(title)
                    .setContentText(text)
                    .setSubText(
                        if (kind == "reminder") {
                            "ND Planning reminder"
                        } else {
                            "ND Planning"
                        }
                    )
                    .setCategory(
                        if (kind == "reminder") {
                            NotificationCompat.CATEGORY_REMINDER
                        } else {
                            NotificationCompat.CATEGORY_ALARM
                        }
                    )
                    .setPriority(
                        NotificationCompat.PRIORITY_MAX
                    )
                    .setVisibility(
                        NotificationCompat.VISIBILITY_PUBLIC
                    )
                    .setPublicVersion(
                        publicVersion
                    )
                    .setVibrate(
                        longArrayOf(
                            0L,
                            250L,
                            250L,
                            250L,
                            250L,
                            250L,
                        )
                    )
                    .setContentIntent(pending)
                    .setAutoCancel(true)
                    .build()
            NotificationManagerCompat.from(applicationContext).notify((System.nanoTime() and 0x7fffffff).toInt(), notification)
        }
        return Result.success()
    }

    companion object { private const val CHANNEL = "nd_planning_schedule_v3" }
}

