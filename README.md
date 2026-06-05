# Market Health Radar

Market Health Radar is a Streamlit website for real-time market diagnosis.

It treats the financial market like a human body:

- Liquidity is market blood flow.
- Volatility is market blood pressure.
- Credit and leverage are chronic disease risk.
- Trend is muscle strength.
- Valuation pressure is body-fat risk.
- Risk appetite is market hormones.
- Macro/sector rotation is the market skeleton.

The app converts these signals into a 0-100 Market Health Index (MHI), then maps the current regime to trading posture and scenario playbooks.

## Features

- Real-time Market Health Index using Yahoo Finance market proxies.
- Scenario playbook for healthy bull, weak breadth, market inflammation, liquidity stress, and defensive regimes.
- QQQ/SPY/SHY monthly momentum strategy reference.
- Serenity Chokepoint Radar for bottleneck-style stock ideas.
- Auto scanner for semiconductor, AI infrastructure, photonics, power, cooling, and specialty-material candidates.
- Manual source scanner for ticker mentions and chokepoint keywords.

## Run Locally

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Or on this Windows machine:

```powershell
.\run_widget.ps1
```

Then open:

```text
http://127.0.0.1:8501
```

## Deploy for Family Use

This project is a Streamlit app. The easiest public deployment path is Streamlit Community Cloud.

1. Push this repository to GitHub.
2. Go to https://share.streamlit.io/
3. Sign in with GitHub.
4. Choose this repository: `IanLiang116/serenity-chokepoint-radar`
5. Set the main file path to:

```text
app.py
```

6. Deploy.
7. Share the generated Streamlit URL with family.

## Files

```text
app.py                  Streamlit website UI
market_health.py        Market Health Index model
strategy.py             QQQ/SPY/SHY monthly momentum strategy
scanner.py              Auto scanner and keyword scoring
healthcheck.py          Lightweight project smoke test
data/                   Universe and candidate CSV files
```

## Health Check

```powershell
python healthcheck.py
```

## Disclaimer

This is an analysis and education tool, not financial advice. It can help structure market judgment, but every trade still needs position sizing, risk control, and independent review.
