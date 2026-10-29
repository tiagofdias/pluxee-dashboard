package pt.personal.pluxee

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import java.util.Base64
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** App-private encrypted storage. No password is ever serialized. */
class SessionVault(private val context: Context) {
    private val prefs = context.getSharedPreferences("private_vault", Context.MODE_PRIVATE)
    private val store get() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private val deviceAlias = "pluxee.personal.device.v1"
    private val biometricAlias = "pluxee.personal.biometric.v1"
    val hasSession get() = prefs.contains("foreground")
    val biometricEnabled get() = prefs.getBoolean("biometric", false)
    val alertsEnabled get() = prefs.getBoolean("alerts", false)
    var showNotificationDetails: Boolean
        get() = prefs.getBoolean("details", false)
        set(value) { prefs.edit().putBoolean("details", value).commit() }
    val deviceId: String get() = prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also { prefs.edit().putString("device_id", it).commit() }

    private fun key(alias: String, biometric: Boolean): SecretKey {
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val builder = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).setRandomizedEncryptionRequired(true).setUserAuthenticationRequired(biometric)
        if (biometric) {
            builder.setInvalidatedByBiometricEnrollment(true)
            if (android.os.Build.VERSION.SDK_INT >= 30) builder.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
            else @Suppress("DEPRECATION") builder.setUserAuthenticationValidityDurationSeconds(-1)
        }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply { init(builder.build()) }.generateKey()
    }
    private fun seal(cipher: Cipher, value: String): String = Base64.getEncoder().encodeToString(cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8)))
    private fun packed(value: String): ByteArray = Base64.getDecoder().decode(value)
    private fun deviceEncrypt(value: String): String = Cipher.getInstance("AES/GCM/NoPadding").run {
        init(Cipher.ENCRYPT_MODE, key(deviceAlias, false)); seal(this, value)
    }
    private fun deviceDecrypt(value: String): String {
        val bytes = packed(value)
        require(bytes.size > 28)
        return Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, key(deviceAlias, false), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            String(doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
        }
    }
    fun saveWithoutBiometric(account: Account) {
        check(prefs.edit().putString("foreground", deviceEncrypt(account.toJson().toString())).putBoolean("biometric", false).commit())
    }
    fun loadWithoutBiometric(): Account? {
        if (biometricEnabled) return null
        return prefs.getString("foreground", null)?.let { Account.fromJson(JSONObject(deviceDecrypt(it))) }
    }
    fun biometricEncryptionCipher(): Cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key(biometricAlias, true)) }
    fun finishBiometricEnable(cipher: Cipher, account: Account) {
        check(prefs.edit().putString("foreground", seal(cipher, account.toJson().toString())).putBoolean("biometric", true).commit())
    }
    fun biometricDecryptionCipher(): Cipher {
        check(biometricEnabled)
        val bytes = packed(prefs.getString("foreground", null) ?: error("Missing session"))
        return Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key(biometricAlias, true), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        }
    }
    fun finishBiometricUnlock(cipher: Cipher): Account {
        val bytes = packed(prefs.getString("foreground", null) ?: error("Missing session"))
        return Account.fromJson(JSONObject(String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)))
    }
    fun allowBackground(account: Account) {
        check(prefs.edit().putString("background", deviceEncrypt(account.toJson().toString())).putBoolean("alerts", true).commit())
    }
    fun backgroundAccount(): Account? = if (!alertsEnabled) null else prefs.getString("background", null)?.let { Account.fromJson(JSONObject(deviceDecrypt(it))) }
    fun backgroundMatches(account: Account): Boolean = runCatching { backgroundAccount()?.let { it.identity() == account.identity() && it.sessionId == account.sessionId } == true }.getOrDefault(false)
    fun disableBackground() { prefs.edit().remove("background").putBoolean("alerts", false).commit() }
    fun readRecord(account: Account): JSONObject? {
        val file = File(context.filesDir, "ledger_${account.identity()}.enc")
        if (!file.exists()) return null
        return JSONObject(deviceDecrypt(String(AtomicFile(file).readFully(), Charsets.UTF_8)))
    }
    fun writeRecord(account: Account, record: JSONObject) {
        val file = AtomicFile(File(context.filesDir, "ledger_${account.identity()}.enc"))
        val stream = file.startWrite()
        try { stream.write(deviceEncrypt(record.toString()).toByteArray(Charsets.UTF_8)); file.finishWrite(stream) }
        catch (error: Exception) { file.failWrite(stream); throw error }
    }
    fun clearAll() {
        prefs.edit().clear().commit()
        context.filesDir.listFiles()?.filter { it.name.startsWith("ledger_") && (it.name.endsWith(".enc") || it.name.endsWith(".enc.bak")) }?.forEach { it.delete() }
        if (store.containsAlias(biometricAlias)) store.deleteEntry(biometricAlias)
    }
}
