from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
import requests


HEADERS = {"User-Agent": "Mozilla/5.0 MarketHealth/1.0"}

MARKET_SYMBOLS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "RSP": "S&P 500 Equal Weight",
    "TLT": "Long Treasury",
    "SHY": "Short Treasury",
    "HYG": "High Yield Credit",
    "LQD": "Investment Grade Credit",
    "UUP": "U.S. Dollar",
    "GLD": "Gold",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLK": "Technology",
    "XLU": "Utilities",
    "^VIX": "VIX",
}

FACTOR_WEIGHTS = {
    "liquidity": 0.20,
    "trend": 0.20,
    "valuation_proxy": 0.10,
    "credit_leverage": 0.15,
    "volatility": 0.15,
    "risk_appetite": 0.10,
    "macro_growth": 0.10,
}


@dataclass(frozen=True)
class MarketDiagnosis:
    score: float
    regime: str
    posture: str
    explanation: str


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:+.2%}"


def yahoo_chart(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "range": period,
        "interval": interval,
        "events": "history",
        "includeAdjustedClose": "true",
    }
    response = requests.get(url, params=params, headers=HEADERS, timeout=15)
    response.raise_for_status()
    payload = response.json()["chart"]["result"][0]
    timestamps = payload.get("timestamp", [])
    quote = payload.get("indicators", {}).get("quote", [{}])[0]
    adjclose = payload.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose")
    close = adjclose or quote.get("close", [])
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None),
            "close": close,
            "volume": quote.get("volume", [None] * len(timestamps)),
        }
    )
    return frame.dropna(subset=["close"]).set_index("date").sort_index()


def load_market_prices(symbols: Iterable[str] = MARKET_SYMBOLS.keys()) -> pd.DataFrame:
    series = {}
    for symbol in symbols:
        try:
            hist = yahoo_chart(symbol)
            if not hist.empty:
                series[symbol] = hist["close"]
        except Exception:
            continue
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).ffill().dropna(how="all")


