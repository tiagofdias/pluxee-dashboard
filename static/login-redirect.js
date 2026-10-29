/* The public demo never collects credentials. Move login to its private origin. */
(function () {
  "use strict";
  const link = document.getElementById("private-login-link");
  const destination = document.body.dataset.privateLoginUrl;
  if (!link || !destination) return;
  try {
    const target = new URL(destination);
    if (target.protocol !== "https:" || target.username || target.password)
      return;
    link.href = target.href;
    if (target.origin !== location.origin) location.replace(target.href);
  } catch (error) {
    // The visible link remains available when automatic navigation is blocked.
  }
})();
