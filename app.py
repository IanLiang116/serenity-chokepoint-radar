from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
import streamlit as st

import scanner


APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "data" / "serenity_universe.csv"
AUTO_SCAN_FILE = APP_DIR / "data" / "auto_scan_results.csv"
CACHE_DIR = APP_DIR / ".serenity_cache"
CACHE_DIR.mkdir(exist_ok=True)

DEFAULT_SOURCES = [
    "https://semiconstocks.com/",
    "https://twiscan.com/en/x/aleabitoreddit",
    "https://www.sotwe.com/aleabitoreddit",
]

KEYWORD_WEIGHTS = {
    "chokepoint": 10,
    "bottleneck": 10,
    "supply shortage": 9,
    "shortage": 7,
    "CPO": 8,
    "co-packaged": 8,
    "silicon photonics": 8,
    "SiPh": 8,
    "InP": 8,
    "indium phosphide": 8,
    "CW laser": 8,
    "800V": 7,
    "GaN": 6,
    "SiC": 6,
    "CHIPS Act": 6,
    "NASDAQ Listing": 6,
    "MSCI": 5,
    "qualification order": 6,
    "backlog": 5,
    "dilution": -10,
    "ATM": -8,
    "offering": -6,
}


@dataclass
class PriceSnapshot:
    price: float | None
    change_pct: float | None
    volume: int | None
    market_cap: float | None


