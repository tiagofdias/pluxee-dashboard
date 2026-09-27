# 💳 Pluxee Portugal — Balance Dashboard & Transaction Monitor

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live%20Dashboard-brightgreen)](https://tiagofdias.github.io/pluxee-dashboard/)
[![Pluxee Mobile API](https://img.shields.io/badge/Pluxee%20API-Mobile%20v2-blue)](https://api.mobile.clients.pluxee.pt)
[![Telegram Notifications](https://img.shields.io/badge/Telegram-Bot%20Alerts-blue?logo=telegram)](https://telegram.org)
[![ntfy.sh](https://img.shields.io/badge/ntfy.sh-Push%20Alerts-orange)](https://ntfy.sh)

A real-time balance dashboard and automated transaction monitor for **Pluxee Portugal** (formerly Sodexo Pass Portugal). Directly communicates with the official Pluxee Portugal Mobile API (`api.mobile.clients.pluxee.pt`) to provide instant, 100% accurate transaction tracking, live balance consultation, and immediate push notifications to **Telegram** and **ntfy.sh**.

---

## ✨ Features

* **⚡ Ultra-Fast Official Mobile API**: Bypasses slow web scraping. Communicates directly with Pluxee's mobile backend (`okhttp/4.12.0`) in ~150ms with clean JSON.
* **📱 Real-Time Push Notifications**:
  * **🔴 Expenses**: Notifies every purchase with the exact merchant name, amount spent, and **remaining running balance**.
  * **🟢 Company Top-Ups**: Automatically alerts when your employer loads meal allowance onto your card each month.
  * **📈 Balance Safeguard**: Extra check detects sudden balance increases even before transaction line items appear.
* **☁️ 100% Free 24/7 Monitoring via GitHub Actions**:
  * Runs automatically every 15 minutes (or on-demand).
  * Requires zero server hosting, credit cards, or maintenance.
* **🌐 Automated GitHub Pages Dashboard**:
  * Live glassmorphism web dashboard hosted on GitHub Pages: [`https://tiagofdias.github.io/pluxee-dashboard/`](https://tiagofdias.github.io/pluxee-dashboard/).
  * Displays total balance, pass breakdowns, animated ring charts, and 20 recent transactions.
* **🔒 Cloud-Persistent State via Telegram**:
  * Backs up transaction fingerprints to a pinned message in Telegram.
  * Survives stateless GitHub Actions runner cycles with zero lost state.

---

## 🔔 Notification Previews

### Expense (Gasto)
> **🔴 Pluxee — Gasto**  
> `MCDONALDS SALDANHA`  
> `-€1,90`  
>   
> 💰 **Saldo restante:** `€76,94`

### Company Monthly Load (Carregamento)
> **🟢 Pluxee — Carregamento**  
> `Carregamento de CAPGEMINI PORTUGAL SA`  
> `+€211,86`  
>   
> 💰 **Saldo restante:** `€273,80`

---

## 🚀 Quick Setup

### 1. Intercept Mobile API Parameters
Using a network proxy (e.g., [HTTP Toolkit](https://httptoolkit.com/), Charles, or Proxyman) on your mobile device, inspect the Pluxee Portugal app requests to obtain:
* **`PLUXEE_API_CLAIM`**: The `ApiClaim` header value from any authorized request.
* **`PLUXEE_CARD_ID`**: The card reference ID (`referenceC`), formatted as `<base64>=<salt>`.
* **`PLUXEE_BENEFIT_ID`**: The benefit reference ID, e.g. `Fjzuh5Hrgz...`.

### 2. Configure Telegram Bot
1. Open Telegram and search for **`@BotFather`**.
2. Create a new bot with `/newbot` and copy your **`TELEGRAM_TOKEN`**.
3. Search for **`@userinfobot`** in Telegram to obtain your personal numerical **`TELEGRAM_CHAT_ID`**.
4. Send `/start` to your newly created bot so it can message you.

### 3. Setup GitHub Actions & Pages
1. Go to your repository **Settings** > **Secrets and variables** > **Actions**.
2. Add the following **Repository Secrets**:
   * `PLUXEE_API_CLAIM`
   * `PLUXEE_CARD_ID`
   * `PLUXEE_BENEFIT_ID`
   * `TELEGRAM_TOKEN`
   * `TELEGRAM_CHAT_ID`
   * `NTFY_TOPIC` (optional, e.g. `pluxee-tiago-a7x9k2`)
3. Go to **Settings** > **Pages**:
   * Set **Source** to **GitHub Actions**.
4. Go to the **Actions** tab and trigger **Pluxee Monitor & GitHub Pages** manually to run the first check and deploy the dashboard!

---

## 💻 Running Locally

### Prerequisites
* Python 3.10+
* `pip install -r requirements.txt`

### Local Configuration
Copy `.env.example` to `.env` and fill in your values:
```env
PLUXEE_API_CLAIM=your_api_claim_token_here
PLUXEE_CARD_ID=bHnxCGNGTfJEdgXDz4paOPlcAr6fOsEDgIgkE84nDT8%3DslEA7yYOHkT0tOM3
PLUXEE_BENEFIT_ID=Fjzuh5HrgzFxK%2FWm9BXIAQ%3D%3DX0kllae3G4hK4L3I
NTFY_TOPIC=pluxee-tiago-a7x9k2
POLL_INTERVAL_SECONDS=300
TELEGRAM_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=123456789
```

### Commands
```powershell
# Send a test notification to Telegram and ntfy
python monitor.py --test

# Run a single transaction check
python monitor.py --once

# Start continuous background monitoring
python monitor.py

# Launch local Flask web dashboard
python app.py
```

---

## 📂 Project Architecture

```
pluxee-dashboard/
├── .github/workflows/
│   └── monitor.yml        # GitHub Actions 15-min cron & Pages deployment
├── pluxee_api.py          # Mobile API client (balance & v2 movements)
├── monitor.py             # Transaction polling, state & push notifications
├── app.py                 # Flask server (local & Render backend)
├── static/
│   ├── index.html         # Responsive dashboard UI
│   ├── style.css          # Glassmorphism dark-theme styling
│   ├── app.js             # Real-time UI rendering & dynamic loaders
│   └── data.json          # Cached site state deployed to Pages
├── requirements.txt       # Python dependencies
└── .env.example           # Environment template
```

---

## 🛡️ License

MIT License. Educational and personal productivity tool. Not affiliated with or endorsed by Pluxee or Sodexo.
