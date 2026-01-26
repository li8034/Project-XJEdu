# XJEdu AstrBot 競賽監控插件

自動拉取西安交通大學教務處的競賽通知，辨識是否為報名相關信息，並在可報名期間內推送、列表與提醒。

## 功能特性
- 監控教務處競賽通知（含子欄目），30 分鐘輪詢一次。
- 每日 09:00 根據已知截止日期提醒距離截止 ≤3 天的競賽。
- AI 解析（可選）：使用配置的對話模型抽取“是否為報名通知”和起止日期。
- 去重與持久化：使用 KV 存儲並落盤到 `competitions_store.json`，避免重複推送。
- 可選 Playwright 支援：處理動態檢測頁面時自動降級保存 HTML 以便排查。

## 快速開始
1. 將本目錄放入 AstrBot 的 `plugins` 目錄，保持結構與 `metadata.yaml` 不變。
2. 如需 AI 解析，編輯 `config_ai.json`，填入 `api_key`、`base_url`、`model`，並確認 `use_ai` 為 `true`。
3. 啟動或重載 AstrBot，插件自動註冊；初次啟動不會推送歷史，只建立定時任務。
4. 在機器人所在會話輸入 `/竞赛帮助` 查看指令列表。

## 指令
- 基礎指令組（comp）
  - `/comp sub`：訂閱競賽推送（群/私聊均可）。
  - `/comp unsub`：退訂競賽推送。
  - `/comp list`：查看當前可報名競賽。
  - `/comp check`：立即抓取一次教務處通知。
  - `/竞赛帮助`：查看幫助說明。
- 管理指令組（cadmin）
  - `/cadmin ai on|off`：開關 AI 解析並顯示狀態。
  - `/cadmin init`：手動初始化同步（不推送歷史）。
  - `/cadmin aitest`：AI 連通性自檢，需先配置密鑰。
  - `/cadmin reset`：清空已讀、緩存並刪除本地存儲文件。
  - `/cadmin stopcheck`：停止定時檢查任務。

## 配置說明
`config_ai.json` 示例字段：
- `use_ai`：是否啟用 AI 解析（KV 中的 `ai_use` 可覆蓋）。
- `base_url` / `api_key` / `model`：模型服務配置，默認指向 DeepSeek。
- `notes`：備註信息，方便標註密鑰來源或代理。

## 運行細節
- 定時任務：30 分鐘一次拉取列表；每日 09:00 發送截止提醒。
- 存儲：競賽列表、已讀 ID、錯誤項會寫入 `competitions_store.json` 並同步到 KV。
- 反爬處理：若遇到動態挑戰，會保存渲染結果以便人工排查；Playwright 為可選依賴。

## 常見問題
- 未獲取到列表：可能被反爬或網絡異常，嘗試 `/comp check` 重拉或 `/cadmin init` 初始化。
- AI 無法解析：確認 `config_ai.json` 已填寫密鑰並使用 `/cadmin ai on` 開啟，然後 `/cadmin aitest` 測試。
- 需要重新推送：用 `/cadmin reset` 清空緩存後，再用 `/comp check`。
