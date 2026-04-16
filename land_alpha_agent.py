"""
LAND ALPHA AGENT — Production Pipeline
========================================
A serverless land deal intelligence system for DFW land banking.

Target Markets: Ellis County, Kaufman County, Waller County
Budget: $100K–$200K | Horizon: 2029 deployment | Target: 12%+ appreciation

Runs via GitHub Actions (daily) or locally for testing.
"""

import json
import os
import logging
import hashlib
import re
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum

# Auto-load .env for local runs (safely skipped in CI where it's not installed)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("LandAlpha")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")


# ── Data Models ────────────────────────────────────────────────────
class DealTier(Enum):
    STRIKE_ZONE = "STRIKE ZONE"
    WATCHLIST = "WATCHLIST"
    MONITOR = "MONITOR"
    PASS = "PASS"


@dataclass
class CountyProfile:
    name: str
    median_ppa: float
    appreciation_rate: float
    risk_score: float
    target_zips: list
    catalysts: list
    search_urls: dict = field(default_factory=dict)


@dataclass
class LandListing:
    listing_id: str
    source: str
    address: str
    county: str
    zip_code: str
    acres: float
    price: float
    price_per_acre: float
    days_on_market: int
    zoning: str
    etj_status: bool
    utilities: str
    school_district: str
    latitude: float
    longitude: float
    dist_to_anchor_mi: float
    url: str
    scraped_at: str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.utcnow().isoformat()
        if not self.price_per_acre and self.acres > 0:
            self.price_per_acre = round(self.price / self.acres, 2)


@dataclass
class DealScore:
    total: float
    tier: DealTier
    breakdown: dict
    projected_value_5yr: float
    projected_gain_5yr: float
    alert_triggered: bool


# ── County Configurations ──────────────────────────────────────────
COUNTY_PROFILES = {
    "Ellis": CountyProfile(
        name="Ellis County",
        median_ppa=38500,
        appreciation_rate=14.2,
        risk_score=8.4,
        target_zips=["75154", "76065", "76084", "75152", "75165"],
        catalysts=[
            "Google Data Center ($600M)",
            "I-35E Corridor Expansion",
            "Midlothian ISD Growth Bond",
        ],
        search_urls={
            "landwatch": "https://www.landwatch.com/ellis-county-texas-land-for-sale",
            "zillow": "https://www.zillow.com/ellis-county-tx/land/",
        },
    ),
    "Kaufman": CountyProfile(
        name="Kaufman County",
        median_ppa=32000,
        appreciation_rate=12.8,
        risk_score=7.9,
        target_zips=["75142", "75189", "75126", "75114", "75160"],
        catalysts=[
            "Samsung Fab Proximity",
            "Bush Turnpike Extension",
            "Forney ISD Bond ($1.2B)",
        ],
        search_urls={
            "landwatch": "https://www.landwatch.com/kaufman-county-texas-land-for-sale",
            "zillow": "https://www.zillow.com/kaufman-county-tx/land/",
        },
    ),
    "Waller": CountyProfile(
        name="Waller County",
        median_ppa=24000,
        appreciation_rate=10.5,
        risk_score=7.2,
        target_zips=["77423", "77445", "77484"],
        catalysts=[
            "Brookshire Industrial Corridor",
            "I-10 Expansion",
            "Amazon Fulfillment Center",
        ],
        search_urls={
            "landwatch": "https://www.landwatch.com/waller-county-texas-land-for-sale",
            "zillow": "https://www.zillow.com/waller-county-tx/land/",
        },
    ),
}

SCORING_WEIGHTS = {
    "ppa_discount": 0.30,
    "appreciation": 0.20,
    "anchor_proximity": 0.15,
    "etj_status": 0.10,
    "days_on_market": 0.10,
    "school_district": 0.08,
    "utilities": 0.07,
}

