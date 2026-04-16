"""
LAND ALPHA AGENT — Production Pipeline
========================================
A serverless land deal intelligence system for DFW land banking.
Designed for AWS Lambda + EventBridge + Telegram + S3.

Author: Built for Prashita's DFW Land Banking Strategy
Target Markets: Ellis County, Kaufman County, Waller County
Budget: $100K–$200K | Horizon: 2029 deployment | Target: 12%+ appreciation

Architecture:
  EventBridge (8AM CST) → Lambda → Scraper → Valuation Engine → S3 + Telegram

Usage:
  Local:  python land_alpha_agent.py
  Lambda: Set handler to land_alpha_agent.lambda_handler
"""

import json
import os
import logging
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

# Auto-load .env for local runs (safely skipped in CI/Lambda where it's not installed)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("LandAlpha")

# Environment variables (set in Lambda or .env)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "land-alpha-data")
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
    appreciation_rate: float  # Annual % YoY
    risk_score: float         # 1-10
    target_zips: list
    catalysts: list
    search_urls: dict = field(default_factory=dict)


@dataclass
class LandListing:
    listing_id: str
    source: str               # "landwatch", "zillow", "redfin"
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
    raw_html_hash: str = ""

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
            "Google Data Center ($600M investment)",
            "I-35E Corridor Expansion",
            "Midlothian ISD Growth Bond",
            "Red Oak ETJ Annexation Activity",
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
            "Samsung Fab Proximity (Taylor spillover)",
            "Bush Turnpike Extension Plans",
            "Forney ISD Bond ($1.2B approved)",
            "Royse City Retail Corridor Growth",
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
            "I-10 Expansion Project",
            "Amazon Fulfillment Center",
            "H-E-B Distribution Hub",
        ],
        search_urls={
            "landwatch": "https://www.landwatch.com/waller-county-texas-land-for-sale",
            "zillow": "https://www.zillow.com/waller-county-tx/land/",
        },
    ),
}


