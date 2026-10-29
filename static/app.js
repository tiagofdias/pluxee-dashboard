/* Pluxee personal dashboard. No build step or chart dependency required. */
(async function () {
  "use strict";
  if (!(await window.Pluxee.ready)) return;
  const $ = (id) => document.getElementById(id);
  const currency = new Intl.NumberFormat("pt-PT", {
    style: "currency",
    currency: "EUR",
  });
  const fmt = (value) => currency.format(Number(value) || 0);
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const text = (id, value) => {
    $(id).textContent = value;
  };
  const day = 86400000;
  const now = new Date();
  const monthKey = (date) =>
    date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0");
  const currentMonth = monthKey(now);
  let transactions = [],
    filtered = [],
    activeFilter = "all",
    pageSize = 8,
    chartMonths = 6;
  let fetching = false,
    loaded = false,
    lastCheck = null;

  function parseDate(value) {
    const parts = String(value || "")
      .split(" ")[0]
      .split("/");
    const d =
      parts.length === 3
        ? new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]))
        : new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  function category(tx) {
    const name = (tx.description || "").toLowerCase();
    if (tx.amount > 0)
      return { key: "income", label: "Carregamento", color: "#bcf5cf" };
    if (/glovo|uber eats|bolt food/.test(name))
      return { key: "delivery", label: "Delivery", color: "#efc3a8" };
    if (
      /continente|pingo doce|supermerc|lidl|aldi|auchan|mercadona|intermarch/.test(
        name,
      )
    )
      return { key: "super", label: "Supermercados", color: "#b9acf3" };
    return { key: "dining", label: "Restauração e outros", color: "#bcf5cf" };
  }
  function normalize(txs) {
    const seen = new Set();
    return txs
      .filter((tx) => {
        const key = [
          tx.date,
          String(tx.description || "")
            .trim()
            .toLowerCase(),
          Number(tx.amount).toFixed(2),
          tx.currency || "EUR",
        ].join("|");
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((tx) => ({
        ...tx,
        amount: Number(tx.amount),
        parsedDate: parseDate(tx.date),
      }))
      .sort((a, b) => (b.parsedDate || 0) - (a.parsedDate || 0));
  }
  function showNotice(message, error) {
    text(error ? "error-text" : "success-text", message);
    const toast = $(error ? "error-toast" : "success-toast");
    toast.classList.remove("hidden");
    if (!error) setTimeout(() => toast.classList.add("hidden"), 4500);
  }
  window.addEventListener("pluxee:notice", (event) =>
    showNotice(event.detail.message, event.detail.error),
  );
  $("error-dismiss").addEventListener("click", () =>
    $("error-toast").classList.add("hidden"),
  );
  text(
    "today-label",
    now.toLocaleDateString("pt-PT", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    }),
  );

  // Calendar-only estimate; no promise that payroll will arrive on these dates.
  function businessDays(year, month) {
    const fixed = new Set([
      "1-1",
      "4-25",
      "5-1",
      "6-10",
      "8-15",
      "10-5",
      "11-1",
      "12-1",
      "12-8",
      "12-25",
    ]);
    const a = year % 19,
      b = Math.floor(year / 100),
      c = year % 100,
      d = Math.floor(b / 4),
      e = b % 4,
      f = Math.floor((b + 8) / 25),
      g = Math.floor((b - f + 1) / 3),
      h = (19 * a + b - d - g + 15) % 30,
      i = Math.floor(c / 4),
      k = c % 4,
      l = (32 + 2 * e + 2 * i - h - k) % 7,
      m = Math.floor((a + 11 * h + 22 * l) / 451);
    const easter = new Date(
      year,
      Math.floor((h + l - 7 * m + 114) / 31) - 1,
      ((h + l - 7 * m + 114) % 31) + 1,
    );
    [-2, 60].forEach((offset) => {
      const date = new Date(easter);
      date.setDate(date.getDate() + offset);
      fixed.add(date.getMonth() + 1 + "-" + date.getDate());
    });
    let count = 0;
    for (
      let date = new Date(year, month, 1);
      date.getMonth() === month;
      date.setDate(date.getDate() + 1)
    ) {
      if (
        date.getDay() !== 0 &&
        date.getDay() !== 6 &&
        !fixed.has(month + 1 + "-" + date.getDate())
      )
        count++;
    }
    return count;
  }
  function forecast(reloads, balance) {
    const last = reloads[0];
    if (!last || !last.parsedDate) {
      [
        "stat-next-reload-amount",
        "stat-daily-budget",
        "daily-rate",
        "workdays",
      ].forEach((id) => text(id, "—"));
      text("stat-next-reload-date", "Histórico insuficiente para estimar");
      text("stat-days-left", "Disponível após o primeiro carregamento");
      return;
    }
    const sourceDays = businessDays(
      last.parsedDate.getFullYear(),
      last.parsedDate.getMonth(),
    );
    const rate = last.amount / sourceDays;
    let target = new Date(now.getFullYear(), now.getMonth(), 24);
    if (
      now.getDate() > 28 ||
      (last.parsedDate.getFullYear() === now.getFullYear() &&
        last.parsedDate.getMonth() === now.getMonth())
    )
      target.setMonth(target.getMonth() + 1);
    // If the usual window has begun, use the remaining end of the window.
    if (target < new Date(now.getFullYear(), now.getMonth(), now.getDate()))
      target.setDate(28);
    const nextDays = businessDays(target.getFullYear(), target.getMonth());
    const days = Math.max(
      1,
      Math.ceil(
        (target - new Date(now.getFullYear(), now.getMonth(), now.getDate())) /
          day,
      ),
    );
    text("stat-next-reload-amount", fmt(rate * nextDays));
    text(
      "stat-next-reload-date",
      "24–28 de " + target.toLocaleDateString("pt-PT", { month: "long" }),
    );
    text("daily-rate", fmt(rate));
    text("workdays", nextDays + " dias");
    text("stat-daily-budget", fmt(Math.max(0, balance) / days));
    text(
      "stat-days-left",
      days + " dias até à janela estimada de carregamento",
    );
  }
  function render(data, source) {
    transactions = normalize(data.transactions || []);
    const valid = transactions.filter(
      (tx) => !tx.is_rejected && Number.isFinite(tx.amount),
    );
    const balance = Number(data.balance.lunch_pass || 0);
    const formatted = fmt(balance).replace(/\s*€/, "");
    $("hero-amount").innerHTML = escape(formatted) + "<span> €</span>";
    const monthExpenses = valid.filter(
      (tx) =>
        tx.amount < 0 &&
        tx.parsedDate &&
        monthKey(tx.parsedDate) === currentMonth,
    );
    const spend = monthExpenses.reduce((sum, tx) => sum - tx.amount, 0);
    text("stat-month-spend", fmt(spend));
    text(
      "stat-month-tx-count",
      monthExpenses.length +
        " compras em " +
        now.toLocaleDateString("pt-PT", { month: "long" }),
    );
    const previousMonth = monthKey(
      new Date(now.getFullYear(), now.getMonth() - 1, 1),
    );
    const previousSpend = valid
      .filter(
        (tx) =>
          tx.amount < 0 &&
          tx.parsedDate &&
          monthKey(tx.parsedDate) === previousMonth,
      )
      .reduce((sum, tx) => sum - tx.amount, 0);
    const comparison = $("spend-comparison");
    comparison.classList.toggle("higher", spend > previousSpend);
    comparison.textContent = previousSpend
      ? (spend > previousSpend ? "↗ +" : "↘ ") +
        Math.round((spend / previousSpend - 1) * 100) +
        "%"
      : "Sem comparação";
    const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    text(
      "week-spend",
      fmt(
        valid
          .filter(
            (tx) =>
              tx.amount < 0 && tx.parsedDate >= monday && tx.parsedDate <= now,
          )
          .reduce((sum, tx) => sum - tx.amount, 0),
      ),
    );
    text(
      "average-purchase",
      monthExpenses.length ? fmt(spend / monthExpenses.length) : "—",
    );
    text("purchase-count", monthExpenses.length + " compras");
    const merchants = {};
    monthExpenses.forEach((tx) => {
      const merchant = /^glovo/i.test(tx.description)
        ? "Glovo"
        : tx.description;
      merchants[merchant] = (merchants[merchant] || 0) + 1;
    });
    const top = Object.entries(merchants).sort((a, b) => b[1] - a[1])[0];
    text("favorite-merchant", top ? top[0] : "Sem compras este mês");
    text("favorite-count", top ? top[1] + " visitas" : "—");
    const reloads = valid.filter(
      (tx) => tx.amount > 0 && /carregamento/i.test(tx.description),
    );
    forecast(reloads, balance);
    renderReloads(reloads);
    renderChart();
    renderCategories();
    const selected = $("tx-period").value;
    const periods = [
      ...new Set(
        transactions
          .filter((tx) => tx.parsedDate)
          .map((tx) => monthKey(tx.parsedDate)),
      ),
    ]
      .sort()
      .reverse();
    $("tx-period").innerHTML =
      '<option value="all">Todo o histórico</option>' +
      periods
        .map(
          (key) =>
            '<option value="' +
            key +
            '">' +
            escape(
              new Date(key + "-01T12:00:00").toLocaleDateString("pt-PT", {
                month: "long",
                year: "numeric",
              }),
            ) +
            "</option>",
        )
        .join("");
    $("tx-period").value = periods.includes(selected) ? selected : "all";
    renderFeed();
    $("export-button").disabled = false;
    const stamp = data.updated_at || data.last_check;
    const date = stamp ? new Date(stamp) : null;
    const stale = date && Date.now() - date.getTime() > 30 * 60 * 1000;
    const cached = source !== "live" || data.cached || stale;
    const state = $("connection-state");
    state.dataset.state = cached ? "cached" : "live";
    state.innerHTML = "<i></i>" + (cached ? "Dados guardados" : "Atualizado");
    text(
      "sync-time",
      date && !Number.isNaN(date.getTime())
        ? date.toLocaleDateString("pt-PT", {
            day: "2-digit",
            month: "2-digit",
          }) +
            " · " +
            date.toLocaleTimeString("pt-PT", {
              hour: "2-digit",
              minute: "2-digit",
            })
        : source === "live"
          ? "Agora"
          : "Data indisponível",
    );
    $("data-notice").classList.toggle("hidden", !cached);
    text(
      "data-notice",
      data.warning ||
        "A mostrar a última sincronização guardada. O saldo pode ter mudado; consulta a data de atualização.",
    );
    loaded = true;
  }
  function renderReloads(reloads) {
    $("reloads-history").innerHTML = reloads.length
      ? reloads
          .slice(0, 4)
          .map(
            (tx) =>
              '<div class="history-item"><span class="history-date">' +
              escape(
                tx.parsedDate
                  ? tx.parsedDate.toLocaleDateString("pt-PT", {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                    })
                  : tx.date,
              ) +
              "</span><strong>+" +
              escape(fmt(tx.amount)) +
              '</strong><span class="history-company">' +
              escape(tx.description.replace(/^Carregamento de /i, "")) +
              "</span></div>",
          )
          .join("")
      : '<p class="muted-note">Ainda não há carregamentos registados.</p>';
  }
  function renderChart() {
    const months = [];
    for (let i = chartMonths - 1; i >= 0; i--) {
      const date = new Date(now.getFullYear(), now.getMonth() - i, 1);
      months.push({ date, key: monthKey(date), income: 0, expenses: 0 });
    }
    transactions.forEach((tx) => {
      if (tx.is_rejected || !tx.parsedDate) return;
      const month = months.find((m) => m.key === monthKey(tx.parsedDate));
      if (month) {
        if (tx.amount > 0) month.income += tx.amount;
        else month.expenses -= tx.amount;
      }
    });
    text("chart-income", fmt(months.reduce((s, m) => s + m.income, 0)));
    text("chart-expenses", fmt(months.reduce((s, m) => s + m.expenses, 0)));
    text("chart-period", "Últimos " + chartMonths + " meses");
    const width = Math.max(
        280,
        Math.min(800, $("monthly-chart").clientWidth - 36),
      ),
      height = 195,
      left = 43,
      right = 10,
      top = 12,
      bottom = 28,
      plotHeight = height - top - bottom;
    const maximum = Math.max(
      50,
      ...months.flatMap((m) => [m.income, m.expenses]),
    );
    const ceiling = Math.ceil(maximum / 50) * 50;
    let content = "";
    for (let i = 0; i <= 3; i++) {
      const y = top + (plotHeight * i) / 3;
      content +=
        '<line class="chart-grid" x1="' +
        left +
        '" x2="' +
        (width - right) +
        '" y1="' +
        y +
        '" y2="' +
        y +
        '"/><text class="chart-label" x="' +
        (left - 10) +
        '" y="' +
        (y + 3) +
        '" text-anchor="end">' +
        Math.round(ceiling * (1 - i / 3)) +
        " €</text>";
    }
    const step = (width - left - right) / months.length,
      barWidth = Math.min(19, step * 0.22);
    months.forEach((m, i) => {
      const x = left + step * (i + 0.5),
        label = m.date
          .toLocaleDateString("pt-PT", { month: "short" })
          .replace(".", "");
      [
        ["income", "#bcf5cf", -barWidth - 2, "Carregamentos"],
        ["expenses", "#b9acf3", 2, "Gastos"],
      ].forEach(([key, color, offset, name]) => {
        const barHeight = (plotHeight * m[key]) / ceiling;
        content +=
          '<rect class="chart-bar" tabindex="0" role="img" aria-label="' +
          escape(label + ": " + name + " " + fmt(m[key])) +
          '" x="' +
          (x + offset) +
          '" y="' +
          (top + plotHeight - barHeight) +
          '" width="' +
          barWidth +
          '" height="' +
          Math.max(barHeight, 1) +
          '" rx="3" fill="' +
          color +
          '"><title>' +
          escape(label + " · " + name + ": " + fmt(m[key])) +
          "</title></rect>";
      });
      if (months.length <= 6 || width > 500 || i % 2 === 0)
        content +=
          '<text class="chart-label" x="' +
          x +
          '" y="' +
          (height - 7) +
          '" text-anchor="middle">' +
          escape(label) +
          "</text>";
    });
    $("monthly-chart").innerHTML =
      '<svg viewBox="0 0 ' +
      width +
      " " +
      height +
      '" preserveAspectRatio="none" role="group" aria-label="Carregamentos e gastos mensais">' +
      content +
      "</svg>";
  }
  function renderCategories() {
    const totals = { delivery: 0, super: 0, dining: 0 };
    transactions.forEach((tx) => {
      if (tx.amount >= 0 || tx.is_rejected) return;
      if (
        $("insight-period").value === "month" &&
        (!tx.parsedDate || monthKey(tx.parsedDate) !== currentMonth)
      )
        return;
      totals[category(tx).key] -= tx.amount;
    });
    const total = Object.values(totals).reduce((a, b) => a + b, 0);
    text("category-total", fmt(total));
    const labels = {
      delivery: ["Delivery", "#efc3a8"],
      super: ["Supermercados", "#b9acf3"],
      dining: ["Restauração e outros", "#bcf5cf"],
    };
    let angle = 0,
      stops = [];
    $("category-legend").innerHTML = Object.entries(totals)
      .map(([key, value]) => {
        const percent = total ? (value / total) * 100 : 0;
        stops.push(
          labels[key][1] + " " + angle + "% " + (angle + percent) + "%",
        );
        angle += percent;
        return (
          '<div class="category-legend-row"><i class="legend-dot" style="background:' +
          labels[key][1] +
          '"></i><div><span>' +
          labels[key][0] +
          "</span><small>" +
          percent.toFixed(0) +
          "% dos gastos</small></div><strong>" +
          escape(fmt(value)) +
          "</strong></div>"
        );
      })
      .join("");
    $("category-donut").style.background = total
      ? "conic-gradient(" + stops.join(",") + ")"
      : "var(--border)";
    $("category-donut").setAttribute(
      "aria-label",
      "Total " +
        fmt(total) +
        ". " +
        Object.entries(totals)
          .map(([key, value]) => labels[key][0] + ": " + fmt(value))
          .join(". "),
    );
  }
  function location(tx) {
    const raw = tx.raw_description || "";
    const parts = raw.split(",");
    return parts.length > 2
      ? parts[parts.length - 2].trim()
      : tx.amount > 0
        ? "Entrada no cartão"
        : "Pagamento com cartão";
  }
  function renderFeed(reset) {
    if (reset) pageSize = 8;
    const query = $("tx-search").value.trim().toLocaleLowerCase("pt-PT");
    filtered = transactions.filter((tx) => {
      if (activeFilter === "expenses" && tx.amount >= 0) return false;
      if (activeFilter === "reloads" && tx.amount <= 0) return false;
      if (
        $("tx-period").value !== "all" &&
        (!tx.parsedDate || monthKey(tx.parsedDate) !== $("tx-period").value)
      )
        return false;
      return (
        !query ||
        [tx.description, tx.raw_description, tx.date, fmt(tx.amount), tx.amount]
          .join(" ")
          .toLocaleLowerCase("pt-PT")
          .includes(query)
      );
    });
    text("tx-badge-count", filtered.length);
    const visible = filtered.slice(0, pageSize);
    $("tx-feed-list").innerHTML = visible.length
      ? visible
          .map((tx, index) => {
            const cat = category(tx),
              income = tx.amount > 0;
            const name = income
              ? tx.description.replace(/^Carregamento de /i, "")
              : tx.description;
            const initials = income
              ? "↙"
              : cat.key === "delivery"
                ? "G"
                : name
                    .split(" ")
                    .filter(Boolean)
                    .slice(0, 2)
                    .map((w) => w[0])
                    .join("");
            const date = tx.parsedDate
              ? tx.parsedDate.toLocaleDateString("pt-PT", {
                  day: "2-digit",
                  month: "short",
                })
              : tx.date;
            return (
              '<div class="transaction"><button class="tx-row" aria-expanded="false" aria-controls="tx-detail-' +
              index +
              '"><span class="tx-merchant"><span class="merchant-icon ' +
              cat.key +
              '">' +
              escape(initials) +
              '</span><span style="min-width:0"><span class="merchant-name">' +
              escape(name) +
              '</span><span class="merchant-location">' +
              escape(location(tx)) +
              " · " +
              escape(tx.date) +
              '</span></span></span><span class="tx-category"><span class="category-pill">' +
              (tx.is_rejected ? "Recusado" : cat.label) +
              '</span></span><span class="tx-date">' +
              escape(date) +
              '</span><span class="tx-amount ' +
              (income ? "income" : "") +
              (tx.is_rejected ? " rejected" : "") +
              '">' +
              (income ? "+" : "") +
              escape(fmt(tx.amount)) +
              '</span><svg class="tx-chevron"><use href="#i-chev"/></svg></button><div id="tx-detail-' +
              index +
              '" class="tx-detail hidden"><span>Estado: <strong>' +
              (tx.is_rejected
                ? "Recusado"
                : tx.effective_date
                  ? "Contabilizado"
                  : "Data de liquidação não indicada") +
              "</strong></span><span>Data efetiva: <strong>" +
              escape(tx.effective_date || "Não indicada") +
              "</strong></span><span>Saldo no movimento: <strong>" +
              (tx.balance != null ? escape(fmt(tx.balance)) : "Não indicado") +
              '</strong></span><span class="tx-detail-note">' +
              escape(tx.raw_description || tx.description) +
              ". O saldo do movimento é histórico e pode diferir do saldo disponível.</span></div></div>"
            );
          })
          .join("")
      : '<div class="empty-state"><svg><use href="#i-search"/></svg><strong>Nenhum movimento encontrado</strong><span>Experimenta outra pesquisa ou escolhe um período diferente.</span></div>';
    text(
      "feed-summary",
      filtered.length
        ? "A mostrar " +
            visible.length +
            " de " +
            filtered.length +
            " movimentos"
        : "Sem movimentos para estes filtros",
    );
    $("load-more").classList.toggle(
      "hidden",
      visible.length >= filtered.length,
    );
    $("export-button").disabled = !filtered.length;
  }
  $("tx-feed-list").addEventListener("click", (event) => {
    const row = event.target.closest(".tx-row");
    if (!row) return;
    const open = row.getAttribute("aria-expanded") === "true";
    row.setAttribute("aria-expanded", !open);
    $(row.getAttribute("aria-controls")).classList.toggle("hidden", open);
  });
  document.querySelectorAll(".filter-chip").forEach((button) =>
    button.addEventListener("click", () => {
      activeFilter = button.dataset.filter;
      document.querySelectorAll(".filter-chip").forEach((b) => {
        b.classList.toggle("active", b === button);
        b.setAttribute("aria-pressed", b === button);
      });
      renderFeed(true);
    }),
  );
  $("tx-search").addEventListener("input", () => renderFeed(true));
  $("tx-period").addEventListener("change", () => renderFeed(true));
  $("load-more").addEventListener("click", () => {
    pageSize += 12;
    renderFeed();
  });
  $("insight-period").addEventListener("change", renderCategories);
  document.querySelectorAll("[data-months]").forEach((button) =>
    button.addEventListener("click", () => {
      chartMonths = Number(button.dataset.months);
      document.querySelectorAll("[data-months]").forEach((b) => {
        b.classList.toggle("selected", b === button);
        b.setAttribute("aria-pressed", b === button);
      });
      renderChart();
    }),
  );
  document.querySelectorAll(".nav-link").forEach((link) =>
    link.addEventListener("click", () => {
      document
        .querySelectorAll(".nav-link")
        .forEach((l) => l.classList.toggle("active", l === link));
    }),
  );
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        const section = entries
          .filter((e) => e.isIntersecting)
          .sort(
            (a, b) => a.boundingClientRect.top - b.boundingClientRect.top,
          )[0];
        if (section)
          document
            .querySelectorAll(".nav-link")
            .forEach((link) =>
              link.classList.toggle(
                "active",
                link.hash === "#" + section.target.id,
              ),
            );
      },
      { rootMargin: "-10% 0px -55% 0px", threshold: 0 },
    );
    ["overview", "transactions", "insights"].forEach((id) =>
      observer.observe($(id)),
    );
  }
  $("export-button").addEventListener("click", () => {
    // Protect spreadsheet cells from formula execution, while keeping amounts numeric.
    const cell = (value) =>
      '"' +
      String(value ?? "")
        .replace(/^[=+@-]/, "'$&")
        .replace(/"/g, '""') +
      '"';
    const rows = [
      [
        "Data",
        "Estabelecimento",
        "Montante EUR",
        "Data efetiva",
        "Saldo histórico EUR",
        "Estado",
      ]
        .map(cell)
        .join(";"),
      ...filtered.map((tx) =>
        [
          cell(tx.date),
          cell(tx.description),
          tx.amount.toFixed(2).replace(".", ","),
          cell(tx.effective_date),
          tx.balance != null
            ? Number(tx.balance).toFixed(2).replace(".", ",")
            : "",
          cell(tx.is_rejected ? "Recusado" : "Registado"),
        ].join(";"),
      ),
    ];
    const url = URL.createObjectURL(
      new Blob(["\ufeff" + rows.join("\r\n")], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download =
      (window.Pluxee.isDemo ? "pluxee-demo-" : "pluxee-movimentos-") +
      now.toISOString().slice(0, 10) +
      ".csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showNotice(filtered.length + " movimentos exportados.", false);
  });
  async function readJSON(url, options) {
    const response = await window.Pluxee.fetch(url, {
      ...options,
      cache: "no-store",
      signal: AbortSignal.timeout(25000),
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    if (!data.balance || !Array.isArray(data.transactions))
      throw new Error("Dados indisponíveis");
    return data;
  }
  async function fetchData() {
    if (fetching) return;
    fetching = true;
    $("refresh-button").disabled = true;
    $("refresh-button").classList.add("refreshing");
    try {
      let data,
        source = "live";
      if (window.Pluxee.isDemo) {
        data = window.PluxeeDemo.createData();
      } else {
        data = await readJSON("/api/balance", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (data.cached) source = "cached";
      }
      if (source === "live" && !data.cached && !data.updated_at)
        data.updated_at = new Date().toISOString();
      render(data, source);
      if (window.Pluxee.isDemo) {
        $("connection-state").innerHTML = "<i></i>Demonstração";
        $("data-notice").classList.remove("hidden");
        $("data-notice").classList.add("demo-notice");
        $("data-notice").textContent =
          "MODO DEMO · Todos os nomes, movimentos e valores são fictícios. Não há ligação a um cartão real.";
      }
    } catch (error) {
      $("connection-state").dataset.state = "error";
      $("connection-state").innerHTML = "<i></i>Sem ligação";
      if (!loaded)
        $("tx-feed-list").innerHTML =
          '<div class="empty-state"><strong>Não foi possível carregar os dados.</strong><span>Verifica a ligação e usa o botão Atualizar para tentar novamente.</span></div>';
      showNotice(
        "Não foi possível atualizar. Os dados já apresentados foram mantidos.",
        true,
      );
    } finally {
      fetching = false;
      $("refresh-button").disabled = false;
      $("refresh-button").classList.remove("refreshing");
    }
  }
  $("refresh-button").addEventListener("click", fetchData);
  async function poll() {
    if (window.Pluxee.isDemo || document.hidden || fetching) return;
    try {
      const response = await window.Pluxee.fetch("/api/notifications/status", {
        signal: AbortSignal.timeout(8000),
        cache: "no-store",
      });
      if (!response.ok) {
        if (loaded) fetchData();
        return;
      }
      const status = await response.json();
      if (
        !status.running ||
        (status.last_check && status.last_check !== lastCheck)
      ) {
        lastCheck = status.last_check;
        fetchData();
      }
    } catch (error) {
      /* Static hosting refreshes its saved data without an API. */ if (loaded)
        fetchData();
    }
  }
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (loaded) renderChart();
    }, 120);
  });
  window.addEventListener("online", fetchData);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) fetchData();
  });
  fetchData();
  setInterval(poll, 60000);
})();

