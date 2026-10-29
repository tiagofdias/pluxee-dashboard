"""History Store — Persistent Ledger for Pluxee Transactions.

Since the Pluxee Mobile API only returns recent movements (capped at ~50-100),
this module continuously accumulates and merges transactions into a persistent
historical ledger so that past movements are preserved forever for analytics.
"""

import os
import json
import hashlib
import cloud_store
from datetime import datetime, timezone


def tx_fingerprint(tx: dict) -> str:
    """Create a deterministic unique fingerprint for a transaction."""
    date = str(tx.get("date", "")).strip()
    desc = str(tx.get("description", "")).strip()
    amt = str(tx.get("amount", "")).strip()
    # Settlement changes balances, effective dates and raw descriptions.
    # These fields are metadata, not the identity of a purchase.
    from decimal import Decimal
    amt = str(Decimal(amt or "0").quantize(Decimal("0.01")))
    raw = f"{date}|{desc.casefold()}|{amt}|{tx.get('currency', 'EUR')}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _parse_tx_date(tx: dict) -> datetime:
    """Parse transaction date for chronological sorting."""
    d_str = str(tx.get("date", "")).split()[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(d_str, fmt)
        except ValueError:
            continue
    return datetime.min


def merge_transactions(existing_txs: list, new_txs: list) -> list:
    """Merge new transactions with historical transactions without duplicates.

    - Retains all past transactions.
    - Prevents duplicates using tx_fingerprint.
    - Sorts all transactions chronologically descending (newest first).
    """
    seen = set()
    merged = []

    # New transactions take precedence (updated descriptions/balances)
    for tx in (new_txs or []):
        fp = tx_fingerprint(tx)
        if fp not in seen:
            seen.add(fp)
            merged.append(tx)

    # Add historical transactions not present in the new batch
    for tx in (existing_txs or []):
        fp = tx_fingerprint(tx)
        if fp not in seen:
            seen.add(fp)
            merged.append(tx)

    # Sort descending by date
    merged.sort(key=_parse_tx_date, reverse=True)
    return merged


def load_history(data_dir: str) -> list:
    """Load historical transactions from history file or fallback to state/static file."""
    if cloud_store.enabled():
        transactions = cloud_store.load_history()
        if transactions is not None:
            return transactions
    history_file = os.path.join(data_dir, "transactions_history.json")
    state_file = os.path.join(data_dir, "transactions.json")

    for path in (history_file, state_file):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        txs = data.get("transactions")
                        if isinstance(txs, list) and txs:
                            return txs
            except Exception:
                pass
    return []


def save_history(data_dir: str, transactions: list) -> None:
    """Save the complete cumulative transaction ledger to disk."""
    if cloud_store.enabled():
        cloud_store.save_history(transactions)
    os.makedirs(data_dir, exist_ok=True)
    history_file = os.path.join(data_dir, "transactions_history.json")
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(transactions, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Could not save transaction history: {e}")
