package pt.personal.pluxee

import org.json.JSONArray
import org.json.JSONObject
import java.math.BigDecimal
import java.math.RoundingMode
import java.security.MessageDigest
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

private val dates = DateTimeFormatter.ofPattern("dd/MM/yyyy")
fun euros(value: Double): String = java.text.NumberFormat.getCurrencyInstance(Locale.forLanguageTag("pt-PT")).format(value)
fun parseDay(value: String): LocalDate? = runCatching { LocalDate.parse(value.substringBefore(' '), dates) }.getOrNull()

data class Account(val sessionId: String, val userId: Long, val benefitId: Long, val cardReference: String, val name: String) {
    fun toJson() = JSONObject().put("session", sessionId).put("user", userId).put("benefit", benefitId).put("card", cardReference).put("name", name)
    fun identity(): String = sha256("$userId|$benefitId")
    override fun toString() = "Account(redacted)"
    companion object {
        fun fromJson(json: JSONObject) = Account(json.getString("session"), json.getLong("user"), json.getLong("benefit"), json.getString("card"), json.optString("name", "A tua conta"))
    }
}

data class Movement(val date: String, val merchant: String, val amount: Double, val historicalBalance: Double?, val effectiveDate: String?, val rejected: Boolean = false, val rawDescription: String = "", val currency: String = "EUR") {
    fun toJson(): JSONObject = JSONObject().put("date", date).put("merchant", merchant).put("amount", amount).put("balance", historicalBalance ?: JSONObject.NULL).put("effective", effectiveDate ?: JSONObject.NULL).put("rejected", rejected).put("raw", rawDescription).put("currency", currency)
    fun baseIdentity(): String = sha256(listOf(date.trim(), merchant.trim().lowercase(Locale.ROOT), BigDecimal.valueOf(amount).setScale(2, RoundingMode.HALF_UP).toPlainString(), currency).joinToString("|"))
    companion object {
        fun fromJson(json: JSONObject) = Movement(json.getString("date"), json.getString("merchant"), json.getDouble("amount"), if (json.isNull("balance")) null else json.getDouble("balance"), if (json.isNull("effective")) null else json.getString("effective"), json.optBoolean("rejected"), json.optString("raw"), json.optString("currency", "EUR"))
    }
}

data class Snapshot(val balance: Double, val movements: List<Movement>, val updatedAt: Long = System.currentTimeMillis()) {
    fun toJson(): JSONObject = JSONObject().put("balance", balance).put("updated", updatedAt).put("movements", JSONArray(movements.map { it.toJson() }))
    companion object {
        fun fromJson(json: JSONObject): Snapshot {
            val txs = json.getJSONArray("movements")
            return Snapshot(json.getDouble("balance"), (0 until txs.length()).map { Movement.fromJson(txs.getJSONObject(it)) }, json.getLong("updated"))
        }
    }
}

fun sha256(value: String): String = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

/** Metadata never identifies a purchase. Occurrence suffixes preserve identical genuine purchases. */
object MovementLedger {
    fun keyed(movements: List<Movement>): List<Pair<String, Movement>> {
        val occurrences = mutableMapOf<String, Int>()
        return movements.map { tx ->
            val base = tx.baseIdentity()
            val count = (occurrences[base] ?: 0) + 1
            occurrences[base] = count
            "$base:$count" to tx
        }
    }
    fun merge(old: List<Movement>, fresh: List<Movement>): List<Movement> {
        val incoming = keyed(fresh)
        val seen = incoming.map { it.first }.toSet()
        return (incoming + keyed(old).filter { it.first !in seen }).map { it.second }
            .sortedByDescending { parseDay(it.date) ?: LocalDate.MIN }.take(3000)
    }
    fun newMovements(previous: Set<String>?, latestDate: LocalDate?, fresh: List<Movement>): List<Pair<String, Movement>> {
        if (previous == null) return emptyList() // First synchronization is a silent baseline.
        return keyed(fresh.filterNot { it.rejected }).filter { (key, tx) -> key !in previous && !tx.rejected && (latestDate == null || (parseDay(tx.date) ?: LocalDate.MIN) >= latestDate) }
    }
}
