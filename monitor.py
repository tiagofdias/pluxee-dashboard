"""Pluxee Transaction Monitor — Telegram Push Notifications.

Periodically checks for new Pluxee transactions using the official Mobile API
and sends push notifications via Telegram, including the transaction details
and exact remaining balance.

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
import io
import argparse
import logging
from datetime import datetime, timezone

import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))
from pluxee_api import fetch_all, PluxeeAuthError, PluxeeConnectionError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

if os.getenv("RENDER"):
    DATA_DIR = "/tmp/pluxee-data"
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

STATE_FILE = os.path.join(DATA_DIR, "transactions.json")
OUTAGE_FILE = os.path.join(DATA_DIR, "outage_state.json")
PID_FILE = os.path.join(DATA_DIR, "monitor.pid")
LOG_FILE = os.path.join(DATA_DIR, "monitor.log")
STATE_MARKER = "📊 PLUXEE_MONITOR_STATE"

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
        pass

    api_claim = os.getenv("PLUXEE_API_CLAIM", "").strip()
    card_id = os.getenv("PLUXEE_CARD_ID", "").strip()
    benefit_id = os.getenv("PLUXEE_BENEFIT_ID", "").strip()
    telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    if not api_claim or not card_id or not benefit_id:
        log.error("PLUXEE_API_CLAIM, PLUXEE_CARD_ID, and PLUXEE_BENEFIT_ID must be configured")
        sys.exit(1)

    return {
        "api_claim": api_claim,
        "card_id": card_id,
        "benefit_id": benefit_id,
        "telegram_token": telegram_token,
        "telegram_chat_id": telegram_chat_id,
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

    return _telegram_load_state()


def save_state(balance, transactions, stale_skip_count=0):
    """Persist the current state to disk and back up to Telegram."""
    os.makedirs(DATA_DIR, exist_ok=True)
    fingerprints = [_tx_fingerprint(tx) for tx in transactions]
    state = {
        "last_check": datetime.now(timezone.utc).isoformat(),
        "balance": balance,
        "transactions": transactions,
        "fingerprints": fingerprints,
        "tx_count": len(transactions),
        "stale_skip_count": stale_skip_count,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    # Backup to Telegram pinned message (survives stateless runner cycles)
    _telegram_save_state(balance, fingerprints, len(transactions))

    # Export static/data.json for GitHub Pages dashboard
    _export_site_data(balance, transactions)


def _export_site_data(balance, transactions):
    """Write static data.json for GitHub Pages dashboard."""
    site_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(site_dir, exist_ok=True)
    site_file = os.path.join(site_dir, "data.json")
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "balance": balance,
        "transactions": transactions,
    }
    try:
        with open(site_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except IOError as e:
        log.warning(f"Could not export static/data.json: {e}")


def _tx_fingerprint(tx):
    """Create a unique fingerprint for a transaction."""
    raw = f"{tx['date']}|{tx['description']}|{tx['amount']}"
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Telegram state persistence
# ---------------------------------------------------------------------------

def _telegram_get_credentials():
    """Get Telegram bot credentials from environment."""
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    return None, None


def _telegram_save_state(balance, fingerprints, tx_count):
    """Save state as a pinned document in Telegram."""
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
    json_bytes = json.dumps(compact, separators=(',', ':'), ensure_ascii=False).encode("utf-8")

    total = sum(balance.values())
    sign = "+" if total >= 0 else "-"
    formatted = f"{abs(total):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    total_str = f"{sign}€{formatted}"
    caption = f"{STATE_MARKER}\n💰 Saldo: {total_str} | {tx_count} transações"

    try:
        old_msg_id = None
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": chat_id},
            timeout=10,
        )
        if r.status_code == 200:
            pinned = r.json().get("result", {}).get("pinned_message")
            if pinned:
                msg_text = pinned.get("caption", "") or pinned.get("text", "")
                if STATE_MARKER in msg_text:
                    old_msg_id = pinned["message_id"]

        file_obj = io.BytesIO(json_bytes)
        send_r = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={
                "chat_id": chat_id,
                "caption": caption,
                "disable_notification": "true",
            },
            files={"document": ("pluxee_state.json", file_obj, "application/json")},
            timeout=15,
        )
        if send_r.status_code == 200:
            new_msg_id = send_r.json()["result"]["message_id"]
            requests.post(
                f"https://api.telegram.org/bot{token}/pinChatMessage",
                json={"chat_id": chat_id, "message_id": new_msg_id, "disable_notification": True},
                timeout=10,
            )
            if old_msg_id:
                requests.post(
                    f"https://api.telegram.org/bot{token}/deleteMessage",
                    json={"chat_id": chat_id, "message_id": old_msg_id},
                    timeout=10,
                )
            log.info("State backed up to Telegram (pinned document)")
    except Exception as e:
        log.warning(f"Failed to back up state to Telegram: {e}")


def _telegram_load_state():
    """Load state from the Telegram pinned message."""
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

        caption = pinned.get("caption", "")
        if STATE_MARKER in caption and pinned.get("document"):
            file_id = pinned["document"]["file_id"]
            file_r = requests.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": file_id},
                timeout=10,
            )
            if file_r.status_code != 200:
                return None
            file_path = file_r.json()["result"]["file_path"]
            dl_r = requests.get(
                f"https://api.telegram.org/file/bot{token}/{file_path}",
                timeout=10,
            )
            if dl_r.status_code != 200:
                return None
            compact = dl_r.json()
        else:
            text = pinned.get("text", "")
            if STATE_MARKER not in text:
                return None
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
    """Detect if the API response looks like a system outage rather than real data."""
    if prev_state is None:
        return False

    prev_tx_count = prev_state.get("tx_count", len(prev_state.get("transactions", [])))
    prev_balance = prev_state.get("balance", {})
    prev_total = sum(prev_balance.values())
    current_total = sum(current_balance.values())

    if prev_tx_count > 0 and prev_total > 0 and len(current_txs) == 0 and current_total == 0:
        return True

    if prev_total > 1.0 and current_total == 0 and len(current_txs) == 0:
        return True

    return False


def _load_outage_state():
    """Load outage tracking state from disk."""
    if not os.path.exists(OUTAGE_FILE):
        return None
    try:
        with open(OUTAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_outage_state(prev_balance):
    """Save outage state to disk."""
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
    """Mark that outage notification was sent."""
    outage = _load_outage_state()
    if outage:
        outage["notification_sent"] = True
        with open(OUTAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(outage, f, indent=2, ensure_ascii=False)


def _clear_outage_state():
    """Clear outage file on recovery."""
    try:
        os.remove(OUTAGE_FILE)
    except OSError:
        pass

# ---------------------------------------------------------------------------
# Telegram Notifications
# ---------------------------------------------------------------------------

def fmt_eur(val):
    """Format a float as a Euro string like €12,34."""
    sign = "+" if val > 0 else ""
    formatted = f"{abs(val):,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{sign}€{formatted}" if val >= 0 else f"-€{formatted}"


def send_notification(title, message):
    """Send push notification directly via Telegram Bot API."""
    token, chat_id = _telegram_get_credentials()
    if not token or not chat_id:
        log.warning("Telegram credentials not configured; skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = f"<b>{title}</b>\n\n{message}"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
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


def notify_transaction(tx, balance_after):
    """Send a Telegram notification for a single transaction."""
    is_credit = tx["amount"] > 0
    emoji = "🟢" if is_credit else "🔴"
    title = f"{emoji} Pluxee — {'Carregamento' if is_credit else 'Gasto'}"

    amount_str = fmt_eur(tx["amount"])
    balance_str = fmt_eur(balance_after)

    message = (
        f"{tx['description']}\n"
        f"{amount_str}\n\n"
        f"💰 Saldo restante: {balance_str}"
    )

    send_notification(title, message)


def send_test_notification():
    """Send a test notification to verify the Telegram setup."""
    send_notification(
        title="🔔 Pluxee Monitor — Teste",
        message=(
            "O monitor Pluxee via Telegram está a funcionar!\n"
            "Irá receber alertas automáticos sempre que houver novas transações ou carregamentos."
        ),
    )

# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------

def write_pid():
    """Write current PID to file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def read_pid():
    """Read PID from file."""
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except (ValueError, IOError):
        return None


