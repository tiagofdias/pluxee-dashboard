"""Pluxee Portugal Balance Dashboard — Flask Backend

Uses the shared pluxee_scraper module for portal scraping.
Includes API endpoints for the notification monitor control.
Works both locally (with .env file) and on Render (with dashboard env vars).
"""

import os
import re
import json
import signal
import subprocess
import traceback
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import pluxee_scraper

app = Flask(__name__, static_folder="static")
CORS(app)

BASE_URL = "https://portal.admin.pluxee.pt"
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "debug")
MONITOR_SCRIPT = os.path.join(os.path.dirname(__file__), "monitor.py")
IS_RENDER = bool(os.getenv("RENDER"))

# Data directory — use /tmp on Render (ephemeral but writable)
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
    # os.getenv() covers Render dashboard vars + real environment
    val = os.getenv(key, "").strip()
    if val:
        return val

    # Fallback: try .env file (local dev)
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
        return  # On Render, env vars are managed via the dashboard

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


@app.route("/api/balance", methods=["POST"])
def get_balance():
    """Fetch the Pluxee balance using provided credentials (NIF + password)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    nif = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not nif or not password:
        return jsonify({"error": "NIF and password are required"}), 400

    try:
        session, soup, dash_url = pluxee_scraper.login(nif, password)
        balance = pluxee_scraper.fetch_balance(session, soup)
        transactions = pluxee_scraper.fetch_transactions(soup)

        # Extract values for debug response
        all_vals_debug = []
        page_text_debug = soup.get_text()
        euro_pattern_debug = re.compile(r'(\d+[.,]\d{2})\s*€|€\s*(\d+[.,]\d{2})')
        for m in euro_pattern_debug.finditer(page_text_debug):
            val_str = m.group(1) or m.group(2)
            try:
                all_vals_debug.append(float(val_str.replace(",", ".")))
            except ValueError:
                pass

        return jsonify({
            "success": True,
            "balance": balance,
            "transactions": transactions,
            "debug": {
                "dashboard_url": dash_url,
                "page_title": soup.title.string if soup.title else None,
                "amounts_found": all_vals_debug,
            }
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 401
    except requests.exceptions.ConnectionError as e:
        print(f"[CONNECTION ERROR] {e}")
        return jsonify({"error": "Could not connect to Pluxee. Please check your internet connection."}), 502
    except Exception as e:
        print(f"[UNEXPECTED ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"error": f"{type(e).__name__}: {str(e)}"}), 500


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

    topic = _get_env("NTFY_TOPIC", "pluxee-tiago-a7x9k2")
    interval = int(_get_env("POLL_INTERVAL_SECONDS", "300"))
    has_creds = bool(_get_env("PLUXEE_NIF") and _get_env("PLUXEE_PASSWORD"))
    has_token = bool(os.getenv("NTFY_TOKEN"))
    has_telegram = bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    # Read last few log lines
    last_log = ""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                last_log = "".join(lines[-5:]) if lines else ""
        except IOError:
            pass

    # Read last state
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
        "topic": topic,
        "interval": interval,
        "has_credentials": has_creds,
        "has_token": has_token,
        "has_telegram": has_telegram,
        "is_render": IS_RENDER,
        "last_check": state.get("last_check") if state else None,
        "last_log": last_log,
    })


@app.route("/api/notifications/start", methods=["POST"])
def notification_start():
    """Start the background monitor.

    On Render: triggers a single cron check immediately (cron-job.org handles the loop).
    Locally: starts monitor.py as a background subprocess.
    """
    data = request.get_json() or {}

    nif = data.get("nif", "").strip() or _get_env("PLUXEE_NIF")
    password = data.get("password", "").strip() or _get_env("PLUXEE_PASSWORD")
    topic = data.get("topic", "").strip() or _get_env("NTFY_TOPIC", "pluxee-tiago-a7x9k2")

    if not nif or not password:
        return jsonify({"error": "Credentials required. Set PLUXEE_NIF and PLUXEE_PASSWORD."}), 400

    if IS_RENDER:
        # On Render: run one check now, cron-job.org handles the rest
        try:
            from monitor import check_for_new_transactions
            config = {
                "nif": nif,
                "password": password,
                "topic": topic,
                "interval": 300,
            }
            count, balance = check_for_new_transactions(config)
            total = sum(balance.values()) if balance else 0
            return jsonify({
                "success": True,
                "running": True,
                "mode": "cron",
                "new_transactions": count,
                "balance": total,
                "topic": topic,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"Check failed: {str(e)}"}), 500
    else:
        # Local: save to .env and start subprocess
        if _is_monitor_running():
            return jsonify({"error": "Monitor is already running", "running": True}), 409

        _save_env({
            "PLUXEE_NIF": nif,
            "PLUXEE_PASSWORD": password,
            "NTFY_TOPIC": topic,
            "POLL_INTERVAL_SECONDS": str(data.get("interval", 300)),
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
                "topic": topic,
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
    """Send a test notification."""
    data = request.get_json() or {}
    topic = data.get("topic", "").strip() or _get_env("NTFY_TOPIC", "pluxee-tiago-a7x9k2")

    try:
        from monitor import send_test_notification
        send_test_notification(topic)
        return jsonify({"success": True, "topic": topic})
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
    if "nif" in data:
        env_updates["PLUXEE_NIF"] = data["nif"].strip()
    if "password" in data:
        env_updates["PLUXEE_PASSWORD"] = data["password"].strip()
    if "topic" in data:
        env_updates["NTFY_TOPIC"] = data["topic"].strip()
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
    """Health check endpoint — use with external cron to keep Render alive."""
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/api/cron/check", methods=["GET", "POST"])
def cron_check():
    """Endpoint for external cron services to trigger a transaction check.

    Set up cron-job.org to hit this every 5 minutes.
    Optionally protect with a secret: ?secret=YOUR_CRON_SECRET
    """
    # Optional secret protection
    cron_secret = os.getenv("CRON_SECRET", "")
    if cron_secret:
        provided = request.args.get("secret", "") or (request.get_json() or {}).get("secret", "")
        if provided != cron_secret:
            return jsonify({"error": "Invalid secret"}), 403

    nif = _get_env("PLUXEE_NIF")
    password = _get_env("PLUXEE_PASSWORD")
    topic = _get_env("NTFY_TOPIC", "pluxee-tiago-a7x9k2")

    if not nif or not password:
        return jsonify({"error": "PLUXEE_NIF and PLUXEE_PASSWORD not configured"}), 500

    try:
        from monitor import check_for_new_transactions
        config = {
            "nif": nif,
            "password": password,
            "topic": topic,
            "interval": 300,
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
