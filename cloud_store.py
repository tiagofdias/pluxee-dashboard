"""Server-only Supabase REST storage. No credentials are exposed to the browser."""
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values


class CloudError(RuntimeError):
    pass


def setting(name, default=""):
    value = os.environ.get(name)
    if value is None:
        value = dotenv_values(Path(__file__).parent / ".env").get(name, default)
    return str(value or default).strip()


def enabled():
    return all(setting(key) for key in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "DASHBOARD_OWNER_ID"))


def auth_ready():
    return enabled() and bool(setting("SUPABASE_PUBLISHABLE_KEY"))


def request(method, path, *, public=False, params=None, payload=None, headers=None):
    url = setting("SUPABASE_URL").rstrip("/")
    key = setting("SUPABASE_PUBLISHABLE_KEY" if public else "SUPABASE_SECRET_KEY")
    if not url or not key:
        raise CloudError("Cloud storage is not configured")
    if not url.startswith("https://"):
        raise CloudError("Supabase requires HTTPS")
    auth_headers = {"apikey": key, "Content-Type": "application/json"}
    # Support existing legacy keys; new sb_secret keys are not JWTs.
    if key.startswith("eyJ"):
        auth_headers["Authorization"] = f"Bearer {key}"
    auth_headers.update(headers or {})
    try:
        response = requests.request(method, url + path, params=params, json=payload,
                                    headers=auth_headers, timeout=15)
        if not response.ok:
            # Never include response bodies, passwords, API keys or tokens in logs/errors.
            raise CloudError(f"Cloud request failed (HTTP {response.status_code})")
        return response.json() if response.content else None
    except (requests.RequestException, ValueError) as exc:
        raise CloudError("Cloud service unavailable") from None


def read_row(table, **filters):
    rows = request("GET", "/rest/v1/" + table,
                   params={**{key: "eq." + str(value) for key, value in filters.items()}, "limit": "1"})
    return rows[0] if rows else None


def upsert(table, record, conflict="user_id"):
    return request("POST", "/rest/v1/" + table, params={"on_conflict": conflict}, payload=record,
                   headers={"Prefer": "resolution=merge-duplicates,return=minimal"})


def load_state():
    row = read_row("pluxee_state", user_id=setting("DASHBOARD_OWNER_ID"))
    return row["state"] if row else None


def save_state(state):
    upsert("pluxee_state", {"user_id": setting("DASHBOARD_OWNER_ID"), "state": state,
                            "updated_at": datetime.now(timezone.utc).isoformat()})


def load_history():
    row = read_row("pluxee_ledger", user_id=setting("DASHBOARD_OWNER_ID"))
    return row["transactions"] if row else None


def save_history(transactions):
    upsert("pluxee_ledger", {"user_id": setting("DASHBOARD_OWNER_ID"), "transactions": transactions,
                             "updated_at": datetime.now(timezone.utc).isoformat()})
