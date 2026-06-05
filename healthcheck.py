from __future__ import annotations

import sys

import pandas as pd

import app
import market_health
import scanner


def main() -> int:
    universe = app.load_universe()
    required = {
        "ticker",
        "name",
        "category",
        "layer",
        "chokepoint_strength",
        "scarcity",
        "vertical_integration",
        "catalyst_strength",
        "institutional_front_run",
        "risk_level",
        "thesis",
    }
    missing = sorted(required - set(universe.columns))
    if missing:
        print(f"missing columns: {missing}")
        return 1
    if universe.empty:
        print("universe is empty")
        return 1
    scores = universe.apply(app.serenity_score, axis=1)
    if scores.isna().any() or not scores.between(0, 100).all():
        print("score range failed")
        return 1
    sample = app.extract_ticker_mentions(
        "Serenity says AXTI is an InP chokepoint and $SIVE is a CPO CW laser bottleneck.",
        {"AXTI", "SIVE"},
    )
    if "AXTI" not in sample or "SIVE" not in sample:
        print("ticker extraction failed")
        return 1
    candidates = scanner.load_candidates()
    if candidates.empty or "ticker" not in candidates.columns:
        print("auto-scan candidate file failed")
        return 1
    text_score = scanner.score_text("CPO silicon photonics InP bottleneck dilution")
    if text_score[0] <= 0 or text_score[1] <= 0:
        print("scanner keyword scoring failed")
        return 1
    factors, diagnosis = market_health.score_market_health(pd.DataFrame())
    if factors.empty or not 0 <= diagnosis.score <= 100:
        print("market health fallback failed")
        return 1
    print(f"ok: {len(universe)} known tickers, {len(candidates)} auto candidates, top score {scores.max():.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
