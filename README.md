# 🏗️ Land Alpha Agent

Serverless land-deal intelligence for DFW land banking. Runs daily via GitHub Actions, sends scored Telegram alerts for Ellis, Kaufman, and Waller County land listings.

## Quick Setup (10 minutes)

### 1. Clone & push this repo to GitHub

```bash
git init
git add .
git commit -m "Initial Land Alpha Agent"
git branch -M main
git remote add origin git@github.com:YOUR_USERNAME/land-alpha-agent.git
git push -u origin main
```

Make sure the repo is **Private** — you don't want competitors seeing your strategy.

### 2. Add your secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather (e.g., `7123456789:AAHxxx...`) |
| `TELEGRAM_CHAT_ID` | From @userinfobot (e.g., `-1001234567890` for channels) |
| `SCRAPINGBEE_API_KEY` | From scrapingbee.com dashboard |

### 3. Trigger your first scan

In the **Actions** tab → **Land Alpha Daily Scan** → **Run workflow** (green button).

Wait ~2 minutes. You'll see a green checkmark and get Telegram messages.

### 4. Done

The workflow now runs automatically every day at 8:00 AM CST.

## Local Testing

```bash
# Copy env template and fill in your tokens
cp .env.example .env
nano .env

# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run a scan
python land_alpha_agent.py
```

## Target Markets

| County | Median $/Acre | Appreciation | Focus Zips |
|--------|--------------|--------------|------------|
| Ellis | $38,500 | 14.2% | 75154, 76065, 76084 |
| Kaufman | $32,000 | 12.8% | 75142, 75189, 75126 |
| Waller | $24,000 | 10.5% | 77423, 77484 |

## Scoring Engine

7 weighted factors produce a 0–10 composite score:

| Factor | Weight |
|--------|--------|
| PPA Discount (vs county median) | 30% |
| County Appreciation Rate | 20% |
| Anchor Proximity | 15% |
| ETJ Status | 10% |
| Days on Market | 10% |
| School District | 8% |
| Utility Availability | 7% |

### Alert Tiers

- 🟢 **STRIKE ZONE** (7.5+): Immediate action
- 🟡 **WATCHLIST** (6.0–7.4): Monitor closely
- ⚪ **MONITOR** (4.5–5.9): Revisit quarterly
- 🔴 **PASS** (< 4.5): Skip

## Tuning

Edit the environment variables in `.github/workflows/daily-scan.yml` to adjust filters:

```yaml
MAX_PRICE: '200000'   # ← your budget ceiling
MAX_PPA: '35000'       # ← max price per acre
MIN_ACRES: '3'         # ← minimum lot size
MIN_SCORE: '6.0'       # ← threshold for Telegram alert
```

## Architecture

```
GitHub Actions Cron (daily 8AM CST)
    │
    ▼
land_alpha_agent.py
    ├── Scraper (ScrapingBee → LandWatch, Zillow)
    ├── Valuation Engine (7-factor scoring)
    ├── Alert Filter (price, acres, score thresholds)
    └── Telegram Notifier (rich deal cards)
```

## Cost

**$0/month** on the GitHub Actions free tier (you'll use ~15 of 2,000 free minutes).
ScrapingBee free tier covers 1,000 requests (~2–3 months of daily scans).

## Project Structure

```
land-alpha-agent/
├── .github/workflows/
│   └── daily-scan.yml       # Cron trigger
├── land_alpha_agent.py      # Main pipeline
├── requirements.txt         # Python deps
├── .env.example             # Env template (safe to commit)
├── .gitignore               # Blocks .env from git
└── README.md
```
