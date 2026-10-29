"""Pluxee Portugal Balance Dashboard — Flask Backend

Uses the official Pluxee Portugal Mobile API (pluxee_api module).
Provides REST API endpoints for balance, transactions, and background notification monitor control.
Works both locally (with .env file) and on Render (with dashboard env vars).
"""

import os
import json
import signal
import subprocess
import traceback
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request, send_from_directory

import pluxee_api
import history_store
import push_notifications

app = Flask(__name__, static_folder="static")
# Render terminates HTTPS at its reverse proxy. Trust exactly that proxy hop.
if os.getenv("RENDER", "").lower() in ("true", "1"):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
import cloud_store
import dashboard_auth
app.register_blueprint(dashboard_auth.blueprint)
app.before_request(dashboard_auth.check_private_request)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024


@app.after_request
def protect_responses(response):
    # Private pages/data must not survive logout in an HTTP cache or a PWA cache.
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    if request.is_secure or cloud_store.setting("RENDER"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.get("/auth.js")
@app.get("/login.js")
@app.get("/demo-data.js")
@app.get("/login.css")
def public_javascript():
    return send_from_directory("static", request.path.lstrip("/"))

MONITOR_SCRIPT = os.path.join(os.path.dirname(__file__), "monitor.py")
IS_RENDER = bool(os.getenv("RENDER"))

if IS_RENDER:
    DATA_DIR = "/tmp/pluxee-data"
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

os.makedirs(DATA_DIR, exist_ok=True)

PID_FILE = os.path.join(DATA_DIR, "monitor.pid")
LOG_FILE = os.path.join(DATA_DIR, "monitor.log")
STATE_FILE = os.path.join(DATA_DIR, "transactions.json")


# ===========================================================================
# Config helpers — works with both .env files AND os.getenv()
# ===========================================================================

def _get_env(key, default=""):
    """Get a config value: checks os.getenv() first, then .env file."""
    val = os.getenv(key, "").strip()
    if val:
        return val

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        if k.strip() == key:
                            return v.strip()
        except IOError:
            pass

    return default


def _save_env(env_vars):
    """Save env vars to .env file (local dev only, no-op on Render)."""
    if IS_RENDER:
        return

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    existing_keys = set()

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}\n")
                        existing_keys.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ===========================================================================
# Routes
# ===========================================================================

@app.route("/")
def index():
    """Serve the main dashboard page."""
    return send_from_directory("static", "index.html")


@app.route("/favicon.ico")
def favicon():
    """Return empty favicon to avoid 404."""
    return "", 204


@app.route("/style.css")
def serve_css():
    return send_from_directory("static", "style.css")


@app.route("/app.js")
def serve_js():
    return send_from_directory("static", "app.js")


@app.route("/sw.js")
def serve_sw():
    """Serve Service Worker from root scope (critical for PWA)."""
    response = send_from_directory("static", "sw.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/manifest.json")
def serve_manifest():
    """Serve PWA Web App Manifest."""
    return send_from_directory("static", "manifest.json", mimetype="application/manifest+json")


@app.route("/icons/<path:filename>")
def serve_icon(filename):
    """Serve PWA icons."""
    return send_from_directory("static/icons", filename)


@app.route("/api/balance", methods=["GET", "POST"])
def get_balance():
    """Only fetch the card belonging to this browser's own Pluxee login."""
    row = g.private_session
    account = row["account"]
    try:
        result = account.fetch_snapshot()
        # Memory only; never merge into the server owner's historical ledger.
        if not account.active:
            return jsonify(error="Session ended"), 401
        row["snapshot"] = result
        return jsonify(result)
    except dashboard_auth.pluxee_mobile_auth.MobileLoginError as error:
        dashboard_auth.revoke_session(row)
        return jsonify(error=str(error)), 401
    except dashboard_auth.pluxee_mobile_auth.MobileUnavailable as error:
        cached = row.get("snapshot")
        if cached:
            return jsonify({**cached, "cached": True, "warning": str(error)}), 200
        return jsonify(error=str(error)), 503


# ===========================================================================
# Notification Monitor API
# ===========================================================================

def _read_pid():
    """Read the monitor PID from the PID file."""
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except (ValueError, IOError):
        return None


def _is_monitor_running():
    """Check if the monitor process is running."""
    pid = _read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False


