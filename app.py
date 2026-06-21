"""Pluxee Portugal Balance Dashboard — Flask Backend

Uses the shared pluxee_scraper module for portal scraping.
Includes API endpoints for the notification monitor control.
"""

import os
import re
import json
import signal
import subprocess
import traceback
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import pluxee_scraper

app = Flask(__name__, static_folder="static")
CORS(app)

BASE_URL = "https://portal.admin.pluxee.pt"
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "debug")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PID_FILE = os.path.join(DATA_DIR, "monitor.pid")
LOG_FILE = os.path.join(DATA_DIR, "monitor.log")
MONITOR_SCRIPT = os.path.join(os.path.dirname(__file__), "monitor.py")


@app.route("/")
def index():
    """Serve the main dashboard page."""
    return send_from_directory("static", "index.html")


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
        # Process doesn't exist — clean up stale PID file
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False


def _load_env():
    """Load the .env file as a dict."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env_vars[key.strip()] = value.strip()
    return env_vars


def _save_env(env_vars):
    """Save env vars to the .env file (preserves comments)."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    existing_keys = set()

    # Read existing file to preserve structure & comments
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

    # Add new keys not in the file
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


@app.route("/api/notifications/status", methods=["GET"])
def notification_status():
    """Check the current notification monitor status."""
    running = _is_monitor_running()
    pid = _read_pid() if running else None
    env = _load_env()

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
    state_file = os.path.join(DATA_DIR, "transactions.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return jsonify({
        "running": running,
        "pid": pid,
        "topic": env.get("NTFY_TOPIC", "pluxee-tiago-a7x9k2"),
        "interval": int(env.get("POLL_INTERVAL_SECONDS", 300)),
        "has_credentials": bool(env.get("PLUXEE_NIF") and env.get("PLUXEE_PASSWORD")),
        "last_check": state.get("last_check") if state else None,
        "last_log": last_log,
    })


@app.route("/api/notifications/start", methods=["POST"])
def notification_start():
    """Start the background monitor."""
    if _is_monitor_running():
        return jsonify({"error": "Monitor is already running", "running": True}), 409

    data = request.get_json() or {}

    # Save credentials to .env if provided
    nif = data.get("nif", "").strip()
    password = data.get("password", "").strip()
    topic = data.get("topic", "pluxee-tiago-a7x9k2").strip()
    interval = data.get("interval", 300)

    if nif and password:
        _save_env({
            "PLUXEE_NIF": nif,
            "PLUXEE_PASSWORD": password,
            "NTFY_TOPIC": topic,
            "POLL_INTERVAL_SECONDS": str(interval),
        })
    else:
        # Check if credentials exist
        env = _load_env()
        if not env.get("PLUXEE_NIF") or not env.get("PLUXEE_PASSWORD"):
            return jsonify({"error": "Credentials required. Provide nif and password."}), 400

    # Start the monitor as a background process
    try:
        import sys
        python = sys.executable
        proc = subprocess.Popen(
            [python, MONITOR_SCRIPT],
            cwd=os.path.dirname(__file__),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Give it a moment to start
        import time
        time.sleep(1)

        if proc.poll() is not None:
            return jsonify({"error": "Monitor process exited immediately. Check logs."}), 500

        return jsonify({
            "success": True,
            "running": True,
            "pid": proc.pid,
            "topic": topic,
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
        # Wait briefly for it to stop
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
    topic = data.get("topic", "").strip()

    if not topic:
        env = _load_env()
        topic = env.get("NTFY_TOPIC", "pluxee-tiago-a7x9k2")

    try:
        from monitor import send_test_notification
        send_test_notification(topic)
        return jsonify({"success": True, "topic": topic})
    except Exception as e:
        return jsonify({"error": f"Failed to send test notification: {str(e)}"}), 500


@app.route("/api/notifications/config", methods=["POST"])
def notification_config():
    """Update notification configuration."""
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
    return jsonify({"status": "ok", "timestamp": __import__("datetime").datetime.utcnow().isoformat()})


@app.route("/api/cron/check", methods=["GET", "POST"])
def cron_check():
    """Endpoint for external cron services to trigger a transaction check.

    This replaces the need for a persistent background monitor process.
    Set up an external cron (e.g. cron-job.org) to hit this every 5 minutes.
    Optionally protect with a secret: ?secret=YOUR_CRON_SECRET
    """
    # Optional secret protection
    cron_secret = os.getenv("CRON_SECRET", "")
    if cron_secret:
        provided = request.args.get("secret", "") or (request.get_json() or {}).get("secret", "")
        if provided != cron_secret:
            return jsonify({"error": "Invalid secret"}), 403

    # Load credentials from environment
    nif = os.getenv("PLUXEE_NIF", "").strip()
    password = os.getenv("PLUXEE_PASSWORD", "").strip()
    topic = os.getenv("NTFY_TOPIC", "pluxee-tiago-a7x9k2").strip()

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
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)

