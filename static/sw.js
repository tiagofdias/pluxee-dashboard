/* Only public assets are cached. Financial data and pages always use the network. */
const CACHE_NAME = "pluxee-public-v5";
const STATIC_ASSETS = [
  "/style.css",
  "/login.css",
  "/app.js",
  "/auth.js",
  "/demo-data.js",
  "/login.js",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)),
  );
  self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith("pluxee-") && name !== CACHE_NAME)
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET")
    return;
  if (!STATIC_ASSETS.includes(url.pathname)) {
    event.respondWith(
      fetch(event.request, { cache: "no-store" }).catch(
        () =>
          new Response("Ligação necessária para aceder ao espaço privado.", {
            status: 503,
            headers: {
              "Cache-Control": "no-store",
              "Content-Type": "text/plain;charset=utf-8",
            },
          }),
      ),
    );
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          event.waitUntil(
            caches
              .open(CACHE_NAME)
              .then((cache) => cache.put(event.request, clone)),
          );
        }
        return response;
      })
      .catch(() => caches.match(event.request)),
  );
});

// ---------------------------------------------------------------------------
// Push Notification — Display native notification
// ---------------------------------------------------------------------------
self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (e) {
    payload = {
      title: "Pluxee",
      body: event.data ? event.data.text() : "Nova notificação",
    };
  }

  const title = payload.title || "Pluxee Dashboard";
  const options = {
    body: payload.body || "",
    icon: payload.icon || "/icons/icon-192.png",
    badge: payload.badge || "/icons/badge-72.png",
    tag: payload.tag || "pluxee-notification",
    renotify: true,
    requireInteraction: false,
    vibrate: [200, 100, 200],
    timestamp: payload.timestamp
      ? new Date(payload.timestamp).getTime()
      : Date.now(),
    data: payload.data || {},
    actions: [
      { action: "open", title: "Ver Dashboard" },
      { action: "dismiss", title: "Fechar" },
    ],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// ---------------------------------------------------------------------------
// Notification Click — Open or focus the dashboard
// ---------------------------------------------------------------------------
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  if (event.action === "dismiss") return;

  const urlToOpen =
    (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windowClients) => {
        // Focus existing window if available
        for (const client of windowClients) {
          if (client.url.includes(self.location.origin) && "focus" in client) {
            client.focus();
            if (urlToOpen !== "/") client.navigate(urlToOpen);
            return;
          }
        }
        // Otherwise open a new window
        return clients.openWindow(urlToOpen);
      }),
  );
});