def remove_pid():
    """Remove PID file."""
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def is_monitor_running():
    """Check if monitor process is running."""
    pid = read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        remove_pid()
        return False

# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def check_for_new_transactions(config):
    """Check Pluxee for new transactions via Mobile API and notify on Telegram."""
    log.info("Checking for new transactions via Pluxee Mobile API...")

    try:
        result = fetch_all(config["api_claim"], config["card_id"], config["benefit_id"], num=20)
    except PluxeeAuthError as e:
        log.error(f"Authentication error: {e}")
        send_notification(
            title="⚠️ Pluxee — Sessão Expirada",
            message=(
                "A sessão da API móvel do Pluxee expirou (401).\n"
                "Por favor, atualize o PLUXEE_API_CLAIM nas definições."
            ),
        )
        return 0, None
    except PluxeeConnectionError as e:
        log.error(f"Connection error: {e}")
        return 0, None
    except Exception as e:
        log.error(f"Unexpected API error: {e}")
        return 0, None

    current_balance = result["balance"]
    current_txs = result["transactions"]
    total = sum(current_balance.values())

    log.info(f"Fetched {len(current_txs)} transactions. Current balance: €{total:.2f}")

    prev_state = load_state()

    if prev_state is None:
        log.info("First run — saving initial state (no notifications sent)")
        save_state(current_balance, current_txs)
        return 0, current_balance

    # Outage detection
    outage_state = _load_outage_state()
    if _looks_like_outage(current_balance, current_txs, prev_state):
        if outage_state is None:
            prev_balance = prev_state.get("balance", {})
            outage_state = _save_outage_state(prev_balance)
            log.warning("⚠️ Outage detected! API returned empty data. Skipping notifications.")
            prev_total = sum(prev_balance.values())
            send_notification(
                title="⚠️ Pluxee — Sistema indisponível",
                message=(
                    f"O sistema Pluxee parece estar em baixo.\n"
                    f"As notificações estão pausadas até o sistema recuperar.\n\n"
                    f"💰 Último saldo conhecido: {fmt_eur(prev_total)}"
                ),
            )
            _mark_outage_notified()
        else:
            log.warning("⚠️ Outage still ongoing. Skipping check.")
        return 0, None

    # Recovery from outage
    if outage_state is not None:
        log.info("✅ System recovered! Reconciling state silently.")
        _clear_outage_state()
        send_notification(
            title="✅ Pluxee — Sistema recuperado",
            message=f"O sistema Pluxee está novamente operacional.\n\n💰 Saldo atual: {fmt_eur(total)}",
        )
        save_state(current_balance, current_txs)
        return 0, current_balance

    # Compare transactions by fingerprint
    if "fingerprints" in prev_state:
        prev_fingerprints = set(prev_state["fingerprints"])
    else:
        prev_fingerprints = set(_tx_fingerprint(tx) for tx in prev_state.get("transactions", []))
    current_fingerprints = set(_tx_fingerprint(tx) for tx in current_txs)

    new_fingerprints = current_fingerprints - prev_fingerprints
    new_txs = [tx for tx in current_txs if _tx_fingerprint(tx) in new_fingerprints]

    prev_balance = prev_state.get("balance", {})
    prev_total = sum(prev_balance.values())

    if new_txs:
        log.info(f"Found {len(new_txs)} new transaction(s)!")
        new_txs_chrono = list(reversed(new_txs))
        for tx in new_txs_chrono:
            bal_after = tx["balance"] if tx.get("balance") is not None else total
            notify_transaction(tx, bal_after)
    else:
        log.info("No new transactions found.")

    # Check for balance changes without transactions
    if abs(total - prev_total) > 0.01 and not new_txs:
        if total == 0 and prev_total > 1.0:
            log.warning("Balance dropped to €0.00 with no new transactions — skipping glitch.")
            return 0, None

        diff = total - prev_total
        direction = "subiu" if diff > 0 else "desceu"
        send_notification(
            title=f"Pluxee — Saldo {direction}",
            message=f"O saldo alterou {fmt_eur(diff)}\n\n💰 Saldo atual: {fmt_eur(total)}",
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

    log.info(f"Monitor started (PID: {os.getpid()}, interval: {interval}s)")

    try:
        while _running:
            try:
                check_for_new_transactions(config)
            except Exception as e:
                log.error(f"Check failed: {e}")

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
    parser = argparse.ArgumentParser(description="Pluxee Transaction Monitor (Telegram)")
    parser.add_argument("--once", action="store_true", help="Run a single check and exit")
    parser.add_argument("--test", action="store_true", help="Send a test Telegram notification and exit")
    parser.add_argument("--status", action="store_true", help="Check if the monitor is running")
    parser.add_argument("--stop", action="store_true", help="Stop a running monitor")
    args = parser.parse_args()

    config = load_config()

    if args.test:
        log.info("Sending test notification to Telegram...")
        send_test_notification()
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

    if is_monitor_running():
        pid = read_pid()
        log.error(f"Monitor is already running (PID: {pid}). Use --stop first.")
        sys.exit(1)

    run_loop(config)


if __name__ == "__main__":
    main()
