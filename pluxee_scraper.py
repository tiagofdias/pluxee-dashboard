"""Pluxee Portugal Scraper — Shared module for balance & transaction extraction.

Extracts data from the Portuguese Pluxee consumer portal
(consumidores.pluxee.pt / portal.admin.pluxee.pt).
Used by both the Flask web dashboard and the background notification monitor.
"""

import os
import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://portal.admin.pluxee.pt"
LOGIN_URL = f"{BASE_URL}/login_processing.php"
DEBUG_DIR = os.path.join(os.path.dirname(__file__), "debug")


def _create_session():
    """Create a requests session with browser-like headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    return session


def _extract_balance_from_soup(page_soup):
    """Extract a euro balance value from a BeautifulSoup page object."""
    # Strategy 1: Look for card-heading class
    heading_el = page_soup.find(class_=re.compile(r"card-heading", re.I))
    if heading_el:
        text = heading_el.get_text(strip=True)
        clean_text = re.sub(r"[^\d,.]", "", text)
        if clean_text:
            try:
                val = float(clean_text.replace(",", "."))
                return val
            except ValueError:
                pass

    # Strategy 2: Look for element near text "O seu saldo"
    title_el = page_soup.find(string=re.compile(r"O seu saldo", re.I))
    if title_el:
        parent = title_el.parent
        heading = parent.find_next(
            class_=re.compile(r"card-heading|valor|amount", re.I)
        )
        if heading:
            text = heading.get_text(strip=True)
            clean_text = re.sub(r"[^\d,.]", "", text)
            if clean_text:
                try:
                    val = float(clean_text.replace(",", "."))
                    return val
                except ValueError:
                    pass

    # Strategy 3: Fallback — look for euro amounts in text
    page_text = page_soup.get_text()
    euro_pattern = re.compile(r'(\d+[.,]\d{2})\s*€|€\s*(\d+[.,]\d{2})')
    all_values = []
    for m in euro_pattern.finditer(page_text):
        val_str = m.group(1) or m.group(2)
        try:
            val = float(val_str.replace(",", "."))
            all_values.append(val)
        except ValueError:
            pass

    if all_values:
        val = max(all_values)
        return val

    return 0.0


def login(nif, password):
    """Authenticate with Pluxee and return (session, dashboard_soup, dashboard_url).

    Raises ValueError on login failure, ConnectionError on network issues.
    """
    session = _create_session()

    # Visit the consumer portal to get cookies
    session.get("https://consumidores.pluxee.pt")

    # Attempt login
    login_r = session.post(LOGIN_URL, data={
        "nif": nif,
        "pass": password,
    })

    try:
        login_data = login_r.json()
    except Exception:
        raise ValueError("Unexpected response from Pluxee. Please try again.")

    if not login_data.get("sucesso"):
        msg = login_data.get("mensagem", "Login failed")
        raise ValueError(msg)

    redirect_url = login_data.get("local", "")
    if not redirect_url:
        raise ValueError("Login succeeded but no redirect URL received")

    if redirect_url.startswith("/"):
        redirect_url = BASE_URL + redirect_url

    # Fetch the dashboard page with a cache-buster query parameter
    import time
    cache_buster = f"cb={int(time.time() * 1000)}"
    if "?" in redirect_url:
        redirect_url_cb = f"{redirect_url}&{cache_buster}"
    else:
        redirect_url_cb = f"{redirect_url}?{cache_buster}"
    dash_r = session.get(redirect_url_cb)

    # Save full dashboard HTML for debugging
    os.makedirs(DEBUG_DIR, exist_ok=True)
    debug_path = os.path.join(DEBUG_DIR, "dashboard.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(dash_r.text)

    soup = BeautifulSoup(dash_r.text, "html.parser")
    return session, soup, dash_r.url


def fetch_balance(session, soup):
    """Extract balance dict from the dashboard soup. Crawls other pass pages if found.

    Returns dict: { lunch_pass, eco_pass, gift_pass, conso_pass }
    """
    balance = {
        "lunch_pass": 0.0,
        "eco_pass": 0.0,
        "gift_pass": 0.0,
        "conso_pass": 0.0,
    }

    # Main balance (Lunch/Refeição card)
    balance["lunch_pass"] = _extract_balance_from_soup(soup)

    # Check for links to other card pages
    links = soup.find_all("a", href=True)
    other_pages = []
    for a in links:
        href = a.get("href", "")
        text = a.get_text(strip=True).lower()
        if any(w in text for w in ["eco", "educação", "gift", "presente", "consumo"]):
            full_url = (
                href if href.startswith("http")
                else (BASE_URL + href if href.startswith("/") else "")
            )
            if full_url:
                other_pages.append((full_url, text))

    # Crawl other card pages
    for url, name in other_pages:
        try:
            page_r = session.get(url)
            if page_r.status_code == 200:
                page_soup = BeautifulSoup(page_r.text, "html.parser")
                val = _extract_balance_from_soup(page_soup)
                if "eco" in name:
                    balance["eco_pass"] = val
                elif any(w in name for w in ["gift", "presente"]):
                    balance["gift_pass"] = val
                elif any(w in name for w in ["consumo", "conso"]):
                    balance["conso_pass"] = val
        except Exception:
            pass

    return balance


def fetch_transactions(soup):
    """Extract transaction list from the dashboard soup.

    Returns list of dicts: [{ date, description, amount }, ...]
    """
    transactions = []
    table = soup.find("table", id="plx-table")
    if not table:
        return transactions

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 3:
            # Date
            date_el = cells[0].find(class_="dateFormatDesk")
            date_str = (
                date_el.get_text(strip=True) if date_el
                else cells[0].get_text(strip=True)
            )

            # Description
            desc_el = cells[1].find(class_="text-left")
            desc_str = (
                desc_el.get_text(strip=True) if desc_el
                else cells[1].get_text(strip=True)
            )
            desc_str = re.sub(r'\s+', ' ', desc_str).strip()

            # Amount
            amount_el = cells[2].find(class_="saldo_p")
            amount_str = (
                amount_el.get_text(strip=True) if amount_el
                else cells[2].get_text(strip=True)
            )

            amount_clean = re.sub(r"[^\d\-.,]", "", amount_str)
            amount_val = 0.0
            if amount_clean:
                try:
                    amount_val = float(amount_clean.replace(",", "."))
                except ValueError:
                    pass

            transactions.append({
                "date": date_str,
                "description": desc_str,
                "amount": amount_val,
            })

    return transactions


def fetch_all(nif, password):
    """One-shot: login, fetch balance & transactions.

    Returns dict: { balance: {...}, transactions: [...], dashboard_url: str }
    """
    session, soup, dash_url = login(nif, password)
    balance = fetch_balance(session, soup)
    transactions = fetch_transactions(soup)
    return {
        "balance": balance,
        "transactions": transactions,
        "dashboard_url": dash_url,
    }
