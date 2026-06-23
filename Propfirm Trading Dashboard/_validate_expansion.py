"""
One-off: validate candidate watchlist-expansion tickers against yfinance.
A ticker "passes" if weekly OHLCV returns >= 60 bars (enough for zone
detection + indicators on the weekly income strategy). Crypto is checked
on daily (it runs the 'daily' strategy only).

Outputs JSON: { passed: [...yaml-ready entries...], failed: [...] }
so we only add instruments the scanner can actually fetch.
"""
import json
import sys
import time
import warnings

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except Exception as e:  # pragma: no cover
    print(json.dumps({"error": f"yfinance import failed: {e}"}))
    sys.exit(1)

# (symbol, name, asset_class, extra_dict)
CANDIDATES = []

# ---- CRYPTO (daily strategy; -USD format) ----
_crypto = [
    ("TRX-USD", "TRXUSD"), ("ATOM-USD", "ATOMUSD"), ("ETC-USD", "ETCUSD"),
    ("XLM-USD", "XLMUSD"), ("ALGO-USD", "ALGOUSD"), ("FIL-USD", "FILUSD"),
    ("NEAR-USD", "NEARUSD"), ("APT-USD", "APTUSD"), ("ARB-USD", "ARBUSD"),
    ("OP-USD", "OPUSD"), ("INJ-USD", "INJUSD"), ("SUI-USD", "SUIUSD"),
    ("HBAR-USD", "HBARUSD"), ("VET-USD", "VETUSD"), ("ICP-USD", "ICPUSD"),
    ("AAVE-USD", "AAVEUSD"), ("MKR-USD", "MKRUSD"), ("GRT-USD", "GRTUSD"),
    ("SAND-USD", "SANDUSD"), ("MANA-USD", "MANAUSD"), ("AXS-USD", "AXSUSD"),
    ("RUNE-USD", "RUNEUSD"), ("FTM-USD", "FTMUSD"), ("XTZ-USD", "XTZUSD"),
    ("THETA-USD", "THETAUSD"), ("EOS-USD", "EOSUSD"), ("NEO-USD", "NEOUSD"),
    ("ZEC-USD", "ZECUSD"), ("DASH-USD", "DASHUSD"), ("CHZ-USD", "CHZUSD"),
    ("SHIB-USD", "SHIBUSD"), ("PEPE-USD", "PEPEUSD"), ("WIF-USD", "WIFUSD"),
    ("POL-USD", "POLUSD"), ("MATIC-USD", "MATICUSD"), ("UNI-USD", "UNIUSD"),
    ("LDO-USD", "LDOUSD"), ("STX-USD", "STXUSD"), ("IMX-USD", "IMXUSD"),
    ("RNDR-USD", "RNDRUSD"), ("TIA-USD", "TIAUSD"), ("SEI-USD", "SEIUSD"),
]
for s, n in _crypto:
    CANDIDATES.append((s, n, "crypto", {"strategies": ["daily"]}))

