package pt.personal.pluxee

import android.Manifest
import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.util.concurrent.TimeUnit

class PluxeeApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("movements", "Movimentos do cartão", NotificationManager.IMPORTANCE_DEFAULT).apply { description = "Novos pagamentos e carregamentos" })
    }
}

object SyncEngine {
    val mutex = Mutex()
    suspend fun refresh(context: Context, account: Account, notify: Boolean): Snapshot = mutex.withLock {
        withContext(Dispatchers.IO) {
            val vault = SessionVault(context)
            val old = vault.readRecord(account)
            val oldSnapshot = old?.optJSONObject("snapshot")?.let { Snapshot.fromJson(it) }
            val seen = old?.optJSONArray("seen")?.let { array -> (0 until array.length()).map { array.getString(it) }.toSet() }
            val latest = old?.optString("latest")?.takeIf { it.isNotBlank() }?.let { LocalDate.parse(it) }
            val fresh = PluxeeApi.snapshot(account)
            if (fresh.balance == 0.0 && fresh.movements.isEmpty() && oldSnapshot != null && oldSnapshot.balance > 1 && oldSnapshot.movements.isNotEmpty()) throw ServiceUnavailable()
            val changes = MovementLedger.newMovements(seen, latest, fresh.movements)
            val merged = fresh.copy(movements = MovementLedger.merge(oldSnapshot?.movements ?: emptyList(), fresh.movements))
            val keys = (seen.orEmpty() + MovementLedger.keyed(fresh.movements.filterNot { it.rejected }).map { it.first }).toList().takeLast(10000)
            val latestDay = (listOfNotNull(latest) + fresh.movements.filterNot { it.rejected }.mapNotNull { parseDay(it.date) }).maxOrNull()
            vault.writeRecord(account, JSONObject().put("snapshot", merged.toJson()).put("seen", JSONArray(keys)).put("latest", latestDay?.toString() ?: ""))
            // Persist deduplication before posting. Never post after logout/account switch.
            if (notify && vault.backgroundMatches(account)) {
                if (changes.size > 1) notifyBatch(context, vault, changes.map { it.second })
                else changes.forEach { (key, movement) -> notifyMovement(context, vault, key, movement) }
            }
            merged
        }
    }
    private fun permitted(context: Context): Boolean = NotificationManagerCompat.from(context).areNotificationsEnabled() && (Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
    private fun contentIntent(context: Context): PendingIntent = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    private fun post(context: Context, tag: String, id: Int, notification: android.app.Notification) {
        if (!permitted(context)) return
        // Permission can be revoked between the check and delivery.
        try { NotificationManagerCompat.from(context).notify(tag, id, notification) }
        catch (_: SecurityException) { /* Respect revoked notification permission. */ }
    }
    private fun notifyBatch(context: Context, vault: SessionVault, movements: List<Movement>) {
        if (!permitted(context)) return
        val text = if (vault.showNotificationDetails) "${movements.size} movimentos · total ${euros(movements.sumOf { it.amount })}" else "Abre a app para consultar os novos movimentos."
        val public = NotificationCompat.Builder(context, "movements").setSmallIcon(R.drawable.ic_notification).setContentTitle("Pluxee Personal").setContentText("Novos movimentos no cartão.").build()
        post(context, "batch", 3, NotificationCompat.Builder(context, "movements").setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("${movements.size} novos movimentos").setContentText(text).setContentIntent(contentIntent(context)).setAutoCancel(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(public).build())
    }
    private fun notifyMovement(context: Context, vault: SessionVault, key: String, tx: Movement) {
        if (!permitted(context)) return
        val generic = NotificationCompat.Builder(context, "movements").setSmallIcon(R.drawable.ic_notification).setContentTitle("Pluxee Personal").setContentText("Novo movimento no cartão. Abre a app para consultar.").build()
        val notification = NotificationCompat.Builder(context, "movements").setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(if (tx.amount > 0) "Carregamento recebido" else "Novo pagamento")
            .setContentText(if (vault.showNotificationDetails) "${tx.merchant} · ${euros(tx.amount)}" else "Novo movimento no cartão. Abre a app para consultar.")
            .setContentIntent(contentIntent(context)).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(generic).build()
        post(context, key, 1, notification)
    }
    fun notifyExpired(context: Context) {
        if (!permitted(context)) return
        post(context, "session", 2, NotificationCompat.Builder(context, "movements").setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Volta a entrar na Pluxee Personal").setContentText("A sessão expirou. As verificações estão em pausa.")
            .setContentIntent(contentIntent(context)).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build())
    }
}

class MovementWorker(context: Context, parameters: WorkerParameters) : CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result {
        val vault = SessionVault(applicationContext)
        val account = try { vault.backgroundAccount() } catch (_: Exception) { vault.disableBackground(); return Result.success() } ?: return Result.success()
        return try { SyncEngine.refresh(applicationContext, account, notify = true); Result.success() }
        catch (_: SessionExpired) {
            SyncEngine.mutex.withLock {
                if (vault.backgroundMatches(account)) { vault.disableBackground(); NotificationSchedule.cancel(applicationContext); SyncEngine.notifyExpired(applicationContext) }
            }
            Result.success()
        } catch (error: Exception) {
            if (error is kotlinx.coroutines.CancellationException) throw error
            if (runAttemptCount < 3) Result.retry() else Result.success()
        }
    }
}

object NotificationSchedule {
    fun start(context: Context) {
        val work = PeriodicWorkRequestBuilder<MovementWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInitialDelay(15, TimeUnit.MINUTES).setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 5, TimeUnit.MINUTES).build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork("movement-check", ExistingPeriodicWorkPolicy.UPDATE, work)
    }
    fun cancel(context: Context) { WorkManager.getInstance(context).cancelUniqueWork("movement-check") }
}