def latest_snapshot(prices: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol in prices.columns:
        close = prices[symbol].dropna()
        if close.empty:
            continue
        latest = float(close.iloc[-1])
        one_day = close.pct_change().iloc[-1] if len(close) > 1 else None
        one_month = latest / close.iloc[-22] - 1 if len(close) > 22 else None
        three_month = latest / close.iloc[-63] - 1 if len(close) > 63 else None
        rows.append(
            {
                "symbol": symbol,
                "name": MARKET_SYMBOLS.get(symbol, symbol),
                "latest": latest,
                "1d": one_day,
                "1m": one_month,
                "3m": three_month,
            }
        )
    return pd.DataFrame(rows)


def above_sma_score(close: pd.Series) -> float:
    close = close.dropna()
    if len(close) < 200:
        return 50
    latest = close.iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    score = 50
    if latest > sma50:
        score += 20
    else:
        score -= 15
    if latest > sma200:
        score += 20
    else:
        score -= 25
    if sma50 > sma200:
        score += 10
    else:
        score -= 10
    return clamp(score)


def relative_return(prices: pd.DataFrame, a: str, b: str, lookback: int = 63) -> float | None:
    if a not in prices or b not in prices:
        return None
    frame = prices[[a, b]].dropna()
    if len(frame) <= lookback:
        return None
    ra = frame[a].iloc[-1] / frame[a].iloc[-lookback] - 1
    rb = frame[b].iloc[-1] / frame[b].iloc[-lookback] - 1
    return float(ra - rb)


def score_market_health(prices: pd.DataFrame) -> tuple[pd.DataFrame, MarketDiagnosis]:
    if prices.empty:
        factors = pd.DataFrame(
            [
                {"factor": key, "label": key, "score": 50, "diagnosis": "資料不足", "signal": "-"}
                for key in FACTOR_WEIGHTS
            ]
        )
        return factors, MarketDiagnosis(50, "資料不足", "等待", "目前無法取得市場資料。")

    spy = prices["SPY"].dropna() if "SPY" in prices else pd.Series(dtype=float)
    qqq = prices["QQQ"].dropna() if "QQQ" in prices else pd.Series(dtype=float)

    trend_score = round((above_sma_score(spy) + above_sma_score(qqq)) / 2, 1) if not spy.empty and not qqq.empty else 50

    vix_latest = float(prices["^VIX"].dropna().iloc[-1]) if "^VIX" in prices and not prices["^VIX"].dropna().empty else None
    if vix_latest is None:
        volatility_score = 50
    elif vix_latest < 14:
        volatility_score = 72
    elif vix_latest < 20:
        volatility_score = 62
    elif vix_latest < 28:
        volatility_score = 42
    elif vix_latest < 40:
        volatility_score = 25
    else:
        volatility_score = 10

    credit_rel = relative_return(prices, "HYG", "LQD")
    credit_score = 50 if credit_rel is None else clamp(55 + credit_rel * 500)

    dollar_1m = None
    if "UUP" in prices and len(prices["UUP"].dropna()) > 22:
        dollar_1m = prices["UUP"].dropna().iloc[-1] / prices["UUP"].dropna().iloc[-22] - 1
    tlt_shy = relative_return(prices, "TLT", "SHY", 22)
    liquidity_score = 55
    if dollar_1m is not None:
        liquidity_score -= dollar_1m * 650
    if tlt_shy is not None:
        liquidity_score += tlt_shy * 250
    liquidity_score = clamp(liquidity_score)

    broad_rel = relative_return(prices, "RSP", "SPY")
    small_rel = relative_return(prices, "IWM", "SPY")
    risk_appetite_score = 50
    if broad_rel is not None:
        risk_appetite_score += broad_rel * 350
    if small_rel is not None:
        risk_appetite_score += small_rel * 250
    risk_appetite_score = clamp(risk_appetite_score)

    discretionary_rel = relative_return(prices, "XLY", "XLP")
    tech_util_rel = relative_return(prices, "XLK", "XLU")
    macro_growth_score = 50
    if discretionary_rel is not None:
        macro_growth_score += discretionary_rel * 300
    if tech_util_rel is not None:
        macro_growth_score += tech_util_rel * 150
    macro_growth_score = clamp(macro_growth_score)

    valuation_proxy_score = clamp(85 - max(0, trend_score - 65) * 0.55 - max(0, risk_appetite_score - 65) * 0.35)

    rows = [
        {
            "factor": "liquidity",
            "label": "流動性 / 市場血液",
            "score": round(liquidity_score, 1),
            "signal": f"美元1月 {pct(dollar_1m)}，TLT/SHY相對 {pct(tlt_shy)}",
            "diagnosis": "寬鬆支持風險資產" if liquidity_score >= 65 else "資金成本或美元壓力偏高" if liquidity_score < 45 else "中性",
        },
        {
            "factor": "trend",
            "label": "趨勢 / 肌肉力量",
            "score": trend_score,
            "signal": "SPY/QQQ 與 50/200 日均線結構",
            "diagnosis": "趨勢完整" if trend_score >= 70 else "趨勢受損" if trend_score < 45 else "趨勢中性或分歧",
        },
        {
            "factor": "valuation_proxy",
            "label": "估值壓力 / 體脂率",
            "score": round(valuation_proxy_score, 1),
            "signal": "以趨勢過熱與風險偏好作代理，不等同正式估值",
            "diagnosis": "容錯率較高" if valuation_proxy_score >= 70 else "追價容錯率下降" if valuation_proxy_score < 50 else "估值壓力中等",
        },
        {
            "factor": "credit_leverage",
            "label": "信用槓桿 / 慢性病",
            "score": round(credit_score, 1),
            "signal": f"HYG/LQD 3月相對 {pct(credit_rel)}",
            "diagnosis": "信用風險可控" if credit_score >= 65 else "信用壓力升溫" if credit_score < 45 else "信用中性",
        },
        {
            "factor": "volatility",
            "label": "波動率 / 血壓",
            "score": round(volatility_score, 1),
            "signal": f"VIX {vix_latest:.2f}" if vix_latest is not None else "VIX 無資料",
            "diagnosis": "波動穩定" if volatility_score >= 65 else "市場發炎" if volatility_score < 45 else "波動偏高但未失控",
        },
        {
            "factor": "risk_appetite",
            "label": "資金情緒 / 荷爾蒙",
            "score": round(risk_appetite_score, 1),
            "signal": f"RSP/SPY {pct(broad_rel)}，IWM/SPY {pct(small_rel)}",
            "diagnosis": "參與廣度改善" if risk_appetite_score >= 65 else "上漲集中或避險偏強" if risk_appetite_score < 45 else "情緒中性",
        },
        {
            "factor": "macro_growth",
            "label": "基本面代理 / 骨骼",
            "score": round(macro_growth_score, 1),
            "signal": f"XLY/XLP {pct(discretionary_rel)}，XLK/XLU {pct(tech_util_rel)}",
            "diagnosis": "景氣風險偏好改善" if macro_growth_score >= 65 else "防禦板塊占優" if macro_growth_score < 45 else "景氣訊號中性",
        },
    ]
    factors = pd.DataFrame(rows)
    weighted = 0.0
    for row in rows:
        weighted += row["score"] * FACTOR_WEIGHTS[row["factor"]]
    score = float(round(weighted, 1))
    diagnosis = diagnose_market(score, factors)
    return factors, diagnosis


def diagnose_market(score: float, factors: pd.DataFrame) -> MarketDiagnosis:
    weak = factors[factors["score"] < 45]["label"].tolist()
    strong = factors[factors["score"] >= 70]["label"].tolist()
    if score >= 80:
        regime = "健康多頭"
        posture = "進攻，但保留停利規則"
        explanation = "市場血液、趨勢與風險承受力大致健康。"
    elif score >= 65:
        regime = "正常偏強"
        posture = "偏多配置，回檔找機會"
        explanation = "多數因子支持風險資產，但仍需控制單一題材曝險。"
    elif score >= 50:
        regime = "亞健康震盪"
        posture = "降低追價，等待確認"
        explanation = "市場還沒進入急症，但內部因子分歧。"
    elif score >= 35:
        regime = "發炎高風險"
        posture = "防守、短線、降低槓桿"
        explanation = "多個指標顯示壓力，策略重點是避免大回撤。"
    else:
        regime = "急症 / 流動性壓力"
        posture = "現金與避險優先"
        explanation = "市場承壓能力低，先等波動和信用壓力退燒。"

    if weak:
        explanation += " 弱項：" + "、".join(weak[:3]) + "。"
    if strong:
        explanation += " 強項：" + "、".join(strong[:3]) + "。"
    return MarketDiagnosis(score, regime, posture, explanation)


def scenario_playbook(diagnosis: MarketDiagnosis, factors: pd.DataFrame) -> pd.DataFrame:
    low = set(factors[factors["score"] < 45]["factor"])
    high = set(factors[factors["score"] >= 70]["factor"])
    rows = []

    if diagnosis.score >= 65 and "trend" in high:
        rows.append(
            {
                "情境": "健康或偏強多頭",
                "判斷": "價格趨勢完整，資金仍願意承擔風險。",
                "策略": "以順勢為主；核心 ETF 或強勢產業分批持有，回檔不破關鍵均線再加碼。",
                "風控": "跌破 50 日線或 MHI 連續轉弱時降部位。",
            }
        )
    if "volatility" in low or "credit_leverage" in low:
        rows.append(
            {
                "情境": "市場發炎",
                "判斷": "VIX 或信用代理惡化，代表壓力可能被槓桿放大。",
                "策略": "降低槓桿與小型股曝險；偏短線，優先流動性高的標的。",
                "風控": "等 VIX 回落、HYG/LQD 修復後再增加風險。",
            }
        )
    if "liquidity" in low:
        rows.append(
            {
                "情境": "流動性收縮",
                "判斷": "美元或利率壓力使市場血液變少。",
                "策略": "少追高估值成長股；提高現金、短債、防禦股權重。",
                "風控": "不要在流動性壓力最大時重倉攤平。",
            }
        )
    if "risk_appetite" in low and "trend" in high:
        rows.append(
            {
                "情境": "外強內弱",
                "判斷": "指數強但廣度不足，可能由少數大型股撐盤。",
                "策略": "持有龍頭可以，但避免擴散到弱勢股；分批停利題材過熱標的。",
                "風控": "若龍頭跌破均線，整體市場容易快速補跌。",
            }
        )
    if diagnosis.score < 50:
        rows.append(
            {
                "情境": "防守期",
                "判斷": "市場像身體發炎，首要目標不是賺最多，而是避免傷害。",
                "策略": "現金、短債、低波動策略；只做小部位反彈或等待 MHI 修復。",
                "風控": "每筆交易先定義錯誤訊號，避免越跌越買。",
            }
        )
    if not rows:
        rows.append(
            {
                "情境": "中性盤整",
                "判斷": "沒有單一方向優勢，市場需要新催化。",
                "策略": "區間交易、分批布局、降低交易頻率。",
                "風控": "等待突破或跌破後再提高部位。",
            }
        )
    return pd.DataFrame(rows)


def factor_weights_frame() -> pd.DataFrame:
    labels = {
        "liquidity": "流動性",
        "trend": "趨勢",
        "valuation_proxy": "估值壓力代理",
        "credit_leverage": "信用與槓桿",
        "volatility": "波動率",
        "risk_appetite": "資金情緒",
        "macro_growth": "基本面代理",
    }
    return pd.DataFrame(
        [{"因子": labels[key], "權重": f"{weight:.0%}"} for key, weight in FACTOR_WEIGHTS.items()]
    )


def data_timestamp(prices: pd.DataFrame) -> str:
    if prices.empty:
        return "-"
    latest = max(idx for idx in prices.index if pd.notna(idx))
    return f"{latest:%Y-%m-%d %H:%M} / 本機更新 {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
