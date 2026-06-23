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
OUTAGE_FILE = os.path.join(DATA_DIR, "outage_state.json")
PID_FILE = os.path.join(DATA_DIR, "monitor.pid")
LOG_FILE = os.path.join(DATA_DIR, "monitor.log")
STATE_MARKER = "📊 PLUXEE_MONITOR_STATE"
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
    """Load the last-known state from disk, falling back to Telegram."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Local file missing (e.g. Render restart wiped /tmp) — try Telegram
    return _telegram_load_state()


def save_state(balance, transactions):
    """Persist the current state to disk and back up to Telegram."""
    os.makedirs(DATA_DIR, exist_ok=True)
    fingerprints = [_tx_fingerprint(tx) for tx in transactions]
    state = {
        "last_check": datetime.now(timezone.utc).isoformat(),
        "balance": balance,
        "transactions": transactions,
        "fingerprints": fingerprints,
        "tx_count": len(transactions),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    # Backup to Telegram pinned message (survives Render restarts)
    _telegram_save_state(balance, fingerprints, len(transactions))


def _tx_fingerprint(tx):
    """Create a unique fingerprint for a transaction."""
    raw = f"{tx['date']}|{tx['description']}|{tx['amount']}"
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Telegram state persistence (survives Render /tmp wipes)
# ---------------------------------------------------------------------------

def _telegram_get_credentials():
    """Get Telegram bot credentials from environment."""
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    return None, None


def _telegram_save_state(balance, fingerprints, tx_count):
    """Save state to a Telegram pinned message as backup.

    Edits the existing pinned message if it belongs to us, otherwise sends
    a new one and pins it silently.
    """
    token, chat_id = _telegram_get_credentials()
    if not token or not chat_id:
        return

    compact = {
        "lc": datetime.now(timezone.utc).isoformat(),
        "bal": {
            "l": balance.get("lunch_pass", 0.0),
            "e": balance.get("eco_pass", 0.0),
            "g": balance.get("gift_pass", 0.0),
            "c": balance.get("conso_pass", 0.0),
        },
        "fps": fingerprints,
        "tc": tx_count,
    }
    text = f"{STATE_MARKER}\n{json.dumps(compact, separators=(',', ':'), ensure_ascii=False)}"

    try:
        # Check for an existing pinned state message to edit in-place
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": chat_id},
            timeout=10,
        )
        if r.status_code == 200:
            pinned = r.json().get("result", {}).get("pinned_message")
            if pinned and STATE_MARKER in pinned.get("text", ""):
                msg_id = pinned["message_id"]
                edit_r = requests.post(
                    f"https://api.telegram.org/bot{token}/editMessageText",
                    json={"chat_id": chat_id, "message_id": msg_id, "text": text},
                    timeout=10,
                )
                if edit_r.status_code == 200:
                    log.info("State backed up to Telegram (edited pinned message)")
                    return
                # "message is not modified" is fine — state hasn't changed
                if edit_r.status_code == 400 and "not modified" in edit_r.text.lower():
                    return

        # No existing pinned state message or edit failed — send new & pin
        send_r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_notification": True},
            timeout=10,
        )
        if send_r.status_code == 200:
            msg_id = send_r.json()["result"]["message_id"]
            requests.post(
                f"https://api.telegram.org/bot{token}/pinChatMessage",
                json={"chat_id": chat_id, "message_id": msg_id,
                      "disable_notification": True},
                timeout=10,
            )
            log.info("State backed up to Telegram (new pinned message)")
    except Exception as e:
        log.warning(f"Failed to back up state to Telegram: {e}")


def _telegram_load_state():
    """Load state from the Telegram pinned message. Returns state dict or None."""
    token, chat_id = _telegram_get_credentials()
    if not token or not chat_id:
        return None

    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": chat_id},
            timeout=10,
        )
        if r.status_code != 200:
            return None

        pinned = r.json().get("result", {}).get("pinned_message")
        if not pinned:
            return None

        text = pinned.get("text", "")
        if STATE_MARKER not in text:
            return None

        # JSON sits on the line after the marker
        json_str = text[text.index(STATE_MARKER) + len(STATE_MARKER):].strip()
        compact = json.loads(json_str)

        state = {
            "last_check": compact.get("lc"),
            "balance": {
                "lunch_pass": compact.get("bal", {}).get("l", 0.0),
                "eco_pass": compact.get("bal", {}).get("e", 0.0),
                "gift_pass": compact.get("bal", {}).get("g", 0.0),
                "conso_pass": compact.get("bal", {}).get("c", 0.0),
            },
            "transactions": [],
            "fingerprints": compact.get("fps", []),
            "tx_count": compact.get("tc", 0),
        }
        log.info(f"State restored from Telegram (tx_count={state['tx_count']})")
        return state
    except Exception as e:
        log.warning(f"Failed to load state from Telegram: {e}")
        return None

# ---------------------------------------------------------------------------
# Outage detection
# ---------------------------------------------------------------------------

def _looks_like_outage(current_balance, current_txs, prev_state):
    """Detect if the API response looks like a system outage rather than real data.

    When Pluxee goes down, the portal returns an empty page with 0 balance
    and 0 transactions. We detect this by comparing against our last known
    good state: if we previously had transactions and balance but now
    everything is gone, it's almost certainly an outage.
    """
    if prev_state is None:
        return False  # First run, can't detect outage

    prev_tx_count = prev_state.get("tx_count", len(prev_state.get("transactions", [])))
    prev_balance = prev_state.get("balance", {})
    prev_total = sum(prev_balance.values())
    current_total = sum(current_balance.values())

    # If we previously had transactions and balance, but now we get nothing,
    # this is almost certainly an outage, not real activity
    if prev_tx_count > 0 and prev_total > 0 and len(current_txs) == 0 and current_total == 0:
        return True

    # If balance suddenly drops to exactly 0 AND all transactions vanished
    if prev_total > 1.0 and current_total == 0 and len(current_txs) == 0:
        return True

    return False


def _load_outage_state():
    """Load the outage tracking state from disk. Returns None if not in outage."""
    if not os.path.exists(OUTAGE_FILE):
        return None
    try:
        with open(OUTAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_outage_state(prev_balance):
    """Save outage state to disk. Called once when an outage is first detected."""
    os.makedirs(DATA_DIR, exist_ok=True)
    state = {
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "notification_sent": False,
        "last_good_balance": prev_balance,
    }
    with open(OUTAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return state


def _mark_outage_notified():
    """Mark that the outage notification has already been sent."""
    outage = _load_outage_state()
    if outage:
        outage["notification_sent"] = True
        with open(OUTAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(outage, f, indent=2, ensure_ascii=False)


def _clear_outage_state():
    """Remove the outage file, signalling recovery."""
    try:
        os.remove(OUTAGE_FILE)
    except OSError:
        pass

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


def notify_transaction(topic, tx, balance_total):
    """Send a notification for a single transaction.

    Args:
        topic: ntfy / Telegram topic
        tx: transaction dict with amount, description
        balance_total: running balance AFTER this transaction (float)
    """
    is_credit = tx["amount"] > 0

    if is_credit:
        emoji = "green_circle"
        title = "Pluxee — Carregamento"
    else:
        emoji = "red_circle"
        title = "Pluxee — Gasto"

    amount_str = fmt_eur(tx["amount"])
    total_str = fmt_eur(balance_total)

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
        priority="default",
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

    Includes outage detection: if the API returns empty data when we previously
    had transactions and balance, we assume the system is down and skip all
    notifications and state updates to prevent false alarms and recovery spam.

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

    # ----- Outage detection -----
    outage_state = _load_outage_state()

    if _looks_like_outage(current_balance, current_txs, prev_state):
        # API appears to be down — don't save state, don't notify about changes
        if outage_state is None:
            # First detection of this outage
            prev_balance = prev_state.get("balance", {})
            outage_state = _save_outage_state(prev_balance)
            log.warning("⚠️  Outage detected! API returned empty data. "
                        "Skipping state update to prevent false notifications.")
            # Send a single "system down" notification
            prev_total = sum(prev_balance.values())
            send_notification(
                topic=config["topic"],
                title="⚠️ Pluxee — Sistema indisponível",
                message=(
                    f"O sistema Pluxee parece estar em baixo.\n"
                    f"Dados devolvidos sem saldo e sem transações.\n"
                    f"\n"
                    f"As notificações estão pausadas até o sistema recuperar.\n"
                    f"💰 Último saldo conhecido: {fmt_eur(prev_total)}"
                ),
                tags="warning",
            )
            _mark_outage_notified()
        else:
            log.warning("⚠️  Outage still ongoing. Skipping check. "
                        f"(down since {outage_state.get('detected_at', 'unknown')})")
        return 0, None

    # ----- Recovery from outage -----
    if outage_state is not None:
        # System is back! We have real data again.
        detected_at = outage_state.get("detected_at", "unknown")
        log.info(f"✅ System recovered! Outage started at {detected_at}. "
                 "Reconciling state silently.")
        _clear_outage_state()
        # Send a single "recovered" notification
        send_notification(
            topic=config["topic"],
            title="✅ Pluxee — Sistema recuperado",
            message=(
                f"O sistema Pluxee está novamente operacional.\n"
                f"\n"
                f"💰 Saldo atual: {fmt_eur(total)}"
            ),
            tags="white_check_mark",
        )
        # Save the current (recovered) state without sending per-transaction
        # notifications — the transactions aren't truly "new", they just
        # reappeared after the outage.
        save_state(current_balance, current_txs)
        return 0, current_balance

    # ----- Normal flow (no outage) -----

    # Compare transactions by fingerprint
    if "fingerprints" in prev_state:
        prev_fingerprints = set(prev_state["fingerprints"])
    else:
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
        # Process in chronological order (portal usually lists newest first)
        new_txs_chrono = list(reversed(new_txs))
        # Compute a running balance so each notification shows the correct
        # intermediate balance, not the same final balance for all.
        remaining = sum(tx["amount"] for tx in new_txs_chrono)
        for tx in new_txs_chrono:
            remaining -= tx["amount"]
            balance_after = total - remaining
            notify_transaction(config["topic"], tx, balance_after)
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
