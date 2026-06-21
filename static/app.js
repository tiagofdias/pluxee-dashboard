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

  const loginView   = $("login-view");
  const balanceView = $("balance-view");
  const loginForm   = $("login-form");
  const usernameIn  = $("username");
  const passwordIn  = $("password");
  const submitBtn   = $("submit-btn");
  const btnLabel    = $("btn-label");
  const btnArrow    = $("btn-arrow");
  const btnSpinner  = $("btn-spinner");
  const errorToast  = $("error-toast");
  const errorText   = $("error-text");
  const logoutBtn   = $("btn-logout");
  const togglePw    = $("toggle-pw");
  const icoEye      = $("ico-eye");
  const icoEyeOff   = $("ico-eye-off");

  const heroAmount  = $("hero-amount");
  const heroRingFill = $("hero-ring-fill");
  const heroRingPct = $("hero-ring-pct");
  const topbarTime  = $("topbar-time");

  const txCount     = $("tx-count");
  const txList      = $("tx-list");

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

  /* ---- Password toggle ---- */
  togglePw.addEventListener("click", function () {
    const show = passwordIn.type === "password";
    passwordIn.type = show ? "text" : "password";
    icoEye.classList.toggle("hidden", !show);
    icoEyeOff.classList.toggle("hidden", show);
  });

  /* ---- Submit ---- */
  loginForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    hideError();

    const u = usernameIn.value.trim();
    const p = passwordIn.value;
    if (!u || !p) { showError("Por favor, introduza o NIF e a palavra-passe."); return; }

    setLoading(true);
    try {
      const res = await fetch("/api/balance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: u, password: p }),
      });
      const data = await res.json();
      if (!res.ok) { showError(data.error || "Something went wrong."); return; }
      if (data.success) renderBalance(data.balance, data.transactions);
    } catch (_) {
      showError("Network error — check your connection.");
    } finally {
      setLoading(false);
    }
  });

  /* ---- Render Balance ---- */
  function renderBalance(b, txs) {
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
      const now = new Date();
      topbarTime.textContent =
        now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) +
        " · " +
        now.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

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
      _savedNif = usernameIn.value.trim();
      _savedPw = passwordIn.value;
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
      
      const item = document.createElement("div");
      item.className = "tx-item";
      item.innerHTML = `
        <div class="tx-left-side">
          <div class="tx-icon-box ${iconClass}">
            ${iconHtml}
          </div>
          <div class="tx-info">
            <p class="tx-desc">${tx.description}</p>
            <p class="tx-date">${tx.date}</p>
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

    usernameIn.value = "";
    passwordIn.value = "";
    hideError();

    // Stop notification status polling
    if (notifPollTimer) {
      clearInterval(notifPollTimer);
      notifPollTimer = null;
    }

    loginView.classList.remove("hidden");
    loginView.style.animation = "fadeUp 0.5s ease both";
    usernameIn.focus();
  });

  /* ========================================
     NOTIFICATION PANEL
     ======================================== */

  var notifStatusDot   = $("notif-status-dot");
  var notifStatusLabel = $("notif-status-label");
  var notifSubtitle    = $("notif-subtitle");
  var notifTopicName   = $("notif-topic-name");
  var notifCopyBtn     = $("notif-copy-btn");
  var notifIntervalVal = $("notif-interval-val");
  var notifLastCheck   = $("notif-last-check");
  var notifToggleBtn   = $("notif-toggle-btn");
  var notifToggleLabel = $("notif-toggle-label");
  var notifBtnPlay     = $("notif-btn-play");
  var notifBtnStop     = $("notif-btn-stop");
  var notifTestBtn     = $("notif-test-btn");
  var notifPollTimer   = null;
  var _monitorRunning  = false;
  var _isRender        = false;
  var _savedNif        = "";
  var _savedPw         = "";

  function updateNotifUI(data) {
    _monitorRunning = data.running;
    _isRender = !!data.is_render;

    if (_isRender) {
      // Render environment (cron-driven)
      if (data.has_credentials) {
        notifStatusDot.className = "notif-status-dot active";
        notifStatusLabel.textContent = "Ativo (Render)";
        notifSubtitle.textContent = "Monitorização gerida por Cron";
        notifToggleLabel.textContent = "Verificar Agora";
        notifBtnPlay.classList.remove("hidden");
        notifBtnStop.classList.add("hidden");
        notifToggleBtn.classList.remove("is-running");
        notifIntervalVal.textContent = "Externo (Cron)";
      } else {
        notifStatusDot.className = "notif-status-dot";
        notifStatusLabel.textContent = "Sem credenciais";
        notifSubtitle.textContent = "Configure credenciais no painel do Render";
        notifToggleLabel.textContent = "Verificar Agora";
        notifBtnPlay.classList.remove("hidden");
        notifBtnStop.classList.add("hidden");
        notifToggleBtn.classList.remove("is-running");
        notifIntervalVal.textContent = "—";
      }
    } else {
      // Local environment (subprocess-driven)
      if (data.running) {
        notifStatusDot.className = "notif-status-dot active";
        notifStatusLabel.textContent = "Ativo";
        notifSubtitle.textContent = "A monitorizar transações";
        notifToggleLabel.textContent = "Parar Monitor";
        notifBtnPlay.classList.add("hidden");
        notifBtnStop.classList.remove("hidden");
        notifToggleBtn.classList.add("is-running");
      } else {
        notifStatusDot.className = "notif-status-dot";
        notifStatusLabel.textContent = "Parado";
        notifSubtitle.textContent = "Receba alertas no telemóvel";
        notifToggleLabel.textContent = "Iniciar Monitor";
        notifBtnPlay.classList.remove("hidden");
        notifBtnStop.classList.add("hidden");
        notifToggleBtn.classList.remove("is-running");
      }

      // Interval
      if (data.interval) {
        var mins = Math.round(data.interval / 60);
        notifIntervalVal.textContent = mins + " min";
      }
    }

    // Topic
    if (data.topic) {
      notifTopicName.textContent = data.topic;
    }

    // Last check
    if (data.last_check) {
      try {
        var d = new Date(data.last_check);
        notifLastCheck.textContent = d.toLocaleString("pt-PT", {
          hour: "2-digit", minute: "2-digit",
          day: "numeric", month: "short",
        });
      } catch (_) {
        notifLastCheck.textContent = data.last_check;
      }
    } else {
      notifLastCheck.textContent = "—";
    }
  }

  function fetchNotifStatus() {
    fetch("/api/notifications/status")
      .then(function (r) { return r.json(); })
      .then(updateNotifUI)
      .catch(function () { /* silent */ });
  }

  /* Copy topic */
  notifCopyBtn.addEventListener("click", function () {
    var topic = notifTopicName.textContent;
    navigator.clipboard.writeText(topic).then(function () {
      notifCopyBtn.classList.add("copied");
      setTimeout(function () { notifCopyBtn.classList.remove("copied"); }, 1500);
    });
  });

  /* Toggle monitor start/stop */
  notifToggleBtn.addEventListener("click", function () {
    notifToggleBtn.disabled = true;

    if (!_isRender && _monitorRunning) {
      // Stop (only local)
      fetch("/api/notifications/stop", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          updateNotifUI({ running: false });
          notifToggleBtn.disabled = false;
        })
        .catch(function () {
          notifToggleBtn.disabled = false;
        });
    } else {
      // Start (local) or Check Now (Render)
      var body = {
        nif: _savedNif || usernameIn.value.trim(),
        password: _savedPw || passwordIn.value,
        topic: notifTopicName.textContent,
      };

      fetch("/api/notifications/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.success) {
            if (_isRender) {
              alert("Verificação manual concluída com sucesso! Novas transações: " + (data.new_transactions || 0));
              fetchNotifStatus();
            } else {
              updateNotifUI({ running: true, topic: data.topic, interval: data.interval });
            }
          } else {
            alert(data.error || "Erro ao iniciar o monitor");
          }
          notifToggleBtn.disabled = false;
        })
        .catch(function () {
          alert("Erro de rede ao ligar ao monitor");
          notifToggleBtn.disabled = false;
        });
    }
  });

  /* Test notification */
  notifTestBtn.addEventListener("click", function () {
    notifTestBtn.disabled = true;
    notifTestBtn.classList.add("is-testing");

    fetch("/api/notifications/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: notifTopicName.textContent }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        notifTestBtn.classList.remove("is-testing");
        if (data.success) {
          notifTestBtn.classList.add("test-success");
          setTimeout(function () {
            notifTestBtn.classList.remove("test-success");
          }, 2000);
        }
        notifTestBtn.disabled = false;
      })
      .catch(function () {
        notifTestBtn.classList.remove("is-testing");
        notifTestBtn.disabled = false;
      });
  });

})();