SCHOOL_DISTRICT_SCORES = {
    "Red Oak ISD": 8, "Midlothian ISD": 9, "Waxahachie ISD": 7,
    "Ennis ISD": 6, "Palmer ISD": 5,
    "Community ISD": 5, "Royse City ISD": 8, "Forney ISD": 9,
    "Terrell ISD": 5, "Kaufman ISD": 6, "Crandall ISD": 5,
    "Royal ISD": 5, "Waller ISD": 6, "Hempstead ISD": 4,
}


# ── Valuation Engine ───────────────────────────────────────────────
class ValuationEngine:
    def __init__(self, weights=None):
        self.weights = weights or SCORING_WEIGHTS

    def score(self, listing, county):
        breakdown = {}

        if county.median_ppa > 0:
            discount_pct = (county.median_ppa - listing.price_per_acre) / county.median_ppa
            breakdown["ppa_discount"] = max(0, min(10, discount_pct * 15))
        else:
            breakdown["ppa_discount"] = 5.0

        breakdown["appreciation"] = min(10, county.appreciation_rate / 1.5)
        breakdown["etj_status"] = 8.0 if listing.etj_status else 3.0

        if listing.days_on_market > 90:
            breakdown["days_on_market"] = 10.0
        elif listing.days_on_market > 60:
            breakdown["days_on_market"] = 9.0
        elif listing.days_on_market > 30:
            breakdown["days_on_market"] = 6.0
        else:
            breakdown["days_on_market"] = 3.0

        breakdown["anchor_proximity"] = max(0, min(10, (20 - listing.dist_to_anchor_mi) / 2))
        breakdown["school_district"] = SCHOOL_DISTRICT_SCORES.get(listing.school_district, 5.0)

        utils = listing.utilities.lower()
        if "all" in utils:
            breakdown["utilities"] = 9.0
        elif "water" in utils and "electric" in utils:
            breakdown["utilities"] = 7.0
        elif "electric" in utils:
            breakdown["utilities"] = 5.0
        else:
            breakdown["utilities"] = 2.0

        total = sum(breakdown[k] * self.weights[k] for k in self.weights)
        total = round(total, 1)

        if total >= 7.5:
            tier = DealTier.STRIKE_ZONE
        elif total >= 6.0:
            tier = DealTier.WATCHLIST
        elif total >= 4.5:
            tier = DealTier.MONITOR
        else:
            tier = DealTier.PASS

        projected = listing.price * ((1 + county.appreciation_rate / 100) ** 5)
        gain = projected - listing.price

        return DealScore(
            total=total,
            tier=tier,
            breakdown={k: round(v, 1) for k, v in breakdown.items()},
            projected_value_5yr=round(projected),
            projected_gain_5yr=round(gain),
            alert_triggered=(total >= 6.0),
        )


# ── Alert Filters ──────────────────────────────────────────────────
@dataclass
class AlertConfig:
    max_price: float = 200_000
    max_ppa: float = 35_000
    min_acres: float = 3.0
    min_score: float = 6.0


def passes_alert_filter(listing, score, config):
    if listing.price > config.max_price:
        return False
    if listing.price_per_acre > config.max_ppa:
        return False
    if listing.acres < config.min_acres:
        return False
    if score.total < config.min_score:
        return False
    return True


