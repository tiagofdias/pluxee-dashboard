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

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import pluxee_api

app = Flask(__name__, static_folder="static")
CORS(app)

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


@app.route("/data.json")
def serve_data():
    return send_from_directory("static", "data.json")


@app.route("/api/balance", methods=["POST"])
def get_balance():
    """Fetch Pluxee balance and transactions via Mobile API."""
    data = request.get_json() or {}

    api_claim = data.get("api_claim", "").strip() or _get_env("PLUXEE_API_CLAIM")
    card_id = data.get("card_id", "").strip() or _get_env("PLUXEE_CARD_ID")
    benefit_id = data.get("benefit_id", "").strip() or _get_env("PLUXEE_BENEFIT_ID")

    if not api_claim or not card_id or not benefit_id:
        return jsonify({
            "error": "Credenciais da API Móvel necessárias (PLUXEE_API_CLAIM, PLUXEE_CARD_ID, PLUXEE_BENEFIT_ID)."
        }), 400

    try:
        result = pluxee_api.fetch_all(api_claim, card_id, benefit_id, num=20)
        return jsonify({
            "success": True,
            "balance": result["balance"],
            "transactions": result["transactions"],
        })
    except pluxee_api.PluxeeAuthError as e:
        return jsonify({"error": f"Sessão expirada ou não autorizada: {str(e)}"}), 401
    except pluxee_api.PluxeeConnectionError as e:
        return jsonify({"error": f"Erro de ligação aos servidores da Pluxee: {str(e)}"}), 502
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Erro inesperado: {str(e)}"}), 500


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
    """Check the current notification monitor status."""
    running = _is_monitor_running()
    pid = _read_pid() if running else None

    interval = int(_get_env("POLL_INTERVAL_SECONDS", "300"))
    has_creds = bool(
        _get_env("PLUXEE_API_CLAIM") and _get_env("PLUXEE_CARD_ID") and _get_env("PLUXEE_BENEFIT_ID")
    )
    has_telegram = bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    last_log = ""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                last_log = "".join(lines[-30:]) if lines else ""
        except IOError:
            pass

    state = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return jsonify({
        "running": running,
        "pid": pid,
        "channel": "Telegram Bot (@CartaoRefeicaoBot)",
        "interval": interval,
        "has_credentials": has_creds,
        "has_telegram": has_telegram,
        "is_render": IS_RENDER,
        "last_check": state.get("last_check") if state else None,
        "last_log": last_log,
    })


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

    if IS_RENDER:
        try:
            from monitor import check_for_new_transactions
            count, balance = check_for_new_transactions(config)
            total = sum(balance.values()) if balance else 0
            return jsonify({
                "success": True,
                "running": True,
                "mode": "cron",
                "new_transactions": count,
                "balance": total,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"Check failed: {str(e)}"}), 500
    else:
        if _is_monitor_running():
            return jsonify({"error": "Monitor is already running", "running": True}), 409

        _save_env({
            "PLUXEE_API_CLAIM": api_claim,
            "PLUXEE_CARD_ID": card_id,
            "PLUXEE_BENEFIT_ID": benefit_id,
            "POLL_INTERVAL_SECONDS": str(interval),
        })

        try:
            import sys
            import time
            proc = subprocess.Popen(
                [sys.executable, MONITOR_SCRIPT],
                cwd=os.path.dirname(__file__),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
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
    if IS_RENDER:
        return jsonify({"success": True, "running": False,
                        "message": "On Render, monitoring is handled by cron-job.org"})

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
# Health / Cron Endpoints
# ===========================================================================

@app.route("/ping", methods=["GET"])
def ping():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/api/cron/check", methods=["GET", "POST"])
def cron_check():
    """Endpoint for external cron services to trigger a transaction check."""
    cron_secret = os.getenv("CRON_SECRET", "")
    if cron_secret:
        provided = request.args.get("secret", "") or (request.get_json() or {}).get("secret", "")
        if provided != cron_secret:
            return jsonify({"error": "Invalid secret"}), 403

    api_claim = _get_env("PLUXEE_API_CLAIM")
    card_id = _get_env("PLUXEE_CARD_ID")
    benefit_id = _get_env("PLUXEE_BENEFIT_ID")
    telegram_token = _get_env("TELEGRAM_TOKEN")
    telegram_chat_id = _get_env("TELEGRAM_CHAT_ID")
    interval = int(_get_env("POLL_INTERVAL_SECONDS", "300"))

    if not api_claim or not card_id or not benefit_id:
        return jsonify({"error": "PLUXEE_API_CLAIM, PLUXEE_CARD_ID, and PLUXEE_BENEFIT_ID not configured"}), 500

    try:
        from monitor import check_for_new_transactions
        config = {
            "api_claim": api_claim,
            "card_id": card_id,
            "benefit_id": benefit_id,
            "telegram_token": telegram_token,
            "telegram_chat_id": telegram_chat_id,
            "interval": interval,
        }
        count, balance = check_for_new_transactions(config)
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
