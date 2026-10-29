"""Web Push Notification Service — PWA Push Notifications.

Replaces Telegram bot notifications with native Web Push API (VAPID).
Sends push notifications directly to registered PWA/browser devices.

Subscriptions are stored in a local JSON file for simplicity.
In production, use a database.
"""

import os
import sys
import json
import logging
import traceback
import hashlib
import cloud_store
from datetime import datetime, timezone

log = logging.getLogger("pluxee-push")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

if os.getenv("RENDER"):
    DATA_DIR = "/tmp/pluxee-data"
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

SUBSCRIPTIONS_FILE = os.path.join(DATA_DIR, "push_subscriptions.json")


def _get_vapid_keys():
    """Get VAPID keys from environment, .env file, or auto-generate in DATA_DIR."""
    public_key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    private_key = os.getenv("VAPID_PRIVATE_KEY", "").strip()

    if not public_key or not private_key:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            k = k.strip()
                            v = v.strip()
                            if k == "VAPID_PUBLIC_KEY" and not public_key:
                                public_key = v
                            elif k == "VAPID_PRIVATE_KEY" and not private_key:
                                private_key = v
            except IOError:
                pass

    os.makedirs(DATA_DIR, exist_ok=True)
    pem_path = os.path.join(DATA_DIR, "vapid_private.pem")
    pub_path = os.path.join(DATA_DIR, "vapid_public.txt")

    # If private_key was provided as a PEM string, write it to pem_path for pywebpush
    if private_key and "-----BEGIN" in private_key:
        try:
            with open(pem_path, "w", encoding="utf-8") as f:
                f.write(private_key.replace("\\n", "\n"))
            private_key = pem_path
        except IOError:
            pass
    elif private_key and os.path.exists(private_key):
        # Already a valid file path
        pass
    elif not private_key and os.path.exists(pem_path):
        private_key = pem_path
        if not public_key and os.path.exists(pub_path):
            try:
                with open(pub_path, "r", encoding="utf-8") as f:
                    public_key = f.read().strip()
            except IOError:
                pass

    # If still missing, auto-generate keypair
    if not public_key or not private_key:
        try:
            from py_vapid import Vapid, utils
            from cryptography.hazmat.primitives import serialization

            v = Vapid()
            v.generate_keys()
            with open(pem_path, "wb") as f:
                f.write(v.private_pem())

            raw_pub = v.public_key.public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
            public_key = utils.b64urlencode(raw_pub)
            with open(pub_path, "w", encoding="utf-8") as f:
                f.write(public_key)

            private_key = pem_path
            log.info("Auto-generated new VAPID keypair in DATA_DIR")
        except Exception as e:
            log.error(f"Failed to auto-generate VAPID keys: {e}")

    return public_key, private_key


def get_vapid_public_key():
    """Return the VAPID public key for client-side subscription."""
    pub, _ = _get_vapid_keys()
    return pub


# ---------------------------------------------------------------------------
# Subscription Management
# ---------------------------------------------------------------------------

LOCAL_SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(__file__), "data", "push_subscriptions.json")


def load_subscriptions():
    """Load all push subscriptions from disk (checking both DATA_DIR and repo data dir)."""
    if cloud_store.enabled():
        rows = cloud_store.request("GET", "/rest/v1/pluxee_push_subscriptions", params={
            "user_id": "eq." + cloud_store.setting("DASHBOARD_OWNER_ID"),
            "expires_at": "gt." + datetime.now(timezone.utc).isoformat(),
        })
        return [row["subscription"] for row in rows]
    for path in (SUBSCRIPTIONS_FILE, LOCAL_SUBSCRIPTIONS_FILE):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    return data
            except (json.JSONDecodeError, IOError):
                pass
    return []


def save_subscriptions(subs):
    """Save subscriptions list to disk in both DATA_DIR and repo data directory."""
    if cloud_store.enabled():
        for sub in subs:
            if not sub.get("session_hash") or not sub.get("session_expires_at"):
                continue  # Never import unauthenticated subscriptions from the old app.
            cloud_store.upsert("pluxee_push_subscriptions", {
                "endpoint_hash": hashlib.sha256(sub["endpoint"].encode()).hexdigest(),
                "user_id": cloud_store.setting("DASHBOARD_OWNER_ID"),
                "session_hash": sub["session_hash"], "expires_at": sub["session_expires_at"],
                "subscription": sub,
            }, conflict="endpoint_hash")
        return
    for path in (SUBSCRIPTIONS_FILE, LOCAL_SUBSCRIPTIONS_FILE):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(subs, f, indent=2, ensure_ascii=False)
        except IOError:
            pass


