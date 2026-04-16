import { useState, useEffect, useCallback } from "react";

const COUNTIES = {
  "Ellis County": {
    medianPPA: 38500, appreciation: 14.2, zips: ["75154", "76065", "76084", "75152"],
    catalysts: ["Google Data Center ($600M)", "I-35E Corridor Expansion", "Midlothian ISD Growth"],
    color: "#10B981", riskScore: 8.4,
    listings: [
      { id: "EL-001", address: "FM 875 & Crisp Rd, Red Oak", acres: 5.2, price: 142000, ppa: 27308, daysOnMarket: 45, zoning: "AG/Residential", etj: true, zip: "75154", lat: 32.505, lng: -96.815, distToAnchor: 3.2, schoolDist: "Red Oak ISD", utilities: "Electric at road" },
      { id: "EL-002", address: "Hwy 287 S, Midlothian", acres: 10.0, price: 285000, ppa: 28500, daysOnMarket: 12, zoning: "Agricultural", etj: false, zip: "76065", lat: 32.472, lng: -96.994, distToAnchor: 5.1, schoolDist: "Midlothian ISD", utilities: "None" },
      { id: "EL-003", address: "Ovilla Rd, Ovilla", acres: 3.8, price: 178000, ppa: 46842, daysOnMarket: 88, zoning: "Residential", etj: true, zip: "75154", lat: 32.526, lng: -96.862, distToAnchor: 2.1, schoolDist: "Red Oak ISD", utilities: "All at road" },
      { id: "EL-004", address: "W Main St, Waxahachie", acres: 2.1, price: 89000, ppa: 42381, daysOnMarket: 34, zoning: "Mixed Use", etj: true, zip: "75165", lat: 32.386, lng: -96.848, distToAnchor: 7.8, schoolDist: "Waxahachie ISD", utilities: "All available" },
    ]
  },
  "Kaufman County": {
    medianPPA: 32000, appreciation: 12.8, zips: ["75142", "75189", "75126", "75114"],
    catalysts: ["Samsung Fab Proximity", "Bush Turnpike Extension", "Forney ISD Bond ($1.2B)"],
    color: "#3B82F6", riskScore: 7.9,
    listings: [
      { id: "KF-001", address: "FM 148, Josephine", acres: 8.3, price: 149000, ppa: 17952, daysOnMarket: 67, zoning: "Agricultural", etj: false, zip: "75142", lat: 32.965, lng: -96.306, distToAnchor: 12.4, schoolDist: "Community ISD", utilities: "Electric nearby" },
      { id: "KF-002", address: "FM 2755, Royse City", acres: 5.0, price: 125000, ppa: 25000, daysOnMarket: 23, zoning: "AG/Residential", etj: true, zip: "75189", lat: 32.975, lng: -96.332, distToAnchor: 8.7, schoolDist: "Royse City ISD", utilities: "Electric at road" },
      { id: "KF-003", address: "Hwy 80, Forney", acres: 4.2, price: 168000, ppa: 40000, daysOnMarket: 15, zoning: "Commercial", etj: true, zip: "75126", lat: 32.748, lng: -96.472, distToAnchor: 4.3, schoolDist: "Forney ISD", utilities: "All available" },
      { id: "KF-004", address: "CR 305, Terrell", acres: 12.5, price: 187000, ppa: 14960, daysOnMarket: 92, zoning: "Agricultural", etj: false, zip: "75160", lat: 32.735, lng: -96.275, distToAnchor: 18.2, schoolDist: "Terrell ISD", utilities: "None" },
      { id: "KF-005", address: "FM 741, Forney", acres: 6.1, price: 195000, ppa: 31967, daysOnMarket: 41, zoning: "Residential", etj: true, zip: "75126", lat: 32.751, lng: -96.445, distToAnchor: 5.0, schoolDist: "Forney ISD", utilities: "Water & Electric" },
    ]
  },
  "Waller County": {
    medianPPA: 24000, appreciation: 10.5, zips: ["77423", "77445", "77484"],
    catalysts: ["Brookshire Industrial Corridor", "I-10 Expansion", "Amazon Fulfillment Center"],
    color: "#F59E0B", riskScore: 7.2,
    listings: [
      { id: "WL-001", address: "FM 359, Brookshire", acres: 7.5, price: 127500, ppa: 17000, daysOnMarket: 55, zoning: "Agricultural", etj: false, zip: "77423", lat: 29.784, lng: -95.950, distToAnchor: 6.2, schoolDist: "Royal ISD", utilities: "Electric nearby" },
      { id: "WL-002", address: "US 290, Waller", acres: 4.0, price: 88000, ppa: 22000, daysOnMarket: 30, zoning: "AG/Residential", etj: true, zip: "77484", lat: 30.057, lng: -95.926, distToAnchor: 9.5, schoolDist: "Waller ISD", utilities: "Electric at road" },
      { id: "WL-003", address: "Cochran Rd, Hempstead", acres: 15.0, price: 225000, ppa: 15000, daysOnMarket: 78, zoning: "Agricultural", etj: false, zip: "77445", lat: 30.097, lng: -96.078, distToAnchor: 14.3, schoolDist: "Hempstead ISD", utilities: "None" },
    ]
  }
};

