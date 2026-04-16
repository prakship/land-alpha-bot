# 🏗️ LAND ALPHA AGENT — Deployment Guide

## Quick Start (Local Testing)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"
export SCRAPINGBEE_API_KEY="your-api-key"

# 3. Run in demo mode (no env vars = demo)
python land_alpha_agent.py

# 4. Run full pipeline
python land_alpha_agent.py
```

## Telegram Setup (5 min, do from phone)

1. Open Telegram, search **@BotFather**
2. Send `/newbot`, name it "Land Alpha Bot"
3. Save the API token → `TELEGRAM_BOT_TOKEN`
4. Search **@userinfobot**, note your ID → `TELEGRAM_CHAT_ID`
5. Create a private channel "Land Alerts", add your bot as admin

## ScrapingBee Setup (free tier)

1. Sign up at [scrapingbee.com](https://www.scrapingbee.com/)
2. Get your API key from the dashboard (1,000 free credits)
3. Save as `SCRAPINGBEE_API_KEY`

## AWS Deployment

### Prerequisites
- AWS CLI configured (`aws configure`)
- AWS SAM CLI installed (`brew install aws-sam-cli`)

### Deploy
```bash
# Build
sam build

# Deploy (first time — guided)
sam deploy --guided

# Deploy (subsequent)
sam deploy
```

### What gets created
| Resource | Purpose |
|----------|---------|
| Lambda Function | Runs the scraper + scoring pipeline |
| EventBridge Rule | Triggers daily at 8:00 AM CST |
| S3 Bucket | Bronze/Silver/Gold data lake |
| CloudWatch Alarm | Alerts if Lambda fails |

## Architecture

```
EventBridge (8AM CST)
    │
    ▼
AWS Lambda (land_alpha_agent.py)
    │
    ├── ScrapingBee API → LandWatch, Zillow
    │       │
    │       ▼
    │   Bronze Layer (S3) ── Raw HTML/JSON
    │       │
    │       ▼
    │   Silver Layer (S3) ── Cleaned & Deduped
    │       │
    │       ▼
    │   Gold Layer (S3) ── Scored Deals
    │
    └── Telegram Bot API → Your Phone
            │
            ├── Deal Alerts (Strike Zone, Watchlist)
            └── Daily Summary
```

## Scoring Engine

7 weighted factors, configurable via environment variables:

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| PPA Discount | 30% | How far below county median $/acre |
| Appreciation | 20% | County-level YoY growth rate |
| Anchor Proximity | 15% | Distance to corporate catalyst |
| ETJ Status | 10% | Inside extraterritorial jurisdiction |
| Days on Market | 10% | Stale listing = negotiation leverage |
| School District | 8% | School quality → residential demand |
| Utilities | 7% | Reduces future development cost |

### Tier Thresholds
- **STRIKE ZONE** (7.5–10): Immediate action
- **WATCHLIST** (6.0–7.4): Monitor closely
- **MONITOR** (4.5–5.9): Revisit quarterly
- **PASS** (0–4.4): Skip

## Target Markets

### Ellis County (Risk Score: 8.4/10)
- Median $/acre: $38,500
- YoY Appreciation: 14.2%
- Key zips: 75154, 76065, 76084
- Catalysts: Google Data Center, I-35E Corridor

### Kaufman County (Risk Score: 7.9/10)
- Median $/acre: $32,000
- YoY Appreciation: 12.8%
- Key zips: 75142, 75189, 75126
- Catalysts: Samsung proximity, Forney ISD Bond

### Waller County (Risk Score: 7.2/10)
- Median $/acre: $24,000
- YoY Appreciation: 10.5%
- Key zips: 77423, 77484
- Catalysts: Brookshire corridor, Amazon fulfillment

## Cost Summary
| Component | Monthly Cost |
|-----------|-------------|
| AWS Lambda | Free (free tier) |
| S3 Storage | ~$0.10 |
| ScrapingBee | Free (1,000 credits) |
| Telegram | Free |
| **Total** | **< $0.10/month** |