# ── Scraper Module ─────────────────────────────────────────────────
class LandScraper:
    def __init__(self, api_key=""):
        self.api_key = api_key or SCRAPINGBEE_API_KEY

    def scrape_landwatch(self, county, max_price=300_000):
        url = county.search_urls.get("landwatch", "")
        if not url or not self.api_key:
            logger.warning(f"Skipping LandWatch scrape for {county.name} (missing URL or API key)")
            return []

        try:
            import requests
            from bs4 import BeautifulSoup

            params = {
                "api_key": self.api_key,
                "url": url,
                "render_js": "true",
                "wait": "2000",
            }
            resp = requests.get(
                "https://app.scrapingbee.com/api/v1/",
                params=params,
                timeout=45
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            listings = []

            for card in soup.select(".property-card, .listing-card, [data-testid='property-card']"):
                try:
                    price_el = card.select_one(".price, [data-testid='price']")
                    acres_el = card.select_one(".acres, [data-testid='acres']")
                    address_el = card.select_one(".address, [data-testid='address']")
                    link_el = card.select_one("a[href]")

                    if not price_el or not acres_el:
                        continue

                    price_text = re.sub(r"[^\d.]", "", price_el.get_text(strip=True))
                    acres_text = re.sub(r"[^\d.]", "", acres_el.get_text(strip=True).split()[0])

                    if not price_text or not acres_text:
                        continue

                    price = float(price_text)
                    acres = float(acres_text)

                    if acres <= 0 or price <= 0:
                        continue

                    address_text = address_el.get_text(strip=True) if address_el else "Unknown"
                    href = link_el.get("href", "") if link_el else ""
                    if href and href.startswith("/"):
                        href = "https://www.landwatch.com" + href

                    listing = LandListing(
                        listing_id=hashlib.md5(f"{address_text}-{price}".encode()).hexdigest()[:10],
                        source="landwatch",
                        address=address_text,
                        county=county.name,
                        zip_code="",
                        acres=acres,
                        price=price,
                        price_per_acre=round(price / acres, 2),
                        days_on_market=0,
                        zoning="Unknown",
                        etj_status=False,
                        utilities="Unknown",
                        school_district="Unknown",
                        latitude=0.0,
                        longitude=0.0,
                        dist_to_anchor_mi=10.0,
                        url=href,
                    )
                    listings.append(listing)

                except (ValueError, AttributeError) as e:
                    logger.debug(f"Failed to parse LandWatch card: {e}")
                    continue

            logger.info(f"Scraped {len(listings)} listings from LandWatch for {county.name}")
            return listings

        except Exception as e:
            logger.error(f"LandWatch scrape failed for {county.name}: {e}")
            return []

    def scrape_zillow(self, county):
        url = county.search_urls.get("zillow", "")
        if not url or not self.api_key:
            logger.warning(f"Skipping Zillow scrape for {county.name} (missing URL or API key)")
            return []

        try:
            import requests
            from bs4 import BeautifulSoup

            params = {
                "api_key": self.api_key,
                "url": url,
                "render_js": "true",
                "premium_proxy": "true",
                "wait": "3000",
            }
            resp = requests.get(
                "https://app.scrapingbee.com/api/v1/",
                params=params,
                timeout=60
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            listings = []

            for card in soup.select("[data-test='property-card'], .list-card, article"):
                try:
                    price_el = card.select_one("[data-test='property-card-price'], .list-card-price")
                    details = card.select_one("[data-test='property-card-details']") or card

                    if not price_el:
                        continue

                    price_text = re.sub(r"[^\d.]", "", price_el.get_text(strip=True))
                    if not price_text:
                        continue
                    price = float(price_text)

                    details_text = details.get_text() if details else ""
                    acres = 1.0
                    acre_match = re.search(r"([\d.]+)\s*acre", details_text, re.I)
                    if acre_match:
                        acres = float(acre_match.group(1))

                    addr_el = card.select_one("address, [data-test='property-card-addr']")
                    address_text = addr_el.get_text(strip=True) if addr_el else "Unknown"

                    link_el = card.select_one("a[href*='/homedetails/']") or card.select_one("a[href]")
                    href = link_el.get("href", "") if link_el else ""
                    if href and href.startswith("/"):
                        href = "https://www.zillow.com" + href

                    listing = LandListing(
                        listing_id=hashlib.md5(f"zillow-{address_text}-{price}".encode()).hexdigest()[:10],
                        source="zillow",
                        address=address_text,
                        county=county.name,
                        zip_code="",
                        acres=acres,
                        price=price,
                        price_per_acre=round(price / acres, 2) if acres > 0 else 0,
                        days_on_market=0,
                        zoning="Unknown",
                        etj_status=False,
                        utilities="Unknown",
                        school_district="Unknown",
                        latitude=0.0,
                        longitude=0.0,
                        dist_to_anchor_mi=10.0,
                        url=href,
                    )
                    listings.append(listing)

                except (ValueError, AttributeError) as e:
                    logger.debug(f"Zillow parse error: {e}")
                    continue

            logger.info(f"Scraped {len(listings)} listings from Zillow for {county.name}")
            return listings

        except Exception as e:
            logger.error(f"Zillow scrape failed for {county.name}: {e}")
            return []


# ── Telegram Notifier ──────────────────────────────────────────────
class TelegramNotifier:
    def __init__(self, token="", chat_id=""):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_deal_alert(self, listing, score, county):
        tier_emoji = {
            DealTier.STRIKE_ZONE: "🟢🎯",
            DealTier.WATCHLIST: "🟡👁️",
            DealTier.MONITOR: "⚪📋",
            DealTier.PASS: "🔴❌",
        }

        discount_pct = round((1 - listing.price_per_acre / county.median_ppa) * 100) if county.median_ppa else 0
        url_line = f"🔗 [View Listing]({listing.url})" if listing.url else "🔗 _(URL not available)_"

        message = f"""
{tier_emoji.get(score.tier, "⚪")} *{score.tier.value}* — Score: *{score.total}/10*

📍 *{listing.address}*
🏘️ {listing.county} | Source: {listing.source.title()}

💰 *${listing.price:,.0f}* | {listing.acres} acres
📊 ${listing.price_per_acre:,.0f}/acre ({discount_pct}% {"below" if discount_pct > 0 else "above"} median)

📈 *5-Year Projection:*
  ${listing.price:,.0f} → ${score.projected_value_5yr:,.0f}
  Gain: *+${score.projected_gain_5yr:,.0f}* ({county.appreciation_rate}% YoY)

{url_line}
"""
        return self._send_message(message)

    def send_daily_summary(self, results, scan_time):
        strike = sum(1 for _, s in results if s.tier == DealTier.STRIKE_ZONE)
        watch = sum(1 for _, s in results if s.tier == DealTier.WATCHLIST)
        total = len(results)

        message = f"""
📊 *LAND ALPHA — Daily Scan Complete*
⏰ {datetime.now().strftime('%B %d, %Y at %I:%M %p UTC')}
⏱️ Scan time: {scan_time:.1f}s

📋 *Results:*
  🎯 Strike Zone: *{strike}*
  👁️ Watchlist: *{watch}*
  📦 Total Scanned: *{total}*

{"🔔 _New deals detected! Check alerts above._" if strike > 0 else "😴 _No new strike-zone deals today._"}
"""
        return self._send_message(message)

    def send_error(self, error_msg):
        message = f"⚠️ *LAND ALPHA — Error*\n\n```\n{error_msg[:500]}\n```"
        return self._send_message(message)

    def _send_message(self, text):
        if not self.token or not self.chat_id:
            logger.error("Telegram not configured (missing token or chat ID)")
            return False
        try:
            import requests
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text.strip(),
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Telegram message sent")
                return True
            else:
                logger.error(f"Telegram error {resp.status_code}: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False


# ── Local Storage (writes to workspace; GitHub Actions uploads as artifact) ──
class LocalStorage:
    def save(self, layer, county, data):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        path = f"{layer}/{county}/{today}"
        os.makedirs(path, exist_ok=True)
        filename = f"{path}/listings.json" if layer != "gold" else f"{path}/deals.json"
        try:
            with open(filename, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Saved {len(data) if isinstance(data, list) else 1} records to {filename}")
            return True
        except Exception as e:
            logger.error(f"Storage write failed: {e}")
            return False


# ── Main Pipeline ──────────────────────────────────────────────────
def run_pipeline(alert_config=None):
    start = time.time()

    if alert_config is None:
        alert_config = AlertConfig(
            max_price=float(os.environ.get("MAX_PRICE", 200_000)),
            max_ppa=float(os.environ.get("MAX_PPA", 35_000)),
            min_acres=float(os.environ.get("MIN_ACRES", 3.0)),
            min_score=float(os.environ.get("MIN_SCORE", 6.0)),
        )

    engine = ValuationEngine()
    scraper = LandScraper()
    notifier = TelegramNotifier()
    storage = LocalStorage()

    all_results = []
    alerts_sent = 0

    for county_key, county in COUNTY_PROFILES.items():
        logger.info(f"━━━ Scanning {county.name} ━━━")

        raw_listings = []
        raw_listings.extend(scraper.scrape_landwatch(county, max_price=alert_config.max_price))
        raw_listings.extend(scraper.scrape_zillow(county))

        if not raw_listings:
            logger.warning(f"No listings found for {county.name}")
            continue

        storage.save("bronze", county_key, [asdict(l) for l in raw_listings])

        # Deduplicate
        seen = set()
        clean_listings = []
        for listing in raw_listings:
            key = f"{listing.address}-{listing.price}"
            if key not in seen:
                seen.add(key)
                clean_listings.append(listing)

        storage.save("silver", county_key, [asdict(l) for l in clean_listings])

        # Score & alert
        scored = []
        for listing in clean_listings:
            score = engine.score(listing, county)
            scored.append((listing, score))

            if passes_alert_filter(listing, score, alert_config):
                notifier.send_deal_alert(listing, score, county)
                alerts_sent += 1
                time.sleep(1)  # Rate limit Telegram

        gold_records = [
            {
                "listing": asdict(l),
                "score": {
                    "total": s.total,
                    "tier": s.tier.value,
                    "breakdown": s.breakdown,
                    "projected_value_5yr": s.projected_value_5yr,
                    "projected_gain_5yr": s.projected_gain_5yr,
                },
            }
            for l, s in scored
        ]
        storage.save("gold", county_key, gold_records)
        all_results.extend(scored)

    elapsed = time.time() - start
    notifier.send_daily_summary(all_results, elapsed)

    logger.info(
        f"Pipeline complete in {elapsed:.1f}s — "
        f"{len(all_results)} listings, {alerts_sent} alerts sent"
    )
    return all_results


# ── Entry Points ──────────────────────────────────────────────────
def lambda_handler(event, context):
    """AWS Lambda entry point (optional — not used for GitHub Actions)."""
    logger.info(f"Lambda triggered: {json.dumps(event)}")
    results = run_pipeline()
    return {
        "statusCode": 200,
        "body": json.dumps({
            "total_listings": len(results),
            "strike_zone": sum(1 for _, s in results if s.tier == DealTier.STRIKE_ZONE),
        }),
    }


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════╗
    ║        🏗️  LAND ALPHA AGENT v1.0        ║
    ║     DFW Land Banking Intelligence       ║
    ╚══════════════════════════════════════════╝
    """)

    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if not SCRAPINGBEE_API_KEY:
        missing.append("SCRAPINGBEE_API_KEY")

    if missing:
        print(f"⚠️  Missing environment variables: {', '.join(missing)}")
        print("   Set them in .env (local) or GitHub Secrets (CI).\n")
        print("Running in DEMO mode — showing config only...\n")

        for county_key, county in COUNTY_PROFILES.items():
            print(f"{'━' * 50}")
            print(f"  {county.name}")
            print(f"{'━' * 50}")
            print(f"  Median PPA:    ${county.median_ppa:,}")
            print(f"  Appreciation:  {county.appreciation_rate}% YoY")
            print(f"  Risk Score:    {county.risk_score}/10")
            print(f"  Target Zips:   {', '.join(county.target_zips)}")
            print(f"  Catalysts:     {', '.join(county.catalysts)}")
            print()

        print("✅ Config valid. Set environment variables and re-run to activate.\n")
    else:
        print("✅ All credentials loaded. Running full pipeline...\n")
        run_pipeline()
