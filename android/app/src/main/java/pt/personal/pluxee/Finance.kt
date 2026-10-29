package pt.personal.pluxee

import java.time.YearMonth

fun spending(movements: List<Movement>, month: YearMonth): Double = movements.filter { !it.rejected && it.amount < 0 && parseDay(it.date)?.let { day -> YearMonth.from(day) == month } == true }.sumOf { -it.amount }

fun exportCsv(movements: List<Movement>): String {
    fun cell(value: String): String {
        val safe = if (value.firstOrNull() in listOf('=', '+', '-', '@', '\t', '\r')) "'" + value else value
        return "\"${safe.replace("\"", "\"\"")}\""
    }
    return "\uFEFFData;Estabelecimento;Montante EUR;Estado\r\n" + movements.joinToString("\r\n") {
        listOf(it.date, it.merchant, String.format(java.util.Locale.ROOT, "%.2f", it.amount), if (it.rejected) "Rejeitado" else "Efetuado").joinToString(";") { value -> cell(value) }
    }
}
