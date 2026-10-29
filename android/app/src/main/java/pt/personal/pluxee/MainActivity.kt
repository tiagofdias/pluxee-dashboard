package pt.personal.pluxee

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MainActivity : FragmentActivity() {
    private val model: AppViewModel by viewModels()
    private var csvContent: String? = null
    private val export = registerForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        if (uri != null) {
            val content = csvContent
            if (content != null) runCatching { contentResolver.openOutputStream(uri)?.use { it.write(content.toByteArray(Charsets.UTF_8)) } }
                .onFailure { model.message("Não foi possível exportar o ficheiro.") }
        }
        csvContent = null
    }
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) model.enableAlerts() else model.message("A permissão foi recusada. Podes ativá-la nas definições Android.")
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setContent { PersonalApp(model, onBiometric = ::authenticate, onAlerts = ::enableAlerts, onExport = { csv ->
            csvContent = csv
            export.launch("pluxee-${if (model.state.demo) "demo-" else ""}movimentos.csv")
        }) }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (isActive) { delay(60_000); model.refresh() }
            }
        }
    }
    override fun onStop() {
        if (!isChangingConfigurations) model.lock()
        super.onStop()
    }
    private fun enableAlerts() {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
        else model.enableAlerts()
    }
    private fun authenticate(enable: Boolean) {
        if (!model.biometricAvailable()) { model.message("Configura uma impressão digital ou biometria forte nas definições Android."); return }
        try {
            val cipher = if (enable) model.vault.biometricEncryptionCipher() else model.vault.biometricDecryptionCipher()
            val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    if (!lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) return
                    val authenticatedCipher = result.cryptoObject?.cipher ?: return
                    if (enable) model.biometricEnabled(authenticatedCipher) else model.biometricUnlocked(authenticatedCipher)
                }
                override fun onAuthenticationError(code: Int, message: CharSequence) {
                    if (code !in listOf(BiometricPrompt.ERROR_NEGATIVE_BUTTON, BiometricPrompt.ERROR_USER_CANCELED, BiometricPrompt.ERROR_CANCELED)) model.message("Não foi possível verificar a biometria. Podes usar email e palavra-passe.")
                }
            })
            val info = BiometricPrompt.PromptInfo.Builder().setTitle(if (enable) "Proteger a sessão" else "Desbloquear Pluxee Personal")
                .setSubtitle("Confirma a tua identidade neste dispositivo")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                .setNegativeButtonText("Cancelar").build()
            prompt.authenticate(info, BiometricPrompt.CryptoObject(cipher))
        } catch (_: Exception) { model.message("A sessão biométrica não pode ser aberta. Usa Sair e entra novamente.") }
    }
}
