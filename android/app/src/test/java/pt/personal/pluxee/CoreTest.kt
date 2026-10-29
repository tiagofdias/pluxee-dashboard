package pt.personal.pluxee

import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.YearMonth

class CoreTest {
    private val purchase = Movement("29/10/2026", "EXAMPLE CAFE", -5.50, 28.64, null)
    @Test fun officialWireVector() { assertEquals("ZRaZftXG+9c78E2US+g0Ow==j1ce6NnE6HKape1N", WireCrypto.encrypt("Test", "j1ce6NnE6HKape1N")) }
    @Test fun randomIvPerRequest() { assertNotEquals(WireCrypto.encrypt("same"), WireCrypto.encrypt("same")) }
    @Test fun firstSyncIsSilent() { assertTrue(MovementLedger.newMovements(null, null, listOf(purchase)).isEmpty()) }
    @Test fun settlementChangesNeverRealert() {
        val seen = MovementLedger.keyed(listOf(purchase)).map { it.first }.toSet()
        val settled = purchase.copy(historicalBalance = 99.0, effectiveDate = "2026-10-30", rawDescription = "Changed")
        assertTrue(MovementLedger.newMovements(seen, LocalDate.of(2026, 10, 29), listOf(settled)).isEmpty())
        assertEquals(1, MovementLedger.merge(listOf(purchase), listOf(settled)).size)
        assertEquals(99.0, MovementLedger.merge(listOf(purchase), listOf(settled)).single().historicalBalance!!, 0.0)
    }
    @Test fun identicalGenuinePurchasesArePreserved() {
        val seen = MovementLedger.keyed(listOf(purchase)).map { it.first }.toSet()
        assertEquals(1, MovementLedger.newMovements(seen, null, listOf(purchase, purchase)).size)
        assertEquals(2, MovementLedger.merge(listOf(purchase), listOf(purchase, purchase)).size)
    }
    @Test fun rejectedAndBackfilledRowsDoNotAlert() {
        assertTrue(MovementLedger.newMovements(emptySet(), LocalDate.of(2026, 10, 29), listOf(purchase.copy(rejected = true), purchase.copy(date = "28/10/2026"))).isEmpty())
    }
    @Test fun spendingIgnoresRejectedAndCredits() {
        assertEquals(5.5, spending(listOf(purchase, purchase.copy(rejected = true), purchase.copy(amount = 100.0)), YearMonth.of(2026, 10)), 0.001)
    }
    @Test fun csvNeutralizesSpreadsheetFormulaAndEscapesQuotes() {
        val csv = exportCsv(listOf(purchase.copy(merchant = "=HYPERLINK(\"example\")")))
        assertTrue(csv.contains("\"'=HYPERLINK(\"\"example\"\")\""))
    }
    @Test fun encryptedRecordModelsRoundTrip() {
        val snapshot = Snapshot(123.45, listOf(purchase), 42)
        assertEquals(snapshot, Snapshot.fromJson(snapshot.toJson()))
    }
}
