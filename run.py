"""Render 24/7 Production Runner.

Runs both the Pluxee real-time transaction monitor and the web dashboard concurrently
in a single supervised Render service container, providing 24/7 real-time notifications
and live dashboard access without needing extra paid worker services.
"""

import os
import sys
import time
import signal
import threading
import subprocess
import requests

MONITOR_SCRIPT = os.path.join(os.path.dirname(__file__), "monitor.py")
PORT = os.getenv("PORT", "5000")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SELF_PING_URL", "")

monitor_proc = None
web_proc = None
_shutting_down = False


def _sig_handler(signum, frame):
    global _shutting_down
    _shutting_down = True
    print(f"[Runner] Received signal {signum}. Shutting down services cleanly...")

    if monitor_proc and monitor_proc.poll() is None:
        try:
            monitor_proc.terminate()
            monitor_proc.wait(timeout=5)
        except Exception:
            try:
                monitor_proc.kill()
            except Exception:
                pass

    if web_proc and web_proc.poll() is None:
        try:
            web_proc.terminate()
            web_proc.wait(timeout=5)
        except Exception:
            try:
                web_proc.kill()
            except Exception:
                pass

    sys.exit(0)


KEEPALIVE_MODE = os.getenv("KEEPALIVE_MODE", "smart").lower().strip()


def is_active_hours():
    """Check if current time is within active hours (07:30 - 23:30 Lisbon/UTC).

    Sleeping 8 hours at night saves 240+ instance hours per month,
    ensuring you only consume ~490 hours of Render's 750 free monthly hours.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    minute_of_day = now.hour * 60 + now.minute
    return (7 * 60 + 30) <= minute_of_day < (23 * 60 + 30)


def keepalive_worker():
    """Periodically ping /ping based on KEEPALIVE_MODE:
    - 'smart' (default): Keeps awake during daytime (07:30-23:30), sleeps at night to save hours.
    - 'off': Completely disabled (allows service to sleep when idle; woken by external cron or visits).
    - 'always': 24/7 continuous pings (uses ~744h/month).
    """
    if KEEPALIVE_MODE == "off":
        print("[Runner] Keepalive is OFF — service will sleep when idle to conserve hours.")
        return

    print(f"[Runner] Keepalive watchdog activated (mode: {KEEPALIVE_MODE}, target: {RENDER_URL or 'local'})")

    while not _shutting_down:
        time.sleep(600)  # Check every 10 minutes
        if _shutting_down:
            break

        if KEEPALIVE_MODE == "smart" and not is_active_hours():
            print("[Runner] Night hours (23:30-07:30) — skipping keepalive ping to allow sleep & save hours.")
            continue

        target = RENDER_URL.rstrip("/") + "/ping" if RENDER_URL else f"http://127.0.0.1:{PORT}/ping"
        try:
            r = requests.get(target, timeout=10)
            print(f"[Runner] Keepalive ping -> {target} (status {r.status_code})")
        except Exception as e:
            print(f"[Runner] Keepalive ping error: {e}")


def start_monitor():
    """Start monitor.py in a supervised subprocess."""
    global monitor_proc
    print("[Runner] Starting Pluxee real-time monitor...")
    monitor_proc = subprocess.Popen(
        [sys.executable, MONITOR_SCRIPT],
        cwd=os.path.dirname(__file__),
    )
    return monitor_proc


def main():
    global web_proc, monitor_proc, _shutting_down

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    # The web dashboard authenticates each user independently. Start the optional
    # owner monitor only when its server-side credentials are configured.
    from cloud_store import setting
    if all(setting(key) for key in ("PLUXEE_API_CLAIM", "PLUXEE_CARD_ID", "PLUXEE_BENEFIT_ID")):
        start_monitor()

    # 2. Start keepalive thread if on Render and not disabled
    if (os.getenv("RENDER") or RENDER_URL) and KEEPALIVE_MODE != "off":
        t = threading.Thread(target=keepalive_worker, daemon=True)
        t.start()

    # 3. Determine web server command
    # On POSIX/Linux (Render), use gunicorn. On Windows, fall back to Python app.py
    if sys.platform.startswith("win"):
        web_cmd = [sys.executable, "app.py"]
    else:
        web_cmd = [
            "gunicorn",
            "app:app",
            "--bind",
            f"0.0.0.0:{PORT}",
            "--workers",
            "1",
            "--threads",
            "4",
            "--timeout",
            "120",
        ]

    print(f"[Runner] Starting web server on port {PORT}: {' '.join(web_cmd)}")
    web_proc = subprocess.Popen(web_cmd, cwd=os.path.dirname(__file__))

    # Supervise loop
    while not _shutting_down:
        time.sleep(5)

        # Check if monitor died unexpectedly
        if monitor_proc and monitor_proc.poll() is not None and not _shutting_down:
            code = monitor_proc.poll()
            print(f"[Runner] ⚠️ Monitor process exited with code {code}. Restarting in 5s...")
            time.sleep(5)
            if not _shutting_down:
                start_monitor()

        # Check if web server died
        if web_proc and web_proc.poll() is not None:
            code = web_proc.poll()
            print(f"[Runner] Web server exited with code {code}. Exiting runner.")
            _sig_handler(signal.SIGTERM, None)
            break


if __name__ == "__main__":
    main()
