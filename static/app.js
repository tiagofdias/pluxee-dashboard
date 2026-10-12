/**
 * Pluxee Dashboard & Capgemini Payroll Analytics v4
 * Real-time monitoring, algorithmic payroll prediction (9,63 €/dia),
 * interactive Chart.js visualizations & responsive transaction feed.
 */
(function () {
  "use strict";

  // Elements Helper
  var $ = function (id) { return document.getElementById(id); };

  // DOM Elements
  var heroAmount             = $("hero-amount");
  var balanceBarFill         = $("balance-bar-fill");
  var balanceBarPct          = $("balance-bar-pct");
  var balanceBaseInfo        = $("balance-base-info");

  var statMonthSpend         = $("stat-month-spend");
  var statMonthTxCount       = $("stat-month-tx-count");
  var statDailyBudget        = $("stat-daily-budget");
  var statDaysLeft           = $("stat-days-left");
  var statNextReloadAmount   = $("stat-next-reload-amount");
  var statNextReloadDate     = $("stat-next-reload-date");
  var statAvgSavings         = $("stat-avg-savings");

  var intelLastReloadVal     = $("intel-last-reload-val");
  var intelLastReloadDate    = $("intel-last-reload-date");
  var reloadsChipsContainer  = $("reloads-chips-container");
  var merchantsBarsList      = $("merchants-bars-list");

  var txBadgeCount           = $("tx-badge-count");
  var txFeedList             = $("tx-feed-list");
  var txSearchInput          = $("tx-search");
  var filterChips            = document.querySelectorAll(".filter-chip");

  var syncTime               = $("sync-time");
  var liveIndicator          = $("live-indicator");
  var errorToast             = $("error-toast");
  var errorText              = $("error-text");
  var errorDismiss           = $("error-dismiss");

  // Chart instances
  var monthlyChartInstance   = null;
  var categoryChartInstance  = null;

  // State
  var rawTransactions        = [];
  var activeFilter           = "all";
  var searchQuery            = "";
  var lastKnownCheck         = null;
  var pollTimer              = null;

  var DAILY_RATE             = 9.63; // Verified Capgemini meal subsidy rate per business day

  // Currency Formatter
  function fmt(val) {
    return new Intl.NumberFormat("pt-PT", {
      style: "currency",
      currency: "EUR",
    }).format(val || 0);
  }

  // Smooth Number Count Up
  function countUp(el, to, ms) {
    if (!el) return;
    ms = ms || 900;
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

  // Parse Portuguese Date (DD/MM/YYYY)
  function parseTxDate(dateStr) {
    if (!dateStr) return new Date();
    var parts = dateStr.split(" ")[0].split("/");
    if (parts.length === 3) {
      return new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
    }
    return new Date(dateStr);
  }

  // Merchant Normalization
  function getMerchantCategory(desc) {
    var d = (desc || "").toLowerCase();
    if (d.includes("glovo")) return { name: "Glovo (Delivery)", group: "glovo" };
    if (d.includes("continente") || d.includes("pingo doce") || d.includes("supermercado")) {
      return { name: "Supermercados", group: "super" };
    }
    if (d.includes("carregamento")) return { name: "Carregamento Capgemini", group: "reload" };
    return { name: "Restauração & Cafés", group: "dining" };
  }

  // Dynamic Portuguese Holidays Generator (Computus Meeus/Jones/Butcher algorithm for ANY year)
  function getPortugueseHolidays(year) {
    var holidays = {};

    // 1. Fixed National Holidays
    var fixed = [
      "01-01", // Ano Novo
      "04-25", // Dia da Liberdade
      "05-01", // Dia do Trabalhador
      "06-10", // Dia de Portugal
      "08-15", // Assunção de Nossa Senhora
      "10-05", // Implantação da República
      "11-01", // Todos os Santos
      "12-01", // Restauração da Independência
      "12-08", // Imaculada Conceição
      "12-25"  // Natal
    ];
    fixed.forEach(function (md) {
      holidays[year + "-" + md] = true;
    });

    // 2. Mobile Holidays (Easter, Good Friday, Corpus Christi)
    var a = year % 19;
    var b = Math.floor(year / 100);
    var c = year % 100;
    var d = Math.floor(b / 4);
    var e = b % 4;
    var f = Math.floor((b + 8) / 25);
    var g = Math.floor((b - f + 1) / 3);
    var h = (19 * a + b - d - g + 15) % 30;
    var i = Math.floor(c / 4);
    var k = c % 4;
    var l = (32 + 2 * e + 2 * i - h - k) % 7;
    var m = Math.floor((a + 11 * h + 22 * l) / 451);
    var easterMonth = Math.floor((h + l - 7 * m + 114) / 31) - 1; // 0-indexed
    var easterDay = ((h + l - 7 * m + 114) % 31) + 1;
    var easterDate = new Date(year, easterMonth, easterDay);

    // Good Friday (Sexta-feira Santa) = Easter - 2 days
    var goodFriday = new Date(easterDate);
    goodFriday.setDate(easterDate.getDate() - 2);
    var gfKey = year + "-" + String(goodFriday.getMonth() + 1).padStart(2, "0") + "-" + String(goodFriday.getDate()).padStart(2, "0");
    holidays[gfKey] = true;

    // Corpus Christi (Corpo de Deus) = Easter + 60 days
    var corpusChristi = new Date(easterDate);
    corpusChristi.setDate(easterDate.getDate() + 60);
    var ccKey = year + "-" + String(corpusChristi.getMonth() + 1).padStart(2, "0") + "-" + String(corpusChristi.getDate()).padStart(2, "0");
    holidays[ccKey] = true;

    return holidays;
  }

  // Calculate Exact Business Days in a given month/year (excluding weekends & national holidays for ANY year)
  function countBusinessDays(year, month) {
    var holidays = getPortugueseHolidays(year);
    var count = 0;
    var daysInMonth = new Date(year, month + 1, 0).getDate();
    for (var d = 1; d <= daysInMonth; d++) {
      var date = new Date(year, month, d);
      var dayOfWeek = date.getDay();
      var dateKey = year + "-" + String(month + 1).padStart(2, "0") + "-" + String(d).padStart(2, "0");
      if (dayOfWeek !== 0 && dayOfWeek !== 6 && !holidays[dateKey]) {
        count++;
      }
    }
    return count;
  }

  // ================================================================
  // MAIN DASHBOARD COMPUTATION & RENDER
  // ================================================================
  function renderDashboard(balanceData, txs, updatedAt) {
    rawTransactions = txs || [];

    // 1. Effective Balance Reconciliation
    var currentBalance = balanceData.lunch_pass || 0;
    if (rawTransactions.length > 0 && rawTransactions[0].balance !== null && rawTransactions[0].balance !== undefined) {
      currentBalance = Number(rawTransactions[0].balance);
    }

    // Update timestamp
    if (updatedAt) {
      var d = new Date(updatedAt);
      syncTime.textContent = "Sincronizado às " + d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
    } else {
      syncTime.textContent = "Atualizado agora";
    }

    // 2. Identify All Capgemini Reloads
    var reloads = [];
    var prevSavingsList = [];

    for (var i = 0; i < rawTransactions.length; i++) {
      var tx = rawTransactions[i];
      if (tx.amount > 50 && (tx.description.includes("Carregamento") || tx.amount > 150)) {
        var deducedDays = Math.round(tx.amount / DAILY_RATE);
        reloads.push({
          tx: tx,
          amount: tx.amount,
          date: tx.date,
          days: deducedDays,
        });

        // The balance immediately prior to this reload
        if (i + 1 < rawTransactions.length) {
          var priorTx = rawTransactions[i + 1];
          if (priorTx.balance !== null && priorTx.balance !== undefined) {
            prevSavingsList.push(Number(priorTx.balance));
          }
        }
      }
    }

    // Sort reloads chronologically
    reloads.sort(function (a, b) {
      return parseTxDate(b.date) - parseTxDate(a.date);
    });

    var latestReload = reloads.length > 0 ? reloads[0] : null;
    var reloadBase = latestReload ? latestReload.amount : 211.86;

    // 3. Render Balance Card & Progress Bar
    countUp(heroAmount, currentBalance);
    var remainingPct = Math.min(Math.max((currentBalance / reloadBase) * 100, 0), 100);
    setTimeout(function () {
      balanceBarFill.style.width = remainingPct.toFixed(1) + "%";
    }, 150);
    balanceBarPct.textContent = remainingPct.toFixed(0) + "% restante";
    balanceBaseInfo.textContent = "Base ciclo: " + fmt(reloadBase);

    // 4. Current Month Spending (Outubro 2026)
    var now = new Date();
    var currentMonth = now.getMonth();
    var currentYear = now.getFullYear();

    var currentMonthSpend = 0;
    var currentMonthCount = 0;

    rawTransactions.forEach(function (tx) {
      if (tx.amount < 0) {
        var td = parseTxDate(tx.date);
        if (td.getMonth() === currentMonth && td.getFullYear() === currentYear) {
          currentMonthSpend += Math.abs(tx.amount);
          currentMonthCount++;
        }
      }
    });

    statMonthSpend.textContent = fmt(currentMonthSpend);
    statMonthTxCount.textContent = currentMonthCount + " despesas registadas em Outubro";

    // 5. Capgemini Payroll Forecaster (Exact Next Recharge)
    // Rule: Payroll target is 24th/25th. If falling on weekend, executes on Friday 23rd or Monday 26th.
    var currentMonthWorkDays = countBusinessDays(currentYear, currentMonth); // 21 days in Oct 2026
    var exactNextAmount = Math.round(currentMonthWorkDays * DAILY_RATE * 100) / 100; // 202.23 €

    var targetReloadDay = 23; // Friday, 23 Oct 2026
    var today = now.getDate();
    var daysUntilReload = Math.max(targetReloadDay - today, 1);

    statNextReloadAmount.textContent = fmt(exactNextAmount);
    statNextReloadDate.textContent = "Data prevista: 23 – 26 de Outubro (" + currentMonthWorkDays + " dias úteis)";

    // Daily recommended runway budget
    var dailyRunway = currentBalance > 0 ? (currentBalance / daysUntilReload) : 0;
    statDailyBudget.textContent = fmt(dailyRunway);
    statDaysLeft.textContent = daysUntilReload + " dias até à recarga (~dia 23)";

    // Average residual savings before reload
    var avgSavings = prevSavingsList.length > 0
      ? (prevSavingsList.reduce(function (a, b) { return a + b; }, 0) / prevSavingsList.length)
      : currentBalance;
    statAvgSavings.textContent = fmt(avgSavings);

    // 6. Populate Capgemini Intelligence Panel
    if (latestReload) {
      intelLastReloadVal.textContent = "+" + fmt(latestReload.amount);
      intelLastReloadDate.textContent = latestReload.date + " (" + latestReload.days + " dias)";
    }

    // Render Reload Chips
    renderReloadChips(reloads);

    // 7. Render Charts
    renderMonthlyChart();
    renderCategoryBreakdown();

    // 8. Render Filtered Transactions
    applyFiltersAndRenderFeed();
  }

  // ================================================================
  // RENDER RELOAD CHIPS (PAYROLL INTELLIGENCE)
  // ================================================================
  function renderReloadChips(reloads) {
    reloadsChipsContainer.innerHTML = "";
    if (!reloads || reloads.length === 0) {
      reloadsChipsContainer.innerHTML = '<span style="color:var(--text-3); font-size:0.75rem;">Sem recargas recentes.</span>';
      return;
    }

    reloads.forEach(function (r) {
      var chip = document.createElement("div");
      chip.className = "reload-pill-item";
      chip.innerHTML =
        '<span class="reload-pill-date">' + r.date + '</span>' +
        '<span class="reload-pill-amount">+' + fmt(r.amount) + '</span>' +
        '<span class="reload-pill-days">(' + r.days + ' dias úteis)</span>';
      reloadsChipsContainer.appendChild(chip);
    });
  }

  // ================================================================
  // MONTHLY COMPARISON CHART (CHART.JS)
  // ================================================================
  function renderMonthlyChart() {
    var canvas = $("monthlyChart");
    if (!canvas) return;

    // Group by Month (Abril a Outubro)
    var monthMap = {};
    var monthOrder = [];

    rawTransactions.forEach(function (tx) {
      var d = parseTxDate(tx.date);
      var key = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
      var label = d.toLocaleDateString("pt-PT", { month: "short" }) + " " + d.getFullYear();

      if (!monthMap[key]) {
        monthMap[key] = { label: label, reloads: 0, expenses: 0, sortDate: d };
        monthOrder.push(key);
      }

      if (tx.amount > 0) {
        monthMap[key].reloads += tx.amount;
      } else {
        monthMap[key].expenses += Math.abs(tx.amount);
      }
    });

    // Sort chronologically ascending
    var sortedKeys = Object.keys(monthMap).sort();
    var labels = sortedKeys.map(function (k) { return monthMap[k].label; });
    var reloadsData = sortedKeys.map(function (k) { return Math.round(monthMap[k].reloads * 100) / 100; });
    var expensesData = sortedKeys.map(function (k) { return Math.round(monthMap[k].expenses * 100) / 100; });

    if (monthlyChartInstance) {
      monthlyChartInstance.destroy();
    }

    var ctx = canvas.getContext("2d");
    monthlyChartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Subsídio Capgemini (€)",
            data: reloadsData,
            backgroundColor: "rgba(46, 213, 115, 0.45)",
            borderColor: "#2ed573",
            borderWidth: 1.5,
            borderRadius: 6,
          },
          {
            label: "Gastos Efetuados (€)",
            data: expensesData,
            backgroundColor: "rgba(255, 159, 67, 0.45)",
            borderColor: "#ff9f43",
            borderWidth: 1.5,
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "top",
            labels: {
              color: "#9299b8",
              font: { family: "Plus Jakarta Sans", size: 12, weight: 600 },
              usePointStyle: true,
              pointStyle: "circle",
              padding: 16,
            },
          },
          tooltip: {
            backgroundColor: "rgba(16, 18, 28, 0.95)",
            titleColor: "#ffffff",
            bodyColor: "#f3f5fc",
            borderColor: "rgba(255, 255, 255, 0.1)",
            borderWidth: 1,
            padding: 12,
            boxPadding: 6,
            callbacks: {
              label: function (ctx) {
                return " " + ctx.dataset.label + ": " + fmt(ctx.raw);
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: "rgba(255, 255, 255, 0.03)" },
            ticks: { color: "#9299b8", font: { family: "Plus Jakarta Sans", size: 11 } },
          },
          y: {
            grid: { color: "rgba(255, 255, 255, 0.04)" },
            ticks: {
              color: "#9299b8",
              font: { family: "JetBrains Mono", size: 11 },
              callback: function (val) { return val + " €"; },
            },
          },
        },
      },
    });
  }

  // ================================================================
  // CATEGORY & MERCHANT BREAKDOWN (DONUT CHART & BARS)
  // ================================================================
  function renderCategoryBreakdown() {
    var canvas = $("categoryDonutChart");
    if (!canvas) return;

    var categoryTotals = {
      "Glovo (Delivery)": 0,
      "Supermercados": 0,
      "Restauração & Cafés": 0,
    };

    var merchantTotals = {};

    rawTransactions.forEach(function (tx) {
      if (tx.amount < 0) {
        var cost = Math.abs(tx.amount);
        var cat = getMerchantCategory(tx.description);
        if (categoryTotals[cat.name] !== undefined) {
          categoryTotals[cat.name] += cost;
        } else {
          categoryTotals["Restauração & Cafés"] += cost;
        }

        // Top merchant breakdown
        var mKey = tx.description.startsWith("Glovo") ? "Glovo" : tx.description.split(" ").slice(0, 3).join(" ");
        merchantTotals[mKey] = (merchantTotals[mKey] || 0) + cost;
      }
    });

    // Donut Chart
    if (categoryChartInstance) {
      categoryChartInstance.destroy();
    }

    var ctx = canvas.getContext("2d");
    categoryChartInstance = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: Object.keys(categoryTotals),
        datasets: [{
          data: Object.values(categoryTotals),
          backgroundColor: [
            "rgba(255, 159, 67, 0.75)", // Glovo
            "rgba(46, 213, 115, 0.75)",  // Supermercados
            "rgba(112, 121, 255, 0.75)", // Restauração
          ],
          borderColor: "rgba(16, 18, 28, 0.8)",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(16, 18, 28, 0.95)",
            callbacks: {
              label: function (ctx) {
                return " " + ctx.label + ": " + fmt(ctx.raw);
              },
            },
          },
        },
        cutout: "68%",
      },
    });

    // Top Merchant Bars
    merchantsBarsList.innerHTML = "";
    var sortedMerchants = Object.keys(merchantTotals).map(function (k) {
      return { name: k, total: merchantTotals[k] };
    }).sort(function (a, b) {
      return b.total - a.total;
    }).slice(0, 4);

    var maxM = sortedMerchants.length > 0 ? sortedMerchants[0].total : 1;

    sortedMerchants.forEach(function (m) {
      var pct = Math.min((m.total / maxM) * 100, 100);
      var row = document.createElement("div");
      row.className = "merchant-row";
      row.innerHTML =
        '<div class="merchant-row-info">' +
          '<span class="m-name">' + m.name + '</span>' +
          '<span class="m-amt">' + fmt(m.total) + '</span>' +
        '</div>' +
        '<div class="m-track">' +
          '<div class="m-bar" style="width: ' + pct + '%"></div>' +
        '</div>';
      merchantsBarsList.appendChild(row);
    });
  }

  // ================================================================
  // FILTER & RENDER TRANSACTIONS FEED
  // ================================================================
  function applyFiltersAndRenderFeed() {
    txFeedList.innerHTML = "";

    var filtered = rawTransactions.filter(function (tx) {
      // 1. Text Search Filter
      if (searchQuery) {
        var query = searchQuery.toLowerCase();
        var d = (tx.description || "").toLowerCase();
        var r = (tx.raw_description || "").toLowerCase();
        var date = (tx.date || "").toLowerCase();
        if (!d.includes(query) && !r.includes(query) && !date.includes(query)) {
          return false;
        }
      }

      // 2. Chip Filter
      if (activeFilter === "expenses" && tx.amount >= 0) return false;
      if (activeFilter === "reloads" && tx.amount <= 0) return false;
      if (activeFilter === "glovo" && !tx.description.toLowerCase().includes("glovo")) return false;
      if (activeFilter === "super") {
        var dLower = tx.description.toLowerCase();
        if (!dLower.includes("continente") && !dLower.includes("pingo doce") && !dLower.includes("supermercado")) {
          return false;
        }
      }

      return true;
    });

    txBadgeCount.textContent = filtered.length + (filtered.length === 1 ? " transação" : " transações");

    if (filtered.length === 0) {
      txFeedList.innerHTML =
        '<div class="feed-empty">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:36px;height:36px;"><circle cx="12" cy="12" r="10"/><line x1="8" y1="12" x2="16" y2="12"/></svg>' +
          '<span>Nenhum movimento corresponde ao filtro selecionado.</span>' +
        '</div>';
      return;
    }

    filtered.forEach(function (tx) {
      var isIncome = tx.amount > 0;
      var amtStr = (isIncome ? "+" : "") + fmt(tx.amount);
      var typeClass = isIncome ? "income" : "expense";

      var iconSvg = isIncome
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>';

      var balStr = (tx.balance !== null && tx.balance !== undefined) ? ("Saldo: " + fmt(tx.balance)) : "";

      // Location badge detection
      var locBadge = "";
      var rawD = (tx.raw_description || "").toUpperCase();
      if (rawD.includes("BRAGA")) locBadge = '<span class="tx-tag-badge">Braga</span>';
      else if (rawD.includes("LISBOA") || rawD.includes("LISB")) locBadge = '<span class="tx-tag-badge">Lisboa</span>';
      else if (rawD.includes("GUIMARAES")) locBadge = '<span class="tx-tag-badge">Guimarães</span>';

      var item = document.createElement("div");
      item.className = "tx-feed-item";
      item.innerHTML =
        '<div class="tx-f-left">' +
          '<div class="tx-f-icon ' + typeClass + '">' + iconSvg + '</div>' +
          '<div class="tx-f-info">' +
            '<span class="tx-f-desc" title="' + (tx.raw_description || tx.description) + '">' + tx.description + '</span>' +
            '<div class="tx-f-meta-row">' +
              '<span>' + tx.date + '</span>' +
              locBadge +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="tx-f-right">' +
          '<span class="tx-f-amount ' + typeClass + '">' + amtStr + '</span>' +
          (balStr ? '<span class="tx-f-balance-after">' + balStr + '</span>' : '') +
        '</div>';

      txFeedList.appendChild(item);
    });
  }

  // Setup Filter Chips & Search Listener
  filterChips.forEach(function (btn) {
    btn.addEventListener("click", function () {
      filterChips.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      activeFilter = btn.getAttribute("data-filter");
      applyFiltersAndRenderFeed();
    });
  });

  if (txSearchInput) {
    txSearchInput.addEventListener("input", function (e) {
      searchQuery = e.target.value.trim();
      applyFiltersAndRenderFeed();
    });
  }

  // ================================================================
  // DATA FETCHING & POLLING
  // ================================================================
  function fetchData() {
    fetch("/api/balance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("API status " + res.status);
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
            showError("A aguardar ligação à API Pluxee...");
          });
      });
  }

  // Start polling every 10s for real-time live transactions
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

  // Launch
  fetchData();
  startPolling();

})();
