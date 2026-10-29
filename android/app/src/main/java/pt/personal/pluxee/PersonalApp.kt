package pt.personal.pluxee

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.util.Locale

private val Mint = Color(0xFFB6F3CF)
private val Muted = Color(0xFF9DAFB4)
private val Scheme = darkColorScheme(primary = Mint, onPrimary = Color(0xFF08251B), background = Color(0xFF0C141B), surface = Color(0xFF15232B), onSurface = Color(0xFFEAF4F2), secondary = Color(0xFF8BCCE0))

@Composable
fun PersonalApp(model: AppViewModel, onBiometric: (Boolean) -> Unit, onAlerts: () -> Unit, onExport: (String) -> Unit) {
    MaterialTheme(colorScheme = Scheme, typography = Typography()) {
        Surface(Modifier.fillMaxSize()) {
            val state = model.state
            var page by remember { mutableIntStateOf(0) }
            var consent by remember { mutableStateOf(false) }
            if (consent) AlertDialog(onDismissRequest = { consent = false }, title = { Text("Alertas em segundo plano") }, text = { Text("Para verificar movimentos com a app bloqueada, uma autorização de sessão fica cifrada neste dispositivo pelo Android Keystore, acessível ao serviço de verificação sem biometria. A palavra-passe não é guardada.\n\nVerificações a cada cerca de 15 minutos; o Android pode adiá-las. A primeira consulta não envia movimentos antigos. Podes desativar ou sair para apagar a autorização.") }, confirmButton = { TextButton(onClick = { consent = false; onAlerts() }) { Text("Ativar alertas") } }, dismissButton = { TextButton(onClick = { consent = false }) { Text("Cancelar") } })
            Column(Modifier.fillMaxSize().safeDrawingPadding()) {
                if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (state.account == null && !state.demo) {
                    LoginScreen(state, model, onBiometric)
                } else {
                    Row(Modifier.fillMaxWidth().padding(24.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(if (state.demo) "DEMONSTRAÇÃO" else "O TEU ESPAÇO", color = Mint, fontSize = 11.sp, letterSpacing = 2.sp)
                            Text(if (state.demo) "Alex Martins" else state.account?.name?.ifBlank { "O teu cartão" }.orEmpty(), fontSize = 24.sp, fontWeight = FontWeight.SemiBold)
                        }
                        Text("✳", color = Mint, fontSize = 36.sp)
                    }
                    state.error?.let { ErrorCard(it, model::dismissError) }
                    val snapshot = state.snapshot
                    Box(Modifier.weight(1f)) {
                        when (page) {
                            0 -> Overview(snapshot, state.demo, model::refresh) { page = 1 }
                            1 -> MovementsScreen(snapshot?.movements.orEmpty(), onExport)
                            2 -> Analytics(snapshot?.movements.orEmpty())
                            else -> SettingsScreen(state, model, { onBiometric(true) }, { consent = true })
                        }
                    }
                    NavigationBar {
                        listOf("Resumo" to "◉", "Movimentos" to "↕", "Análise" to "▥", "Definições" to "⚙").forEachIndexed { index, item ->
                            NavigationBarItem(selected = page == index, onClick = { page = index }, icon = { Text(item.second, fontSize = 22.sp) }, label = { Text(item.first, fontSize = 10.sp) })
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LoginScreen(state: AppState, model: AppViewModel, onBiometric: (Boolean) -> Unit) {
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var show by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(28.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        item { Text("✳  Pluxee Personal", color = Mint, fontSize = 23.sp, fontWeight = FontWeight.SemiBold) }
        item { Spacer(Modifier.height(24.dp)); Text(if (state.locked) "Bem-vindo\nde volta." else "O teu cartão.\nMais simples.", fontSize = 40.sp, lineHeight = 46.sp, fontWeight = FontWeight.Medium) }
        item { Text(if (state.locked) "Desbloqueia o teu espaço privado." else "Saldo, movimentos e hábitos. Num espaço só teu.", color = Muted) }
        state.error?.let { item { ErrorCard(it, model::dismissError) } }
        if (state.locked) {
            item { Button(onClick = { onBiometric(false) }, modifier = Modifier.fillMaxWidth(), enabled = !state.loading) { Text("Desbloquear com biometria") } }
            item { TextButton(onClick = model::logout) { Text("Sair e entrar com email") } }
        } else {
            item { OutlinedTextField(email, { email = it }, Modifier.fillMaxWidth(), label = { Text("Email") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), enabled = !state.loading) }
            item { OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Palavra-passe") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), visualTransformation = if (show) VisualTransformation.None else PasswordVisualTransformation(), trailingIcon = { TextButton(onClick = { show = !show }) { Text(if (show) "Ocultar" else "Mostrar") } }, enabled = !state.loading) }
            item { Button(onClick = { model.login(email, password); password = "" }, enabled = !state.loading && email.isNotBlank() && password.isNotEmpty(), modifier = Modifier.fillMaxWidth().height(54.dp)) { Text("Entrar  ↗") } }
            item { Text("Usa os dados da app Pluxee Portugal. A palavra-passe é enviada à Pluxee e não é guardada.", color = Muted, fontSize = 12.sp) }
            item { OutlinedButton(onClick = model::demo, Modifier.fillMaxWidth(), enabled = !state.loading) { Text("Explorar com dados fictícios") } }
        }
        item { Text("Aplicação pessoal independente. Sem base de dados na cloud.", color = Muted, fontSize = 12.sp) }
    }
}

@Composable
private fun ErrorCard(message: String, dismiss: () -> Unit) {
    Card(Modifier.fillMaxWidth().padding(horizontal = 12.dp), colors = CardDefaults.cardColors(containerColor = Color(0xFF382C24))) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) { Text(message, Modifier.weight(1f), fontSize = 13.sp); TextButton(onClick = dismiss) { Text("OK") } }
    }
}

@Composable
private fun Overview(snapshot: Snapshot?, demo: Boolean, refresh: () -> Unit, movements: () -> Unit) {
    val month = YearMonth.now()
    LazyColumn(contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        item { Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF1D3E36)), shape = RoundedCornerShape(26.dp)) { Column(Modifier.fillMaxWidth().padding(26.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { Text("SALDO DISPONÍVEL", color = Mint, fontSize = 11.sp, letterSpacing = 2.sp); Text(snapshot?.let { euros(it.balance) } ?: "—", fontSize = 42.sp, fontWeight = FontWeight.SemiBold); Text("Cartão refeição   •   ${if (demo) "Dados fictícios" else "Pluxee Portugal"}", color = Mint, fontSize = 12.sp) } } }
        item { Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { Metric("Gasto este mês", euros(spending(snapshot?.movements.orEmpty(), month)), Modifier.weight(1f)); Metric("Mês anterior", euros(spending(snapshot?.movements.orEmpty(), month.minusMonths(1))), Modifier.weight(1f)) } }
        item { Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) { Text("Últimos movimentos", Modifier.weight(1f), fontSize = 20.sp); TextButton(onClick = movements) { Text("Ver todos") } } }
        items(snapshot?.movements.orEmpty().take(5)) { MovementRow(it) }
        if (snapshot != null && snapshot.movements.isEmpty()) item { Text("Sem movimentos disponíveis.", color = Muted) }
        item { Text(snapshot?.let { "Atualizado às " + java.text.SimpleDateFormat("HH:mm · dd/MM", Locale("pt", "PT")).format(java.util.Date(it.updatedAt)) } ?: "A consultar o cartão…", color = Muted, fontSize = 12.sp); if (!demo) TextButton(onClick = refresh) { Text("Atualizar agora ↻") } }
    }
}

@Composable
private fun Metric(label: String, value: String, modifier: Modifier = Modifier) { Card(modifier) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { Text(label, color = Muted, fontSize = 12.sp); Text(value, fontSize = 22.sp) } } }

@Composable
private fun MovementRow(movement: Movement) {
    var detail by remember { mutableStateOf(false) }
    if (detail) AlertDialog(onDismissRequest = { detail = false }, title = { Text(movement.merchant) }, text = { Text("${movement.date}\n${euros(movement.amount)}\n${if (movement.rejected) "Rejeitado" else "Efetuado"}" + (movement.historicalBalance?.let { "\nSaldo após movimento: ${euros(it)}" } ?: "")) }, confirmButton = { TextButton(onClick = { detail = false }) { Text("Fechar") } })
    Card(onClick = { detail = true }, Modifier.fillMaxWidth()) { Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) { Text(if (movement.amount > 0) "↙" else "↗", color = Mint, fontSize = 24.sp, modifier = Modifier.padding(end = 14.dp)); Column(Modifier.weight(1f)) { Text(movement.merchant, maxLines = 2, fontSize = 14.sp); Text(movement.date + if (movement.rejected) " · Rejeitado" else "", color = Muted, fontSize = 12.sp) }; Text(euros(movement.amount), color = if (movement.amount > 0) Mint else MaterialTheme.colorScheme.onSurface, fontWeight = FontWeight.SemiBold) } }
}

@Composable
private fun MovementsScreen(movements: List<Movement>, export: (String) -> Unit) {
    var query by remember { mutableStateOf("") }
    var filter by remember { mutableIntStateOf(0) }
    val visible = movements.filter { it.merchant.contains(query, ignoreCase = true) && (filter == 0 || (filter == 1 && it.amount < 0) || (filter == 2 && it.amount > 0)) }
    LazyColumn(contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("Os teus movimentos", fontSize = 26.sp) }
        item { OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text("Pesquisar estabelecimento") }, singleLine = true) }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf("Todos", "Pagamentos", "Créditos").forEachIndexed { i, title -> FilterChip(selected = filter == i, onClick = { filter = i }, label = { Text(title) }) } } }
        item { Row(verticalAlignment = Alignment.CenterVertically) { Text("${visible.size} movimentos", Modifier.weight(1f), color = Muted); TextButton(onClick = { export(exportCsv(visible)) }, enabled = visible.isNotEmpty()) { Text("Exportar CSV") } } }
        items(visible) { MovementRow(it) }
        if (visible.isEmpty()) item { Text("Não há movimentos para mostrar.", color = Muted) }
    }
}

