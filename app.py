from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
import streamlit as st

import market_health
import scanner
import strategy


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


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .main .block-container { padding-top: 1.2rem; max-width: 1280px; }
        h1, h2, h3 { letter-spacing: 0; }
        .status-band {
            border-left: 5px solid #2563eb;
            padding: 0.85rem 1rem;
            background: #f8fafc;
            margin: 0.5rem 0 1rem;
        }
        .factor-note {
            font-size: 0.92rem;
            color: #475569;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    status = str(row.get("status", "")).lower()
    if status == "flipped":
        raw -= 25
    if status == "scenario":
        raw -= 20
    return max(0, min(100, round(raw / 4.0, 1)))


def action_band(score: float, risk: float) -> str:
    if score >= 75 and risk <= 4:
        return "核心觀察 / 可積極研究"
    if score >= 65:
        return "偏強候選 / 等回檔"
    if score >= 50:
        return "觀察清單 / 等催化"
    if score >= 35:
        return "保守追蹤"
    return "避開 / 風險優先"


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
        change = (price / prev - 1) * 100 if price and prev else None
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
    params = {"range": "6mo", "interval": "1d"}
    try:
        r = requests.get(url, params=params, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        rows = []
        for ts, close in zip(timestamps, closes):
            if close is not None:
                rows.append({"date": datetime.fromtimestamp(ts), "close": close})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["date", "close"])


@st.cache_data(ttl=600, show_spinner=False)
def cached_market_prices() -> pd.DataFrame:
    return market_health.load_market_prices()


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
    combined: dict[str, dict[str, int | str | set[str]]] = {}
    for url in urls:
        text = load_text_from_url(url)
        for ticker, item in extract_ticker_mentions(text, known_tickers).items():
            current = combined.setdefault(
                ticker,
                {"mentions": 0, "keyword_score": 0, "sources": set(), "context": ""},
            )
            current["mentions"] = int(current["mentions"]) + int(item["count"])
            current["keyword_score"] = int(current["keyword_score"]) + int(item["keyword_score"])
            assert isinstance(current["sources"], set)
            current["sources"].add(url)
            if not current["context"]:
                current["context"] = str(item["context"])

    rows = []
    for ticker, item in combined.items():
        sources = item["sources"]
        rows.append(
            {
                "ticker": ticker,
                "mentions": item["mentions"],
                "keyword_score": item["keyword_score"],
                "sources": ", ".join(sorted(sources)) if isinstance(sources, set) else "",
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


def render_market_health() -> None:
    st.subheader("即時市場健康指數")
    st.caption("用人體健康模型分析金融市場：流動性像血液，波動率像血壓，信用槓桿像慢性病，趨勢像肌肉力量。")

    if st.button("重新抓取市場資料"):
        cached_market_prices.clear()

    prices = cached_market_prices()
    factors, diagnosis = market_health.score_market_health(prices)
    playbook = market_health.scenario_playbook(diagnosis, factors)

    m1, m2, m3 = st.columns([1, 1, 2])
    m1.metric("MHI 市場健康指數", f"{diagnosis.score:.1f}/100")
    m2.metric("市場狀態", diagnosis.regime)
    m3.markdown(
        f"""
        <div class="status-band">
        <strong>操作姿態：</strong>{diagnosis.posture}<br>
        <span class="factor-note">{diagnosis.explanation}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.15, 1])
    with left:
        chart_data = factors.set_index("label")["score"] if not factors.empty else pd.Series(dtype=float)
        st.bar_chart(chart_data, height=330)
    with right:
        st.dataframe(
            factors[["label", "score", "diagnosis", "signal"]],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("情境拆解與交易應對")
    st.dataframe(playbook, use_container_width=True, hide_index=True)

    st.subheader("市場代理指標")
    snapshot = market_health.latest_snapshot(prices)
    if snapshot.empty:
        st.warning("目前無法取得 Yahoo Finance 市場資料，請稍後重試或確認網路。")
    else:
        display = snapshot.copy()
        for col in ["1d", "1m", "3m"]:
            display[col] = display[col].map(lambda x: market_health.pct(x))
        display["latest"] = display["latest"].map(lambda x: f"{x:,.2f}")
        st.dataframe(display, use_container_width=True, hide_index=True)

    with st.expander("模型權重與限制"):
        st.dataframe(market_health.factor_weights_frame(), use_container_width=True, hide_index=True)
        st.write(
            "估值、信用與景氣使用 ETF/指數代理資料，適合做即時風險儀表板；正式交易仍應搭配財報、利率、信用利差、部位大小與停損規則。"
        )
        st.caption(f"資料時間：{market_health.data_timestamp(prices)}")


def render_momentum_strategy() -> None:
    st.subheader("月線動能策略")
    st.caption("以 QQQ、SPY、SHY 做 12 個月相對動能。這是規則型參考，不是保證獲利。")
    if st.button("更新動能策略"):
        with st.spinner("抓取 Yahoo 調整收盤價並重新回測..."):
            signals, stats, signal = strategy.run(write=True)
    else:
        try:
            signals, stats, signal = strategy.run(write=False)
        except Exception as exc:
            st.error(f"策略資料取得失敗：{exc}")
            return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最新訊號月份", str(signal["signal_date"]))
    c2.metric("建議持有", str(signal["recommended_holding"]))
    c3.metric("QQQ 12M", f"{float(signal['qqq_12m_return']):.2%}")
    c4.metric("SPY 12M", f"{float(signal['spy_12m_return']):.2%}")

    stats_df = pd.DataFrame(
        [
            {
                "策略": item.name,
                "CAGR": f"{item.cagr:.2%}",
                "波動": f"{item.volatility:.2%}",
                "Sharpe": f"{item.sharpe:.2f}",
                "最大回撤": f"{item.max_drawdown:.2%}",
                "$1 成長": f"{item.growth_multiple:.2f}x",
            }
            for item in stats
        ]
    )
    st.dataframe(stats_df, use_container_width=True, hide_index=True)
    st.line_chart(
        signals.tail(48).set_index("holding_month")["strategy_return"],
        height=260,
    )


def render_serenity_radar(universe: pd.DataFrame, filtered: pd.DataFrame) -> None:
    st.subheader("Serenity Chokepoint Radar")
    st.caption("尋找 AI 基礎設施、半導體、光通訊、封裝、電力與材料供應鏈中的瓶頸型公司。")

    top = filtered.head(5)
    cols = st.columns(5)
    for col, (_, row) in zip(cols, top.iterrows()):
        snap = fetch_yahoo_snapshot(row["ticker"])
        col.metric(row["ticker"], f"{row['serenity_score']:.1f}", delta=format_pct(snap.change_pct), help=row["thesis"])

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


def render_auto_scan(universe: pd.DataFrame) -> None:
    st.subheader("Auto scanner")
    st.caption("從候選清單抓 Yahoo quote/profile/news，尋找具 chokepoint、scarcity、catalyst 特徵的公司。")
    limit = st.slider("掃描數量", 5, 60, 25, 5)
    run_auto = st.button("執行 auto scan")

    if run_auto:
        with st.spinner("掃描候選公司中..."):
            result = scanner.run_auto_scan(limit=limit)
        st.success(f"完成：{len(result)} 筆候選")
    elif AUTO_SCAN_FILE.exists():
        result = pd.read_csv(AUTO_SCAN_FILE)
    else:
        result = pd.DataFrame()

    if result.empty:
        st.info("尚無 auto scan 結果。")
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
    available = [col for col in display_cols if col in result.columns]
    st.dataframe(result[available].head(80), use_container_width=True, hide_index=True)

    selected = st.selectbox("查看候選細節", result["ticker"].tolist())
    row = result[result["ticker"] == selected].iloc[0]
    st.markdown(f"### {row.get('ticker')} - {row.get('name')}")
    st.write(f"主題：{row.get('theme', '-')}")
    st.write(f"市值：{format_money(row.get('market_cap'))}")
    st.write(f"正面線索：{row.get('positive_hits') or '-'}")
    st.write(f"風險線索：{row.get('negative_hits') or '-'}")
    st.write(row.get("evidence") or "沒有摘要證據。")
    if row.get("news_evidence"):
        st.caption(row.get("news_evidence"))


def render_manual_scan(universe: pd.DataFrame) -> None:
    st.subheader("手動來源掃描")
    st.caption("貼上網站 URL，掃描 ticker 與瓶頸關鍵字。適合追蹤特定社群、新聞頁或產業網站。")
    source_text = st.text_area("URL，一行一個", "\n".join(DEFAULT_SOURCES), height=130)
    run_scan = st.button("掃描來源")
    if not run_scan:
        return

    urls = [line.strip() for line in source_text.splitlines() if line.strip()]
    known_full = set(universe["ticker"].str.upper())
    known_short = set(universe["ticker"].str.replace(r"\..*$", "", regex=True).str.upper())
    scan = scan_sources(urls, known_full | known_short)
    known = known_full | known_short
    if scan.empty:
        st.warning("沒有找到 ticker。可以換來源或加入更明確的 ticker 文字。")
    else:
        scan["known_in_universe"] = scan["ticker"].str.upper().isin(known)
        st.dataframe(scan.head(80), use_container_width=True, hide_index=True)


def render_ticker_detail(universe: pd.DataFrame, filtered: pd.DataFrame) -> None:
    st.subheader("個股細節")
    options = filtered["ticker"].tolist() if not filtered.empty else universe["ticker"].tolist()
    selected = st.selectbox("選擇 ticker", options)
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
        st.markdown(f"### {row['name']}")
        st.write(row["thesis"])
        chart = fetch_yahoo_history(selected)
        if not chart.empty:
            st.line_chart(chart.set_index("date")["close"])
        else:
            st.warning("Yahoo Finance 無法取得這個 ticker 的歷史價格。")


def render_methodology() -> None:
    st.subheader("方法論")
    st.markdown(
        """
        這個網站分成兩層：

        1. **市場健康指數 MHI**：判斷現在該進攻、防守或等待。
        2. **Serenity Radar**：在市場狀態允許時，尋找供應鏈瓶頸型股票。

        MHI 使用即時市場代理資料，但不是醫學儀器，也不是投資建議。它的用途是把分散的市場訊號轉成一個可重複檢查的框架。
        """
    )
    st.dataframe(market_health.factor_weights_frame(), use_container_width=True, hide_index=True)
    st.markdown(
        """
        核心判斷問題：

        - 市場現在健康、亞健康、發炎，還是急症？
        - 上漲是基本面、流動性還是情緒推動？
        - 風險是短期波動，還是信用與槓桿的結構問題？
        - 如果判斷錯了，哪個訊號代表要退出？
        """
    )


def sidebar_filters(universe: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.header("篩選")
        categories = ["全部"] + sorted(universe["category"].unique().tolist())
        category = st.selectbox("類別", categories)
        min_score = st.slider("最低 Serenity 分數", 0, 100, 45)
        hide_scenario = st.checkbox("隱藏 scenario 狀態", value=True)
        st.divider()
        st.header("說明")
        st.caption("MHI 資料約快取 10 分鐘；Serenity 個股行情約快取 15 分鐘。")

    filtered = universe.copy()
    if category != "全部":
        filtered = filtered[filtered["category"] == category]
    if hide_scenario:
        filtered = filtered[filtered["status"].str.lower() != "scenario"]
    return filtered[filtered["serenity_score"] >= min_score].sort_values("serenity_score", ascending=False)


def main() -> None:
    st.set_page_config(page_title="Market Health Radar", layout="wide")
    inject_css()
    st.title("Market Health Radar")
    st.caption("用人體健康模型即時分析市場，再連到股票瓶頸雷達與動能策略。")

    universe = load_universe()
    universe["serenity_score"] = universe.apply(serenity_score, axis=1)
    universe["action"] = universe.apply(lambda r: action_band(r["serenity_score"], r["risk_level"]), axis=1)
    filtered = sidebar_filters(universe)

    tab_market, tab_strategy, tab_radar, tab_auto, tab_manual, tab_detail, tab_method = st.tabs(
        ["市場健康", "交易策略", "股票雷達", "Auto scan", "來源掃描", "個股細節", "方法論"]
    )

    with tab_market:
        render_market_health()
    with tab_strategy:
        render_momentum_strategy()
    with tab_radar:
        render_serenity_radar(universe, filtered)
    with tab_auto:
        render_auto_scan(universe)
    with tab_manual:
        render_manual_scan(universe)
    with tab_detail:
        render_ticker_detail(universe, filtered)
    with tab_method:
        render_methodology()


if __name__ == "__main__":
    main()