def load_universe() -> pd.DataFrame:
    df = pd.read_csv(DATA_FILE)
    numeric_cols = [
        "chokepoint_strength",
        "scarcity",
        "vertical_integration",
        "catalyst_strength",
        "institutional_front_run",
        "risk_level",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def serenity_score(row: pd.Series) -> float:
    raw = (
        row["chokepoint_strength"] * 24
        + row["scarcity"] * 20
        + row["vertical_integration"] * 14
        + row["catalyst_strength"] * 18
        + row["institutional_front_run"] * 14
        - row["risk_level"] * 10
    )
    if str(row.get("status", "")).lower() == "flipped":
        raw -= 25
    if str(row.get("status", "")).lower() == "scenario":
        raw -= 20
    return max(0, min(100, round(raw / 4.0, 1)))


def action_band(score: float, risk: float) -> str:
    if score >= 75 and risk <= 4:
        return "核心觀察"
    if score >= 65:
        return "高波動觀察"
    if score >= 50:
        return "等待催化"
    if score >= 35:
        return "僅追蹤"
    return "避開 / 僅作情境工具"


@st.cache_data(ttl=900, show_spinner=False)
def fetch_yahoo_snapshot(ticker: str) -> PriceSnapshot:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": "5d", "interval": "1d"}
    try:
        r = requests.get(url, params=params, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = None
        if price and prev:
            change = (price / prev - 1) * 100
        return PriceSnapshot(
            price=float(price) if price is not None else None,
            change_pct=float(change) if change is not None else None,
            volume=meta.get("regularMarketVolume"),
            market_cap=meta.get("marketCap"),
        )
    except Exception:
        return PriceSnapshot(None, None, None, None)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_yahoo_history(ticker: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": "3mo", "interval": "1d"}
    try:
        r = requests.get(url, params=params, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        rows = []
        for ts, close in zip(timestamps, closes):
            if close is not None:
                rows.append({"date": datetime.fromtimestamp(ts).date(), "close": close})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["date", "close"])


def load_text_from_url(url: str) -> str:
    cache_name = re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_")[:80] + ".txt"
    cache_file = CACHE_DIR / cache_name
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        text = r.text[:400_000]
        cache_file.write_text(text, encoding="utf-8")
        return text
    except Exception:
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8", errors="ignore")
        return ""


def extract_ticker_mentions(text: str, known_tickers: Iterable[str] = ()) -> dict[str, dict[str, int | str]]:
    mentions: dict[str, dict[str, int | str]] = {}
    patterns = [(m.group(1), m.start(), m.end()) for m in re.finditer(r"\$([A-Z][A-Z0-9.\-]{1,9})\b", text)]
    for ticker in known_tickers:
        escaped = re.escape(ticker)
        for match in re.finditer(rf"(?<![A-Z0-9.$]){escaped}(?![A-Z0-9.\-])", text, flags=re.IGNORECASE):
            patterns.append((ticker.upper(), match.start(), match.end()))

    for ticker, start_i, end_i in patterns:
        ticker = ticker.replace("$", "").upper()
        start = max(0, start_i - 260)
        end = min(len(text), end_i + 260)
        window = re.sub(r"\s+", " ", text[start:end])
        score = 0
        for keyword, weight in KEYWORD_WEIGHTS.items():
            if keyword.lower() in window.lower():
                score += weight
        current = mentions.setdefault(ticker, {"count": 0, "keyword_score": 0, "context": ""})
        current["count"] = int(current["count"]) + 1
        current["keyword_score"] = int(current["keyword_score"]) + score
        if not current["context"]:
            current["context"] = window[:300]
    return mentions


def scan_sources(urls: Iterable[str], known_tickers: Iterable[str] = ()) -> pd.DataFrame:
    combined: dict[str, dict[str, int | str]] = {}
    for url in urls:
        text = load_text_from_url(url)
        for ticker, item in extract_ticker_mentions(text, known_tickers).items():
            current = combined.setdefault(
                ticker,
                {"mentions": 0, "keyword_score": 0, "sources": set(), "context": ""},
            )
            current["mentions"] = int(current["mentions"]) + int(item["count"])
            current["keyword_score"] = int(current["keyword_score"]) + int(item["keyword_score"])
            current["sources"].add(url)
            if not current["context"]:
                current["context"] = str(item["context"])

    rows = []
    for ticker, item in combined.items():
        rows.append(
            {
                "ticker": ticker,
                "mentions": item["mentions"],
                "keyword_score": item["keyword_score"],
                "sources": ", ".join(sorted(item["sources"])),
                "context": item["context"],
            }
        )
    if not rows:
        return pd.DataFrame(columns=["ticker", "mentions", "keyword_score", "sources", "context"])
    return pd.DataFrame(rows).sort_values(["keyword_score", "mentions"], ascending=False)


def format_money(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    return f"{value:,.2f}"


def format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:+.2f}%"


def render_methodology() -> None:
    st.subheader("Serenity 風格邏輯")
    st.markdown(
        """
這個雷達把 Serenity 公開展現出的 chokepoint 研究方法，整理成可重複的流程。

1. 從已確認的大需求開始：AI data center、CPO、silicon photonics、800V power、散熱、advanced packaging。
2. 往上游拆供應鏈，找出難以替代的供應商。
3. 優先找物理卡點：substrate、laser、optical engine、testing、packaging、power、cooling、specialty materials。
4. 尋找催化：qualification order、產能擴張、CHIPS Act、backlog、新廠、指數納入或上市事件。
5. 風險扣分：dilution、ATM offering、資產負債表弱、下市風險、過度擁擠的大型股交易。

V1 是 Serenity 已知標的雷達。V2 新增自動掃描器，會用同樣邏輯去更大的候選池裡找新標的。
        """
    )
    st.info("這是研究工具，只用來找值得深入研究的候選股，不是買賣建議。")


def render_auto_scan(universe: pd.DataFrame) -> None:
    st.subheader("自動掃描器：尋找新的 Serenity-like 候選股")
    st.write(
        "這個掃描器會檢查更廣的候選池，包含 photonics、功率半導體、advanced packaging、"
        "半導體測試、data-center power/cooling、specialty materials。它會讀公開公司描述與 Yahoo 新聞摘要，"
        "再列出命中的關鍵字證據。"
    )
    limit = st.slider("掃描數量", 5, 60, 25, 5)
    col_a, col_b = st.columns([1, 3])
    with col_a:
        run_auto = st.button("執行自動掃描")
    with col_b:
        st.caption(f"候選池檔案：{scanner.CANDIDATE_FILE}")

    if run_auto:
        with st.spinner("正在掃描公開公司資料與新聞..."):
            result = scanner.run_auto_scan(limit=limit)
        st.success(f"掃描完成：{len(result)} 個候選股")
    elif AUTO_SCAN_FILE.exists():
        result = pd.read_csv(AUTO_SCAN_FILE)
    else:
        result = pd.DataFrame()

    if result.empty:
        st.caption("目前還沒有自動掃描結果。請按「執行自動掃描」。")
        return

    known = set(universe["ticker"].astype(str).str.upper())
    result = result.copy()
    result["already_in_serenity_pool"] = result["ticker"].astype(str).str.upper().isin(known)
    display_cols = [
        "ticker",
        "name",
        "theme",
        "serenity_like_score",
        "chokepoint_strength",
        "scarcity",
        "catalyst_strength",
        "institutional_front_run",
        "risk_level",
        "positive_hits",
        "negative_hits",
        "already_in_serenity_pool",
    ]
    st.dataframe(result[display_cols].head(80), use_container_width=True, hide_index=True)

    selected = st.selectbox("查看自動掃描候選股", result["ticker"].tolist())
    row = result[result["ticker"] == selected].iloc[0]
    st.markdown(f"### {row['ticker']} - {row['name']}")
    st.write(f"主題：{row.get('theme', '-')}")
    st.write(f"市值：{format_money(row.get('market_cap'))}")
    st.write(f"正面證據：{row.get('positive_hits') or '-'}")
    st.write(f"風險證據：{row.get('negative_hits') or '-'}")
    st.write(row.get("evidence") or "沒有抓到公司描述證據。")
    if row.get("news_evidence"):
        st.caption(row.get("news_evidence"))


def main() -> None:
    st.set_page_config(page_title="Serenity Chokepoint Radar", layout="wide")
    st.title("Serenity Chokepoint Radar")
    st.caption("用 Serenity 風格的 AI 供應鏈卡點邏輯，尋找值得關注的候選股。")

    universe = load_universe()
    universe["serenity_score"] = universe.apply(serenity_score, axis=1)
    universe["action"] = universe.apply(lambda r: action_band(r["serenity_score"], r["risk_level"]), axis=1)

    with st.sidebar:
        st.header("篩選")
        categories = ["全部"] + sorted(universe["category"].unique().tolist())
        category = st.selectbox("類別", categories)
        min_score = st.slider("最低 Serenity 分數", 0, 100, 45)
        hide_scenario = st.checkbox("隱藏槓桿 / 情境工具", value=True)
        st.divider()
        st.header("手動來源掃描")
        source_text = st.text_area("URL，一行一個", "\n".join(DEFAULT_SOURCES), height=120)
        run_scan = st.button("掃描貼上的來源")

    filtered = universe.copy()
    if category != "全部":
        filtered = filtered[filtered["category"] == category]
    if hide_scenario:
        filtered = filtered[filtered["status"].str.lower() != "scenario"]
    filtered = filtered[filtered["serenity_score"] >= min_score].sort_values("serenity_score", ascending=False)

    top = filtered.head(5)
    cols = st.columns(5)
    for col, (_, row) in zip(cols, top.iterrows()):
        snap = fetch_yahoo_snapshot(row["ticker"])
        col.metric(row["ticker"], f"{row['serenity_score']:.1f}", delta=format_pct(snap.change_pct), help=row["thesis"])

    tab_radar, tab_auto, tab_manual, tab_detail, tab_method = st.tabs(
        ["已知雷達", "自動掃描", "手動掃描", "標的細節", "方法論"]
    )

    with tab_radar:
        table = filtered[
            [
                "ticker",
                "name",
                "category",
                "layer",
                "conviction",
                "status",
                "serenity_score",
                "risk_level",
                "action",
                "thesis",
            ]
        ].copy()
        st.dataframe(table, use_container_width=True, hide_index=True)

    with tab_auto:
        render_auto_scan(universe)

    with tab_manual:
        st.write("貼上公開網頁，系統會掃描 ticker 與 Serenity 風格關鍵字。")
        if run_scan:
            urls = [line.strip() for line in source_text.splitlines() if line.strip()]
            known_full = set(universe["ticker"].str.upper())
            known_short = set(universe["ticker"].str.replace(r"\..*$", "", regex=True).str.upper())
            scan = scan_sources(urls, known_full | known_short)
            known = known_full | known_short
            if scan.empty:
                st.warning("沒有找到 ticker。來源可能阻擋抓取，或需要登入。")
            else:
                scan["known_in_universe"] = scan["ticker"].str.upper().isin(known)
                st.dataframe(scan.head(80), use_container_width=True, hide_index=True)
        else:
            st.caption("按「掃描貼上的來源」後，才會讀取公開頁面。")

    with tab_detail:
        selected = st.selectbox("選擇標的", filtered["ticker"].tolist() if not filtered.empty else universe["ticker"].tolist())
        row = universe[universe["ticker"] == selected].iloc[0]
        left, right = st.columns([1, 2])
        snap = fetch_yahoo_snapshot(selected)
        with left:
            st.metric("Serenity 分數", f"{serenity_score(row):.1f}")
            st.metric("價格", format_money(snap.price), format_pct(snap.change_pct))
            st.metric("市值", format_money(snap.market_cap))
            st.write(f"行動分類：{action_band(serenity_score(row), row['risk_level'])}")
            st.write(f"風險：{int(row['risk_level'])}/5")
        with right:
            st.subheader(row["name"])
            st.write(row["thesis"])
            chart = fetch_yahoo_history(selected)
            if not chart.empty:
                st.line_chart(chart.set_index("date")["close"])
            else:
                st.warning("Yahoo Finance 沒有回傳這個 ticker 的歷史價格。")

    with tab_method:
        render_methodology()
        st.subheader("檔案")
        st.write(f"已知 Serenity universe：{DATA_FILE}")
        st.write(f"自動掃描候選池：{scanner.CANDIDATE_FILE}")
        st.write(f"自動掃描輸出：{AUTO_SCAN_FILE}")


if __name__ == "__main__":
    main()