@Composable
private fun Analytics(movements: List<Movement>) {
    val month = YearMonth.now()
    val months = (5 downTo 0).map { month.minusMonths(it.toLong()) }
    val max = months.maxOf { spending(movements, it) }.coerceAtLeast(1.0)
    val merchants = movements.filter { !it.rejected && it.amount < 0 && parseDay(it.date)?.let { day -> YearMonth.from(day) == month } == true }.groupBy { it.merchant }.mapValues { (_, rows) -> rows.sumOf { -it.amount } }.toList().sortedByDescending { it.second }
    LazyColumn(contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item { Text("Percebe os teus hábitos", fontSize = 26.sp); Text("Despesas nos últimos seis meses", color = Muted) }
        items(months) { period -> val amount = spending(movements, period); Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { Row { Text(period.format(DateTimeFormatter.ofPattern("MMM yyyy", Locale("pt", "PT"))), Modifier.weight(1f)); Text(euros(amount)) }; LinearProgressIndicator(progress = { (amount / max).toFloat() }, modifier = Modifier.fillMaxWidth().height(8.dp), color = Mint) } }
        item { Text("Onde gastaste este mês", fontSize = 20.sp) }
        items(merchants.take(10)) { (name, amount) -> Metric(name, euros(amount), Modifier.fillMaxWidth()) }
        item { Text("A análise usa apenas o histórico disponível neste dispositivo. A API pode disponibilizar uma janela limitada de movimentos.", color = Muted, fontSize = 12.sp) }
    }
}

