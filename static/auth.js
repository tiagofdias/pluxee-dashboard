/* Session tokens stay in an HttpOnly cookie; only the CSRF token lives in memory. */
(function () {
  "use strict";
  const demo =
    document.body.dataset.demo === "true" ||
    /\/demo(?:\.html)?\/?$/.test(location.pathname);
  let csrf = "";
  function showProfile(name) {
    name =
      typeof name === "string" && name.trim() ? name.trim() : "A tua conta";
    const words = name.split(/\s+/u);
    const initials =
      name === "A tua conta"
        ? "EU"
        : (
            Array.from(words[0])[0] +
            (words.length > 1 ? Array.from(words[words.length - 1])[0] : "")
          ).toLocaleUpperCase("pt-PT");
    document.querySelectorAll("[data-profile-name]").forEach((el) => {
      el.textContent = name;
      el.title = name;
    });
    document.querySelectorAll("[data-profile-initials]").forEach((el) => {
      el.textContent = initials;
      el.setAttribute("aria-label", name);
    });
  }
  function lock() {
    document.querySelector(".workspace")?.replaceChildren();
    location.replace("./login");
  }
  const api = {
    isDemo: demo,
    pushAvailable: false,
    async fetch(url, options = {}) {
      if (demo) throw new Error("A demonstração não acede à API privada.");
      const headers = new Headers(options.headers || {});
      headers.set("X-Pluxee-Request", "1");
      if (
        !["GET", "HEAD", "OPTIONS"].includes(
          (options.method || "GET").toUpperCase(),
        )
      )
        headers.set("X-CSRF-Token", csrf);
      const response = await fetch(url, {
        ...options,
        headers,
        credentials: "same-origin",
        cache: "no-store",
      });
      if (response.status === 401) {
        lock();
        throw new Error("Sessão terminada");
      }
      return response;
    },
  };
  api.ready = (async () => {
    if (!demo) {
      try {
        const response = await fetch("/api/auth/session", {
          cache: "no-store",
          credentials: "same-origin",
          signal: AbortSignal.timeout(15000),
        });
        const session = await response.json();
        if (!response.ok || !session.authenticated) {
          lock();
          return false;
        }
        csrf = session.csrf_token;
        api.pushAvailable = session.push_available === true;
        showProfile(session.display_name);
      } catch (error) {
        lock();
        return false;
      }
    }
    document.body.classList.remove("auth-pending");
    const action = document.getElementById("session-action");
    if (action) {
      action.textContent = demo ? "Entrar" : "Sair";
      action.disabled = false;
      action.addEventListener("click", async () => {
        if (demo) {
          location.href = document.body.dataset.loginUrl || "./login";
          return;
        }
        action.disabled = true;
        try {
          const response = await api.fetch("/api/auth/logout", {
            method: "POST",
          });
          if (!response.ok)
            throw new Error(
              "Não foi possível terminar a sessão. Tenta novamente.",
            );
          lock();
        } catch (error) {
          action.disabled = false;
          window.dispatchEvent(
            new CustomEvent("pluxee:notice", {
              detail: { message: error.message, error: true },
            }),
          );
        }
      });
    }
    if (!api.pushAvailable)
      document.getElementById("notification-bell")?.classList.add("hidden");
    if (demo) {
      showProfile("Alex Martins");
      document.title = "Pluxee · Demonstração";
      document.getElementById("notification-bell")?.classList.add("hidden");
      const badge = document.createElement("span");
      badge.className = "demo-mode-tag";
      badge.textContent = "DEMO";
      document.querySelector(".breadcrumb")?.append(badge);
    }
    return true;
  })();
  window.Pluxee = api;
  window.addEventListener("pageshow", async (event) => {
    if (!event.persisted || demo) return;
    document.body.classList.add("auth-pending");
    try {
      const response = await api.fetch("/api/auth/session");
      if (!response.ok) {
        lock();
        return;
      }
      const session = await response.json();
      csrf = session.csrf_token;
      showProfile(session.display_name);
      document.body.classList.remove("auth-pending");
    } catch (error) {
      lock();
    }
  });
})();
