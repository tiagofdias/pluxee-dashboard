(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const submit = $("login-submit");
  $("toggle-password").addEventListener("click", () => {
    const visible = $("login-password").type === "password";
    $("login-password").type = visible ? "text" : "password";
    $("toggle-password").textContent = visible ? "Ocultar" : "Mostrar";
    $("toggle-password").setAttribute("aria-pressed", visible);
  });
  async function initialize() {
    try {
      const response = await fetch("/api/auth/session", {
        credentials: "same-origin",
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      // Upgrade the old worker even before login. Versioned assets prevent the
      // legacy cache-first worker from mixing old CSS/JS with the new page.
      if ("serviceWorker" in navigator && data.configured !== undefined) {
        navigator.serviceWorker
          .register("./sw.js", { updateViaCache: "none" })
          .then((registration) => registration.update())
          .catch(() => {});
      }
      if (data.authenticated) {
        location.replace("./");
        return;
      }
      if (data.configured === false) {
        $("login-config").textContent =
          "O acesso privado está em configuração. Entretanto, podes explorar a demonstração com dados fictícios.";
        $("login-config").classList.remove("hidden");
        return;
      }
      if (response.status !== 401) throw new Error();
      submit.disabled = false;
    } catch (error) {
      $("login-config").textContent =
        "O acesso privado está temporariamente indisponível. A demonstração continua disponível.";
      $("login-config").classList.remove("hidden");
    }
  }
  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = "A verificar…";
    $("login-error").classList.add("hidden");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal: AbortSignal.timeout(45000),
        headers: {
          "Content-Type": "application/json",
          "X-Pluxee-Request": "1",
        },
        body: JSON.stringify({
          email: $("login-email").value.trim(),
          password: $("login-password").value,
        }),
      });
      const data = await response.json();
      $("login-password").value = "";
      if (!response.ok)
        throw new Error(data.error || "Não foi possível iniciar sessão.");
      location.replace("./");
    } catch (error) {
      $("login-error").textContent =
        error.name === "TimeoutError"
          ? "A ligação demorou demasiado. Tenta novamente."
          : error.message;
      $("login-error").classList.remove("hidden");
      submit.disabled = false;
      submit.textContent = "Entrar com segurança ↗";
    }
  });
  initialize();
})();