@Composable
private fun SettingsScreen(state: AppState, model: AppViewModel, biometric: () -> Unit, alerts: () -> Unit) {
    LazyColumn(contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        item { Text("Ao teu ritmo", fontSize = 26.sp); Text("Segurança e notificações", color = Muted) }
        if (state.demo) item { Text("A demonstração usa apenas dados fictícios. Entra para ativar biometria e alertas.", color = Mint) }
        item { Setting("Desbloqueio biométrico", "Protege a sessão com a biometria forte do Android.", state.biometric, !state.demo && !state.loading) { if (it) biometric() else model.disableBiometric() } }
        item { Setting("Novos movimentos", "Verificações no dispositivo, aproximadamente a cada 15 minutos. Podem ser adiadas pelo Android.", state.alerts, !state.demo && !state.loading) { if (it) alerts() else model.disableAlerts() } }
        item { Setting("Detalhes nas notificações", "Mostrar estabelecimento e montante. Desativado: mensagem discreta.", state.showDetails, !state.demo && state.alerts) { model.details(it) } }
        item { Card { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) { Text("Os teus dados ficam contigo", color = Mint, fontSize = 18.sp); Text("A app consulta diretamente a Pluxee. A sessão e o histórico são cifrados no dispositivo. A palavra-passe nunca é guardada. Sair apaga os dados locais e termina as verificações.", color = Muted); Text("A biometria desbloqueia uma sessão existente; quando a Pluxee a expirar, será necessário entrar novamente.", color = Muted, fontSize = 12.sp) } } }
        item { OutlinedButton(onClick = model::logout, enabled = !state.loading, modifier = Modifier.fillMaxWidth()) { Text(if (state.demo) "Sair da demonstração" else "Sair e apagar dados locais") } }
        item { Text("Pluxee Personal · 1.0.0\nProjeto independente, sem afiliação à Pluxee.", color = Muted, fontSize = 12.sp) }
    }
}

@Composable
private fun Setting(title: String, description: String, checked: Boolean, enabled: Boolean, change: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) { Column(Modifier.weight(1f)) { Text(title, fontWeight = FontWeight.SemiBold); Text(description, color = Muted, fontSize = 12.sp) }; Switch(checked, change, enabled = enabled) }
}
