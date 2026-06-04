from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CANDIDATE_FILE = DATA_DIR / "auto_scan_candidates.csv"
OUTPUT_FILE = DATA_DIR / "auto_scan_results.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 SerenityRadar/2.0"}

POSITIVE_KEYWORDS = {
    "chokepoint": 12,
    "bottleneck": 12,
    "capacity constrained": 11,
    "shortage": 8,
    "sole supplier": 12,
    "only supplier": 12,
    "qualification": 9,
    "qualified": 7,
    "backlog": 7,
    "long-term agreement": 7,
    "supply agreement": 7,
    "data center": 6,
    "hyperscale": 7,
    "hyperscaler": 7,
    "ai infrastructure": 8,
    "artificial intelligence": 5,
    "cpo": 10,
    "co-packaged": 10,
    "silicon photonics": 10,
    "photonic": 8,
    "optical interconnect": 9,
    "optical engine": 9,
    "transceiver": 8,
    "laser": 7,
    "cw laser": 10,
    "inp": 10,
    "indium phosphide": 10,
    "gan": 8,
    "sic": 8,
    "silicon carbide": 8,
    "800v": 8,
    "power module": 7,
    "advanced packaging": 8,
    "chiplet": 7,
    "hbm": 6,
    "probe card": 7,
    "test equipment": 7,
    "metrology": 6,
    "thermal": 6,
    "liquid cooling": 8,
    "cooling": 5,
    "substrate": 7,
    "wafer": 6,
    "specialty foundry": 8,
    "specialty materials": 8,
    "chips act": 8,
    "expansion": 5,
    "new facility": 6,
}

NEGATIVE_KEYWORDS = {
    "dilution": 12,
    "atm offering": 12,
    "offering": 8,
    "going concern": 12,
    "restructuring": 8,
    "delisting": 12,
    "bankruptcy": 14,
    "impairment": 8,
    "layoff": 5,
    "lawsuit": 6,
}


def load_candidates(path: Path = CANDIDATE_FILE) -> pd.DataFrame:
    return pd.read_csv(path)


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def yahoo_quote(tickers: Iterable[str]) -> dict[str, dict]:
    symbols = ",".join(tickers)
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    try:
        r = requests.get(url, params={"symbols": symbols}, headers=HEADERS, timeout=12)
        r.raise_for_status()
        rows = r.json().get("quoteResponse", {}).get("result", [])
        return {row.get("symbol", "").upper(): row for row in rows if row.get("symbol")}
    except Exception:
        return {}


def yahoo_search(symbol: str) -> dict:
    url = "https://query1.finance.yahoo.com/v1/finance/search"
    try:
        r = requests.get(
            url,
            params={"q": symbol, "quotesCount": 1, "newsCount": 6, "enableFuzzyQuery": "false"},
            headers=HEADERS,
            timeout=12,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def yahoo_profile(symbol: str) -> dict:
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    try:
        r = requests.get(
            url,
            params={"modules": "assetProfile,summaryProfile,price,defaultKeyStatistics,financialData"},
            headers=HEADERS,
            timeout=12,
        )
        r.raise_for_status()
        result = r.json().get("quoteSummary", {}).get("result") or []
        return result[0] if result else {}
    except Exception:
        return {}


def raw_value(obj: object) -> object:
    if isinstance(obj, dict) and "raw" in obj:
        return obj["raw"]
    return obj


def score_text(text: str) -> tuple[int, int, list[str], list[str]]:
    lower = text.lower()
    positive_hits = []
    negative_hits = []
    positive_score = 0
    negative_score = 0
    for keyword, weight in POSITIVE_KEYWORDS.items():
        if keyword_present(lower, keyword):
            positive_hits.append(keyword)
            positive_score += weight
    for keyword, weight in NEGATIVE_KEYWORDS.items():
        if keyword_present(lower, keyword):
            negative_hits.append(keyword)
            negative_score += weight
    return positive_score, negative_score, positive_hits, negative_hits


def keyword_present(lower_text: str, keyword: str) -> bool:
    keyword_lower = keyword.lower()
    if re.fullmatch(r"[a-z0-9]{2,4}", keyword_lower):
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword_lower)}(?![a-z0-9])", lower_text) is not None
    return keyword_lower in lower_text


def any_keyword(lower_text: str, keywords: Iterable[str]) -> bool:
    return any(keyword_present(lower_text, keyword) for keyword in keywords)