const WEIGHTS = {
  ppaDiscount: 0.30,
  appreciation: 0.20,
  etj: 0.10,
  daysOnMarket: 0.10,
  anchorProximity: 0.15,
  schoolDistrict: 0.08,
  utilities: 0.07,
};

const SCHOOL_SCORES = {
  "Red Oak ISD": 8, "Midlothian ISD": 9, "Waxahachie ISD": 7,
  "Community ISD": 5, "Royse City ISD": 8, "Forney ISD": 9, "Terrell ISD": 5,
  "Royal ISD": 5, "Waller ISD": 6, "Hempstead ISD": 4,
};

function scoreListing(listing, county) {
  const ppaDiscount = Math.max(0, Math.min(10, ((county.medianPPA - listing.ppa) / county.medianPPA) * 15));
  const appreciationScore = Math.min(10, county.appreciation / 1.5);
  const etjScore = listing.etj ? 8 : 3;
  const domScore = listing.daysOnMarket > 60 ? 9 : listing.daysOnMarket > 30 ? 6 : 3;
  const anchorScore = Math.max(0, Math.min(10, (20 - listing.distToAnchor) / 2));
  const schoolScore = (SCHOOL_SCORES[listing.schoolDist] || 5);
  const utilScore = listing.utilities === "All available" || listing.utilities === "All at road" ? 9 : listing.utilities === "Water & Electric" ? 7 : listing.utilities.includes("Electric") ? 5 : 2;

  const total = (
    ppaDiscount * WEIGHTS.ppaDiscount +
    appreciationScore * WEIGHTS.appreciation +
    etjScore * WEIGHTS.etj +
    domScore * WEIGHTS.daysOnMarket +
    anchorScore * WEIGHTS.anchorProximity +
    schoolScore * WEIGHTS.schoolDistrict +
    utilScore * WEIGHTS.utilities
  );

  return {
    total: Math.round(total * 10) / 10,
    breakdown: { ppaDiscount: Math.round(ppaDiscount*10)/10, appreciationScore: Math.round(appreciationScore*10)/10, etjScore, domScore, anchorScore: Math.round(anchorScore*10)/10, schoolScore, utilScore },
    tag: total >= 7.5 ? "STRIKE ZONE" : total >= 6 ? "WATCHLIST" : total >= 4.5 ? "MONITOR" : "PASS",
    tagColor: total >= 7.5 ? "#10B981" : total >= 6 ? "#F59E0B" : total >= 4.5 ? "#6B7280" : "#EF4444",
  };
}

function formatCurrency(n) { return "$" + n.toLocaleString(); }

// ── Mini chart component ──
function SparkBar({ values, max, color, height = 32 }) {
  const w = 100 / values.length;
  return (
    <svg viewBox={`0 0 100 ${height}`} style={{ width: "100%", height }}>
      {values.map((v, i) => {
        const h = (v / max) * height;
        return <rect key={i} x={i * w + 1} y={height - h} width={w - 2} height={h} rx={1} fill={color} opacity={0.6 + (i / values.length) * 0.4} />;
      })}
    </svg>
  );
}

// ── Weight slider ──
function WeightSlider({ label, value, onChange }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
      <span style={{ width: 130, fontSize: 11, color: "var(--muted)", fontFamily: "'JetBrains Mono', monospace" }}>{label}</span>
      <input type="range" min={0} max={50} value={Math.round(value * 100)} onChange={e => onChange(parseInt(e.target.value) / 100)}
        style={{ flex: 1, accentColor: "#10B981", height: 4 }} />
      <span style={{ width: 36, fontSize: 11, textAlign: "right", color: "#10B981", fontFamily: "'JetBrains Mono', monospace" }}>{Math.round(value * 100)}%</span>
    </div>
  );
}