def add_subscription(subscription_info):
    """Register a new push subscription.

    Args:
        subscription_info: dict with keys 'endpoint', 'keys' (containing 'p256dh' and 'auth')

    Returns:
        bool: True if added, False if already existed
    """
    subs = load_subscriptions()
    endpoint = subscription_info.get("endpoint", "")

    # Avoid duplicates
    for s in subs:
        if s.get("endpoint") == endpoint:
            # Update keys in case they changed
            s["keys"] = subscription_info.get("keys", {})
            s["updated_at"] = datetime.now(timezone.utc).isoformat()
            s["session_hash"] = subscription_info.get("session_hash")
            s["session_expires_at"] = subscription_info.get("session_expires_at")
            save_subscriptions(subs)
            return False

    subs.append({
        "session_hash": subscription_info.get("session_hash"),
        "session_expires_at": subscription_info.get("session_expires_at"),
        "endpoint": endpoint,
        "keys": subscription_info.get("keys", {}),
        "expirationTime": subscription_info.get("expirationTime"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    save_subscriptions(subs)
    log.info(f"New push subscription registered: {endpoint[:60]}...")
    return True


def remove_subscription(endpoint):
    """Remove a push subscription by endpoint URL."""
    if cloud_store.enabled():
        cloud_store.request("DELETE", "/rest/v1/pluxee_push_subscriptions", params={
            "endpoint_hash": "eq." + hashlib.sha256(endpoint.encode()).hexdigest(),
            "user_id": "eq." + cloud_store.setting("DASHBOARD_OWNER_ID"),
        })
        return True
    subs = load_subscriptions()
    initial_count = len(subs)
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    if len(subs) < initial_count:
        save_subscriptions(subs)
        log.info(f"Removed push subscription: {endpoint[:60]}...")
        return True
    return False


# ---------------------------------------------------------------------------
# Push Notification Sending
# ---------------------------------------------------------------------------

def send_push_notification(title, body, icon=None, badge=None, tag=None, data=None, url=None):
    """Send a push notification to ALL registered devices.

    Args:
        title: Notification title
        body: Notification body text
        icon: URL to notification icon (optional)
        badge: URL to notification badge (optional)
        tag: Notification tag for grouping (optional)
        data: Extra data dict to pass to the client (optional)
        url: URL to open when notification is clicked (optional)

    Returns:
        dict: { "sent": int, "failed": int, "removed": int }
    """
    from pywebpush import webpush, WebPushException

    public_key, private_key = _get_vapid_keys()
    if not public_key or not private_key:
        log.warning("VAPID keys not configured — cannot send push notifications.")
        return {"sent": 0, "failed": 0, "removed": 0}

    subs = load_subscriptions()
    if not subs:
        log.info("No push subscriptions registered.")
        return {"sent": 0, "failed": 0, "removed": 0}

    payload = {
        "title": title,
        "body": body,
        "icon": icon or "/icons/icon-192.png",
        "badge": badge or "/icons/badge-72.png",
        "tag": tag or "pluxee-notification",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data or {},
    }
    if url:
        payload["data"]["url"] = url

    payload_json = json.dumps(payload, ensure_ascii=False)

    sent = 0
    failed = 0
    to_remove = []

    vapid_claims = {
        "sub": "mailto:pluxee-dashboard@example.com",
    }

    for sub in subs:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": sub.get("keys", {}),
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload_json,
                vapid_private_key=private_key,
                vapid_claims=vapid_claims,
            )
            sent += 1
        except WebPushException as e:
            log.error(f"Push failed to {sub['endpoint'][:50]}: {e}")
            # 404 or 410 means subscription is no longer valid
            if hasattr(e, 'response') and e.response is not None:
                status = e.response.status_code
                if status in (404, 410):
                    to_remove.append(sub["endpoint"])
            failed += 1
        except Exception as e:
            log.error(f"Unexpected push error: {e}")
            traceback.print_exc()
            failed += 1

    # Clean up expired subscriptions
    if to_remove:
        for endpoint in to_remove:
            remove_subscription(endpoint)

    log.info(f"Push notifications: {sent} sent, {failed} failed, {len(to_remove)} removed")
    return {"sent": sent, "failed": failed, "removed": len(to_remove)}


def send_transaction_notification(tx, balance_after):
    """Send a push notification for a new transaction."""
    is_credit = tx["amount"] > 0

    if is_credit:
        title = "🟢 Carregamento Recebido"
        tag = "pluxee-reload"
    else:
        title = "🔴 Pagamento Efetuado"
        tag = "pluxee-payment"

    amount = abs(tx["amount"])
    amount_str = f"{'+'if is_credit else '-'}€{amount:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    balance_str = f"€{balance_after:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")

    body = f"{tx['description']}\n{amount_str} · Saldo: {balance_str}"

    return send_push_notification(
        title=title,
        body=body,
        tag=tag,
        data={
            "type": "transaction",
            "amount": tx["amount"],
            "balance": balance_after,
            "description": tx["description"],
        },
        url="/",
    )


def send_test_push_notification():
    """Send a test push notification to verify setup."""
    return send_push_notification(
        title="🔔 Pluxee — Teste",
        body="As notificações push estão a funcionar! Irás receber alertas automáticos de transações.",
        tag="pluxee-test",
        data={"type": "test"},
        url="/",
    )


def send_outage_notification(last_balance):
    """Notify about Pluxee system outage."""
    balance_str = f"€{last_balance:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return send_push_notification(
        title="⚠️ Sistema Pluxee Indisponível",
        body=f"O sistema Pluxee parece estar em baixo.\nÚltimo saldo: {balance_str}",
        tag="pluxee-outage",
        data={"type": "outage"},
    )


def send_recovery_notification(current_balance):
    """Notify about Pluxee system recovery."""
    balance_str = f"€{current_balance:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return send_push_notification(
        title="✅ Sistema Pluxee Recuperado",
        body=f"O sistema está novamente operacional.\nSaldo atual: {balance_str}",
        tag="pluxee-recovery",
        data={"type": "recovery"},
    )


def send_auth_expired_notification():
    """Notify about expired API session."""
    return send_push_notification(
        title="⚠️ Sessão Expirada",
        body="A sessão da API Pluxee expirou. Atualize o PLUXEE_API_CLAIM nas definições.",
        tag="pluxee-auth",
        data={"type": "auth_expired"},
    )
