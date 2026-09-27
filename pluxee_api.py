"""Pluxee Portugal Mobile API Client.

Directly communicates with the official Pluxee Portugal mobile backend
(https://api.mobile.clients.pluxee.pt), replacing legacy HTML scraping.
Provides real-time balance and accurate movement/transaction data in pure JSON.
"""

import logging
import requests

log = logging.getLogger("pluxee-api")

BASE_URL = "https://api.mobile.clients.pluxee.pt"
DEFAULT_USER_AGENT = "okhttp/4.12.0"


class PluxeeApiError(Exception):
    """Base exception for Pluxee API errors."""
    pass


class PluxeeAuthError(PluxeeApiError):
    """Raised when authentication fails or ApiClaim session has expired (401)."""
    pass


class PluxeeConnectionError(PluxeeApiError):
    """Raised on network connectivity issues."""
    pass


def _get_headers(api_claim: str) -> dict:
    """Construct standard mobile app headers."""
    return {
        "ApiClaim": api_claim,
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Encoding": "gzip",
        "Connection": "Keep-Alive",
    }


def get_balance(api_claim: str, card_id: str) -> float:
    """Fetch real-time card balance in Euros.

    Args:
        api_claim: Mobile API session claim token.
        card_id: Card reference ID (referenceC), e.g. bHnxCGNG...

    Returns:
        float: Current balance in Euros.

    Raises:
        PluxeeAuthError: If ApiClaim is invalid or expired.
        PluxeeApiError: If API returns an error response.
    """
    url = f"{BASE_URL}/api/benefit/card/balance?Id={card_id}&idLanguage=1"
    headers = _get_headers(api_claim)

    try:
        res = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        raise PluxeeConnectionError(f"Network error while fetching balance: {e}") from e

    if res.status_code == 401:
        raise PluxeeAuthError("Pluxee session unauthorized (401). ApiClaim has expired or is invalid.")

    try:
        data = res.json()
    except Exception as e:
        raise PluxeeApiError(f"Invalid JSON response from balance API: {res.text[:150]}") from e

    if data.get("code") == -1:
        raise PluxeeAuthError(data.get("message", "Unauthorized"))

    balance_val = data.get("data", {}).get("balance")
    if balance_val is None:
        raise PluxeeApiError(f"Balance data missing from response: {data}")

    try:
        return float(balance_val)
    except (ValueError, TypeError) as e:
        raise PluxeeApiError(f"Could not parse balance value '{balance_val}': {e}") from e


def get_movements(api_claim: str, benefit_id: str, num: int = 20) -> list:
    """Fetch recent movements/transactions for a benefit card.

    Args:
        api_claim: Mobile API session claim token.
        benefit_id: Benefit reference ID, e.g. Fjzuh5H...
        num: Number of movements to retrieve (default: 20).

    Returns:
        list of dicts: [
            {
                "date": "24/09/2026",
                "description": "SOLSTICIO MEL",
                "amount": -15.00,
                "balance": 61.94,
                "currency": "EUR",
                "effective_date": "23/09/2026",
                "raw_description": "Compra SOLSTICIO MEL...",
                "is_rejected": False
            },
            ...
        ]
    """
    url = f"{BASE_URL}/api/benefit/card/v2/movements?email=&benefitId={benefit_id}&num={num}&idLanguage=1"
    headers = _get_headers(api_claim)

    try:
        res = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        raise PluxeeConnectionError(f"Network error while fetching movements: {e}") from e

    if res.status_code == 401:
        raise PluxeeAuthError("Pluxee session unauthorized (401). ApiClaim has expired or is invalid.")

    try:
        data = res.json()
    except Exception as e:
        raise PluxeeApiError(f"Invalid JSON response from movements API: {res.text[:150]}") from e

    if data.get("code") == -1:
        raise PluxeeAuthError(data.get("message", "Unauthorized"))

    raw_movements = data.get("data") or []
    transactions = []

    for m in raw_movements:
        try:
            total_val = float(str(m.get("total", "0")).replace(",", "."))
        except (ValueError, TypeError):
            total_val = 0.0

        bal_raw = m.get("balance")
        bal_val = None
        if bal_raw is not None:
            try:
                bal_val = float(str(bal_raw).replace(",", "."))
            except (ValueError, TypeError):
                pass

        establishment = (m.get("establishment") or "").strip()
        description = (m.get("description") or "").strip()
        display_desc = establishment if establishment else description

        transactions.append({
            "date": m.get("transactionDate", ""),
            "description": display_desc,
            "amount": total_val,
            "balance": bal_val,
            "currency": m.get("currency", "EUR"),
            "effective_date": m.get("effectiveDate"),
            "raw_description": description,
            "is_rejected": bool(m.get("isRejected", False)),
        })

    return transactions


def fetch_all(api_claim: str, card_id: str, benefit_id: str, num: int = 20) -> dict:
    """One-shot: Fetch both current balance and recent transactions.

    Returns:
        dict: {
            "balance": {
                "lunch_pass": float,
                "eco_pass": 0.0,
                "gift_pass": 0.0,
                "conso_pass": 0.0
            },
            "transactions": [ ... ]
        }
    """
    bal = get_balance(api_claim, card_id)
    txs = get_movements(api_claim, benefit_id, num=num)

    return {
        "balance": {
            "lunch_pass": bal,
            "eco_pass": 0.0,
            "gift_pass": 0.0,
            "conso_pass": 0.0,
        },
        "transactions": txs,
    }