// ── Deal Card ──
function DealCard({ listing, score, county, expanded, onToggle }) {
  const isPremium = score.tag === "STRIKE ZONE";
  return (
    <div onClick={onToggle} style={{
      background: isPremium ? "linear-gradient(135deg, rgba(16,185,129,0.08), rgba(16,185,129,0.02))" : "rgba(255,255,255,0.02)",
      border: `1px solid ${isPremium ? "rgba(16,185,129,0.3)" : "rgba(255,255,255,0.06)"}`,
      borderRadius: 10, padding: "14px 16px", cursor: "pointer",
      transition: "all 0.2s", marginBottom: 8,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: score.tagColor, background: `${score.tagColor}18`, padding: "2px 8px", borderRadius: 4, fontFamily: "'JetBrains Mono', monospace", letterSpacing: 0.5 }}>
              {score.tag}
            </span>
            <span style={{ fontSize: 11, color: "var(--muted)", fontFamily: "'JetBrains Mono', monospace" }}>{listing.id}</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>{listing.address}</div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>{listing.schoolDist} · {listing.zoning}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#10B981", fontFamily: "'JetBrains Mono', monospace" }}>{score.total}</div>
          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: -2 }}>/ 10</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap" }}>
        {[
          { label: "PRICE", value: formatCurrency(listing.price) },
          { label: "ACRES", value: listing.acres },
          { label: "$/ACRE", value: formatCurrency(listing.ppa) },
          { label: "DISCOUNT", value: `${Math.round((1 - listing.ppa / county.medianPPA) * 100)}%` },
          { label: "DOM", value: `${listing.daysOnMarket}d` },
          { label: "ETJ", value: listing.etj ? "YES" : "NO" },
        ].map(({ label, value }) => (
          <div key={label}>
            <div style={{ fontSize: 9, color: "var(--muted)", letterSpacing: 1, fontFamily: "'JetBrains Mono', monospace" }}>{label}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", fontFamily: "'JetBrains Mono', monospace" }}>{value}</div>
          </div>
        ))}
      </div>
      {expanded && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text)", marginBottom: 8, letterSpacing: 0.5 }}>SCORE BREAKDOWN</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 20px" }}>
            {[
              { label: "PPA Discount", val: score.breakdown.ppaDiscount, w: WEIGHTS.ppaDiscount },
              { label: "Appreciation", val: score.breakdown.appreciationScore, w: WEIGHTS.appreciation },
              { label: "ETJ Status", val: score.breakdown.etjScore, w: WEIGHTS.etj },
              { label: "Days on Market", val: score.breakdown.domScore, w: WEIGHTS.daysOnMarket },
              { label: "Anchor Proximity", val: score.breakdown.anchorScore, w: WEIGHTS.anchorProximity },
              { label: "School District", val: score.breakdown.schoolScore, w: WEIGHTS.schoolDistrict },
              { label: "Utilities", val: score.breakdown.utilScore, w: WEIGHTS.utilities },
            ].map(({ label, val, w }) => (
              <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>{label}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 50, height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ width: `${val * 10}%`, height: "100%", background: val >= 7 ? "#10B981" : val >= 5 ? "#F59E0B" : "#EF4444", borderRadius: 2 }} />
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text)", fontFamily: "'JetBrains Mono', monospace", width: 24, textAlign: "right" }}>{val}</span>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "rgba(59,130,246,0.1)", color: "#3B82F6", fontFamily: "'JetBrains Mono', monospace" }}>
              📍 {listing.distToAnchor}mi to anchor
            </span>
            <span style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "rgba(245,158,11,0.1)", color: "#F59E0B", fontFamily: "'JetBrains Mono', monospace" }}>
              ⚡ {listing.utilities}
            </span>
            <span style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: "rgba(16,185,129,0.1)", color: "#10B981", fontFamily: "'JetBrains Mono', monospace" }}>
              📈 {county.appreciation}% YoY
            </span>
          </div>
          <div style={{ marginTop: 10, padding: 10, background: "rgba(16,185,129,0.05)", borderRadius: 6, border: "1px solid rgba(16,185,129,0.1)" }}>
            <div style={{ fontSize: 10, color: "#10B981", fontWeight: 700, marginBottom: 4 }}>5-YEAR PROJECTION</div>
            <div style={{ fontSize: 12, color: "var(--text)", fontFamily: "'JetBrains Mono', monospace" }}>
              {formatCurrency(listing.price)} → {formatCurrency(Math.round(listing.price * Math.pow(1 + county.appreciation / 100, 5)))}
              <span style={{ color: "#10B981", marginLeft: 6 }}>+{formatCurrency(Math.round(listing.price * (Math.pow(1 + county.appreciation / 100, 5) - 1)))}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function LandAlphaAgent() {
  const [activeTab, setActiveTab] = useState("deals");
  const [selectedCounty, setSelectedCounty] = useState("all");
  const [weights, setWeights] = useState({ ...WEIGHTS });
  const [expandedCard, setExpandedCard] = useState(null);
  const [minScore, setMinScore] = useState(0);
  const [sortBy, setSortBy] = useState("score");
  const [alertConfig, setAlertConfig] = useState({ maxPrice: 200000, maxPPA: 35000, minAcres: 3, minScore: 6.0 });
  const [agentStatus, setAgentStatus] = useState("idle");
  const [lastScan, setLastScan] = useState(null);
  const [scanLog, setScanLog] = useState([]);

  // Build scored listings
  const allListings = [];
  Object.entries(COUNTIES).forEach(([name, county]) => {
    county.listings.forEach(l => {
      const score = scoreListing(l, county);
      allListings.push({ ...l, score, countyName: name, county });
    });
  });

  const filtered = allListings
    .filter(l => selectedCounty === "all" || l.countyName === selectedCounty)
    .filter(l => l.score.total >= minScore)
    .sort((a, b) => {
      if (sortBy === "score") return b.score.total - a.score.total;
      if (sortBy === "price") return a.price - b.price;
      if (sortBy === "ppa") return a.ppa - b.ppa;
      if (sortBy === "dom") return b.daysOnMarket - a.daysOnMarket;
      return 0;
    });

  const strikeZoneCount = allListings.filter(l => l.score.tag === "STRIKE ZONE").length;
  const watchlistCount = allListings.filter(l => l.score.tag === "WATCHLIST").length;
  const avgScore = allListings.length ? (allListings.reduce((s, l) => s + l.score.total, 0) / allListings.length).toFixed(1) : 0;

  const simulateScan = useCallback(() => {
    setAgentStatus("scanning");
    setScanLog(prev => [...prev, { time: new Date().toLocaleTimeString(), msg: "Initializing scan..." }]);
    const steps = [
      { delay: 600, msg: "Connecting to LandWatch API..." },
      { delay: 1200, msg: "Scraping Kaufman County (5 results)..." },
      { delay: 1800, msg: "Scraping Ellis County (4 results)..." },
      { delay: 2400, msg: "Scraping Waller County (3 results)..." },
      { delay: 3000, msg: "Running valuation engine..." },
      { delay: 3600, msg: "Applying deal filters..." },
      { delay: 4000, msg: `✅ Scan complete. ${strikeZoneCount} deals in Strike Zone.` },
    ];
    steps.forEach(({ delay, msg }) => {
      setTimeout(() => {
        setScanLog(prev => [...prev, { time: new Date().toLocaleTimeString(), msg }]);
        if (delay === 4000) {
          setAgentStatus("complete");
          setLastScan(new Date());
        }
      }, delay);
    });
  }, [strikeZoneCount]);

  const tabs = [
    { id: "deals", label: "Deal Flow", icon: "◆" },
    { id: "intel", label: "Market Intel", icon: "◉" },
    { id: "weights", label: "Scoring", icon: "⚖" },
    { id: "agent", label: "Agent", icon: "⚡" },
  ];

  return (
    <div style={{
      fontFamily: "'Outfit', sans-serif",
      background: "#0A0E17",
      color: "#E2E8F0",
      minHeight: "100vh",
      padding: 0,
      "--text": "#E2E8F0",
      "--muted": "#64748B",
      "--surface": "#111827",
      "--border": "rgba(255,255,255,0.06)",
    }}>
      <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet" />

      {/* Header */}
      <div style={{ padding: "20px 20px 0", borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ width: 10, height: 10, background: "#10B981", borderRadius: "50%", boxShadow: "0 0 12px rgba(16,185,129,0.5)" }} />
              <span style={{ fontSize: 20, fontWeight: 800, letterSpacing: -0.5, background: "linear-gradient(135deg, #10B981, #3B82F6)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                LAND ALPHA
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, fontFamily: "'JetBrains Mono', monospace" }}>
              DFW Land Banking Intelligence · v1.0
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: "#10B981", fontFamily: "'JetBrains Mono', monospace" }}>{strikeZoneCount}</div>
            <div style={{ fontSize: 9, color: "var(--muted)", letterSpacing: 1 }}>STRIKE ZONE</div>
          </div>
        </div>

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 16 }}>
          {[
            { label: "LISTINGS", value: allListings.length, color: "#E2E8F0" },
            { label: "WATCHLIST", value: watchlistCount, color: "#F59E0B" },
            { label: "AVG SCORE", value: avgScore, color: "#3B82F6" },
            { label: "COUNTIES", value: Object.keys(COUNTIES).length, color: "#8B5CF6" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ background: "var(--surface)", borderRadius: 8, padding: "10px 12px", border: "1px solid var(--border)" }}>
              <div style={{ fontSize: 18, fontWeight: 700, color, fontFamily: "'JetBrains Mono', monospace" }}>{value}</div>
              <div style={{ fontSize: 9, color: "var(--muted)", letterSpacing: 1 }}>{label}</div>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 0 }}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
              flex: 1, padding: "10px 0", background: "none", border: "none", cursor: "pointer",
              color: activeTab === t.id ? "#10B981" : "var(--muted)",
              borderBottom: activeTab === t.id ? "2px solid #10B981" : "2px solid transparent",
              fontSize: 12, fontWeight: 600, fontFamily: "'Outfit', sans-serif", transition: "all 0.2s",
            }}>
              <span style={{ marginRight: 4 }}>{t.icon}</span> {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: 20 }}>

        {/* ── DEALS TAB ── */}
        {activeTab === "deals" && (
          <div>
            {/* Filters */}
            <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
              <select value={selectedCounty} onChange={e => setSelectedCounty(e.target.value)}
                style={{ background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 10px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace" }}>
                <option value="all">All Counties</option>
                {Object.keys(COUNTIES).map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                style={{ background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 10px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace" }}>
                <option value="score">Sort: Score</option>
                <option value="price">Sort: Price ↑</option>
                <option value="ppa">Sort: $/Acre ↑</option>
                <option value="dom">Sort: DOM ↓</option>
              </select>
              <select value={minScore} onChange={e => setMinScore(parseFloat(e.target.value))}
                style={{ background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 6, padding: "6px 10px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace" }}>
                <option value={0}>Min: Any</option>
                <option value={4.5}>Min: 4.5+</option>
                <option value={6}>Min: 6.0+</option>
                <option value={7.5}>Min: 7.5+</option>
              </select>
            </div>

            {/* Listing Cards */}
            {filtered.map(l => (
              <DealCard key={l.id} listing={l} score={l.score} county={l.county}
                expanded={expandedCard === l.id} onToggle={() => setExpandedCard(expandedCard === l.id ? null : l.id)} />
            ))}
            {filtered.length === 0 && (
              <div style={{ textAlign: "center", padding: 40, color: "var(--muted)" }}>No listings match current filters</div>
            )}
          </div>
        )}

        {/* ── MARKET INTEL TAB ── */}
        {activeTab === "intel" && (
          <div>
            {Object.entries(COUNTIES).map(([name, county]) => {
              const countyListings = allListings.filter(l => l.countyName === name);
              const ppas = countyListings.map(l => l.ppa);
              return (
                <div key={name} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={{ width: 8, height: 8, borderRadius: "50%", background: county.color }} />
                        <span style={{ fontSize: 15, fontWeight: 700 }}>{name}</span>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{countyListings.length} active listings</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontSize: 11, color: "var(--muted)" }}>Risk Score</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: county.color, fontFamily: "'JetBrains Mono', monospace" }}>{county.riskScore}</div>
                    </div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 12 }}>
                    <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 6, padding: 10 }}>
                      <div style={{ fontSize: 9, color: "var(--muted)", letterSpacing: 1 }}>MEDIAN $/ACRE</div>
                      <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{formatCurrency(county.medianPPA)}</div>
                    </div>
                    <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 6, padding: 10 }}>
                      <div style={{ fontSize: 9, color: "var(--muted)", letterSpacing: 1 }}>APPRECIATION</div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: "#10B981", fontFamily: "'JetBrains Mono', monospace" }}>{county.appreciation}%</div>
                    </div>
                    <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 6, padding: 10 }}>
                      <div style={{ fontSize: 9, color: "var(--muted)", letterSpacing: 1 }}>TARGET ZIPS</div>
                      <div style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace", marginTop: 2 }}>{county.zips.length}</div>
                    </div>
                  </div>

                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 6, letterSpacing: 0.5 }}>PPA DISTRIBUTION</div>
                    <SparkBar values={ppas.sort((a, b) => a - b)} max={Math.max(...ppas)} color={county.color} height={28} />
                  </div>

                  <div style={{ fontSize: 10, fontWeight: 700, color: "var(--muted)", marginBottom: 6, letterSpacing: 0.5 }}>GROWTH CATALYSTS</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {county.catalysts.map(c => (
                      <span key={c} style={{ fontSize: 10, padding: "3px 8px", borderRadius: 4, background: `${county.color}15`, color: county.color, fontFamily: "'JetBrains Mono', monospace" }}>
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* ── SCORING TAB ── */}
        {activeTab === "weights" && (
          <div>
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Scoring Weights</div>
              <WeightSlider label="PPA Discount" value={weights.ppaDiscount} onChange={v => setWeights(w => ({ ...w, ppaDiscount: v }))} />
              <WeightSlider label="Appreciation" value={weights.appreciation} onChange={v => setWeights(w => ({ ...w, appreciation: v }))} />
              <WeightSlider label="ETJ Status" value={weights.etj} onChange={v => setWeights(w => ({ ...w, etj: v }))} />
              <WeightSlider label="Days on Market" value={weights.daysOnMarket} onChange={v => setWeights(w => ({ ...w, daysOnMarket: v }))} />
              <WeightSlider label="Anchor Proximity" value={weights.anchorProximity} onChange={v => setWeights(w => ({ ...w, anchorProximity: v }))} />
              <WeightSlider label="School District" value={weights.schoolDistrict} onChange={v => setWeights(w => ({ ...w, schoolDistrict: v }))} />
              <WeightSlider label="Utilities" value={weights.utilities} onChange={v => setWeights(w => ({ ...w, utilities: v }))} />
              <div style={{ marginTop: 8, fontSize: 11, color: Math.abs(Object.values(weights).reduce((a, b) => a + b, 0) - 1) < 0.02 ? "#10B981" : "#EF4444", fontFamily: "'JetBrains Mono', monospace" }}>
                Total: {Math.round(Object.values(weights).reduce((a, b) => a + b, 0) * 100)}%
                {Math.abs(Object.values(weights).reduce((a, b) => a + b, 0) - 1) >= 0.02 && " (should equal 100%)"}
              </div>
            </div>

            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Score Tier Definitions</div>
              {[
                { tag: "STRIKE ZONE", range: "7.5 – 10", color: "#10B981", desc: "Immediate action. Below-market PPA in high-growth corridor with infrastructure signals." },
                { tag: "WATCHLIST", range: "6.0 – 7.4", color: "#F59E0B", desc: "Strong fundamentals. Monitor for price drops or zoning changes." },
                { tag: "MONITOR", range: "4.5 – 5.9", color: "#6B7280", desc: "Decent land, missing 1-2 key criteria. Revisit quarterly." },
                { tag: "PASS", range: "0 – 4.4", color: "#EF4444", desc: "Overpriced, poor location, or missing critical infrastructure." },
              ].map(t => (
                <div key={t.tag} style={{ display: "flex", gap: 10, marginBottom: 10, alignItems: "flex-start" }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: t.color, background: `${t.color}18`, padding: "3px 8px", borderRadius: 4, fontFamily: "'JetBrains Mono', monospace", whiteSpace: "nowrap", marginTop: 1 }}>
                    {t.tag}
                  </span>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>{t.range}</div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{t.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── AGENT TAB ── */}
        {activeTab === "agent" && (
          <div>
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>Agent Status</div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: agentStatus === "scanning" ? "#F59E0B" : agentStatus === "complete" ? "#10B981" : "#64748B",
                    animation: agentStatus === "scanning" ? "pulse 1s infinite" : "none" }} />
                  <span style={{ fontSize: 11, color: "var(--muted)", fontFamily: "'JetBrains Mono', monospace", textTransform: "uppercase" }}>{agentStatus}</span>
                </div>
              </div>
              <button onClick={simulateScan} disabled={agentStatus === "scanning"}
                style={{
                  width: "100%", padding: "12px 0", background: agentStatus === "scanning" ? "rgba(245,158,11,0.15)" : "linear-gradient(135deg, #10B981, #059669)",
                  color: agentStatus === "scanning" ? "#F59E0B" : "#fff",
                  border: "none", borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: agentStatus === "scanning" ? "not-allowed" : "pointer",
                  fontFamily: "'Outfit', sans-serif", transition: "all 0.2s",
                }}>
                {agentStatus === "scanning" ? "⏳ Scanning..." : "▶ Run Manual Scan"}
              </button>
              {lastScan && (
                <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 8, fontFamily: "'JetBrains Mono', monospace" }}>
                  Last scan: {lastScan.toLocaleString()}
                </div>
              )}
            </div>

            {/* Scan Log */}
            {scanLog.length > 0 && (
              <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>Scan Log</div>
                <div style={{ maxHeight: 200, overflowY: "auto" }}>
                  {scanLog.map((log, i) => (
                    <div key={i} style={{ fontSize: 11, color: log.msg.startsWith("✅") ? "#10B981" : "var(--muted)", fontFamily: "'JetBrains Mono', monospace", marginBottom: 4 }}>
                      <span style={{ color: "#64748B", marginRight: 8 }}>{log.time}</span>{log.msg}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Alert Config */}
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 16, marginBottom: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>🔔 Alert Filters</div>
              {[
                { label: "Max Price", key: "maxPrice", prefix: "$" },
                { label: "Max $/Acre", key: "maxPPA", prefix: "$" },
                { label: "Min Acres", key: "minAcres", prefix: "" },
                { label: "Min Score", key: "minScore", prefix: "" },
              ].map(({ label, key, prefix }) => (
                <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>{label}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    {prefix && <span style={{ fontSize: 12, color: "var(--muted)" }}>{prefix}</span>}
                    <input type="number" value={alertConfig[key]}
                      onChange={e => setAlertConfig(prev => ({ ...prev, [key]: parseFloat(e.target.value) || 0 }))}
                      style={{ width: 90, background: "rgba(255,255,255,0.05)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 4, padding: "4px 8px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", textAlign: "right" }}
                    />
                  </div>
                </div>
              ))}
              <div style={{ marginTop: 12, padding: 10, background: "rgba(16,185,129,0.05)", borderRadius: 6, border: "1px solid rgba(16,185,129,0.1)" }}>
                <div style={{ fontSize: 10, color: "#10B981", fontWeight: 700, marginBottom: 4 }}>MATCHING DEALS</div>
                <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>
                  {allListings.filter(l =>
                    l.price <= alertConfig.maxPrice &&
                    l.ppa <= alertConfig.maxPPA &&
                    l.acres >= alertConfig.minAcres &&
                    l.score.total >= alertConfig.minScore
                  ).length} listings
                </div>
              </div>
            </div>

            {/* Pipeline Config */}
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>Pipeline Config</div>
              {[
                { label: "Schedule", value: "Daily @ 8:00 AM CST" },
                { label: "Sources", value: "LandWatch · Zillow · Redfin" },
                { label: "Target Counties", value: "Ellis · Kaufman · Waller" },
                { label: "Storage", value: "S3 (Bronze/Silver/Gold)" },
                { label: "Alerts", value: "Telegram Bot" },
              ].map(({ label, value }) => (
                <div key={label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>{label}</span>
                  <span style={{ fontSize: 11, color: "var(--text)", fontFamily: "'JetBrains Mono', monospace" }}>{value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        input[type=range] { -webkit-appearance: none; appearance: none; background: rgba(255,255,255,0.06); border-radius: 4px; }
        input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px; border-radius: 50%; background: #10B981; cursor: pointer; }
        select { outline: none; }
        select option { background: #111827; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
      `}</style>
    </div>
  );
}
