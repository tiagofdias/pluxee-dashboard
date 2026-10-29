# Credential-login investigation — 2026-10-29

Confirmed from public first-party resources:

- The official Pluxee login page links consumers to `https://portal.admin.pluxee.pt/`.
- Its form uses `nif` and `pass`, with action `/login_processing.php`.
- The published `/assets/js/auth.min.js` handles `sucesso`, `mensagem` and `local`.
- A request to that endpoint without account credentials returned those JSON fields
  and no successful login. No account was tested or retried.
- The repository's earlier `pluxee_scraper.py` also implemented this credential flow.
  That is implementation evidence, not proof of a current successful login.
- The existing ApiClaim is opaque, not a readable JWT. Its value was not printed.
- The checked standard Swagger/OpenAPI locations did not provide mobile-auth docs.
  This does not establish that a mobile login endpoint does not exist.

Still unverified:

- A current successful credential login using POST rather than the legacy page's
  JSONP GET (the checker never puts a password in a URL).
- Whether authenticated responses contain a mobile ApiClaim, or only portal cookies.
- Whether a discovered claim works with the mobile balance/movements endpoints.

Run `python scripts/check_pluxee_login.py` from a private local terminal to make
one credential login attempt. The password is hidden and never saved. Redirects
are restricted to official HTTPS portal hosts. The result shows only status flags,
not passwords, cookies, HTML, financial information or claim values. No automatic
retry is performed. Six isolated tests cover the checker; live credential login
has not been tested because the credentials are not available in this workspace.

Sources:

- https://www.pluxee.pt/login/
- https://portal.admin.pluxee.pt/
- https://portal.admin.pluxee.pt/assets/js/auth.min.js

No username/password flow has been wired into the dashboard yet. The public demo
and backend privacy protections remain in place. Supabase has not been provisioned.

## Updated after APK analysis

The supplied Pluxee Portugal 3.0.7 APK resolves the mobile-auth question:
`CryptoUtilsKt.encrypt` encrypts UTF-8 text with AES-256/CBC and PKCS padding,
encodes the ciphertext with Base64, then appends the 16-character random IV.
`UserRepository` applies this to email and password before login. Its `getApiClaim`
applies the same function to the returned `sessionId`. Numeric user and benefit
IDs are encrypted when used in the observed API queries.

`pluxee_crypto.py` reproduces the APK's built-in, non-account test vector. A fresh
claim generated from the existing locally configured session was accepted by the
live balance endpoint. No password was recovered from screenshots or submitted.
The user subsequently completed a real local credential login: the server returned
HTTP 200 for authentication, session validation, and the balance/movements request.
The web form and terminal checker now use
the mobile email/password flow rather than the portal's NIF login.

Sessions now live only in server memory. Supabase is optional for the separate
owner monitor, not required for dashboard authentication. Decompiled sources and
APK tooling remain under ignored `debug/apk-analysis/` and are not shipped.