# ── Scoring Weights ────────────────────────────────────────────────
SCORING_WEIGHTS = {
    "ppa_discount": 0.30,      # How far below county median $/acre
    "appreciation": 0.20,      # County-level YoY appreciation rate
    "etj_status": 0.10,        # Inside ETJ = higher growth potential
    "days_on_market": 0.10,    # Stale listings = negotiation leverage
    "anchor_proximity": 0.15,  # Distance to corporate/infrastructure anchor
    "school_district": 0.08,   # School quality correlates w/ residential demand
    "utilities": 0.07,         # Utility availability reduces development cost
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
    """
    Multi-factor scoring engine for raw land deal evaluation.
    Produces a 0–10 composite score with tier classification.
    """

    def __init__(self, weights: dict = None):
        self.weights = weights or SCORING_WEIGHTS

    def score(self, listing: LandListing, county: CountyProfile) -> DealScore:
        breakdown = {}

        # 1. PPA Discount (how far below median)
        if county.median_ppa > 0:
            discount_pct = (county.median_ppa - listing.price_per_acre) / county.median_ppa
            breakdown["ppa_discount"] = max(0, min(10, discount_pct * 15))
        else:
            breakdown["ppa_discount"] = 5.0

        # 2. Appreciation rate
        breakdown["appreciation"] = min(10, county.appreciation_rate / 1.5)

        # 3. ETJ status
        breakdown["etj_status"] = 8.0 if listing.etj_status else 3.0

        # 4. Days on market (stale = motivated seller)
        if listing.days_on_market > 90:
            breakdown["days_on_market"] = 10.0
        elif listing.days_on_market > 60:
            breakdown["days_on_market"] = 9.0
        elif listing.days_on_market > 30:
            breakdown["days_on_market"] = 6.0
        else:
            breakdown["days_on_market"] = 3.0

        # 5. Anchor proximity
        breakdown["anchor_proximity"] = max(0, min(10, (20 - listing.dist_to_anchor_mi) / 2))

        # 6. School district quality
        breakdown["school_district"] = SCHOOL_DISTRICT_SCORES.get(listing.school_district, 5.0)

        # 7. Utility availability
        utils = listing.utilities.lower()
        if "all" in utils:
            breakdown["utilities"] = 9.0
        elif "water" in utils and "electric" in utils:
            breakdown["utilities"] = 7.0
        elif "electric" in utils:
            breakdown["utilities"] = 5.0
        else:
            breakdown["utilities"] = 2.0

        # Weighted composite
        total = sum(breakdown[k] * self.weights[k] for k in self.weights)
        total = round(total, 1)

        # Tier classification
        if total >= 7.5:
            tier = DealTier.STRIKE_ZONE
        elif total >= 6.0:
            tier = DealTier.WATCHLIST
        elif total >= 4.5:
            tier = DealTier.MONITOR
        else:
            tier = DealTier.PASS

        # 5-year projection
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
    notify_strike_zone_only: bool = False
    appreciation_zips: list = field(default_factory=lambda: [
        # DFW High-Growth Zips
        "75154", "76065", "76084", "75142", "75189", "75126",
        # Waller Corridor
        "77423", "77484",
    ])


def passes_alert_filter(listing: LandListing, score: DealScore, config: AlertConfig) -> bool:
    """Check if a listing passes all alert criteria."""
    if listing.price > config.max_price:
        return False
    if listing.price_per_acre > config.max_ppa:
        return False
    if listing.acres < config.min_acres:
        return False
    if score.total < config.min_score:
        return False
    if config.notify_strike_zone_only and score.tier != DealTier.STRIKE_ZONE:
        return False
    return True


# ── Scraper Module ─────────────────────────────────────────────────
class LandScraper:
    """
    Hybrid scraper using ScrapingBee API for anti-bot bypass.
    Supports LandWatch, Zillow, and Redfin as data sources.
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or SCRAPINGBEE_API_KEY

    def scrape_landwatch(self, county: CountyProfile, max_price: float = 300_000) -> list:
        """
        Scrape LandWatch for land listings in a county.
        Uses ScrapingBee to bypass anti-bot protections.
        """
        url = county.search_urls.get("landwatch", "")
        if not url:
            logger.warning(f"No LandWatch URL configured for {county.name}")
            return []

        try:
            import requests
            from bs4 import BeautifulSoup

            # ScrapingBee request with JS rendering
            params = {
                "api_key": self.api_key,
                "url": f"{url}?sort=price_low&max_price={int(max_price)}&property_type=land",
                "render_js": "true",
                "wait": "2000",
            }
            resp = requests.get("https://app.scrapingbee.com/api/v1/", params=params, timeout=30)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            listings = []

            # Parse listing cards (LandWatch structure as of 2025)
            for card in soup.select(".property-card, .listing-card, [data-testid='property-card']"):
                try:
                    price_el = card.select_one(".price, [data-testid='price']")
                    acres_el = card.select_one(".acres, [data-testid='acres']")
                    address_el = card.select_one(".address, [data-testid='address']")
                    link_el = card.select_one("a[href]")

                    if not all([price_el, acres_el]):
                        continue

                    price_text = price_el.get_text(strip=True).replace("$", "").replace(",", "")
                    acres_text = acres_el.get_text(strip=True).split()[0]

                    price = float(price_text)
                    acres = float(acres_text)

                    if acres <= 0 or price <= 0:
                        continue

                    listing = LandListing(
                        listing_id=hashlib.md5(f"{address_el.get_text(strip=True) if address_el else ''}-{price}".encode()).hexdigest()[:10],
                        source="landwatch",
                        address=address_el.get_text(strip=True) if address_el else "Unknown",
                        county=county.name,
                        zip_code="",  # Extract from address
                        acres=acres,
                        price=price,
                        price_per_acre=round(price / acres, 2),
                        days_on_market=0,  # Requires detail page
                        zoning="Unknown",
                        etj_status=False,
                        utilities="Unknown",
                        school_district="Unknown",
                        latitude=0.0,
                        longitude=0.0,
                        dist_to_anchor_mi=0.0,
                        url=link_el["href"] if link_el else "",
                        raw_html_hash=hashlib.md5(str(card).encode()).hexdigest()[:8],
                    )
                    listings.append(listing)

                except (ValueError, AttributeError) as e:
                    logger.debug(f"Failed to parse card: {e}")
                    continue

            logger.info(f"Scraped {len(listings)} listings from LandWatch for {county.name}")
            return listings

        except ImportError:
            logger.error("Install dependencies: pip install requests beautifulsoup4")
            return []
        except Exception as e:
            logger.error(f"LandWatch scrape failed for {county.name}: {e}")
            return []

    def scrape_zillow(self, county: CountyProfile) -> list:
        """
        Scrape Zillow for land listings. Zillow is more aggressive with anti-bot,
        so ScrapingBee's premium_proxy and stealth_proxy flags are recommended.
        """
        url = county.search_urls.get("zillow", "")
        if not url:
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
            resp = requests.get("https://app.scrapingbee.com/api/v1/", params=params, timeout=45)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            listings = []

            for card in soup.select("[data-test='property-card'], .list-card"):
                try:
                    price_el = card.select_one("[data-test='property-card-price'], .list-card-price")
                    details = card.select_one("[data-test='property-card-details']")

                    if not price_el:
                        continue

                    price_text = price_el.get_text(strip=True).replace("$", "").replace(",", "").replace("+", "")
                    price = float(price_text)

                    # Extract acres from details text
                    details_text = details.get_text() if details else ""
                    acres = 1.0  # default
                    if "acre" in details_text.lower():
                        import re
                        acre_match = re.search(r'([\d.]+)\s*acre', details_text, re.I)
                        if acre_match:
                            acres = float(acre_match.group(1))

                    link_el = card.select_one("a[href*='/homedetails/']")

                    listing = LandListing(
                        listing_id=hashlib.md5(f"zillow-{price}-{acres}".encode()).hexdigest()[:10],
                        source="zillow",
                        address=card.select_one("address, [data-test='property-card-addr']").get_text(strip=True) if card.select_one("address") else "Unknown",
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
                        dist_to_anchor_mi=0.0,
                        url=f"https://www.zillow.com{link_el['href']}" if link_el else "",
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
    """Send deal alerts to a Telegram channel/chat."""

    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_deal_alert(self, listing: LandListing, score: DealScore, county: CountyProfile):
        """Format and send a rich deal alert to Telegram."""
        tier_emoji = {
            DealTier.STRIKE_ZONE: "🟢🎯",
            DealTier.WATCHLIST: "🟡👁️",
            DealTier.MONITOR: "⚪📋",
            DealTier.PASS: "🔴❌",
        }

        discount_pct = round((1 - listing.price_per_acre / county.median_ppa) * 100)

        message = f"""
{tier_emoji.get(score.tier, "⚪")} *{score.tier.value}* — Score: *{score.total}/10*

📍 *{listing.address}*
🏘️ {listing.county} | {listing.school_district}

💰 *${listing.price:,.0f}* | {listing.acres} acres
📊 ${listing.price_per_acre:,.0f}/acre ({discount_pct}% {'below' if discount_pct > 0 else 'above'} median)
📅 {listing.days_on_market} days on market
🏗️ Zoning: {listing.zoning} | ETJ: {'✅' if listing.etj_status else '❌'}
⚡ Utilities: {listing.utilities}

📈 *5-Year Projection:*
  ${listing.price:,.0f} → ${score.projected_value_5yr:,.0f}
  Gain: *+${score.projected_gain_5yr:,.0f}* ({county.appreciation_rate}% YoY)

🔗 [View Listing]({listing.url})

—
_Score Breakdown:_
{self._format_breakdown(score.breakdown)}
"""
        return self._send_message(message)

    def send_daily_summary(self, results: list, scan_time: float):
        """Send end-of-scan summary."""
        strike = sum(1 for _, s in results if s.tier == DealTier.STRIKE_ZONE)
        watch = sum(1 for _, s in results if s.tier == DealTier.WATCHLIST)
        total = len(results)

        message = f"""
📊 *LAND ALPHA — Daily Scan Complete*
⏰ {datetime.now().strftime('%B %d, %Y at %I:%M %p CST')}
⏱️ Scan time: {scan_time:.1f}s

📋 *Results:*
  🎯 Strike Zone: *{strike}*
  👁️ Watchlist: *{watch}*
  📦 Total Scanned: *{total}*

{'🔔 _New deals detected! Check alerts above._' if strike > 0 else '😴 _No new strike zone deals today._'}
"""
        return self._send_message(message)

    def _format_breakdown(self, breakdown: dict) -> str:
        labels = {
            "ppa_discount": "PPA Discount",
            "appreciation": "Appreciation",
            "etj_status": "ETJ Status",
            "days_on_market": "Days on Market",
            "anchor_proximity": "Anchor Prox.",
            "school_district": "School Dist.",
            "utilities": "Utilities",
        }
        lines = []
        for key, val in breakdown.items():
            bar = "█" * int(val) + "░" * (10 - int(val))
            lines.append(f"  `{labels.get(key, key):15s}` {bar} {val}")
        return "\n".join(lines)

    def _send_message(self, text: str) -> bool:
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
                logger.info("Telegram alert sent successfully")
                return True
            else:
                logger.error(f"Telegram API error: {resp.status_code} — {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False


# ── S3 Storage (Bronze/Silver/Gold) ────────────────────────────────
class S3Storage:
    """
    Medallion architecture for land data:
      Bronze: Raw scraped HTML/JSON (immutable)
      Silver: Cleaned, deduplicated listings
      Gold:   Scored and enriched deals
    """

    def __init__(self, bucket: str = ""):
        self.bucket = bucket or S3_BUCKET

    def save_bronze(self, raw_data: list, county: str):
        """Save raw scrape to S3 Bronze layer."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"bronze/{county}/{today}/listings.json"
        return self._put_json(key, [asdict(l) for l in raw_data])

    def save_silver(self, clean_data: list, county: str):
        """Save cleaned listings to S3 Silver layer."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"silver/{county}/{today}/listings.json"
        return self._put_json(key, [asdict(l) for l in clean_data])

    def save_gold(self, scored_data: list, county: str):
        """Save scored deals to S3 Gold layer."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"gold/{county}/{today}/deals.json"
        records = []
        for listing, score in scored_data:
            records.append({
                "listing": asdict(listing),
                "score": {
                    "total": score.total,
                    "tier": score.tier.value,
                    "breakdown": score.breakdown,
                    "projected_value_5yr": score.projected_value_5yr,
                    "projected_gain_5yr": score.projected_gain_5yr,
                },
            })
        return self._put_json(key, records)

    def load_previous_listings(self, county: str, days_back: int = 7) -> list:
        """Load previous listings to detect price drops."""
        previous = []
        for d in range(1, days_back + 1):
            date = (datetime.utcnow() - timedelta(days=d)).strftime("%Y-%m-%d")
            key = f"silver/{county}/{date}/listings.json"
            data = self._get_json(key)
            if data:
                previous.extend(data)
        return previous

    def _put_json(self, key: str, data) -> bool:
        try:
            import boto3
            s3 = boto3.client("s3")
            s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(data, indent=2),
                ContentType="application/json",
            )
            logger.info(f"Saved to s3://{self.bucket}/{key}")
            return True
        except Exception as e:
            logger.error(f"S3 write failed: {e}")
            # Fallback: save locally
            os.makedirs(os.path.dirname(key), exist_ok=True)
            with open(key, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved locally to {key}")
            return False

    def _get_json(self, key: str):
        try:
            import boto3
            s3 = boto3.client("s3")
            resp = s3.get_object(Bucket=self.bucket, Key=key)
            return json.loads(resp["Body"].read())
        except Exception:
            return None


# ── Price Drop Detector ────────────────────────────────────────────
def detect_price_drops(current: list, previous: list, threshold_pct: float = 5.0) -> list:
    """
    Compare current listings against historical data to find price drops.
    A listing that drops 5%+ after 90 days = "Strike Zone" opportunity.
    """
    prev_map = {}
    for p in previous:
        addr = p.get("address", "") if isinstance(p, dict) else p.address
        price = p.get("price", 0) if isinstance(p, dict) else p.price
        if addr not in prev_map or price < prev_map[addr]:
            prev_map[addr] = price

    drops = []
    for listing in current:
        addr = listing.address
        if addr in prev_map:
            old_price = prev_map[addr]
            if old_price > 0:
                drop_pct = ((old_price - listing.price) / old_price) * 100
                if drop_pct >= threshold_pct:
                    drops.append({
                        "listing": listing,
                        "old_price": old_price,
                        "new_price": listing.price,
                        "drop_pct": round(drop_pct, 1),
                        "drop_amount": round(old_price - listing.price),
                    })
                    logger.info(f"💰 PRICE DROP: {addr} — ${old_price:,.0f} → ${listing.price:,.0f} ({drop_pct:.1f}%)")

    return drops


# ── Main Pipeline ──────────────────────────────────────────────────
def run_pipeline(alert_config: AlertConfig = None):
    """Execute the full Land Alpha pipeline."""
    import time
    start = time.time()

    if alert_config is None:
        alert_config = AlertConfig()

    engine = ValuationEngine()
    scraper = LandScraper()
    notifier = TelegramNotifier()
    storage = S3Storage()

    all_results = []

    for county_key, county in COUNTY_PROFILES.items():
        logger.info(f"━━━ Scanning {county.name} ━━━")

        # 1. Scrape (Bronze)
        raw_listings = []
        raw_listings.extend(scraper.scrape_landwatch(county, max_price=alert_config.max_price))
        raw_listings.extend(scraper.scrape_zillow(county))

        if not raw_listings:
            logger.warning(f"No listings found for {county.name}")
            continue

        storage.save_bronze(raw_listings, county_key)

        # 2. Clean & Deduplicate (Silver)
        seen = set()
        clean_listings = []
        for listing in raw_listings:
            key = f"{listing.address}-{listing.price}"
            if key not in seen:
                seen.add(key)
                clean_listings.append(listing)

        storage.save_silver(clean_listings, county_key)

        # 3. Score & Filter (Gold)
        scored = []
        for listing in clean_listings:
            score = engine.score(listing, county)
            scored.append((listing, score))

            # Check alert filter
            if passes_alert_filter(listing, score, alert_config):
                notifier.send_deal_alert(listing, score, county)

        storage.save_gold(scored, county_key)
        all_results.extend(scored)

        # 4. Check for price drops
        previous = storage.load_previous_listings(county_key)
        drops = detect_price_drops(clean_listings, previous)
        for drop in drops:
            logger.info(f"🔻 Price drop alert: {drop['listing'].address} — {drop['drop_pct']}% off")

    # 5. Daily summary
    elapsed = time.time() - start
    notifier.send_daily_summary(all_results, elapsed)

    logger.info(f"Pipeline complete in {elapsed:.1f}s — {len(all_results)} listings processed")
    return all_results


# ── AWS Lambda Handler ─────────────────────────────────────────────
def lambda_handler(event, context):
    """AWS Lambda entry point, triggered by EventBridge."""
    logger.info(f"Lambda triggered: {json.dumps(event)}")

    config = AlertConfig(
        max_price=float(os.environ.get("MAX_PRICE", 200_000)),
        max_ppa=float(os.environ.get("MAX_PPA", 35_000)),
        min_acres=float(os.environ.get("MIN_ACRES", 3.0)),
        min_score=float(os.environ.get("MIN_SCORE", 6.0)),
    )

    results = run_pipeline(config)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Land Alpha scan complete",
            "total_listings": len(results),
            "strike_zone": sum(1 for _, s in results if s.tier == DealTier.STRIKE_ZONE),
            "watchlist": sum(1 for _, s in results if s.tier == DealTier.WATCHLIST),
        }),
    }


