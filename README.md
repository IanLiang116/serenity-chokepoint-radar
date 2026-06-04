# Serenity Chokepoint Radar

本系統是本機版 Serenity-style 選股雷達。它不是投資建議，也不是保證獲利工具，而是把 Serenity 公開展現出的「AI 供應鏈卡點 / chokepoint」研究邏輯整理成可重複的篩選流程。

## 這個系統可以做什麼

### 1. Known radar

這是 V1 功能。

它讀取：

```text
data/serenity_universe.csv
```

目前內建 Serenity 相關公開資料中常見的 36 個標的，例如 AXTI、SIVE.ST、AAOI、SOI.PA、XFAB.PA、3363.TWO 等。

它會依照以下因子計算 Serenity score：

- chokepoint strength
- scarcity
- vertical integration
- catalyst strength
- institutional front-run potential
- risk level

### 2. Auto scanner

這是 V2 新功能。

它不只看 Serenity 講過的股票，而是用 Serenity-like 邏輯去掃新的候選池。

候選池在：

```text
data/auto_scan_candidates.csv
```

目前包含 photonics、CPO、InP/GaN/SiC、semiconductor testing、advanced packaging、data-center power/cooling、specialty materials 等方向的 50 個候選標的。

掃描器會讀公開 Yahoo 公司資料與新聞摘要，再根據下列關鍵字打分：

- chokepoint
- bottleneck
- CPO
- silicon photonics
- InP
- CW laser
- GaN
- SiC
- advanced packaging
- probe card
- metrology
- liquid cooling
- data center
- qualification
- backlog
- CHIPS Act
- dilution
- ATM offering
- delisting

掃描結果會輸出到：

```text
data/auto_scan_results.csv
```

### 3. Manual scan

你可以貼公開網頁 URL，例如整理文、X 鏡像頁、產業文章。

系統會掃裡面的 ticker，並用 Serenity 關鍵字加權，找出可能值得放進雷達的新標的。

## 怎麼打開

最簡單方式：雙擊桌面捷徑：

```text
Serenity Chokepoint Radar
```

或者到這個資料夾：

```text
C:\Users\ianli\OneDrive\文件\股票
```

雙擊：

```text
start_serenity_radar.cmd
```

啟動後打開瀏覽器：

```text
http://127.0.0.1:8501
```

也可以用 PowerShell：

```powershell
.\run_widget.ps1
```

## 怎麼用 Auto scanner

1. 打開系統。
2. 點上方分頁 `Auto scanner`。
3. 選擇 Scan limit。
4. 按 `Run auto scan`。
5. 看 `serenity_like_score`、positive_hits、negative_hits。

重點不是只看分數，而是看 evidence：

- positive_hits：為什麼它像 Serenity 會研究的卡點。
- negative_hits：有沒有稀釋、ATM、下市、破產等風險詞。
- already_in_serenity_pool：是否已經在原本 Serenity 相關池子中。

如果 `already_in_serenity_pool = False` 且分數高，代表它可能是「Serenity 沒公開講過、但邏輯相似」的新候選。

## 健康檢查

```powershell
& "C:\Users\ianli\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" healthcheck.py
```

## 安全邊界

- 不讀 Gmail、Notion、Google Drive、Canva 或 Chrome 私人資料。
- 不保存帳密。
- 不修改 Windows 登錄檔。
- 不自動設定開機啟動。
- 只在本資料夾內寫入掃描結果與快取。

## 重要限制

這個系統目前不是全市場無限掃描，而是「可擴充候選池掃描」。要掃更多股票，可以把 ticker 加到：

```text
data/auto_scan_candidates.csv
```

未來可以再升級成：

- 自動抓全美股小市值半導體/材料/設備公司
- 自動讀 SEC filings
- 自動抓 earnings call transcript
- 加入股價動能與成交量異動
- 加入財務風險與估值分數

現在的 V2 已經能用 Serenity 的邏輯找新候選，但仍需要你對高分標的做基本面確認與風險控管。