(async function () {
  "use strict";
  if (
    !(await window.Pluxee.ready) ||
    window.Pluxee.isDemo ||
    !window.Pluxee.pushAvailable
  )
    return;
  function showError(message) {
    window.dispatchEvent(
      new CustomEvent("pluxee:notice", {
        detail: { message: message, error: true },
      }),
    );
  }
  // ================================================================
  // PWA: SERVICE WORKER & PUSH NOTIFICATIONS
  // ================================================================

  var pushBanner = document.getElementById("push-banner");
  var pushEnableBtn = document.getElementById("push-enable-btn");
  var pushTestBtn = document.getElementById("push-test-btn");
  var pushDismissBtn = document.getElementById("push-dismiss-btn");
  var notificationBell = document.getElementById("notification-bell");
  var successToast = document.getElementById("success-toast");
  var successText = document.getElementById("success-text");

  var pwaInstallBanner = document.getElementById("pwa-install-banner");
  var pwaInstallBtn = document.getElementById("pwa-install-btn");
  var pwaInstallDismiss = document.getElementById("pwa-install-dismiss");

  var deferredInstallPrompt = null;

  function showSuccess(msg) {
    if (successText) successText.textContent = msg;
    if (successToast) {
      successToast.classList.remove("hidden");
      setTimeout(function () {
        successToast.classList.add("hidden");
      }, 4000);
    }
  }

  // Convert URL-safe base64 to Uint8Array (for VAPID key)
  function urlBase64ToUint8Array(base64String) {
    var padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    var base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    var rawData = window.atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; i++) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  // Register Service Worker
  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return Promise.resolve(null);

    return navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then(function (registration) {
        console.log("SW registered:", registration.scope);
        return registration;
      })
      .catch(function (err) {
        console.error("SW registration failed:", err);
        return null;
      });
  }

  // Check current push subscription state
  function checkPushState() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      // Push not supported
      if (notificationBell) notificationBell.style.display = "none";
      return;
    }

    navigator.serviceWorker.ready.then(function (registration) {
      registration.pushManager.getSubscription().then(function (subscription) {
        if (subscription) {
          // Already subscribed
          if (notificationBell) notificationBell.classList.add("active");
          if (pushBanner) pushBanner.classList.add("hidden");
          if (pushTestBtn) pushTestBtn.classList.remove("hidden");

          // Re-sync with server in case cloud container restarted
          window.Pluxee.fetch("/api/push/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(subscription.toJSON()),
          }).catch(function () {});
        } else {
          // Not subscribed — show prompt after brief delay (unless dismissed)
          if (notificationBell) notificationBell.classList.remove("active");
          var dismissed = localStorage.getItem("pluxee_push_dismissed");
          if (!dismissed) {
            setTimeout(function () {
              if (pushBanner) pushBanner.classList.remove("hidden");
            }, 3000);
          }
        }
      });
    });
  }

  // Subscribe to push notifications
  function subscribePush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      showError("Push notifications não suportadas neste browser.");
      return;
    }

    // 1. Get VAPID public key from server
    window.Pluxee.fetch("/api/push/vapid-public-key")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data.publicKey) {
          showError("VAPID keys não configuradas no servidor.");
          return;
        }

        var applicationServerKey = urlBase64ToUint8Array(data.publicKey);

        return navigator.serviceWorker.ready.then(function (registration) {
          return registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: applicationServerKey,
          });
        });
      })
      .then(function (subscription) {
        if (!subscription) return;

        // 2. Send subscription to server
        return window.Pluxee.fetch("/api/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(subscription.toJSON()),
        }).then(function (r) {
          return r.json();
        });
      })
      .then(function (result) {
        if (result && result.success) {
          showSuccess("Notificações push ativadas! 🔔");
          if (notificationBell) {
            notificationBell.classList.add("active");
            notificationBell.classList.add("ringing");
            setTimeout(function () {
              notificationBell.classList.remove("ringing");
            }, 1000);
          }
          if (pushBanner) pushBanner.classList.add("hidden");
          if (pushTestBtn) pushTestBtn.classList.remove("hidden");
        }
      })
      .catch(function (err) {
        console.error("Push subscription failed:", err);
        if (err.name === "NotAllowedError") {
          showError(
            "Permissão de notificação negada. Ativa nas definições do browser.",
          );
        } else {
          showError("Erro ao ativar notificações: " + err.message);
        }
      });
  }

  // Unsubscribe from push
  function unsubscribePush() {
    navigator.serviceWorker.ready.then(function (registration) {
      registration.pushManager.getSubscription().then(function (subscription) {
        if (!subscription) return;

        var endpoint = subscription.endpoint;
        subscription.unsubscribe().then(function () {
          window.Pluxee.fetch("/api/push/unsubscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ endpoint: endpoint }),
          });
          if (notificationBell) notificationBell.classList.remove("active");
          if (pushTestBtn) pushTestBtn.classList.add("hidden");
          showSuccess("Notificações push desativadas.");
        });
      });
    });
  }

  // Test push notification
  function testPush() {
    window.Pluxee.fetch("/api/push/test", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data.success) {
          showSuccess(
            "Notificação de teste enviada! Verifica o teu dispositivo.",
          );
        } else {
          showError(data.error || "Erro ao enviar notificação de teste.");
        }
      })
      .catch(function () {
        showError("Erro de ligação ao servidor.");
      });
  }

  // Bell button click: toggle push or show banner
  if (notificationBell) {
    notificationBell.addEventListener("click", function () {
      if (notificationBell.classList.contains("active")) {
        // Already subscribed — offer to unsubscribe or test
        if (confirm("Notificações push ativas.\n\nDesativar notificações?")) {
          unsubscribePush();
        } else {
          testPush();
        }
      } else {
        // Not subscribed — trigger subscription
        subscribePush();
      }
    });
  }

  // Push banner buttons
  if (pushEnableBtn) {
    pushEnableBtn.addEventListener("click", function () {
      subscribePush();
    });
  }

  if (pushTestBtn) {
    pushTestBtn.addEventListener("click", function () {
      testPush();
    });
  }

  if (pushDismissBtn) {
    pushDismissBtn.addEventListener("click", function () {
      if (pushBanner) pushBanner.classList.add("hidden");
      localStorage.setItem("pluxee_push_dismissed", "1");
    });
  }

  // ================================================================
  // PWA: INSTALL PROMPT (Add to Home Screen)
  // ================================================================

  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredInstallPrompt = e;

    // Show install banner after a delay (if not already installed)
    var installed = localStorage.getItem("pluxee_pwa_installed");
    if (!installed) {
      setTimeout(function () {
        if (pwaInstallBanner) pwaInstallBanner.classList.remove("hidden");
      }, 5000);
    }
  });

  if (pwaInstallBtn) {
    pwaInstallBtn.addEventListener("click", function () {
      if (deferredInstallPrompt) {
        deferredInstallPrompt.prompt();
        deferredInstallPrompt.userChoice.then(function (result) {
          if (result.outcome === "accepted") {
            showSuccess("App Pluxee instalada! 📱");
            localStorage.setItem("pluxee_pwa_installed", "1");
          }
          deferredInstallPrompt = null;
          if (pwaInstallBanner) pwaInstallBanner.classList.add("hidden");
        });
      }
    });
  }

  if (pwaInstallDismiss) {
    pwaInstallDismiss.addEventListener("click", function () {
      if (pwaInstallBanner) pwaInstallBanner.classList.add("hidden");
      localStorage.setItem("pluxee_pwa_installed", "dismissed");
    });
  }

  // Detect app already installed
  window.addEventListener("appinstalled", function () {
    localStorage.setItem("pluxee_pwa_installed", "1");
    if (pwaInstallBanner) pwaInstallBanner.classList.add("hidden");
  });

  // ================================================================
  // INIT: Register SW & Check Push State
  // ================================================================
  registerServiceWorker().then(function () {
    checkPushState();
  });

  // Launch data fetch & polling
})();
