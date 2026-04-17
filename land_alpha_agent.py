"""
LAND ALPHA AGENT v2.0 — Production Pipeline (Data-Validated)
=============================================================
Fixes from v1.0:
  - Acre values are now validated with range checks and confidence scoring
  - sqft-to-acre conversion handles Zillow's lot size format
  - Never defaults to 1 acre — if we can't confirm acreage, listing is SKIPPED
  - Every alert shows a data confidence badge (HIGH/MEDIUM/LOW)
  - Rejected listings are logged with specific reasons for auditing

Target Markets: Ellis County, Kaufman County, Waller County
Budget: $100K-$200K | Horizon: 2029 | Target: 12%+ appreciation
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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("LandAlpha")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")

SQFT_PER_ACRE = 43560.0


class DealTier(Enum):
    STRIKE_ZONE = "STRIKE ZONE"
    WATCHLIST = "WATCHLIST"
    MONITOR = "MONITOR"
    PASS = "PASS"


class DataConfidence(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    REJECTED = "REJECTED"


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
    confidence: str = "HIGH"
    confidence_notes: str = ""
    acres_raw_text: str = ""

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


# =====================================================================
# DATA VALIDATOR — the core fix for bad acre values
# =====================================================================
class DataValidator:
    MIN_ACRES = 0.25
    MAX_ACRES = 500
    MIN_PRICE = 5_000
    MAX_PRICE = 2_000_000
    MIN_PPA = 500
    MAX_PPA = 200_000

    @classmethod
    def parse_acres(cls, text):
        """
        Extract acres from text. Handles:
          - '10.5 acres', '10.5 ac', '10.5 Acres'
          - '43560 sqft' -> converts to 1.0 acre
          - '3 lots' -> rejects (can't determine acreage)
        Returns (acres, confidence, raw_match) or (None, 'REJECTED', reason).
        """
        if not text:
            return None, "REJECTED", "Empty text"

        clean = text.strip()

        # Pattern 1: Explicit acres (highest confidence)
        acre_match = re.search(r"([\d,]+\.?\d*)\s*(?:acres?|ac\.?)\b", clean, re.I)
        if acre_match:
            val = float(acre_match.group(1).replace(",", ""))
            if cls.MIN_ACRES <= val <= cls.MAX_ACRES:
                return val, "HIGH", acre_match.group(0)
            elif val > cls.MAX_ACRES:
                return None, "REJECTED", f"Acres too high ({val})"
            elif val > 0:
                return val, "MEDIUM", f"{acre_match.group(0)} (very small lot)"

        # Pattern 2: sqft -> convert to acres
        sqft_match = re.search(r"([\d,]+\.?\d*)\s*(?:sq\.?\s*ft\.?|sqft|square\s*feet?)\b", clean, re.I)
        if sqft_match:
            sqft = float(sqft_match.group(1).replace(",", ""))
            if sqft > 0:
                acres = round(sqft / SQFT_PER_ACRE, 3)
                if acres >= cls.MIN_ACRES:
                    return acres, "MEDIUM", f"{sqft_match.group(0)} = {acres} acres"
                else:
                    return None, "REJECTED", f"Lot too small after sqft conversion ({acres} ac)"

        # Pattern 3: lots -> reject
        lot_match = re.search(r"([\d]+)\s*lots?\b", clean, re.I)
        if lot_match:
            return None, "REJECTED", f"Listed as lots ({lot_match.group(0)})"

        return None, "REJECTED", f"No acreage found in: '{clean[:80]}'"

    @classmethod
    def parse_price(cls, text):
        if not text:
            return None, "No price text"

        price_match = re.search(r"\$?\s*([\d,]+\.?\d*)\s*(k|m|K|M)?", text.strip())
        if not price_match:
            return None, f"No price in: '{text[:50]}'"

        val = float(price_match.group(1).replace(",", ""))
        suffix = (price_match.group(2) or "").upper()
        if suffix == "K":
            val *= 1_000
        elif suffix == "M":
            val *= 1_000_000

        if val < cls.MIN_PRICE:
            return None, f"Price too low (${val:,.0f})"
        if val > cls.MAX_PRICE:
            return None, f"Price too high (${val:,.0f})"

        return val, None

    @classmethod
    def validate_listing(cls, listing, county):
        notes = []

        if listing.acres <= 0:
            return False, DataConfidence.REJECTED, ["Acres is zero or negative"]
        if listing.acres < cls.MIN_ACRES:
            return False, DataConfidence.REJECTED, [f"Acres too small ({listing.acres})"]
        if listing.acres > cls.MAX_ACRES:
            return False, DataConfidence.REJECTED, [f"Acres too large ({listing.acres})"]
        if listing.price <= 0:
            return False, DataConfidence.REJECTED, ["Price is zero or negative"]

        ppa = listing.price_per_acre
        if ppa < cls.MIN_PPA:
            return False, DataConfidence.REJECTED, [f"PPA too low (${ppa:,.0f}/ac)"]
        if ppa > cls.MAX_PPA:
            return False, DataConfidence.REJECTED, [f"PPA too high (${ppa:,.0f}/ac)"]

        if county.median_ppa > 0:
            ratio = ppa / county.median_ppa
            if ratio < 0.1:
                return False, DataConfidence.REJECTED, [f"PPA is {ratio:.0%} of median — likely bad data"]
            elif ratio < 0.3:
                notes.append(f"PPA is {ratio:.0%} of median — great deal or bad data?")

        # Block the old 1.0 default bug
        if listing.acres == 1.0 and not listing.acres_raw_text:
            return False, DataConfidence.REJECTED, ["Acres defaulted to 1.0 — unverified"]

        if listing.confidence == "MEDIUM" or notes:
            confidence = DataConfidence.MEDIUM
        else:
            confidence = DataConfidence.HIGH

        return True, confidence, notes

    @classmethod
    def validate_batch(cls, listings, county):
        valid = []
        rejected = []

        for listing in listings:
            is_valid, confidence, notes = cls.validate_listing(listing, county)

            if is_valid:
                listing.confidence = confidence.value
                listing.confidence_notes = " | ".join(notes) if notes else ""
                valid.append(listing)
            else:
                rejected.append({
                    "listing_id": listing.listing_id,
                    "address": listing.address,
                    "price": listing.price,
                    "acres": listing.acres,
                    "ppa": listing.price_per_acre,
                    "source": listing.source,
                    "reason": " | ".join(notes),
                    "acres_raw_text": listing.acres_raw_text,
                })
                logger.warning(
                    f"REJECTED: {listing.address} | "
                    f"${listing.price:,.0f} | {listing.acres} ac | "
                    f"${listing.price_per_acre:,.0f}/ac | "
                    f"Reason: {' | '.join(notes)}"
                )

        logger.info(f"Validation: {len(valid)} passed, {len(rejected)} rejected out of {len(listings)}")
        return valid, rejected


# ── County Configurations ──────────────────────────────────────────
COUNTY_PROFILES = {
    "Ellis": CountyProfile(
        name="Ellis County", median_ppa=38500, appreciation_rate=14.2, risk_score=8.4,
        target_zips=["75154", "76065", "76084", "75152", "75165"],
        catalysts=["Google Data Center ($600M)", "I-35E Corridor Expansion", "Midlothian ISD Growth Bond"],
        search_urls={
            "landwatch": "https://www.landwatch.com/ellis-county-texas-land-for-sale",
            "zillow": "https://www.zillow.com/ellis-county-tx/land/",
        },
    ),
    "Kaufman": CountyProfile(
        name="Kaufman County", median_ppa=32000, appreciation_rate=12.8, risk_score=7.9,
        target_zips=["75142", "75189", "75126", "75114", "75160"],
        catalysts=["Samsung Fab Proximity", "Bush Turnpike Extension", "Forney ISD Bond ($1.2B)"],
        search_urls={
            "landwatch": "https://www.landwatch.com/kaufman-county-texas-land-for-sale",
            "zillow": "https://www.zillow.com/kaufman-county-tx/land/",
        },
    ),
    "Waller": CountyProfile(
        name="Waller County", median_ppa=24000, appreciation_rate=10.5, risk_score=7.2,
        target_zips=["77423", "77445", "77484"],
        catalysts=["Brookshire Industrial Corridor", "I-10 Expansion", "Amazon Fulfillment Center"],
        search_urls={
            "landwatch": "https://www.landwatch.com/waller-county-texas-land-for-sale",
            "zillow": "https://www.zillow.com/waller-county-tx/land/",
        },
    ),
}

SCORING_WEIGHTS = {
    "ppa_discount": 0.30, "appreciation": 0.20, "anchor_proximity": 0.15,
    "etj_status": 0.10, "days_on_market": 0.10, "school_district": 0.08, "utilities": 0.07,
}

SCHOOL_DISTRICT_SCORES = {
    "Red Oak ISD": 8, "Midlothian ISD": 9, "Waxahachie ISD": 7, "Ennis ISD": 6, "Palmer ISD": 5,
    "Community ISD": 5, "Royse City ISD": 8, "Forney ISD": 9, "Terrell ISD": 5, "Kaufman ISD": 6,
    "Crandall ISD": 5, "Royal ISD": 5, "Waller ISD": 6, "Hempstead ISD": 4,
}


class ValuationEngine:
    def __init__(self, weights=None):
        self.weights = weights or SCORING_WEIGHTS

    def score(self, listing, county):
        bd = {}
        if county.median_ppa > 0:
            bd["ppa_discount"] = max(0, min(10, ((county.median_ppa - listing.price_per_acre) / county.median_ppa) * 15))
        else:
            bd["ppa_discount"] = 5.0
        bd["appreciation"] = min(10, county.appreciation_rate / 1.5)
        bd["etj_status"] = 8.0 if listing.etj_status else 3.0
        bd["days_on_market"] = 10.0 if listing.days_on_market > 90 else 9.0 if listing.days_on_market > 60 else 6.0 if listing.days_on_market > 30 else 3.0
        bd["anchor_proximity"] = max(0, min(10, (20 - listing.dist_to_anchor_mi) / 2))
        bd["school_district"] = SCHOOL_DISTRICT_SCORES.get(listing.school_district, 5.0)
        u = listing.utilities.lower()
        bd["utilities"] = 9.0 if "all" in u else 7.0 if ("water" in u and "electric" in u) else 5.0 if "electric" in u else 2.0

        total = round(sum(bd[k] * self.weights[k] for k in self.weights), 1)
        tier = DealTier.STRIKE_ZONE if total >= 7.5 else DealTier.WATCHLIST if total >= 6.0 else DealTier.MONITOR if total >= 4.5 else DealTier.PASS
        proj = listing.price * ((1 + county.appreciation_rate / 100) ** 5)

        return DealScore(total=total, tier=tier, breakdown={k: round(v, 1) for k, v in bd.items()},
                         projected_value_5yr=round(proj), projected_gain_5yr=round(proj - listing.price), alert_triggered=(total >= 6.0))


@dataclass
class AlertConfig:
    max_price: float = 200_000
    max_ppa: float = 35_000
    min_acres: float = 3.0
    min_score: float = 6.0


def passes_alert_filter(listing, score, config):
    return (listing.price <= config.max_price and listing.price_per_acre <= config.max_ppa and
            listing.acres >= config.min_acres and score.total >= config.min_score)


# ── Scraper (FIXED) ───────────────────────────────────────────────
class LandScraper:
    def __init__(self, api_key=""):
        self.api_key = api_key or SCRAPINGBEE_API_KEY

    def _extract_acres_from_card(self, card):
        full_text = card.get_text(" ", strip=True)

        # Try dedicated acre elements first
        for sel in [".acres", "[data-testid='acres']", ".lot-size", ".property-acres"]:
            el = card.select_one(sel)
            if el:
                acres, conf, raw = DataValidator.parse_acres(el.get_text(strip=True))
                if acres is not None:
                    return acres, conf, raw

        # Fall back to full card text
        acres, conf, raw = DataValidator.parse_acres(full_text)
        if acres is not None:
            return acres, conf, raw

        # Check data attributes
        for attr in ["data-acres", "data-lot-size", "data-area"]:
            val = card.get(attr)
            if val:
                acres, conf, raw = DataValidator.parse_acres(val)
                if acres is not None:
                    return acres, conf, f"attr:{attr}={raw}"

        return None, "REJECTED", f"No acreage in card: '{full_text[:100]}'"

    def scrape_landwatch(self, county, max_price=300_000):
        url = county.search_urls.get("landwatch", "")
        if not url or not self.api_key:
            logger.warning(f"Skipping LandWatch for {county.name}")
            return []

        try:
            import requests
            from bs4 import BeautifulSoup

            resp = requests.get("https://app.scrapingbee.com/api/v1/",
                params={"api_key": self.api_key, "url": url, "render_js": "true", "wait": "2000"},
                timeout=45)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            listings = []
            skipped = 0

            for card in soup.select(".property-card, .listing-card, [data-testid='property-card'], .property-listing, .search-result"):
                try:
                    price_el = card.select_one(".price, [data-testid='price'], .property-price, span[class*='price']")
                    if not price_el:
                        continue

                    price, err = DataValidator.parse_price(price_el.get_text(strip=True))
                    if price is None:
                        skipped += 1
                        continue

                    acres, conf, raw = self._extract_acres_from_card(card)
                    if acres is None:
                        skipped += 1
                        continue

                    address_el = card.select_one(".address, [data-testid='address'], .property-address, h2, h3")
                    address_text = address_el.get_text(strip=True) if address_el else "Unknown"
                    link_el = card.select_one("a[href]")
                    href = link_el.get("href", "") if link_el else ""
                    if href and href.startswith("/"):
                        href = "https://www.landwatch.com" + href

                    listings.append(LandListing(
                        listing_id=hashlib.md5(f"{address_text}-{price}-{acres}".encode()).hexdigest()[:10],
                        source="landwatch", address=address_text, county=county.name, zip_code="",
                        acres=round(acres, 2), price=price, price_per_acre=round(price / acres, 2),
                        days_on_market=0, zoning="Unknown", etj_status=False, utilities="Unknown",
                        school_district="Unknown", latitude=0.0, longitude=0.0, dist_to_anchor_mi=10.0,
                        url=href, confidence=conf, acres_raw_text=raw,
                    ))
                except (ValueError, AttributeError) as e:
                    skipped += 1
                    continue

            logger.info(f"LandWatch {county.name}: {len(listings)} parsed, {skipped} skipped")
            return listings
        except Exception as e:
            logger.error(f"LandWatch failed for {county.name}: {e}")
            return []

    def scrape_zillow(self, county):
        url = county.search_urls.get("zillow", "")
        if not url or not self.api_key:
            logger.warning(f"Skipping Zillow for {county.name}")
            return []

        try:
            import requests
            from bs4 import BeautifulSoup

            resp = requests.get("https://app.scrapingbee.com/api/v1/",
                params={"api_key": self.api_key, "url": url, "render_js": "true", "premium_proxy": "true", "wait": "3000"},
                timeout=60)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            listings = []
            skipped = 0

            for card in soup.select("[data-test='property-card'], .list-card, article, .property-card, [class*='ListItem']"):
                try:
                    price_el = card.select_one("[data-test='property-card-price'], .list-card-price, span[class*='Price'], [class*='price']")
                    if not price_el:
                        continue

                    price, err = DataValidator.parse_price(price_el.get_text(strip=True))
                    if price is None:
                        skipped += 1
                        continue

                    acres, conf, raw = self._extract_acres_from_card(card)
                    if acres is None:
                        skipped += 1
                        continue

                    addr_el = card.select_one("address, [data-test='property-card-addr'], [class*='address']")
                    address_text = addr_el.get_text(strip=True) if addr_el else "Unknown"
                    link_el = card.select_one("a[href*='/homedetails/']") or card.select_one("a[href]")
                    href = link_el.get("href", "") if link_el else ""
                    if href and href.startswith("/"):
                        href = "https://www.zillow.com" + href

                    listings.append(LandListing(
                        listing_id=hashlib.md5(f"zillow-{address_text}-{price}-{acres}".encode()).hexdigest()[:10],
                        source="zillow", address=address_text, county=county.name, zip_code="",
                        acres=round(acres, 2), price=price, price_per_acre=round(price / acres, 2) if acres > 0 else 0,
                        days_on_market=0, zoning="Unknown", etj_status=False, utilities="Unknown",
                        school_district="Unknown", latitude=0.0, longitude=0.0, dist_to_anchor_mi=10.0,
                        url=href, confidence=conf, acres_raw_text=raw,
                    ))
                except (ValueError, AttributeError) as e:
                    skipped += 1
                    continue

            logger.info(f"Zillow {county.name}: {len(listings)} parsed, {skipped} skipped")
            return listings
        except Exception as e:
            logger.error(f"Zillow failed for {county.name}: {e}")
            return []


# ── Telegram ───────────────────────────────────────────────────────
class TelegramNotifier:
    def __init__(self, token="", chat_id=""):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_deal_alert(self, listing, score, county):
        tier_emoji = {DealTier.STRIKE_ZONE: "🟢🎯", DealTier.WATCHLIST: "🟡👁️", DealTier.MONITOR: "⚪📋", DealTier.PASS: "🔴❌"}
        conf_badge = {"HIGH": "🟢 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🔴 LOW"}
        discount = round((1 - listing.price_per_acre / county.median_ppa) * 100) if county.median_ppa else 0
        url_line = f"🔗 [View Listing]({listing.url})" if listing.url else ""
        notes_line = f"\n⚠️ _{listing.confidence_notes}_" if listing.confidence_notes else ""

        message = f"""
{tier_emoji.get(score.tier, "⚪")} *{score.tier.value}* — Score: *{score.total}/10*
📊 Data Confidence: {conf_badge.get(listing.confidence, "⚪ UNK")}

📍 *{listing.address}*
🏘️ {listing.county} | {listing.source.title()}

💰 *${listing.price:,.0f}* | *{listing.acres} acres*
📐 ${listing.price_per_acre:,.0f}/acre ({discount}% {"below" if discount > 0 else "above"} median)
📝 Parsed from: `{listing.acres_raw_text}`

📈 *5-Year:* ${listing.price:,.0f} → ${score.projected_value_5yr:,.0f} (*+${score.projected_gain_5yr:,.0f}*)

{url_line}{notes_line}
"""
        return self._send(message)

    def send_daily_summary(self, results, scan_time, rejected_count=0):
        strike = sum(1 for _, s in results if s.tier == DealTier.STRIKE_ZONE)
        watch = sum(1 for _, s in results if s.tier == DealTier.WATCHLIST)
        high = sum(1 for l, _ in results if l.confidence == "HIGH")
        med = sum(1 for l, _ in results if l.confidence == "MEDIUM")

        message = f"""
📊 *LAND ALPHA v2.0 — Daily Scan*
⏰ {datetime.now().strftime('%B %d, %Y %I:%M %p UTC')}
⏱️ {scan_time:.1f}s

📋 *Results:*
  🎯 Strike Zone: *{strike}*
  👁️ Watchlist: *{watch}*
  📦 Valid: *{len(results)}*
  🚫 Rejected (bad data): *{rejected_count}*

🔬 *Data Quality:*
  🟢 High Confidence: *{high}*
  🟡 Medium Confidence: *{med}*

{"🔔 _Deals above!_" if strike > 0 else "😴 _No strike-zone deals today._"}
"""
        return self._send(message)

    def send_error(self, msg):
        return self._send(f"⚠️ *LAND ALPHA Error*\n```\n{msg[:500]}\n```")

    def _send(self, text):
        if not self.token or not self.chat_id:
            logger.error("Telegram not configured")
            return False
        try:
            import requests
            r = requests.post(f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text.strip(), "parse_mode": "Markdown", "disable_web_page_preview": True}, timeout=10)
            if r.status_code == 200:
                logger.info("Telegram sent")
                return True
            logger.error(f"Telegram {r.status_code}: {r.text}")
            return False
        except Exception as e:
            logger.error(f"Telegram failed: {e}")
            return False


class LocalStorage:
    def save(self, layer, county, data):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        path = f"{layer}/{county}/{today}"
        os.makedirs(path, exist_ok=True)
        fn = f"{path}/{'deals' if layer == 'gold' else 'listings'}.json"
        try:
            with open(fn, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Saved {len(data) if isinstance(data, list) else 1} records to {fn}")
        except Exception as e:
            logger.error(f"Storage failed: {e}")


# ── Pipeline ──────────────────────────────────────────────────────
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
    all_rejected = 0
    alerts_sent = 0

    for county_key, county in COUNTY_PROFILES.items():
        logger.info(f"━━━ Scanning {county.name} ━━━")

        raw = []
        raw.extend(scraper.scrape_landwatch(county, max_price=alert_config.max_price))
        raw.extend(scraper.scrape_zillow(county))

        if not raw:
            logger.warning(f"No listings for {county.name}")
            continue

        storage.save("bronze", county_key, [asdict(l) for l in raw])

        # Dedup
        seen = set()
        deduped = []
        for l in raw:
            k = f"{l.address}-{l.price}-{l.acres}"
            if k not in seen:
                seen.add(k)
                deduped.append(l)

        # VALIDATE
        valid, rejected = DataValidator.validate_batch(deduped, county)
        all_rejected += len(rejected)
        if rejected:
            storage.save("rejected", county_key, rejected)

        storage.save("silver", county_key, [asdict(l) for l in valid])

        # Score & alert
        scored = []
        for listing in valid:
            score = engine.score(listing, county)
            scored.append((listing, score))
            if passes_alert_filter(listing, score, alert_config):
                notifier.send_deal_alert(listing, score, county)
                alerts_sent += 1
                time.sleep(1)

        storage.save("gold", county_key, [{"listing": asdict(l), "score": {"total": s.total, "tier": s.tier.value,
            "breakdown": s.breakdown, "projected_value_5yr": s.projected_value_5yr, "projected_gain_5yr": s.projected_gain_5yr}}
            for l, s in scored])
        all_results.extend(scored)

    elapsed = time.time() - start
    notifier.send_daily_summary(all_results, elapsed, rejected_count=all_rejected)
    logger.info(f"Done in {elapsed:.1f}s — {len(all_results)} valid, {all_rejected} rejected, {alerts_sent} alerts")
    return all_results


def lambda_handler(event, context):
    logger.info(f"Lambda: {json.dumps(event)}")
    results = run_pipeline()
    return {"statusCode": 200, "body": json.dumps({"total": len(results),
        "strike_zone": sum(1 for _, s in results if s.tier == DealTier.STRIKE_ZONE)})}


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════╗
    ║      🏗️  LAND ALPHA AGENT v2.0          ║
    ║   ✅ Data-Validated · Confidence-Scored  ║
    ╚══════════════════════════════════════════╝
    """)
    missing = [v for v in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SCRAPINGBEE_API_KEY"] if not os.environ.get(v)]
    if missing:
        print(f"⚠️  Missing: {', '.join(missing)}")
        print("Running DEMO mode...\n")
        for k, c in COUNTY_PROFILES.items():
            print(f"{'━'*50}\n  {c.name}\n{'━'*50}")
            print(f"  Median PPA:   ${c.median_ppa:,}  |  Growth: {c.appreciation_rate}%")
            print(f"  Zips: {', '.join(c.target_zips)}\n")
        print(f"📐 Validation: Acres {DataValidator.MIN_ACRES}-{DataValidator.MAX_ACRES} | "
              f"PPA ${DataValidator.MIN_PPA:,}-${DataValidator.MAX_PPA:,} | "
              f"sqft auto-converts | 1.0ac default BLOCKED\n")
    else:
        print("✅ Running full pipeline...\n")
        run_pipeline()