# ---- GLOBAL EQUITIES / ADRs ----
_equities = [
    # Europe ADRs
    ("SAP", "SAP (SAP SE)"), ("NVS", "NVS (Novartis)"), ("AZN", "AZN (AstraZeneca)"),
    ("SHEL", "SHEL (Shell)"), ("BP", "BP (BP plc)"), ("HSBC", "HSBC (HSBC)"),
    ("UL", "UL (Unilever)"), ("TTE", "TTE (TotalEnergies)"), ("SNY", "SNY (Sanofi)"),
    ("DEO", "DEO (Diageo)"), ("RIO", "RIO (Rio Tinto)"), ("BHP", "BHP (BHP Group)"),
    ("GSK", "GSK (GSK plc)"), ("BTI", "BTI (British Am Tobacco)"), ("ING", "ING (ING Groep)"),
    ("E", "E (Eni)"), ("STLA", "STLA (Stellantis)"), ("ABBV", "ABBV2 (dup-skip)"),
    ("PHG", "PHG (Philips)"), ("BUD", "BUD (AB InBev)"),
    # Asia ADRs
    ("TM", "TM (Toyota)"), ("SONY", "SONY (Sony)"), ("NIO", "NIO (NIO Inc)"),
    ("XPEV", "XPEV (XPeng)"), ("LI", "LI (Li Auto)"), ("BIDU", "BIDU (Baidu)"),
    ("NTES", "NTES (NetEase)"), ("TCOM", "TCOM (Trip.com)"), ("HMC", "HMC (Honda)"),
    ("MUFG", "MUFG (Mitsubishi UFJ)"), ("INFY", "INFY (Infosys)"), ("IBN", "IBN (ICICI Bank)"),
    ("HDB", "HDB (HDFC Bank)"), ("WIT", "WIT (Wipro)"),
    # US large/mid caps across sectors
    ("BRK-B", "BRK.B (Berkshire)"), ("PG", "PG (Procter & Gamble)"), ("HD", "HD (Home Depot)"),
    ("LOW", "LOW (Lowe's)"), ("TGT", "TGT (Target)"), ("CMCSA", "CMCSA (Comcast)"),
    ("NEE", "NEE (NextEra)"), ("DUK", "DUK (Duke Energy)"), ("SO", "SO (Southern Co)"),
    ("LIN", "LIN (Linde)"), ("APD", "APD (Air Products)"), ("SHW", "SHW (Sherwin-Williams)"),
    ("FCX", "FCX (Freeport)"), ("NEM", "NEM (Newmont)"), ("DE", "DE (Deere)"),
    ("UPS", "UPS (UPS)"), ("FDX", "FDX (FedEx)"), ("GD", "GD (General Dynamics)"),
    ("MMM", "MMM (3M)"), ("EMR", "EMR (Emerson)"), ("ETN", "ETN (Eaton)"),
    ("ITW", "ITW (Illinois Tool)"), ("TXN", "TXN (Texas Instr)"), ("ADI", "ADI (Analog Devices)"),
    ("MCHP", "MCHP (Microchip)"), ("KLAC", "KLAC (KLA Corp)"), ("LRCX", "LRCX (Lam Research)"),
    ("SNPS", "SNPS (Synopsys)"), ("CDNS", "CDNS (Cadence)"), ("NOW", "NOW (ServiceNow)"),
    ("INTU", "INTU (Intuit)"), ("PANW", "PANW (Palo Alto)"), ("FTNT", "FTNT (Fortinet)"),
    ("ZS", "ZS (Zscaler)"), ("NET", "NET (Cloudflare)"), ("SNOW", "SNOW (Snowflake)"),
    ("DDOG", "DDOG (Datadog)"), ("MDB", "MDB (MongoDB)"), ("RBLX", "RBLX (Roblox)"),
    ("U", "U (Unity)"), ("PINS", "PINS (Pinterest)"), ("SNAP", "SNAP (Snap)"),
    ("AFRM", "AFRM (Affirm)"), ("DASH", "DASH (DoorDash)"), ("RIVN", "RIVN (Rivian)"),
    ("LCID", "LCID (Lucid)"), ("F", "F (Ford)"), ("GM", "GM (General Motors)"),
    ("DAL", "DAL (Delta)"), ("UAL", "UAL (United Airlines)"), ("CCL", "CCL (Carnival)"),
]
for tup in _equities:
    s, n = tup
    CANDIDATES.append((s, n, "equities", {}))

# ---- EQUITY INDICES (more countries) ----
_indices = [
    ("^NSEI", "IN50 (Nifty 50)"), ("^BSESN", "INSENSEX (BSE Sensex)"),
    ("^BVSP", "BR (Bovespa)"), ("^GSPTSE", "CA60 (TSX)"),
    ("^KS11", "KR (KOSPI)"), ("^TWII", "TW (Taiwan)"),
    ("^MXX", "MX (IPC Mexico)"), ("^STI", "SG (Straits Times)"),
    ("^JKSE", "ID (Jakarta)"), ("^AORD", "AU-ORD (All Ordinaries)"),
]
for s, n in _indices:
    CANDIDATES.append((s, n, "equity_indices", {}))

# ---- FOREX EXOTICS / extra crosses ----
_forex = [
    ("USDDKK=X", "USDDKK"), ("USDHUF=X", "USDHUF"), ("USDCZK=X", "USDCZK"),
    ("USDINR=X", "USDINR"), ("USDCNH=X", "USDCNH"), ("USDTHB=X", "USDTHB"),
    ("EURTRY=X", "EURTRY"), ("EURPLN=X", "EURPLN"), ("EURHUF=X", "EURHUF"),
    ("EURNOK=X", "EURNOK"), ("EURSEK=X", "EURSEK"), ("GBPSEK=X", "GBPSEK"),
]
for s, n in _forex:
    CANDIDATES.append((s, n, "forex", {}))


def check(symbol, asset_class):
    interval = "1d" if asset_class == "crypto" else "1wk"
    period = "729d" if asset_class == "crypto" else "10y"
    min_bars = 120 if asset_class == "crypto" else 60
    try:
        df = yf.download(
            symbol, interval=interval, period=period,
            progress=False, auto_adjust=True, threads=False,
        )
        n = 0 if df is None else len(df.dropna())
        return n >= min_bars, n
    except Exception as e:
        return False, f"err:{e}"


passed, failed = [], []
seen = set()
for symbol, name, ac, extra in CANDIDATES:
    if symbol in seen:
        continue
    seen.add(symbol)
    ok, bars = check(symbol, ac)
    rec = {"symbol": symbol, "name": name, "asset_class": ac, "bars": bars, "extra": extra}
    (passed if ok else failed).append(rec)
    print(f"{'OK ' if ok else 'XX '} {symbol:14s} {ac:15s} bars={bars}", file=sys.stderr, flush=True)
    time.sleep(0.25)

out = {
    "passed_count": len(passed),
    "failed_count": len(failed),
    "passed": passed,
    "failed": [f["symbol"] for f in failed],
}
with open("_validate_expansion_result.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print(json.dumps({"passed_count": len(passed), "failed_count": len(failed)}))
