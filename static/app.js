/**
 * Pluxee Balance Dashboard — Frontend Logic
 */
(function () {
  "use strict";

  /* ---- Inject SVG gradient for ring chart ---- */
  const svgNS = "http://www.w3.org/2000/svg";
  const ringDefs = document.createElementNS(svgNS, "defs");
  ringDefs.innerHTML = `
    <linearGradient id="ring-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#7c83ff"/>
      <stop offset="100%" stop-color="#b07aff"/>
    </linearGradient>`;
  document.querySelector(".hero-ring").prepend(ringDefs);

  /* ---- DOM ---- */
  const $ = (s) => document.getElementById(s);

  const loginView      = $("login-view");
  const balanceView    = $("balance-view");
  const loginForm      = $("login-form");
  const apiStatusBadge = $("api-status-badge");
  const apiStatusText  = $("api-status-text");
  const tokenFields    = $("token-fields");
  const apiClaimIn     = $("api-claim");
  const toggleTokenBtn = $("toggle-token-btn");
  const submitBtn      = $("submit-btn");
  const btnLabel       = $("btn-label");
  const btnArrow       = $("btn-arrow");
  const btnSpinner     = $("btn-spinner");
  const errorToast     = $("error-toast");
  const errorText      = $("error-text");
  const logoutBtn      = $("btn-logout");

  const heroAmount     = $("hero-amount");
  const heroRingFill   = $("hero-ring-fill");
  const heroRingPct    = $("hero-ring-pct");
  const topbarTime     = $("topbar-time");

  const txCount        = $("tx-count");
  const txList         = $("tx-list");

  const passes = {
    lunch: { val: $("val-lunch"), bar: $("bar-lunch") },
    eco:   { val: $("val-eco"),   bar: $("bar-eco") },
    gift:  { val: $("val-gift"),  bar: $("bar-gift") },
    conso: { val: $("val-conso"), bar: $("bar-conso") },
  };

  const RING_CIRCUMFERENCE = 2 * Math.PI * 52; // r=52

  /* ---- Helpers ---- */
  function fmt(val) {
    return new Intl.NumberFormat("pt-PT", {
      style: "currency",
      currency: "EUR",
    }).format(val);
  }

  function countUp(el, to, ms) {
    ms = ms || 1100;
    const t0 = performance.now();
    (function tick(now) {
      const p = Math.min((now - t0) / ms, 1);
      const e = 1 - Math.pow(1 - p, 3);           // ease-out cubic
      el.textContent = fmt(to * e);
      if (p < 1) requestAnimationFrame(tick);
    })(t0);
  }

  function showError(msg) {
    errorText.textContent = msg;
    errorToast.classList.remove("hidden");
    errorToast.style.animation = "none";
    void errorToast.offsetHeight;
    errorToast.style.animation = "";
  }

  function hideError() { errorToast.classList.add("hidden"); }

  function setLoading(on) {
    submitBtn.disabled = on;
    btnLabel.classList.toggle("hidden", on);
    btnArrow.classList.toggle("hidden", on);
    btnSpinner.classList.toggle("hidden", !on);
  }

  /* ---- Toggle Token Field ---- */
  toggleTokenBtn.addEventListener("click", function () {
    tokenFields.classList.toggle("hidden");
    if (!tokenFields.classList.contains("hidden")) {
      apiClaimIn.focus();
    }
  });

  /* ---- Check Initial Config Status / Load Site Data ---- */
  async function checkInitialStatus() {
    // 1. Check if static data.json exists (e.g. GitHub Pages)
    try {
      const res = await fetch("./data.json?cb=" + Date.now());
      if (res.ok) {
        const data = await res.json();
        if (data.balance && data.transactions) {
          renderBalance(data.balance, data.transactions, data.updated_at);
          return;
        }
      }
    } catch (_) {}

    // 2. Otherwise check server API status (local Flask backend)
    try {
      const res = await fetch("/api/notifications/status");
      const data = await res.json();
      if (data.has_credentials) {
        apiStatusBadge.classList.remove("warning");
        apiStatusText.textContent = "⚡ API Móvel Conectada · Pronto a consultar";
      } else {
        apiStatusBadge.classList.add("warning");
        apiStatusText.textContent = "⚠️ ApiClaim não configurado. Introduza o token abaixo.";
        tokenFields.classList.remove("hidden");
      }
    } catch (_) {
      apiStatusBadge.classList.add("warning");
      apiStatusText.textContent = "⚠️ Modo estático ou servidor offline";
    }
  }
  checkInitialStatus();

  /* ---- Submit ---- */
  loginForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    hideError();

    const claim = apiClaimIn ? apiClaimIn.value.trim() : "";
    const reqBody = claim ? { api_claim: claim } : {};

    setLoading(true);
    try {
      const res = await fetch("/api/balance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Ocorreu um erro ao obter os dados.");
        if (res.status === 401) {
          tokenFields.classList.remove("hidden");
          apiStatusBadge.classList.add("warning");
          apiStatusText.textContent = "⚠️ Sessão expirada. Atualize o ApiClaim.";
        }
        return;
      }
      if (data.success) {
        renderBalance(data.balance, data.transactions);
      }
    } catch (_) {
      showError("Erro de ligação — verifique a sua ligação à internet.");
    } finally {
      setLoading(false);
    }
  });


  /* ---- Render Balance ---- */
  function renderBalance(b, txs, updatedAt) {
    loginView.style.animation = "fadeOut 0.3s ease forwards";
    setTimeout(function () {
      loginView.classList.add("hidden");
      loginView.style.animation = "";
      balanceView.classList.remove("hidden");

      const vals = {
        lunch: b.lunch_pass || 0,
        eco:   b.eco_pass   || 0,
        gift:  b.gift_pass  || 0,
        conso: b.conso_pass || 0,
      };
      const total = vals.lunch + vals.eco + vals.gift + vals.conso;

      // Time stamp
      if (updatedAt) {
        const d = new Date(updatedAt);
        topbarTime.textContent =
          "Atualizado: " +
          d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" }) +
          " · " +
          d.toLocaleDateString("pt-PT", { day: "numeric", month: "short", year: "numeric" });
      } else {
        const now = new Date();
        topbarTime.textContent =
          now.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" }) +
          " · " +
          now.toLocaleDateString("pt-PT", { day: "numeric", month: "short", year: "numeric" });
      }

      // Animate total
      countUp(heroAmount, total);

      // Ring (animate to 100%)
      setTimeout(function () {
        heroRingFill.style.strokeDashoffset = "0";
        heroRingPct.textContent = "100%";
      }, 200);

      // Passes
      var maxVal = Math.max(vals.lunch, vals.eco, vals.gift, vals.conso, 1);
      var delay = 250;
      Object.keys(vals).forEach(function (key, i) {
        setTimeout(function () {
          countUp(passes[key].val, vals[key], 1000);
          var pct = Math.max((vals[key] / maxVal) * 100, vals[key] > 0 ? 6 : 0);
          passes[key].bar.style.width = pct + "%";
        }, delay + i * 100);
      });

      // Render transactions
      renderTransactions(txs || []);

      // Init notification panel
      fetchNotifStatus();
      if (notifPollTimer) clearInterval(notifPollTimer);
      notifPollTimer = setInterval(fetchNotifStatus, 15000);
    }, 280);
  }

  /* ---- Render Transactions ---- */
  function renderTransactions(txs) {
    txList.innerHTML = "";
    if (txs.length === 0) {
      txCount.textContent = "0 transações";
      txList.innerHTML = `<div class="tx-empty">Nenhum movimento recente encontrado.</div>`;
      return;
    }

    txCount.textContent = txs.length + " transações";
    
    txs.forEach(function (tx) {
      const isPositive = tx.amount > 0;
      const amtStr = (isPositive ? "+" : "") + fmt(tx.amount);
      const amtClass = isPositive ? "positive" : "negative";
      
      const iconHtml = isPositive 
        ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>`
        : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line></svg>`;
        
      const iconClass = isPositive ? "tx-icon-positive" : "tx-icon-negative";
      const balStr = (tx.balance !== null && tx.balance !== undefined)
        ? ` · Saldo: ${fmt(tx.balance)}`
        : "";
      
      const item = document.createElement("div");
      item.className = "tx-item";
      item.innerHTML = `
        <div class="tx-left-side">
          <div class="tx-icon-box ${iconClass}">
            ${iconHtml}
          </div>
          <div class="tx-info">
            <p class="tx-desc">${tx.description}</p>
            <p class="tx-date">${tx.date}${balStr}</p>
          </div>
        </div>
        <span class="tx-amount ${amtClass}">${amtStr}</span>
      `;
      txList.appendChild(item);
    });
  }

  /* ---- Logout ---- */
  logoutBtn.addEventListener("click", function () {
    balanceView.classList.add("hidden");

    // Reset
    heroAmount.textContent = fmt(0);
    heroRingFill.style.strokeDashoffset = RING_CIRCUMFERENCE;
    heroRingPct.textContent = "0%";
    Object.keys(passes).forEach(function (k) {
      passes[k].val.textContent = fmt(0);
      passes[k].bar.style.width = "0";
    });

    txList.innerHTML = "";
    txCount.textContent = "0 transações";
    hideError();

    // Stop notification status polling
    if (notifPollTimer) {
      clearInterval(notifPollTimer);
      notifPollTimer = null;
    }

    loginView.classList.remove("hidden");
    loginView.style.animation = "fadeUp 0.5s ease both";
    checkInitialStatus();
  });

  /* ========================================
     NOTIFICATION PANEL (TELEGRAM BOT)
     ======================================== */

  var notifStatusDot   = $("notif-status-dot");
  var notifStatusLabel = $("notif-status-label");
  var notifSubtitle    = $("notif-subtitle");
  var notifIntervalVal = $("notif-interval-val");
  var notifLastCheck   = $("notif-last-check");
  var notifTestBtn     = $("notif-test-btn");
  var notifPollTimer   = null;

  function updateNotifUI(data) {
    if (!data) return;

    if (notifStatusDot) notifStatusDot.className = "notif-status-dot active";
    if (notifStatusLabel) notifStatusLabel.textContent = "Ativo";
    if (notifSubtitle) notifSubtitle.textContent = "Alertas instantâneos via @CartaoRefeicaoBot";

    if (data.interval && notifIntervalVal) {
      var mins = Math.round(data.interval / 60);
      notifIntervalVal.textContent = mins + " min (GitHub Actions)";
    }

    if (data.last_check && notifLastCheck) {
      try {
        var d = new Date(data.last_check);
        notifLastCheck.textContent = d.toLocaleString("pt-PT", {
          hour: "2-digit", minute: "2-digit",
          day: "numeric", month: "short",
        });
      } catch (_) {
        notifLastCheck.textContent = data.last_check;
      }
    }
  }

  function fetchNotifStatus() {
    // 1. Try local/server backend
    fetch("/api/notifications/status")
      .then(function (r) {
        if (!r.ok) throw new Error("Not backend");
        return r.json();
      })
      .then(updateNotifUI)
      .catch(function () {
        // 2. Static GitHub Pages mode: use data.json timestamp
        fetch("./data.json?cb=" + Date.now())
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.updated_at) {
              updateNotifUI({
                running: true,
                interval: 900,
                last_check: data.updated_at,
              });
            }
          })
          .catch(function () {});
      });
  }

  /* Test notification button */
  if (notifTestBtn) {
    notifTestBtn.addEventListener("click", function () {
      notifTestBtn.disabled = true;
      notifTestBtn.classList.add("is-testing");

      fetch("/api/notifications/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("Status " + r.status);
          return r.json();
        })
        .then(function (data) {
          notifTestBtn.classList.remove("is-testing");
          if (data.success) {
            notifTestBtn.classList.add("test-success");
            setTimeout(function () {
              notifTestBtn.classList.remove("test-success");
            }, 2500);
          }
          notifTestBtn.disabled = false;
        })
        .catch(function () {
          // In static mode or if API endpoint isn't available, open the bot directly in Telegram
          notifTestBtn.classList.remove("is-testing");
          notifTestBtn.disabled = false;
          window.open("https://t.me/CartaoRefeicaoBot", "_blank");
        });
    });
  }

})();

