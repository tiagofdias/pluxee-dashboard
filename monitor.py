"""Pluxee Transaction Monitor — Background service with ntfy push notifications.

Periodically checks for new Pluxee transactions and sends push notifications
to your Android phone via ntfy.sh, including the transaction details and
remaining balance.

Usage:
    python monitor.py              # Run with .env config
    python monitor.py --once       # Single check (useful for cron)
    python monitor.py --test       # Send a test notification
"""

import os
import sys
import json
import time
import signal
import hashlib
import argparse
import logging
from datetime import datetime, timezone

import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))
from pluxee_scraper import fetch_all

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# On Render, use /tmp (persists between requests on the same instance).
# Locally, use ./data
if os.getenv("RENDER"):
    DATA_DIR = "/tmp/pluxee-data"
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

STATE_FILE = os.path.join(DATA_DIR, "transactions.json")
PID_FILE = os.path.join(DATA_DIR, "monitor.pid")
LOG_FILE = os.path.join(DATA_DIR, "monitor.log")
NTFY_URL = "https://ntfy.sh"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("pluxee-monitor")

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config():
    """Load configuration from environment variables (supports .env via dotenv)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except ImportError:
        pass  # dotenv not installed, rely on OS env vars

    nif = os.getenv("PLUXEE_NIF", "").strip()
    password = os.getenv("PLUXEE_PASSWORD", "").strip()
    topic = os.getenv("NTFY_TOPIC", "pluxee-tiago-a7x9k2").strip()
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    if not nif or not password:
        log.error("PLUXEE_NIF and PLUXEE_PASSWORD must be set in .env or environment")
        sys.exit(1)

    return {
        "nif": nif,
        "password": password,
        "topic": topic,
        "interval": interval,
    }

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state():
    """Load the last-known state from disk."""
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_state(balance, transactions):
    """Persist the current state to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    state = {
        "last_check": datetime.now(timezone.utc).isoformat(),
        "balance": balance,
        "transactions": transactions,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _tx_fingerprint(tx):
    """Create a unique fingerprint for a transaction."""
    raw = f"{tx['date']}|{tx['description']}|{tx['amount']}"
    return hashlib.md5(raw.encode()).hexdigest()

# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

def fmt_eur(val):
    """Format a float as a Euro string like €12,34."""
    sign = "+" if val > 0 else ""
    formatted = f"{abs(val):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{sign}€{formatted}" if val >= 0 else f"-€{formatted}"


def send_telegram(token, chat_id, title, message):
    """Send a push notification via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Format message with bold title
    text = f"<b>{title}</b>\n\n{message}"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=10
        )
        if r.status_code == 200:
            log.info(f"Telegram notification sent: {title}")
            return True
        else:
            log.warning(f"Telegram responded with status {r.status_code}: {r.text}")
            return False
    except Exception as e:
        log.error(f"Failed to send Telegram notification: {e}")
        return False


def send_notification(topic, title, message, tags=None, priority=None):
    """Send a push notification via ntfy.sh and/or Telegram."""
    # 1. Try sending via Telegram if credentials are set
    tg_token = os.getenv("TELEGRAM_TOKEN", "").strip()
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    tg_success = False
    if tg_token and tg_chat_id:
        tg_success = send_telegram(tg_token, tg_chat_id, title, message)

    # 2. Try sending via ntfy
    url = f"{NTFY_URL}"
    payload = {
        "topic": topic,
        "title": title,
        "message": message,
    }
    if tags:
        payload["tags"] = [tags] if isinstance(tags, str) else tags
    if priority:
        payload["priority"] = 3  # default priority

    headers = {"Content-Type": "application/json"}
    token = os.getenv("NTFY_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    ntfy_success = False
    try:
        r = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            log.info(f"ntfy notification sent: {title}")
            ntfy_success = True
        else:
            log.warning(f"ntfy responded with status {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Failed to send ntfy notification: {e}")

    return tg_success or ntfy_success


def notify_transaction(topic, tx, balance):
    """Send a notification for a single transaction."""
    is_credit = tx["amount"] > 0
    total = sum(balance.values())

    if is_credit:
        emoji = "green_circle"
        title = "Pluxee — Carregamento"
    else:
        emoji = "red_circle"
        title = "Pluxee — Gasto"

    amount_str = fmt_eur(tx["amount"])
    total_str = fmt_eur(total)

    message = (
        f"{tx['description']}\n"
        f"{amount_str}\n"
        f"\n"
        f"💰 Saldo restante: {total_str}"
    )

    send_notification(
        topic=topic,
        title=title,
        message=message,
        tags=emoji,
        priority="default" if is_credit else "default",
    )


def send_test_notification(topic):
    """Send a test notification to verify the setup."""
    send_notification(
        topic=topic,
        title="🔔 Pluxee Monitor — Teste",
        message=(
            "O monitor de notificações está a funcionar!\n"
            "Irá receber alertas sempre que houver novas transações."
        ),
        tags="white_check_mark",
        priority="default",
    )

# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------

def write_pid():
    """Write the current PID to the PID file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def read_pid():
    """Read the PID from the PID file. Returns None if not found."""
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except (ValueError, IOError):
        return None


def remove_pid():
    """Remove the PID file."""
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def is_monitor_running():
    """Check if a monitor process is currently running."""
    pid = read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)  # Check if process exists
        return True
    except OSError:
        remove_pid()
        return False

# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def check_for_new_transactions(config):
    """Check Pluxee for new transactions and send notifications for any found.

    Returns (new_count, balance) tuple.
    """
    log.info("Checking for new transactions...")

    try:
        result = fetch_all(config["nif"], config["password"])
    except ValueError as e:
        log.error(f"Login/fetch error: {e}")
        return 0, None
    except requests.exceptions.ConnectionError as e:
        log.error(f"Connection error: {e}")
        return 0, None
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        return 0, None

    current_balance = result["balance"]
    current_txs = result["transactions"]
    total = sum(current_balance.values())

    log.info(f"Fetched {len(current_txs)} transactions. Balance: €{total:.2f}")

    # Load previous state
    prev_state = load_state()

    if prev_state is None:
        # First run — save state, don't notify (we don't know what's "new")
        log.info("First run — saving initial state (no notifications sent)")
        save_state(current_balance, current_txs)
        return 0, current_balance

    # Compare transactions by fingerprint
    prev_fingerprints = set(
        _tx_fingerprint(tx) for tx in prev_state.get("transactions", [])
    )
    current_fingerprints = set(_tx_fingerprint(tx) for tx in current_txs)

    new_fingerprints = current_fingerprints - prev_fingerprints
    new_txs = [
        tx for tx in current_txs
        if _tx_fingerprint(tx) in new_fingerprints
    ]

    if new_txs:
        log.info(f"Found {len(new_txs)} new transaction(s)!")
        for tx in new_txs:
            notify_transaction(config["topic"], tx, current_balance)
    else:
        log.info("No new transactions found.")

    # Also check for balance changes without visible transactions
    prev_balance = prev_state.get("balance", {})
    prev_total = sum(prev_balance.values())
    if abs(total - prev_total) > 0.01 and not new_txs:
        diff = total - prev_total
        direction = "subiu" if diff > 0 else "desceu"
        send_notification(
            topic=config["topic"],
            title=f"Pluxee — Saldo {direction}",
            message=(
                f"O saldo alterou {fmt_eur(diff)}\n"
                f"\n"
                f"💰 Saldo atual: {fmt_eur(total)}"
            ),
            tags="chart_with_upwards_trend" if diff > 0 else "chart_with_downwards_trend",
        )

    # Save updated state
    save_state(current_balance, current_txs)
    return len(new_txs), current_balance

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True

def _handle_signal(signum, frame):
    global _running
    log.info("Received stop signal. Shutting down...")
    _running = False


def run_loop(config):
    """Run the monitor in a continuous loop."""
    global _running

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    write_pid()
    interval = config["interval"]

    log.info(f"Monitor started (PID: {os.getpid()}, interval: {interval}s, topic: {config['topic']})")

    try:
        while _running:
            try:
                check_for_new_transactions(config)
            except Exception as e:
                log.error(f"Check failed: {e}")

            # Sleep in small increments so we can respond to signals
            for _ in range(interval):
                if not _running:
                    break
                time.sleep(1)
    finally:
        remove_pid()
        log.info("Monitor stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pluxee Transaction Monitor")
    parser.add_argument("--once", action="store_true", help="Run a single check and exit")
    parser.add_argument("--test", action="store_true", help="Send a test notification and exit")
    parser.add_argument("--status", action="store_true", help="Check if the monitor is running")
    parser.add_argument("--stop", action="store_true", help="Stop a running monitor")
    args = parser.parse_args()

    config = load_config()

    if args.test:
        log.info(f"Sending test notification to topic: {config['topic']}")
        send_test_notification(config["topic"])
        return

    if args.status:
        if is_monitor_running():
            pid = read_pid()
            print(f"Monitor is running (PID: {pid})")
        else:
            print("Monitor is not running")
        return

    if args.stop:
        pid = read_pid()
        if pid and is_monitor_running():
            os.kill(pid, signal.SIGTERM)
            print(f"Sent stop signal to monitor (PID: {pid})")
        else:
            print("Monitor is not running")
            remove_pid()
        return

    if args.once:
        count, balance = check_for_new_transactions(config)
        if balance:
            total = sum(balance.values())
            print(f"Check complete. {count} new transaction(s). Balance: €{total:.2f}")
        return

    # Default: run continuous loop
    if is_monitor_running():
        pid = read_pid()
        log.error(f"Monitor is already running (PID: {pid}). Use --stop first.")
        sys.exit(1)

    run_loop(config)


if __name__ == "__main__":
    main()