# ── Local Execution ───────────────────────────────────────────────
if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════╗
    ║        🏗️  LAND ALPHA AGENT v1.0        ║
    ║     DFW Land Banking Intelligence       ║
    ╠══════════════════════════════════════════╣
    ║  Counties: Ellis · Kaufman · Waller     ║
    ║  Budget: $100K–$200K                    ║
    ║  Horizon: 2029 · Target: 12%+ YoY      ║
    ╚══════════════════════════════════════════╝
    """)

    # Check for required env vars
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if not SCRAPINGBEE_API_KEY:
        missing.append("SCRAPINGBEE_API_KEY")

    if missing:
        print(f"⚠️  Missing environment variables: {', '.join(missing)}")
        print("   Set them before running the full pipeline:")
        print("   export TELEGRAM_BOT_TOKEN='your-token-here'")
        print("   export TELEGRAM_CHAT_ID='your-chat-id'")
        print("   export SCRAPINGBEE_API_KEY='your-key'")
        print()
        print("Running in DEMO mode with sample data...\n")

        # Demo mode: score the sample data
        engine = ValuationEngine()

        for county_key, county in COUNTY_PROFILES.items():
            print(f"\n{'━' * 50}")
            print(f"  {county.name} | Median PPA: ${county.median_ppa:,} | Growth: {county.appreciation_rate}%")
            print(f"{'━' * 50}")
            print(f"  Catalysts: {', '.join(county.catalysts[:2])}")
            print(f"  Target Zips: {', '.join(county.target_zips)}")
            print()

        print("\n✅ Config validated. Set environment variables and re-run to activate the pipeline.")
    else:
        run_pipeline()