def infer_factor_scores(text: str, market_cap: float | None) -> dict[str, int]:
    lower = text.lower()

    chokepoint = 1
    if any_keyword(lower, ["chokepoint", "bottleneck", "cpo", "silicon photonics", "inp", "cw laser"]):
        chokepoint += 3
    if any_keyword(lower, ["gan", "sic", "advanced packaging", "probe card", "liquid cooling", "metrology"]):
        chokepoint += 2

    scarcity = 1
    if any_keyword(lower, ["sole supplier", "only supplier", "capacity constrained", "shortage", "qualification"]):
        scarcity += 3
    if any_keyword(lower, ["specialty", "substrate", "wafer", "foundry", "backlog"]):
        scarcity += 2

    vertical = 1
    if any_keyword(lower, ["vertically integrated", "manufactures", "designs", "fabricates"]):
        vertical += 3
    if any_keyword(lower, ["materials", "components", "modules", "systems"]):
        vertical += 1

    catalyst = 1
    if any_keyword(lower, ["chips act", "expansion", "new facility", "supply agreement", "qualification", "backlog"]):
        catalyst += 3
    if any_keyword(lower, ["ai", "data center", "hyperscale", "nvidia"]):
        catalyst += 1

    front_run = 2
    if market_cap:
        if market_cap < 750_000_000:
            front_run = 5
        elif market_cap < 3_000_000_000:
            front_run = 4
        elif market_cap < 10_000_000_000:
            front_run = 3
        elif market_cap > 50_000_000_000:
            front_run = 1

    risk = 2
    if any_keyword(lower, ["dilution", "atm offering", "going concern", "delisting", "bankruptcy"]):
        risk += 3
    elif any_keyword(lower, ["offering", "restructuring", "impairment", "lawsuit"]):
        risk += 2
    if market_cap and market_cap < 500_000_000:
        risk += 1

    return {
        "chokepoint_strength": min(5, chokepoint),
        "scarcity": min(5, scarcity),
        "vertical_integration": min(5, vertical),
        "catalyst_strength": min(5, catalyst),
        "institutional_front_run": min(5, front_run),
        "risk_level": min(5, risk),
    }


def serenity_like_score(factors: dict[str, int]) -> float:
    raw = (
        factors["chokepoint_strength"] * 24
        + factors["scarcity"] * 20
        + factors["vertical_integration"] * 14
        + factors["catalyst_strength"] * 18
        + factors["institutional_front_run"] * 14
        - factors["risk_level"] * 10
    )
    return max(0, min(100, round(raw / 4.0, 1)))


def scan_candidate(row: pd.Series, quote_map: dict[str, dict]) -> dict:
    ticker = str(row["ticker"]).strip()
    symbol_key = ticker.upper()
    quote = quote_map.get(symbol_key, {})
    search = yahoo_search(ticker)
    profile = yahoo_profile(ticker)

    asset_profile = profile.get("assetProfile") or profile.get("summaryProfile") or {}
    description = clean_text(asset_profile.get("longBusinessSummary"))
    sector = clean_text(asset_profile.get("sector") or quote.get("sector"))
    industry = clean_text(asset_profile.get("industry") or quote.get("industry"))

    news_rows = []
    for item in search.get("news", [])[:6]:
        title = clean_text(item.get("title"))
        publisher = clean_text(item.get("publisher"))
        link = clean_text(item.get("link"))
        news_rows.append(f"{title} {publisher} {link}")

    text = " ".join(
        [
            clean_text(row.get("name")),
            clean_text(row.get("theme")),
            sector,
            industry,
            description,
            " ".join(news_rows),
        ]
    )
    positive_score, negative_score, positive_hits, negative_hits = score_text(text)

    market_cap = raw_value((profile.get("price") or {}).get("marketCap")) or quote.get("marketCap")
    try:
        market_cap = float(market_cap) if market_cap else None
    except Exception:
        market_cap = None

    factors = infer_factor_scores(text, market_cap)
    base_score = serenity_like_score(factors)
    keyword_adjustment = min(18, positive_score / 5) - min(16, negative_score / 3)
    final_score = max(0, min(100, round(base_score + keyword_adjustment, 1)))

    return {
        "scan_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ticker": ticker,
        "name": clean_text(row.get("name")) or quote.get("shortName") or ticker,
        "theme": clean_text(row.get("theme")),
        "region": clean_text(row.get("region")),
        "sector": sector,
        "industry": industry,
        "market_cap": market_cap,
        "serenity_like_score": final_score,
        **factors,
        "positive_hits": ", ".join(positive_hits[:12]),
        "negative_hits": ", ".join(negative_hits[:8]),
        "evidence": description[:500],
        "news_evidence": " | ".join(news_rows[:3])[:700],
    }


def run_auto_scan(limit: int | None = None, output_file: Path = OUTPUT_FILE) -> pd.DataFrame:
    candidates = load_candidates()
    if limit:
        candidates = candidates.head(limit)
    quote_map = yahoo_quote(candidates["ticker"].astype(str).tolist())
    rows = [scan_candidate(row, quote_map) for _, row in candidates.iterrows()]
    result = pd.DataFrame(rows).sort_values("serenity_like_score", ascending=False)
    output_file.parent.mkdir(exist_ok=True)
    result.to_csv(output_file, index=False)
    return result


if __name__ == "__main__":
    df = run_auto_scan()
    print(df[["ticker", "name", "serenity_like_score", "positive_hits", "negative_hits"]].head(20).to_string(index=False))
