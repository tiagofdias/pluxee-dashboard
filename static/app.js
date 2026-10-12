/**
 * Pluxee Balance Dashboard — Frontend Logic v2
 * Auto-loads balance data. No login view needed.
 */
(function () {
  "use strict";

  /* ---- DOM ---- */
  var $ = function (s) { return document.getElementById(s); };

  var heroAmount      = $("hero-amount");
  var heroUpdated     = $("hero-updated");
  var heroBarFill     = $("hero-bar-fill");
  var heroShimmer     = $("hero-shimmer");
  var liveIndicator   = $("live-indicator");

  var statLastSpend   = $("stat-last-spend-val");
  var statTxCount     = $("stat-tx-count-val");
  var statDailyAvg    = $("stat-daily-avg-val");

  var txCount         = $("tx-count");
  var txList          = $("tx-list");
  var txEmpty         = $("tx-empty");

  var errorToast      = $("error-toast");
  var errorText       = $("error-text");
  var errorDismiss    = $("error-dismiss");

  var pollTimer       = null;
  var lastKnownCheck  = null;
  var hasRendered     = false;
  var MAX_BALANCE     = 210; // max expected monthly for bar width calc

  /* ---- Helpers ---- */
  function fmt(val) {
    return new Intl.NumberFormat("pt-PT", {
      style: "currency",
      currency: "EUR",
    }).format(val);
  }

  function countUp(el, to, ms) {
    ms = ms || 1200;
    var t0 = performance.now();
    (function tick(now) {
      var p = Math.min((now - t0) / ms, 1);
      var e = 1 - Math.pow(1 - p, 3); // ease-out cubic
      el.textContent = fmt(to * e);
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  }

  function showError(msg) {
    errorText.textContent = msg;
    errorToast.classList.remove("hidden");
  }

  function hideError() {
    errorToast.classList.add("hidden");
  }

  if (errorDismiss) {
    errorDismiss.addEventListener("click", hideError);
  }

  function formatTimestamp(dateStr) {
    try {
      var d = new Date(dateStr);
      var time = d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });
      var date = d.toLocaleDateString("pt-PT", { day: "numeric", month: "short" });
      return time + " · " + date;
    } catch (_) {
      return dateStr;
    }
  }

  /* ---- Load data ---- */
  function loadData() {
    // 1. Try server API first (Render deployment)
    fetch("/api/balance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("API error " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (data.success) {
          renderBalance(data.balance, data.transactions, data.updated_at);
          if (data.cached && data.warning) {
            showError(data.warning);
          }
        }
      })
      .catch(function () {
        // 2. Fallback to static data.json
        fetch("./data.json?cb=" + Date.now())
          .then(function (res) {
            if (!res.ok) throw new Error("No data");
            return res.json();
          })
          .then(function (data) {
            if (data.balance && data.transactions) {
              renderBalance(data.balance, data.transactions, data.updated_at);
            }
          })
          .catch(function () {
            showError("Não foi possível carregar os dados. A tentar novamente...");
            // Set live indicator to offline
            if (liveIndicator) {
              liveIndicator.querySelector(".live-dot").style.background = "#ff6b6b";
              liveIndicator.querySelector(".live-dot").style.boxShadow = "0 0 10px rgba(255, 107, 107, 0.6)";
              liveIndicator.querySelector(".live-label").textContent = "Offline";
              liveIndicator.querySelector(".live-label").style.color = "#ff6b6b";
              liveIndicator.style.background = "rgba(255, 107, 107, 0.08)";
              liveIndicator.style.borderColor = "rgba(255, 107, 107, 0.15)";
            }
          });
      });
  }

  /* ---- Render Balance ---- */
  function renderBalance(b, txs, updatedAt) {
    // Reconcile effective lunch pass balance
    var lunchVal = b.lunch_pass || 0;
    if (txs && txs.length > 0) {
      var latest = txs[0];
      if (latest.balance !== null && latest.balance !== undefined) {
        lunchVal = Number(latest.balance);
      }
    }

    // Update timestamp
    if (updatedAt) {
      heroUpdated.textContent = formatTimestamp(updatedAt);
    } else {
      heroUpdated.textContent = formatTimestamp(new Date().toISOString());
    }

    // Animate the balance amount
    if (!hasRendered) {
      countUp(heroAmount, lunchVal);
      hasRendered = true;
    } else {
      heroAmount.textContent = fmt(lunchVal);
    }

    // Animate the progress bar
    var barPct = Math.min((lunchVal / MAX_BALANCE) * 100, 100);
    setTimeout(function () {
      heroBarFill.style.width = barPct + "%";
    }, 200);

    // Hide shimmer after first load
    if (heroShimmer) {
      setTimeout(function () {
        heroShimmer.style.display = "none";
      }, 2000);
    }

    // Stats
    computeStats(txs || []);

    // Transactions
    renderTransactions(txs || []);

    // Reset live indicator to active
    if (liveIndicator) {
      liveIndicator.querySelector(".live-dot").style.background = "";
      liveIndicator.querySelector(".live-dot").style.boxShadow = "";
      liveIndicator.querySelector(".live-label").textContent = "Em tempo real";
      liveIndicator.querySelector(".live-label").style.color = "";
      liveIndicator.style.background = "";
      liveIndicator.style.borderColor = "";
    }
  }

  /* ---- Compute Stats ---- */
  function computeStats(txs) {
    // Last spend (most recent negative transaction)
    var lastSpend = null;
    for (var i = 0; i < txs.length; i++) {
      if (txs[i].amount < 0) {
        lastSpend = txs[i];
        break;
      }
    }
    if (lastSpend) {
      statLastSpend.textContent = fmt(Math.abs(lastSpend.amount));
    } else {
      statLastSpend.textContent = "—";
    }

    // Transaction count
    statTxCount.textContent = txs.length;

    // Daily average spend (only negatives)
    var totalSpend = 0;
    var spendCount = 0;
    var dates = {};
    for (var j = 0; j < txs.length; j++) {
      if (txs[j].amount < 0) {
        totalSpend += Math.abs(txs[j].amount);
        spendCount++;
        // Count unique dates
        var txDate = txs[j].date ? txs[j].date.split(" ")[0] : "";
        if (txDate) dates[txDate] = true;
      }
    }
    var uniqueDays = Object.keys(dates).length || 1;
    if (spendCount > 0) {
      statDailyAvg.textContent = fmt(totalSpend / uniqueDays);
    } else {
      statDailyAvg.textContent = "—";
    }
  }

  /* ---- Render Transactions ---- */
  function renderTransactions(txs) {
    txList.innerHTML = "";

    if (txs.length === 0) {
      txCount.textContent = "0";
      txList.innerHTML = '<div class="tx-empty"><div class="tx-empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div><p>Nenhum movimento recente encontrado.</p></div>';
      return;
    }

    txCount.textContent = txs.length;

    txs.forEach(function (tx, idx) {
      var isPositive = tx.amount > 0;
      var amtStr = (isPositive ? "+" : "") + fmt(tx.amount);
      var amtClass = isPositive ? "positive" : "negative";

      var iconHtml = isPositive
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>';

      var iconClass = isPositive ? "tx-icon-positive" : "tx-icon-negative";
      var balStr = (tx.balance !== null && tx.balance !== undefined)
        ? fmt(tx.balance)
        : "";

      var item = document.createElement("div");
      item.className = "tx-item";
      item.style.animation = "fadeIn 0.3s var(--ease) " + (idx * 0.04) + "s both";
      item.innerHTML =
        '<div class="tx-left-side">' +
          '<div class="tx-icon-box ' + iconClass + '">' + iconHtml + '</div>' +
          '<div class="tx-info">' +
            '<p class="tx-desc">' + tx.description + '</p>' +
            '<p class="tx-date">' + tx.date + '</p>' +
          '</div>' +
        '</div>' +
        '<div class="tx-right-side">' +
          '<span class="tx-amount ' + amtClass + '">' + amtStr + '</span>' +
          (balStr ? '<span class="tx-balance-after">Saldo: ' + balStr + '</span>' : '') +
        '</div>';

      txList.appendChild(item);
    });
  }

  /* ---- Auto-refresh polling ---- */
  function startPolling() {
    // Poll notification status for changes
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(function () {
      // Try server status endpoint for live updates
      fetch("/api/notifications/status")
        .then(function (r) {
          if (!r.ok) throw new Error("No backend");
          return r.json();
        })
        .then(function (data) {
          if (data.last_check && lastKnownCheck !== data.last_check) {
            lastKnownCheck = data.last_check;
            // New data available, refresh
            loadData();
          } else if (!lastKnownCheck && data.last_check) {
            lastKnownCheck = data.last_check;
          }
        })
        .catch(function () {
          // Static mode: just poll data.json for changes
          fetch("./data.json?cb=" + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (d.updated_at && d.updated_at !== lastKnownCheck) {
                lastKnownCheck = d.updated_at;
                if (d.balance && d.transactions) {
                  renderBalance(d.balance, d.transactions, d.updated_at);
                }
              }
            })
            .catch(function () {});
        });
    }, 10000); // every 10 seconds
  }

  /* ---- Init ---- */
  loadData();
  startPolling();

})();
