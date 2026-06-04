# Serenity-style Stock Selection Methodology

Updated: 2026-06-04

## Core idea

Serenity's public investing style can be summarized as:

> Do not only buy the obvious AI winners. Move upstream and find the physical supply-chain bottlenecks that AI infrastructure cannot scale without.

The system therefore searches for companies with:

1. Confirmed demand from AI infrastructure.
2. Constrained supply.
3. Hard-to-replace products.
4. Under-recognized market position.
5. Near-term catalysts.
6. Manageable risk.

## Six-factor scoring model

### 1. Chokepoint strength

Does the company sit in a part of the chain that can slow down the whole system?

High-signal areas:

- CPO
- silicon photonics
- InP substrates
- CW lasers
- optical engines
- transceivers
- SiC / GaN power
- advanced packaging
- probe cards and semiconductor test
- data-center power and cooling

### 2. Scarcity

Is supply hard to increase quickly?

Positive signals:

- shortage
- capacity constrained
- long qualification cycle
- sole supplier / limited supplier base
- specialty materials
- specialty foundry
- substrate or wafer bottleneck

### 3. Vertical integration

Does the company control more of its own stack?

Positive signals:

- designs and manufactures
- owns materials or wafer supply
- controls modules and systems
- has internal process know-how

### 4. Catalyst strength

What can force the market to re-rate the company?

Positive signals:

- qualification order
- backlog
- new supply agreement
- CHIPS Act funding
- new facility
- capacity expansion
- Nasdaq listing
- index inclusion
- major customer validation

### 5. Institutional front-run potential

Is this still under-followed?

Higher scores usually go to:

- small and mid caps
- foreign-listed names
- low analyst coverage
- technical suppliers that are not yet obvious AI winners

Lower scores go to:

- mega-cap consensus trades
- names already crowded by institutions

### 6. Risk level

The system deducts for:

- dilution
- ATM offering
- going concern language
- delisting
- bankruptcy
- weak balance sheet
- reflexive KOL-driven spikes
- very low liquidity

## V1 versus V2

### V1: Known Serenity radar

V1 ranks names that Serenity or Serenity-related public sources have already discussed.

File:

```text
data/serenity_universe.csv
```

This is useful for tracking the known Serenity universe.

### V2: Auto scanner

V2 uses the same logic to search a broader candidate pool.

Files:

```text
data/auto_scan_candidates.csv
data/auto_scan_results.csv
scanner.py
```

The scanner fetches public company descriptions and Yahoo news snippets, then scores keyword evidence and risk evidence.

The purpose is to find:

```text
stocks Serenity may not have publicly mentioned, but that resemble his chokepoint logic
```

## How to interpret auto-scan results

Do not blindly buy the highest score.

Use the output as a research queue:

- `serenity_like_score`: overall fit with the framework.
- `positive_hits`: why the company was selected.
- `negative_hits`: risk words that require caution.
- `already_in_serenity_pool`: whether it is already in the known Serenity universe.
- `evidence`: company description evidence.
- `news_evidence`: recent public-news evidence.

The most interesting candidates are often:

```text
high score + not already in Serenity pool + clear positive hits + no severe negative hits
```

## Current limitation

The system is now an automatic candidate-pool scanner, not yet a complete global market scanner.

To expand coverage, add tickers to:

```text
data/auto_scan_candidates.csv
```

Future upgrades can add:

- SEC filing search
- earnings-call transcript search
- full US micro/small-cap semiconductor screen
- Taiwan/Japan/Europe supply-chain screens
- price momentum and volume anomaly filters
- balance-sheet quality scoring
- valuation normalization

## Safety note

This tool is for research only. It produces candidates for deeper work, not buy or sell signals.
