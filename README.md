# 費半 × 台積電ADR × 台指期夜盤 每日行情

放在 GitHub Pages 上的靜態網頁。GitHub Actions 每天自動抓資料、更新 `data/*.json`，網頁開啟時讀取最新資料。不需要伺服器，也不依賴任何 AI 服務帳號。

## 資料與更新時間

| 項目 | 來源 | 自動更新（台北時間） |
|---|---|---|
| 費城半導體指數收盤 | Yahoo Finance（^SOX） | 週二～週六 06:35 |
| 台積電 ADR 收盤（美元） | Yahoo Finance（TSM） | 週二～週六 06:35 |
| 台指期近月夜盤收盤、較開盤參考價漲跌、成交量 | 臺灣期貨交易所 每日交易行情（盤後交易時段） | 週一～週五 16:35 |

- 期交所把夜盤歸到「下一個營業日」，大約在隔天下午才公布在每日行情裡，所以夜盤數字會在**起盤隔天 16:35 後**出現在網頁上。
- 程式只會**新增**缺的日期、**補上**空白的成交量，不會改動既有數字；若新來源和既有數字不同，會寫在 `data/meta.json` 的 `warnings`，網頁底部也會顯示提醒。
- GitHub 排程可能延遲 5～30 分鐘，屬正常現象。

## 第一次設定（約 10 分鐘）

1. **建立 repository**：登入 GitHub → 右上角「+」→ New repository。名稱例如 `market-dashboard`，選 **Public**（免費帳號的 GitHub Pages 需要公開 repo），按 Create repository。
2. **上傳檔案**：在新 repo 頁面點「uploading an existing file」，把解壓縮後資料夾**裡面的全部內容**（`index.html`、`README.md`、`data`、`scripts`、`vendor`、`.github`）拖進去，按 Commit changes。
   - 注意：`.github` 是隱藏資料夾。Mac 在 Finder 按 `Cmd + Shift + .` 顯示；Windows 在檔案總管「檢視 → 隱藏的項目」勾選。務必確認 `.github/workflows/update.yml` 有上傳到。
3. **開啟 Actions 寫入權限**：Settings → Actions → General → 最下方 Workflow permissions 選 **Read and write permissions** → Save。
4. **開啟網頁**：Settings → Pages → Build and deployment 的 Source 選 **Deploy from a branch**，Branch 選 `main`、資料夾 `/ (root)` → Save。約 1～2 分鐘後網址會顯示在同一頁，格式為 `https://<你的帳號>.github.io/market-dashboard/`。
5. **手動試跑一次**：Actions 分頁 → 左側「每日更新行情資料」→ 右側 **Run workflow**。綠色勾勾代表成功；點進去「抓資料」步驟可看到這次新增了哪些日期與提醒。

## 日常維護

- 什麼都不用做。每次更新都會產生一筆提交，repo 會保持活躍，GitHub 不會停用排程。
- 若想停止：Actions → 每日更新行情資料 → 右上角「…」→ Disable workflow。
- 若要手動修正某天數字：直接在 GitHub 網頁上編輯 `data/sox.json`、`data/tsm.json` 或 `data/txf.json`。

## 檔案說明

```
index.html                 網頁（讀 data/*.json 畫圖表）
data/sox.json              [{"date","close"}]                  美東交易日
data/tsm.json              [{"date","close"}]                  美東交易日，美元
data/txf.json              [{"date","close","chg","vol"}]       夜盤起盤日（台北 D 15:00 至 D+1 05:00）
data/meta.json             最後檢查時間、本次新增、提醒
scripts/update.py          抓資料程式
.github/workflows/update.yml   排程設定
vendor/d3.min.js           圖表函式庫（d3 v7.9.0，ISC 授權），放在本地以免外部 CDN 失效
```

僅供參考，非投資建議。
