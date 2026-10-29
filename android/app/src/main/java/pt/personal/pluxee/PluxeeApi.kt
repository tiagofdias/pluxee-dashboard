package pt.personal.pluxee

import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.TimeUnit

class SessionExpired : Exception("A sessão Pluxee expirou. Entra novamente com email e palavra-passe.")
class LoginRejected : Exception("A Pluxee recusou o login. Confirma os dados na app oficial antes de tentar novamente.")
class ServiceUnavailable : Exception("Não foi possível ligar à Pluxee. Os dados guardados continuam disponíveis.")
class UnsupportedAccount(message: String) : Exception(message)

object PluxeeApi {
    private val client = OkHttpClient.Builder().connectTimeout(20, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).callTimeout(45, TimeUnit.SECONDS).followRedirects(false).retryOnConnectionFailure(false).build()
    private const val origin = "https://api.mobile.clients.pluxee.pt"
    private fun call(path: String, session: String? = null, query: Map<String, String> = emptyMap(), payload: JSONObject? = null): JSONObject {
        val url = (origin + path).toHttpUrl().newBuilder().addQueryParameter("idLanguage", "1")
        query.forEach { (key, value) -> url.addQueryParameter(key, value) }
        val request = Request.Builder().url(url.build()).header("User-Agent", "okhttp/4.12.0").header("Accept", "application/json")
        session?.let { request.header("ApiClaim", WireCrypto.encrypt(it)) }
        payload?.let { request.post(it.toString().toRequestBody("application/json; charset=utf-8".toMediaType())) }
        try {
            client.newCall(request.build()).execute().use { response ->
                val body = response.body?.string() ?: throw ServiceUnavailable()
                val json = try { JSONObject(body) } catch (_: Exception) { throw ServiceUnavailable() }
                if (response.code >= 500 || response.code == 429) throw ServiceUnavailable()
                if (response.code == 401 || json.optInt("code") == -1) {
                    if (session != null) throw SessionExpired() else throw LoginRejected()
                }
                if (!response.isSuccessful) {
                    if (payload != null) throw LoginRejected() else throw ServiceUnavailable()
                }
                return json
            }
        } catch (_: IOException) { throw ServiceUnavailable() }
    }
    fun login(email: String, password: String, deviceId: String, model: String): Account {
        require(email.contains('@') && password.isNotEmpty())
        val stamp = SimpleDateFormat("EEEE MMMM yyyy HH:mm:ss zZ", Locale.US).format(Date())
        val payload = JSONObject().put("Email", WireCrypto.encrypt(email.trim())).put("Password", WireCrypto.encrypt(password))
            .put("KeyMd5", "").put("Token", "").put("OriginDataRequest", "$stamp|||Android")
            .put("DeviceUuid", deviceId).put("DeviceModel", model).put("Platform", "android")
        val response = call("/api/user/login", payload = payload)
        if (response.optInt("code") != 3) throw LoginRejected()
        val user = response.optJSONObject("data") ?: throw LoginRejected()
        val session = user.optString("sessionId").takeIf { it.isNotBlank() } ?: throw LoginRejected()
        val userId = user.getLong("userId")
        val cards = call("/api/benefit/v2", session, mapOf("userId" to WireCrypto.encrypt(userId.toString()))).optJSONArray("data") ?: throw ServiceUnavailable()
        val meals = (0 until cards.length()).map { cards.getJSONObject(it) }.filter {
            it.optString("referenceC").isNotBlank() && (it.optInt("productId") == 33 || it.optString("service").contains("refei", ignoreCase = true))
        }
        if (meals.isEmpty()) throw UnsupportedAccount("Não foi encontrado um cartão refeição nesta conta.")
        if (meals.size > 1) throw UnsupportedAccount("Esta conta tem vários cartões refeição. A seleção de cartão ainda não está disponível.")
        val personal = user.optJSONObject("personalInfo") ?: JSONObject()
        val name = listOf(personal.optString("name"), personal.optString("surname")).filter { it.isNotBlank() }.joinToString(" ").take(120).ifBlank { "A tua conta" }
        val card = meals.single()
        return Account(session, userId, card.getLong("benefitId"), card.getString("referenceC"), name)
    }
    fun snapshot(account: Account): Snapshot {
        val balanceData = call("/api/benefit/card/balance", account.sessionId, mapOf("Id" to account.cardReference)).optJSONObject("data") ?: throw ServiceUnavailable()
        val balance = balanceData.optString("balance").replace(',', '.').toDoubleOrNull() ?: throw ServiceUnavailable()
        val response = call("/api/benefit/card/v2/movements", account.sessionId, mapOf("email" to "", "benefitId" to WireCrypto.encrypt(account.benefitId.toString()), "num" to "100"))
        val movements = response.optJSONArray("data") ?: throw ServiceUnavailable()
        val txs = (0 until movements.length()).map { index ->
            val tx = movements.getJSONObject(index)
            val amount = tx.optString("total").replace(',', '.').toDoubleOrNull() ?: throw ServiceUnavailable()
            val merchant = tx.optString("establishment").ifBlank { tx.optString("description", "Movimento") }
            Movement(tx.optString("transactionDate"), merchant, amount, tx.optString("balance").replace(',', '.').toDoubleOrNull(), if (tx.isNull("effectiveDate")) null else tx.optString("effectiveDate"), tx.optBoolean("isRejected"), tx.optString("description"), tx.optString("currency", "EUR"))
        }
        return Snapshot(balance, txs)
    }
}
