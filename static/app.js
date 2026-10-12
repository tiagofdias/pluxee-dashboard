/**
 * Pluxee Dashboard — Full-Width Financial Analytics v3
 * Real-time monitoring, monthly metrics, spend breakdown & interactive search.
 */
(function () {
  "use strict";

  // Elements
  var $ = function (id) { return document.getElementById(id); };

  var heroAmount         = $("hero-amount");
  var balanceBarFill     = $("balance-bar-fill");
  var balanceBarPct      = $("balance-bar-pct");
  var balanceReloadRef   = $("balance-reload-ref");

  var statMonthSpend     = $("stat-month-spend");
  var statMonthTxCount   = $("stat-month-tx-count");
  var statDailyBudget    = $("stat-daily-budget");
  var statDaysLeft       = $("stat-days-left");
  var statLastReload     = $("stat-last-reload");
  var statLastReloadDate = $("stat-last-reload-date");

  var txTotalBadge       = $("tx-total-badge");
  var txList             = $("tx-list");
  var txSearchInput      = $("tx-search-input");
  var merchantList       = $("merchant-list");

  var metricAvgTx        = $("metric-avg-tx");
  var metricBiggestSpend = $("metric-biggest-spend");
  var metricActiveDays   = $("metric-active-days");
  var metricNextReload   = $("metric-next-reload");

  var syncTime           = $("sync-time");
  var liveIndicator      = $("live-indicator");
  var errorToast         = $("error-toast");
  var errorText          = $("error-text");
  var errorDismiss       = $("error-dismiss");

  var rawTransactions    = [];
  var lastKnownCheck     = null;
  var pollTimer          = null;

  // Currency Formatter
  function fmt(val) {
    return new Intl.NumberFormat("pt-PT", {
      style: "currency",
      currency: "EUR",
    }).format(val || 0);
  }

  // Count up animation
  function countUp(el, to, ms) {
    ms = ms || 1000;
    var t0 = performance.now();
    (function tick(now) {
      var p = Math.min((now - t0) / ms, 1);
      var e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(to * e);
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  }

  function showError(msg) {
    if (errorText) errorText.textContent = msg;
    if (errorToast) errorToast.classList.remove("hidden");
  }

  if (errorDismiss) {
    errorDismiss.addEventListener("click", function () {
      errorToast.classList.add("hidden");
    });
  }

  // Parse Portuguese Date: DD/MM/YYYY
  function parseDate(dStr) {
    if (!dStr) return new Date();
    var parts = dStr.split(" ")[0].split("/");
    if (parts.length === 3) {
      return new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
    }
    return new Date(dStr);
  }

  // Clean Merchant Name
  function cleanMerchantName(desc) {
    if (!desc) return "Outros";
    var d = desc.trim();
    if (d.startsWith("Glovo")) return "Glovo";
    if (d.includes("PINGO DOCE")) return "Pingo Doce";
    if (d.includes("MCDONALDS")) return "McDonald's";
    if (d.includes("Carregamento")) return "Carregamento Empresa";
    // Return first 2-3 words capitalized
    return d.split(" ").slice(0, 3).join(" ");
  }

  // Main Render Function
  function renderDashboard(balanceData, txs, updatedAt) {
    rawTransactions = txs || [];

    // Reconcile effective lunch pass balance
    var lunchBalance = balanceData.lunch_pass || 0;
    if (rawTransactions.length > 0 && rawTransactions[0].balance !== null && rawTransactions[0].balance !== undefined) {
      lunchBalance = Number(rawTransactions[0].balance);
    }

    // 1. Sync timestamp
    if (updatedAt) {
      var d = new Date(updatedAt);
      syncTime.textContent = "Sincronizado às " + d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
    } else {
      syncTime.textContent = "Atualizado agora";
    }

    // 2. Find last reload (income > 50€)
    var lastReloadTx = null;
    for (var i = 0; i < rawTransactions.length; i++) {
      if (rawTransactions[i].amount > 50) {
        lastReloadTx = rawTransactions[i];
        break;
      }
    }
    var reloadBase = lastReloadTx ? lastReloadTx.amount : 211.86;
    if (lastReloadTx) {
      statLastReload.textContent = "+" + fmt(lastReloadTx.amount);
      statLastReloadDate.textContent = lastReloadTx.description + " · " + lastReloadTx.date;
    } else {
      statLastReload.textContent = "—";
      statLastReloadDate.textContent = "Sem registo recente";
    }

    // 3. Render Available Balance & Progress Bar
    countUp(heroAmount, lunchBalance);
    var remainingPct = Math.min(Math.max((lunchBalance / reloadBase) * 100, 0), 100);
    setTimeout(function () {
      balanceBarFill.style.width = remainingPct.toFixed(1) + "%";
    }, 150);
    balanceBarPct.textContent = remainingPct.toFixed(0) + "% restante";
    balanceReloadRef.textContent = "Base: " + fmt(reloadBase);

    // 4. Current Month Spend Analytics
    // Determine the active month from the latest transaction or current date
    var now = new Date();
    var targetMonth = now.getMonth();
    var targetYear = now.getFullYear();
    if (rawTransactions.length > 0) {
      var latestDate = parseDate(rawTransactions[0].date);
      targetMonth = latestDate.getMonth();
      targetYear = latestDate.getFullYear();
    }

    var monthNames = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
    var currentMonthName = monthNames[targetMonth];

    var currentMonthExpenses = 0;
    var currentMonthExpenseCount = 0;
    var maxExpenseThisMonth = 0;
    var activeDaysMap = {};
    var merchantTotals = {};

    rawTransactions.forEach(function (tx) {
      if (tx.amount < 0) {
        var tDate = parseDate(tx.date);
        var cost = Math.abs(tx.amount);

        // Group by merchant across recent history
        var mName = cleanMerchantName(tx.description);
        merchantTotals[mName] = (merchantTotals[mName] || 0) + cost;

        // Current month filter
        if (tDate.getMonth() === targetMonth && tDate.getFullYear() === targetYear) {
          currentMonthExpenses += cost;
          currentMonthExpenseCount++;
          if (cost > maxExpenseThisMonth) {
            maxExpenseThisMonth = cost;
          }
          var dayKey = tDate.getDate();
          activeDaysMap[dayKey] = true;
        }
      }
    });

    statMonthSpend.textContent = fmt(currentMonthExpenses);
    statMonthTxCount.textContent = currentMonthExpenseCount + " despesas em " + currentMonthName;

    // 5. Daily Runway Budget
    // Company reloads are usually around the 24th
    var reloadDayOfMonth = 24;
    var todayDay = now.getDate();
    var daysUntilReload = reloadDayOfMonth > todayDay ? (reloadDayOfMonth - todayDay) : (30 - todayDay + reloadDayOfMonth);
    if (daysUntilReload <= 0) daysUntilReload = 1;

    var dailyBudget = lunchBalance > 0 ? (lunchBalance / daysUntilReload) : 0;
    statDailyBudget.textContent = fmt(dailyBudget);
    statDaysLeft.textContent = daysUntilReload + " dias até à recarga (~dia " + reloadDayOfMonth + ")";

    // 6. Additional Card Metrics Panel
    var avgTx = currentMonthExpenseCount > 0 ? (currentMonthExpenses / currentMonthExpenseCount) : 0;
    metricAvgTx.textContent = fmt(avgTx);
    metricBiggestSpend.textContent = maxExpenseThisMonth > 0 ? fmt(maxExpenseThisMonth) : "—";
    var activeDaysCount = Object.keys(activeDaysMap).length;
    metricActiveDays.textContent = activeDaysCount + " dias";
    metricNextReload.textContent = "~24 de " + currentMonthName;

    // 7. Render Top Merchants
    renderTopMerchants(merchantTotals);

    // 8. Render Transactions List
    filterAndRenderTransactions("");
  }

  // Render Top Merchants with Progress Bars
  function renderTopMerchants(merchantTotals) {
    merchantList.innerHTML = "";
    var sorted = Object.keys(merchantTotals).map(function (k) {
      return { name: k, total: merchantTotals[k] };
    }).sort(function (a, b) {
      return b.total - a.total;
    }).slice(0, 5);

    if (sorted.length === 0) {
      merchantList.innerHTML = '<p style="color:var(--text-3); font-size:0.8rem;">Sem dados suficientes.</p>';
      return;
    }

    var highest = sorted[0].total || 1;

    sorted.forEach(function (m) {
      var pct = Math.min((m.total / highest) * 100, 100);
      var item = document.createElement("div");
      item.className = "merchant-item";
      item.innerHTML =
        '<div class="merchant-info">' +
          '<span class="merchant-name">' + m.name + '</span>' +
          '<span class="merchant-total">' + fmt(m.total) + '</span>' +
        '</div>' +
        '<div class="merchant-bar-track">' +
          '<div class="merchant-bar-fill" style="width: ' + pct + '%"></div>' +
        '</div>';
      merchantList.appendChild(item);
    });
  }

  // Filter & Render Transactions
  function filterAndRenderTransactions(filterQuery) {
    txList.innerHTML = "";
    var query = (filterQuery || "").toLowerCase().trim();

    var filtered = rawTransactions.filter(function (tx) {
      if (!query) return true;
      var desc = (tx.description || "").toLowerCase();
      var raw = (tx.raw_description || "").toLowerCase();
      var date = (tx.date || "").toLowerCase();
      return desc.includes(query) || raw.includes(query) || date.includes(query);
    });

    txTotalBadge.textContent = filtered.length + (filtered.length === 1 ? " transação" : " transações");

    if (filtered.length === 0) {
      txList.innerHTML =
        '<div class="tx-empty-state">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:36px; height:36px;"><circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/></svg>' +
          '<span>Nenhum movimento encontrado.</span>' +
        '</div>';
      return;
    }

    filtered.forEach(function (tx) {
      var isIncome = tx.amount > 0;
      var amtStr = (isIncome ? "+" : "") + fmt(tx.amount);
      var typeClass = isIncome ? "is-income" : "is-expense";

      var iconHtml = isIncome
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="width:16px;height:16px;"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="width:16px;height:16px;"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>';

      var balStr = (tx.balance !== null && tx.balance !== undefined) ? ("Saldo: " + fmt(tx.balance)) : "";

      var row = document.createElement("div");
      row.className = "tx-item";
      row.innerHTML =
        '<div class="tx-left">' +
          '<div class="tx-avatar ' + typeClass + '">' + iconHtml + '</div>' +
          '<div class="tx-details">' +
            '<span class="tx-title" title="' + (tx.raw_description || tx.description) + '">' + tx.description + '</span>' +
            '<div class="tx-meta">' +
              '<span>' + tx.date + '</span>' +
              (tx.raw_description && tx.raw_description.includes("BRAGA") ? '<span class="tx-meta-badge">Braga</span>' : '') +
              (tx.raw_description && tx.raw_description.includes("LISBOA") ? '<span class="tx-meta-badge">Lisboa</span>' : '') +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="tx-right">' +
          '<span class="tx-amount ' + typeClass + '">' + amtStr + '</span>' +
          (balStr ? '<span class="tx-running-balance">' + balStr + '</span>' : '') +
        '</div>';

      txList.appendChild(row);
    });
  }

  // Live Search listener
  if (txSearchInput) {
    txSearchInput.addEventListener("input", function (e) {
      filterAndRenderTransactions(e.target.value);
    });
  }

  // Fetch Data Routine
  function fetchData() {
    fetch("/api/balance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("API error");
        return res.json();
      })
      .then(function (data) {
        if (data.success) {
          renderDashboard(data.balance, data.transactions, data.updated_at);
          if (data.cached && data.warning) showError(data.warning);
        }
      })
      .catch(function () {
        // Fallback to static data.json
        fetch("./data.json?cb=" + Date.now())
          .then(function (res) { return res.json(); })
          .then(function (data) {
            if (data.balance && data.transactions) {
              renderDashboard(data.balance, data.transactions, data.updated_at);
            }
          })
          .catch(function () {
            showError("Sem ligação aos dados em tempo real. A tentar reconectar...");
          });
      });
  }

  // Polling for 24/7 background monitor updates
  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function () {
      fetch("/api/notifications/status")
        .then(function (r) { return r.json(); })
        .then(function (status) {
          if (status.last_check && status.last_check !== lastKnownCheck) {
            lastKnownCheck = status.last_check;
            fetchData();
          }
        })
        .catch(function () {});
    }, 10000);
  }

  // Startup
  fetchData();
  startPolling();

})();
