# 🧠 Advantech AI Selection Tool - 程式邏輯架構與串接說明

本文件旨在說明專案目前的程式邏輯架構，詳細解析「**前端 UI**」、「**後端 FastAPI 服務**」與「**資料/AI 處理層**」各支程式是如何分工與互相串接的。

---

## 1. 🎨 前端 UI 互動層 (Frontend / Browser)

這是使用者直接操作的介面層，主要職責是收集使用者行為、維護畫面狀態，並向後端發起 API 請求。

*   **`frontend/select_ui_with_options_claude.html`** (主頁面)：
    *   系統唯一的入口畫面。
    *   負責整體版面配置，包含左側的「硬體與場景篩選區」、中間的「選型結果表格」、右下角的「AI Chatbot 浮動面板」。
*   **`frontend/js/scenes.js`** (場景資料定義)：
    *   負責定義「應用場景模板」（如：鐵路車載、電力系統、智慧工廠等）。
    *   內含各場景的圖示、文字描述，以及**預設的必選/建議條件**（例如：鐵路場景預設必須有 EN50155 認證）。
*   **`frontend/js/app.js`** (前端核心中樞)：
    *   **場景連動與狀態管理**：讀取 `scenes.js`，將預設值填入畫面。同時負責偵測使用者是否有「手動修改」預設值，藉此觸發 `(已修改)` 的橘色警示標籤與恢復預設按鈕。
    *   **選型搜尋邏輯**：收集畫面上所有的條件（如 Port 數、Management Type 等），打包成 JSON 格式送給後端選型 API (`/api/submitProdType`)，拿到結果後動態渲染下方的 HTML 表格。
    *   **Chatbot 互動邏輯**：負責攔截對話框的輸入文字，連同「目前畫面上搜出的型號 (Context)」，一併發送給後端 AI API (`/api/chat`)，並將回傳的 Markdown 報告渲染到聊天視窗中。
*   **`frontend/css/style.css`** (視覺樣式)：
    *   提供高質感的 Glassmorphism (毛玻璃) 視覺設計，包含各種狀態標籤 (藍/綠/橘) 的動態樣式。

---

## 2. ⚙️ 後端 API 服務層 (Backend / FastAPI)

負責接收前端請求、處理商業邏輯、與資料庫溝通，並回傳格式化的資料給前端。

*   **`app/main.py`** (後端心臟 / Entry Point)：
    *   啟動 Uvicorn 伺服器的進入點。
    *   負責掛載靜態網頁（讓瀏覽器能讀到 `frontend/` 下的 HTML/JS/CSS）。
    *   啟動並註冊兩條主要的 API 路由 (Router)：`selection.py` 與 `chat.py`。
*   **`app/api/selection.py`** (選型過濾 API)：
    *   提供 `/api/submitProdType` 端點。
    *   **邏輯轉換**：負責將前端送來的 JSON 條件轉為 **MongoDB 聚合查詢指令**。例如：將 Management Type 轉為正則表達式 (Regex) 進行模糊比對，將 Port 數轉為 `>=` 比較運算。
    *   直接向 MongoDB `product_specs` Collection 撈取資料後，回傳產品列表給前端表格。
*   **`app/api/chat.py`** (AI 對話 API)：
    *   提供 `/api/chat` 端點。
    *   接收前端的自然語言提問與上下文型號，並觸發底層的 **RAG 3-Stage 管線** 進行處理。

---

## 3. 🧠 資料庫與 AI 處理層 (Data & AI Pipeline)

當後端收到需要深度資料處理或生成式 AI 輔助的任務時，會呼叫這些底層模組。

*   **`app/llm_gateway.py`** (AI 安全閘道器)：
    *   對接 Google Gemini 的核心橋樑。
    *   專案內任何需要呼叫大語言模型 (LLM) 的地方都必須經過此閘道。
    *   負責處理 API Key 管理、自動重試 (Retry)、限流保護 (RPM Control)，以及記錄所有呼叫日誌 (`llm_usage.log`)。

*   **RAG 3-Stage 管線** (處理 AI 問答的核心引擎，由 `chat.py` 依序呼叫)：
    1.  **`intent_parser.py` (意圖解析)**：第一階段。將使用者的自然語言丟給 Gemini Flash 模型，抽取出裡面的規格條件並轉換為結構化的 JSON（例如將「八埠防震交換機」轉為 `{"port": 8, "cert": "EN50155"}`）。
    2.  **`hard_filter.py` (資料庫過濾)**：第二階段。拿著上一步的 JSON 去 MongoDB 進行精準過濾（Text-to-SQL 的概念），撈出真實存在且符合條件的硬體規格。
    3.  **`report_generator.py` (報告生成)**：第三階段。將撈出來的生硬規格 JSON 資料，再次丟給 Gemini 模型，要求其根據使用者的原始問題，撰寫成一篇易讀、專業的 Markdown 選型推薦報告。

*   **`sync_specs_to_mongo.py`** (非同步資料同步腳本)：
    *   這是一支獨立於 API 之外的資料維護腳本（通常由排程或工程師手動觸發）。
    *   負責讀取 PM 維護的 **Google Sheets**。
    *   執行複雜的資料清洗（處理合併儲存格）與 **雙軌 Join**（將硬體型號與軟體系列功能進行配對）。
    *   最後將整理好的完美資料寫入 **MongoDB (`product_specs`)**，作為選型 API 與 RAG 引擎的唯一真實資料來源 (Single Source of Truth)。

---

## 🔄 核心資料流向總結 (Data Flow Summary)

1. **手動條件選型流向**：
   `使用者介面操作` ➡️ `app.js` (打包 JSON) ➡️ `app/main.py` ➡️ `selection.py` (轉化為 MongoDB Query) ➡️ `MongoDB` ➡️ 回傳表格資料。
   
2. **AI Chatbot 智能對話流向**：
   `對話輸入` ➡️ `app.js` ➡️ `app/main.py` ➡️ `chat.py` ➡️ `intent_parser.py` (理解意圖) ➡️ `hard_filter.py` (比對資料庫) ➡️ `report_generator.py` (生成報告) ➡️ 回傳前端對話框。
   
3. **資料庫維護流向**：
   `Google Sheets (PM)` ➡️ `sync_specs_to_mongo.py` (清洗/Join) ➡️ `MongoDB (系統庫)`。
