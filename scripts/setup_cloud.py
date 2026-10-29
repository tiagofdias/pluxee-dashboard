"""Create the invited owner and import local data after configuring Supabase.

The SQL migration must be applied first. Run this from a private local terminal;
passwords are entered with getpass and never saved in .env or printed.
"""
import argparse
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cloud_store as cloud
import history_store
from dotenv import set_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-owner", action="store_true")
    parser.add_argument("--import-local", action="store_true")
    args = parser.parse_args()
    if not all(cloud.setting(k) for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY")):
        raise SystemExit("Configure the three Supabase values in .env first. Never paste secret keys in chat.")
    if args.create_owner:
        if cloud.setting("DASHBOARD_OWNER_ID"):
            raise SystemExit("An owner is already configured. No account was created.")
        email = input("Owner email: ").strip()
        password = getpass.getpass("New password (12+ characters): ")
        if len(password) < 12 or password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords must match and contain at least 12 characters.")
        user = cloud.request("POST", "/auth/v1/admin/users", payload={"email": email, "password": password, "email_confirm": True})
        set_key(str(ROOT / ".env"), "DASHBOARD_OWNER_ID", user["id"], quote_mode="never")
        print("Invited owner created. Owner UUID saved locally; copy it to your hosting secrets.")
    if args.import_local:
        if not cloud.enabled():
            raise SystemExit("Configure DASHBOARD_OWNER_ID first.")
        path = ROOT / "data" / "transactions.json"
        if not path.exists():
            raise SystemExit("No local private state found.")
        state = json.loads(path.read_text(encoding="utf-8"))
        existing = cloud.load_state()
        if existing:
            raise SystemExit("Cloud state already exists; refusing to overwrite it with an older local snapshot.")
        transactions = state.get("transactions", [])
        for name in ("transactions_history.json", "previous_public_snapshot.json"):
            file = ROOT / "data" / name
            if file.exists():
                history = json.loads(file.read_text(encoding="utf-8"))
                transactions = history_store.merge_transactions(history if isinstance(history, list) else history.get("transactions", []), transactions)
        cloud.save_history(transactions)
        state["transactions"] = transactions
        state["fingerprints"] = [history_store.tx_fingerprint(tx) for tx in transactions]
        state["tx_count"] = len(transactions)
        cloud.save_state(state)
        print("Private history imported into the owner's cloud storage. No data was published.")


if __name__ == "__main__":
    try:
        main()
    except cloud.CloudError:
        raise SystemExit("Supabase request failed. Check configuration and the applied migration; no credentials were printed.")
