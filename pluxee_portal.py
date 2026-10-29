"""Official consumer portal login, for verifying credential-based access.

No password, cookies, personal HTML or token values are logged or written to disk.
This authenticates a web session; it does not assume it is a mobile ApiClaim.
"""
import re
from urllib.parse import urljoin, urlsplit

import requests

PORTAL = "https://portal.admin.pluxee.pt"
ALLOWED_HOSTS = {"portal.admin.pluxee.pt", "consumidores.pluxee.pt"}


class PortalLoginError(Exception):
    pass


def _safe_portal_url(value):
    url = urljoin(PORTAL + "/", value)
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise PortalLoginError("The portal returned an unexpected redirect. Login was stopped.")
    return url


def _claim_from_json(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "apiclaim" and isinstance(child, str) and child.strip():
                return child
            candidate = _claim_from_json(child)
            if candidate:
                return candidate
    elif isinstance(value, list):
        for child in value:
            candidate = _claim_from_json(child)
            if candidate:
                return candidate
    return None


class PortalSession:
    def __init__(self):
        self._http = requests.Session()
        self._http.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/html", "Origin": PORTAL, "Referer": PORTAL + "/"})
        self.authenticated = False
        self.mobile_claim = None
        self.claim_source = None

    def close(self):
        self._http.close()
        self.mobile_claim = None
        self.authenticated = False

    def _get_page(self, url):
        for _ in range(4):
            response = self._http.get(_safe_portal_url(url), timeout=20, allow_redirects=False)
            if response.is_redirect:
                url = _safe_portal_url(response.headers.get("Location", ""))
                continue
            if not response.ok:
                raise PortalLoginError("The consumer portal is temporarily unavailable.")
            return response
        raise PortalLoginError("The portal redirected too many times. Login was stopped.")

    def login(self, nif, password):
        if not isinstance(nif, str) or not re.fullmatch(r"[0-9]{9}", nif.strip()):
            raise PortalLoginError("Enter the nine-digit NIF used by the official consumer portal.")
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise PortalLoginError("Enter your Pluxee password.")
        self.authenticated = False
        self.mobile_claim = None
        self.claim_source = None
        try:
            self._get_page(PORTAL + "/")
            # Use POST body only. Never reproduce the legacy site's password-in-URL JSONP.
            response = self._http.post(PORTAL + "/login_processing.php", data={"nif": nif.strip(), "pass": password, "reg": "true"}, timeout=20, allow_redirects=False)
            if not response.ok or response.is_redirect:
                raise PortalLoginError("The credential login endpoint did not accept a POST response.")
            try:
                result = response.json()
            except ValueError:
                raise PortalLoginError("The portal did not return the expected login response.") from None
            if not isinstance(result, dict) or result.get("sucesso") is not True:
                # Do not reflect upstream HTML or identifiers into errors.
                raise PortalLoginError("Pluxee did not accept the login. No retry was attempted.")
            redirect = result.get("local")
            if not isinstance(redirect, str) or not redirect:
                raise PortalLoginError("The portal did not provide an authenticated page.")
            dashboard = self._get_page(_safe_portal_url(redirect))
            # Detect an immediate return to the login form instead of an authenticated page.
            if re.search(r'id=[\"\x27]login_form_page[\"\x27]', dashboard.text, re.I):
                raise PortalLoginError("The portal returned to the login page; the session was not verified.")
            self.authenticated = True
            claim = _claim_from_json(result)
            source = "login JSON" if claim else None
            if not claim:
                claim = dashboard.headers.get("ApiClaim") or response.headers.get("ApiClaim")
                source = "response header" if claim else None
            if not claim:
                match = re.search(r'[\"\x27]?ApiClaim[\"\x27]?\s*[:=]\s*[\"\x27]([^\"\x27\s<>]{16,})[\"\x27]', dashboard.text, re.I)
                if match:
                    claim, source = match.group(1), "authenticated page"
            self.mobile_claim, self.claim_source = claim, source
            return {"portal_login_verified": True, "api_claim_found": bool(claim), "claim_source": source}
        except requests.RequestException:
            raise PortalLoginError("Connection to the official portal failed. No retry was attempted.") from None