@app.route("/api/notifications/status", methods=["GET"])
def notification_status():
    """Session-local refresh status. Never return the owner's logs or PID."""
    snapshot = g.private_session.get("snapshot") or {}
    return jsonify(running=False, last_check=snapshot.get("updated_at"), push_available=False)


@app.route("/api/notifications/start", methods=["POST"])
def notification_start():
    """Start the background monitor."""
    data = request.get_json() or {}

    api_claim = data.get("api_claim", "").strip() or _get_env("PLUXEE_API_CLAIM")
    card_id = data.get("card_id", "").strip() or _get_env("PLUXEE_CARD_ID")
    benefit_id = data.get("benefit_id", "").strip() or _get_env("PLUXEE_BENEFIT_ID")
    telegram_token = data.get("telegram_token", "").strip() or _get_env("TELEGRAM_TOKEN")
    telegram_chat_id = data.get("telegram_chat_id", "").strip() or _get_env("TELEGRAM_CHAT_ID")
    interval = int(data.get("interval", 0) or _get_env("POLL_INTERVAL_SECONDS", "300"))

    if not api_claim or not card_id or not benefit_id:
        return jsonify({"error": "Credenciais da API Móvel necessárias (PLUXEE_API_CLAIM, etc.)."}), 400

    config = {
        "api_claim": api_claim,
        "card_id": card_id,
        "benefit_id": benefit_id,
        "telegram_token": telegram_token,
        "telegram_chat_id": telegram_chat_id,
        "interval": interval,
    }

    if _is_monitor_running():
        return jsonify({"success": True, "running": True, "pid": _read_pid()}), 200

    if not IS_RENDER:
        _save_env({
            "PLUXEE_API_CLAIM": api_claim,
            "PLUXEE_CARD_ID": card_id,
            "PLUXEE_BENEFIT_ID": benefit_id,
            "POLL_INTERVAL_SECONDS": str(interval),
        })

    try:
        import sys
        import time
        env = os.environ.copy()
        env["PLUXEE_API_CLAIM"] = api_claim
        env["PLUXEE_CARD_ID"] = card_id
        env["PLUXEE_BENEFIT_ID"] = benefit_id
        if telegram_token:
            env["TELEGRAM_TOKEN"] = telegram_token
        if telegram_chat_id:
            env["TELEGRAM_CHAT_ID"] = telegram_chat_id
        env["POLL_INTERVAL_SECONDS"] = str(interval)

        proc = subprocess.Popen(
            [sys.executable, MONITOR_SCRIPT],
            cwd=os.path.dirname(__file__),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        time.sleep(1)
        if proc.poll() is not None:
            return jsonify({"error": "Monitor process exited immediately. Check logs."}), 500

        return jsonify({
            "success": True,
            "running": True,
            "mode": "subprocess",
            "pid": proc.pid,
        })
    except Exception as e:
        return jsonify({"error": f"Failed to start monitor: {str(e)}"}), 500


@app.route("/api/notifications/stop", methods=["POST"])
def notification_stop():
    """Stop the background monitor."""
    pid = _read_pid()
    if not pid or not _is_monitor_running():
        return jsonify({"success": True, "running": False, "message": "Monitor was not running"})

    try:
        os.kill(pid, signal.SIGTERM)
        import time
        for _ in range(10):
            time.sleep(0.5)
            if not _is_monitor_running():
                break
        return jsonify({"success": True, "running": False})
    except OSError as e:
        return jsonify({"error": f"Failed to stop monitor: {str(e)}"}), 500


@app.route("/api/notifications/test", methods=["POST"])
def notification_test():
    """Send a test notification to Telegram."""
    try:
        from monitor import send_test_notification
        send_test_notification()
        return jsonify({"success": True})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Failed to send test notification: {str(e)}"}), 500


@app.route("/api/notifications/config", methods=["POST"])
def notification_config():
    """Update notification configuration (local only)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    env_updates = {}
    if "api_claim" in data:
        env_updates["PLUXEE_API_CLAIM"] = data["api_claim"].strip()
    if "card_id" in data:
        env_updates["PLUXEE_CARD_ID"] = data["card_id"].strip()
    if "benefit_id" in data:
        env_updates["PLUXEE_BENEFIT_ID"] = data["benefit_id"].strip()
    if "telegram_token" in data:
        env_updates["TELEGRAM_TOKEN"] = data["telegram_token"].strip()
    if "telegram_chat_id" in data:
        env_updates["TELEGRAM_CHAT_ID"] = data["telegram_chat_id"].strip()
    if "interval" in data:
        env_updates["POLL_INTERVAL_SECONDS"] = str(int(data["interval"]))

    if env_updates:
        _save_env(env_updates)

    return jsonify({"success": True})


# ===========================================================================
# PWA Push Notification API
# ===========================================================================

@app.route("/api/push/vapid-public-key", methods=["GET"])
def push_vapid_key():
    """Return the VAPID public key for client-side push subscription."""
    key = push_notifications.get_vapid_public_key()
    if not key:
        return jsonify({"error": "VAPID keys not configured."}), 500
    return jsonify({"publicKey": key})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    """Register a new push notification subscription."""
    data = request.get_json()
    if not data or not data.get("endpoint"):
        return jsonify({"error": "Invalid subscription data."}), 400

    data["session_hash"] = g.private_session["token_hash"]
    data["session_expires_at"] = g.private_session["expires_at"]
    is_new = push_notifications.add_subscription(data)
    return jsonify({
        "success": True,
        "is_new": is_new,
        "subscriptions": len(push_notifications.load_subscriptions()),
    })


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    """Remove a push notification subscription."""
    data = request.get_json()
    endpoint = data.get("endpoint", "") if data else ""
    if not endpoint:
        return jsonify({"error": "Endpoint required."}), 400

    removed = push_notifications.remove_subscription(endpoint)
    return jsonify({"success": True, "removed": removed})


@app.route("/api/push/test", methods=["POST"])
def push_test():
    """Send a test push notification to all registered devices."""
    try:
        result = push_notifications.send_test_push_notification()
        return jsonify({"success": True, **result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Failed to send test push: {str(e)}"}), 500


@app.route("/api/push/status", methods=["GET"])
def push_status():
    """Check push notification configuration status."""
    subs = push_notifications.load_subscriptions()
    has_vapid = bool(push_notifications.get_vapid_public_key())
    return jsonify({
        "configured": has_vapid,
        "subscriptions": len(subs),
        "devices": [
            {
                "endpoint_short": s.get("endpoint", "")[:60] + "...",
                "created_at": s.get("created_at"),
            }
            for s in subs
        ],
    })


# ===========================================================================
# Health / Cron Endpoints
# ===========================================================================

@app.route("/ping", methods=["GET"])
def ping():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/api/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """Telegram webhook endpoint for instant command processing (e.g. /balance)."""
    data = request.get_json() or {}
    msg = data.get("message")
    if not msg:
        return jsonify({"ok": True})

    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id")
    if not text or not chat_id:
        return jsonify({"ok": True})

    auth_chat_id = _get_env("TELEGRAM_CHAT_ID")
    if auth_chat_id and str(chat_id) != str(auth_chat_id):
        return jsonify({"ok": True})

    try:
        from monitor import handle_telegram_message, load_config
        config = load_config()
        handle_telegram_message(config, text, chat_id)
    except Exception as e:
        traceback.print_exc()

    return jsonify({"ok": True})


@app.route("/api/cron/check", methods=["GET", "POST"])
def cron_check():
    """Endpoint for external cron services to trigger a transaction check."""
    api_claim = _get_env("PLUXEE_API_CLAIM")
    card_id = _get_env("PLUXEE_CARD_ID")
    benefit_id = _get_env("PLUXEE_BENEFIT_ID")
    telegram_token = _get_env("TELEGRAM_TOKEN")
    telegram_chat_id = _get_env("TELEGRAM_CHAT_ID")
    interval = int(_get_env("POLL_INTERVAL_SECONDS", "300"))

    if not api_claim or not card_id or not benefit_id:
        return jsonify({"error": "PLUXEE_API_CLAIM, PLUXEE_CARD_ID, and PLUXEE_BENEFIT_ID not configured"}), 500

    try:
        from monitor import check_for_new_transactions, process_telegram_updates
        config = {
            "api_claim": api_claim,
            "card_id": card_id,
            "benefit_id": benefit_id,
            "telegram_token": telegram_token,
            "telegram_chat_id": telegram_chat_id,
            "interval": interval,
        }
        process_telegram_updates(config, timeout=0)
        count, balance = check_for_new_transactions(config)
        process_telegram_updates(config, timeout=0)
        total = sum(balance.values()) if balance else 0

        return jsonify({
            "success": True,
            "new_transactions": count,
            "balance": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
