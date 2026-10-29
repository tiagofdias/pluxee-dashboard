package pt.personal.pluxee

import android.app.Application
import android.app.NotificationManager
import android.os.Build
import androidx.biometric.BiometricManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import javax.crypto.Cipher


data class AppState(val account: Account? = null, val snapshot: Snapshot? = null, val locked: Boolean = false, val hasSaved: Boolean = false, val biometric: Boolean = false, val alerts: Boolean = false, val showDetails: Boolean = false, val loading: Boolean = false, val error: String? = null, val demo: Boolean = false)

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val context get() = getApplication<Application>().applicationContext
    val vault = SessionVault(context)
    var state by mutableStateOf(AppState(hasSaved = vault.hasSession, biometric = vault.biometricEnabled, locked = vault.biometricEnabled && vault.hasSession, alerts = vault.alertsEnabled, showDetails = vault.showNotificationDetails))
        private set
    private var operation: Job? = null
    init {
        if (vault.hasSession && !vault.biometricEnabled) {
            viewModelScope.launch {
                try {
                    val account = withContext(Dispatchers.IO) { vault.loadWithoutBiometric() }
                    if (account != null) opened(account)
                } catch (_: Exception) { clearSession("Não foi possível abrir a sessão guardada. Entra novamente.") }
            }
        }
    }
    fun dismissError() { state = state.copy(error = null) }
    fun message(message: String) { state = state.copy(error = message, loading = false) }
    fun login(email: String, password: String) {
        if (state.loading) return
        state = state.copy(loading = true, error = null)
        operation = viewModelScope.launch {
            try {
                val account = withContext(Dispatchers.IO) { PluxeeApi.login(email, password, vault.deviceId, Build.MODEL) }
                SyncEngine.mutex.withLock {
                    withContext(Dispatchers.IO) {
                        // A new login never inherits another account's monitoring grant.
                        vault.disableBackground(); NotificationSchedule.cancel(context)
                        vault.saveWithoutBiometric(account)
                    }
                }
                opened(account)
            } catch (error: Exception) {
                if (error is kotlinx.coroutines.CancellationException) throw error
                state = state.copy(loading = false, error = safeMessage(error))
            }
        }
    }
    fun biometricAvailable(): Boolean = BiometricManager.from(context).canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) == BiometricManager.BIOMETRIC_SUCCESS
    fun biometricUnlocked(cipher: Cipher) {
        try { opened(vault.finishBiometricUnlock(cipher)) }
        catch (_: Exception) { viewModelScope.launch { clearSession("A biometria mudou ou a sessão não pode ser aberta. Entra novamente.") } }
    }
    fun biometricEnabled(cipher: Cipher) {
        val account = state.account ?: return
        try { vault.finishBiometricEnable(cipher, account); state = state.copy(biometric = true, hasSaved = true) }
        catch (_: Exception) { message("Não foi possível ativar a biometria.") }
    }
    fun disableBiometric() {
        val account = state.account ?: return
        try { vault.saveWithoutBiometric(account); state = state.copy(biometric = false) }
        catch (_: Exception) { message("Não foi possível alterar a proteção.") }
    }
    private fun opened(account: Account) {
        state = AppState(account = account, hasSaved = true, biometric = vault.biometricEnabled, alerts = vault.alertsEnabled, showDetails = vault.showNotificationDetails)
        viewModelScope.launch {
            val cached = withContext(Dispatchers.IO) { runCatching { vault.readRecord(account)?.optJSONObject("snapshot")?.let { Snapshot.fromJson(it) } }.getOrNull() }
            if (state.account === account) { state = state.copy(snapshot = cached); refresh() }
        }
    }
    fun refresh() {
        val account = state.account ?: return
        if (state.loading || state.demo || state.locked) return
        state = state.copy(loading = true, error = null)
        operation = viewModelScope.launch {
            try {
                val snapshot = SyncEngine.refresh(context, account, notify = vault.alertsEnabled)
                if (state.account === account) state = state.copy(snapshot = snapshot, loading = false, alerts = vault.alertsEnabled)
            } catch (error: Exception) {
                if (error is kotlinx.coroutines.CancellationException) throw error
                if (error is SessionExpired) clearSession(error.message ?: "A sessão expirou.")
                else if (state.account === account) state = state.copy(loading = false, error = safeMessage(error))
            }
        }
    }
    fun enableAlerts() {
        val account = state.account ?: return
        if (state.loading) return
        state = state.copy(loading = true, error = null)
        operation = viewModelScope.launch {
            try {
                val snapshot = SyncEngine.refresh(context, account, notify = false)
                SyncEngine.mutex.withLock { withContext(Dispatchers.IO) { vault.allowBackground(account); NotificationSchedule.start(context) } }
                state = state.copy(snapshot = snapshot, alerts = true, loading = false)
            } catch (error: Exception) {
                if (error is kotlinx.coroutines.CancellationException) throw error
                if (error is SessionExpired) clearSession(error.message ?: "A sessão expirou.") else message(safeMessage(error))
            }
        }
    }
    fun disableAlerts() { vault.disableBackground(); NotificationSchedule.cancel(context); state = state.copy(alerts = false) }
    fun details(value: Boolean) { vault.showNotificationDetails = value; state = state.copy(showDetails = value) }
    fun lock() { if (state.biometric && !state.demo) { state = state.copy(account = null, snapshot = null, locked = true, loading = false); operation?.cancel() } }
    fun logout() { operation?.cancel(); state = state.copy(loading = true); viewModelScope.launch { clearSession(null) } }
    private suspend fun clearSession(message: String?) {
        SyncEngine.mutex.withLock { withContext(Dispatchers.IO) { NotificationSchedule.cancel(context); vault.clearAll(); context.getSystemService(NotificationManager::class.java).cancelAll() } }
        state = AppState(error = message)
    }
    fun demo() {
        if (state.hasSaved) { message("Termina a sessão guardada antes de abrir a demonstração."); return }
        state = AppState(snapshot = DemoData.snapshot(), demo = true)
    }
    private fun safeMessage(error: Exception) = when (error) {
        is LoginRejected, is SessionExpired, is ServiceUnavailable, is UnsupportedAccount -> error.message ?: "Não foi possível concluir o pedido."
        else -> "Não foi possível concluir o pedido. Tenta novamente."
    }
}

object DemoData {
    fun snapshot(): Snapshot {
        val today = LocalDate.now()
        val entries = mutableListOf<Movement>()
        val names = listOf("CAFÉ AURORA", "SUPERMERCADO EXEMPLO", "BISTRO VERDE", "Glovo DEMO")
        for (offset in 5 downTo 0) {
            val month = YearMonth.from(today).minusMonths(offset.toLong())
            val dates = (listOf(24 to true) + listOf(2, 6, 10, 14, 19, 23, 27).map { it to false }).sortedBy { it.first }
            dates.forEachIndexed { index, (day, credit) ->
                val date = month.atDay(day)
                if (date <= today) entries += Movement(date.format(DateTimeFormatter.ofPattern("dd/MM/yyyy")), if (credit) "Carregamento de EMPRESA DEMONSTRAÇÃO" else names[index % names.size], if (credit) 220.50 else -(8.50 + index * 2.15 + offset), null, date.toString())
            }
        }
        var balance = 125.0
        val balanced = entries.map { balance += it.amount; it.copy(historicalBalance = balance) }.reversed()
        return Snapshot(balance, balanced)
    }
}
