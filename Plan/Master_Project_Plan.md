# Advantech AI 選型工具 — RAG Chatbot 系統架構計畫書

> **版本**：v1.2 — 2026-04-17（向量資料庫由 ChromaDB 改為 MongoDB Atlas Vector Search，並導入 uv 進行環境控管）  
> **作者**：AI Architecture Review  
> **適用對象**：系統開發工程師、PM、AI/ML 工程師

---

## 目錄

1. [系統定位與核心價值](#一系統定位與核心價值)
2. [整體系統架構](#二整體系統架構)
3. [完整資料流程](#三完整資料流程)
   - [3.1 資料維護寫入流程](#31-資料維護寫入流程google-sheets--mongodb)
   - [3.2 硬體篩選查詢流程](#32-硬體篩選查詢流程)
   - [3.3 RAG Chatbot 查詢流程（核心）](#33-rag-chatbot-查詢流程核心)
4. [各層元件詳細設計](#四各層元件詳細設計)
   - [4.1 資料維護層 — Google Sheets](#41-資料維護層--google-sheets)
   - [4.2 資料庫層 — MongoDB](#42-資料庫層--mongodb)
   - [4.3 向量搜尋層 — MongoDB Atlas Vector Search](#43-向量搜尋層--mongodb-atlas-vector-search)
   - [4.4 RAG 後端服務 — FastAPI](#44-rag-後端服務--fastapi)
   - [4.5 選型後端服務 — Flask](#45-選型後端服務--flask)
   - [4.6 前端介面](#46-前端介面)
   - [4.7 開發環境與套件版本控管 — uv](#47-開發環境與套件版本控管--uv)
5. [RAG Pipeline 深度設計](#五rag-pipeline-深度設計)
6. [開發階段規劃](#六開發階段規劃)
7. [風險評估與對策](#七風險評估與對策)
8. [設計決策紀錄](#八設計決策紀錄)

---

## 一、系統定位與核心價值

本系統是 Advantech 工業交換機的**內部選型輔助平台**，解決以下核心痛點：

| 現況痛點 | 系統解決方案 |
|---|---|
| 業務需翻閱多份 PDF Datasheet 才能選型 | AI 自動閱讀規格，秒出推薦理由 |
| 不同型號軟體功能差異難以比較 | 三態值結構化儲存，AI 精準對比 |
| 資料散落在 Excel，版本不一致 | Google Sheets 為唯一資料入口，同步至 MongoDB |
| AI 回答範圍過廣，不聚焦在目標型號 | Hybrid Retrieval：Hard Filter 先鎖定範圍 |

**兩個核心功能整合在同一頁面：**

- **硬體預篩選工具**（頁面主區域）：條件篩選快速縮小型號範圍
- **AI 規格查詢 Chatbot**（右下角浮動面板）：感知篩選結果，自然語言深度查詢

---

## 二、整體系統架構

### 四層架構總覽

```
╔══════════════════════════════════════════════════════════════════╗
║  LAYER 1 ── 資料維護層                                           ║
║                                                                  ║
║  Google Sheets（線上共編，非工程師友善）                          ║
║  ┌─────────────┐ ┌──────────────┐ ┌─────────────────────────┐   ║
║  │ Ind SW Tab  │ │ Train SW Tab │ │ SW Specs Tab            │   ║
║  │ (硬體規格)   │ │ (車載硬體)   │ │ (軟體功能·三態值)        │   ║
║  │ 維護者: PM/RD│ │ 維護者: PM/RD│ │ 維護者: SW 軟體組        │   ║
║  └─────────────┘ └──────────────┘ └─────────────────────────┘   ║
║                      │ sync_specs_to_mongo.py（定期手動執行）     ║
╚══════════════════════╪═══════════════════════════════════════════╝
                       │ ① 讀取 → 驗證 → 展開 → upsert
╔══════════════════════╪═══════════════════════════════════════════╗
║  LAYER 2 ── 資料庫層（MongoDB Atlas 統一管理）                    ║
║             ▼                                                    ║
║  MongoDB Atlas（三層 Collection + 原生向量搜尋）                  ║
║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   ║
║  │hardware_specs│  │software_specs│  │   product_specs      │   ║
║  │ 1 doc = 1 設備│  │1 doc = 1系列 │  │ (自動合併，查詢主層)  │   ║
║  │              │  │  × 1 fw版本  │  │    禁止手動編輯       │   ║
║  └──────────────┘  └──────────────┘  └──────────────────────┘   ║
║                                                ↕ Hard Filter     ║
║  datasheet_chunks Collection（向量索引建立於此）                  ║
║  ┌──────────────────────────────────────────────────────────┐    ║
║  │ { chunk_id, product_pn, text, embedding: [float×768] }   │    ║
║  │ Atlas Search Index（knnVector, cosine）建於 embedding 欄  │    ║
║  │ $vectorSearch 支援 pre-filter: { product_pn: {$in: ...} } │    ║
║  └──────────────────────────────────────────────────────────┘    ║
╚══════════════════════╪═══════════════════════════════════════════╝
          ┌────────────┼─────────────┐
          ▼            ▼             ▼
╔═════════════════════════════════════════════════════════════════╗
║  LAYER 3 ── 後端服務層（單一 FastAPI 實例）                       ║
║                                                                 ║
║  FastAPI :8000 (整合所有 API)                                     ║
║  ├── 選型工具 API:                                                ║
║  │   ├── GET /api/searchProdType (軟硬體條件即時下拉)               ║
║  │   └── POST /api/submitProdType (查詢符合條件的產品清單)          ║
║  ├── RAG Chatbot API:                                           ║
║  │   └── POST /api/chat                                         ║
║  │         五階段 RAG Pipeline:                                 ║
║  │         ① 關鍵字意圖解析                                     ║
║  │         ② MongoDB Hard Filter                               ║
║  │         ③ Atlas Vector Search                               ║
║  │         ④ LLM Re-ranking                                    ║
║  │         ⑤ Gemini 報告生成                                   ║
╚══════════════════════╪══════════════╪══════════════════════════╝
                       └──────────────┘
                              ▼
╔═════════════════════════════════════════════════════════════════╗
║  LAYER 4 ── 前端介面層                                          ║
║                                                                 ║
║  select_ui_with_options.html                                    ║
║  ┌────────────────────────────┐  ┌────────────────────────────┐ ║
║  │  硬體預篩選區              │  │  AI Chatbot（浮動面板）     │ ║
║  │  • 管理類型 / Port 數      │  │  • 感知已篩選型號           │ ║
║  │  • Application 篩選        │  │  • 自然語言查詢             │ ║
║  │  • 即時型號搜尋            │  │  • Quick Prompt 捷徑        │ ║
║  │  • 選型結果表格            │  │  • Markdown 回答渲染        │ ║
║  └────────────────────────────┘  └────────────────────────────┘ ║
╚═════════════════════════════════════════════════════════════════╝
```

### 技術棧摘要

| 層次 | 技術選擇 | 角色 |
|---|---|---|
| 資料維護 | Google Sheets + gspread | 唯一資料入口，非工程師可操作 |
| 結構化資料庫 | MongoDB Atlas | 三層 Collection，product_specs 為查詢主層 |
| 向量搜尋 | MongoDB Atlas Vector Search | 原生整合於 Atlas，`$vectorSearch` pipeline 支援 pre-filter |
| 統一後端框架 | FastAPI | 統一處理選型條件篩選 API 與 RAG Pipeline 執行，支援 Pydantic 驗證與非同步處理 |
| LLM / Embedding | Google Gemini | 意圖解析、Embedding（text-embedding-004）、Re-ranking、報告生成 |
| 前端 | HTML + Vanilla JS | 篩選頁 + Chatbot 浮動面板 |
| 環境與套件管理 | uv | 提供極速的 Python 虛擬環境建立，透過 `uv.lock` 確保開發/維運環境套件版本絕對一致 |

---

## 三、完整資料流程

### 3.1 資料維護寫入流程（Google Sheets → MongoDB）

這是整個系統的**資料根源**，決定 AI 能查到什麼資料。

```
┌─────────────────────────────────────────────────────────────────┐
│                     Google Sheets 資料維護                       │
│  PM/RD 在 Google Sheet 新增或修改型號資料                        │
│  [Ind SW / Train SW Tab]                                        │
│   product_pn | model_name | software_series | firmware_ver      │
│   application | lifecycle | rj45_gige | fiber_gige | ...        │
│  [SW Specs Tab]                                                 │
│   software_series | firmware_ver | vlan_802_1q | rstp |        │
│   iec_61850 | profinet | mrp | ieee_802_1x | ...               │
│   (三態值：● = full / ○ = optional / - = no)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                  工程師執行 sync_specs_to_mongo.py
                             │
                    STEP 1: 讀取與驗證
                    - 驗證 ERROR 級（FK斷鍊/PoE超限等）
                    - 驗證 WARN 級（Port總數不符等）
                    - 輸出 validation_report.json
                    - BLOCKED 型號不寫入 product_specs
                             │
                    STEP 2: 資料轉換與展開
                    expand_series()：
                    "EKI-5700/7400/7700" + fw "1.03.XX"
                    → EKI-5700::1.03.XX
                    → EKI-7400::1.03.XX
                    → EKI-7700::1.03.XX

                    mark_latest()：同系列多版本標記 is_latest

                    三態值正規化：● → "full" / ○ → "optional" / - → "no"
                             │
                    STEP 3: 寫入 MongoDB
                    ① upsert hardware_specs（by product_pn）
                    ② upsert software_specs（by series::fw_ver）
                    ③ merge HW + SW → upsert product_specs（非BLOCKED才寫）
                    ④ 確認 Compound Index 存在
                             │
                             ▼
                  ✅ 選型工具與 AI 即時感知新資料
```

> **設計關鍵**：`product_specs` 永遠是 Hardware + Software 的最新合併結果，禁止手動寫入，確保單一真相來源（Single Source of Truth）。

---

### 3.2 軟硬體篩選查詢流程

```
使用者在前端設定篩選/搜尋條件
  固定條件：
    管理類型（Managed/Unmanaged）
    Port 數量（8/16/24...）
  即時搜尋欄（輸入關鍵字）：
    可搜尋清單包含 76 項（硬體條件 11項 + 軟體功能 65項）
        │
        ▼
【即時搜尋】GET /api/searchProdType?q=VLAN
      → FastAPI 進行模糊比對（大小寫不敏感）
      → 回傳排序後的符合「特徵條件清單」（例如：VLAN 802.1Q）讓 user 在下拉選單選取
        │
        ▼（使用者將選取的特徵作為條件加入，並按下送出）
【條件篩選】POST /api/submitProdType
      body: { items: ["vlan_802_1q", "profinet", ...], type: "Managed", portnum: 8 }
        │
        ▼
FastAPI → MongoDB product_specs 基本與進階過濾 (Query Builder)
  基本條件 (利用 Dict mapping 轉換為 MongoDB query)：
    - function: "Managed"
    - total_port_count: 8
  特徵條件 (items)：
    - software.l2_switching.vlan_802_1q 用 $in: ["full", "in_development", "optional"] 查詢
  回傳條件：
    - lifecycle: { "$ne": "EOL" }
    - is_latest: true
        │
        ▼
回傳 products[] → 前端渲染表格
  ↓ 同時更新
acquiredModels[] ← prod_name（完整料號）
        │
        ▼
Chatbot contextBar 自動更新：
  「AI 已鎖定分析：EKI-7720G、EKI-7710E（共2個型號）」
```

---

### 3.3 RAG Chatbot 查詢流程（核心）

這是整個系統最複雜的部分，採用**五階段 Hybrid Retrieval 架構**：

```
使用者在 Chatbot 輸入自然語言問題
例：「我需要在鐵路車廂部署，要支援IEC61850，寬溫，有哪些推薦？」
        │
        ▼
前端打包 payload 送出 POST /api/chat
  {
    message: "我需要在鐵路...",
    context: {
      selected_models: ["EKI-7720G-4F1-AE", ...],  ← 硬體篩選鎖定的型號
      filters: { type: "Managed", portnum: 8 }
    },
    history: [{ role, content }, ...].slice(-12)     ← 最近 12 筆對話
  }
        │
        ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STAGE 1：關鍵字意圖解析（Gemini LLM）

  輸入：使用者自然語言問題
  輸出：結構化 JSON
  {
    "filter": {
      "application": "Rolling Stock",   ← 從問句中抽取
      "function": null,
      "has_poe": null,
      "temp_grade": "Wide",             ← 「寬溫」→ "Wide"
      "port_count_min": null
    },
    "software_requirements": ["iec_61850"],  ← 軟體功能清單
    "semantic_query": "鐵路車廂部署推薦選型"  ← 語意查詢殘餘部分
  }
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STAGE 2：關鍵字比對 ── MongoDB Hard Filter

  以 intent JSON + context.selected_models 建構 Mongo Query：
  base_filter：lifecycle != EOL，is_latest = true
  + application = "Rolling Stock"
  + temp_grade  = "Wide"
  + software iec_61850 = "full" 或 "optional"（展開為 $or）
  + 若 selected_models 非空：product_pn 限縮在此集合內

  OUTPUT：候選型號子集（通常 3~20 筆）+ product_pn 列表
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼ candidate_pns = ["EKI-6xx", "EKI-7xx", ...]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STAGE 3：語意匹配 ── MongoDB Atlas Vector Search

  query_text = intent["semantic_query"]
  → Gemini text-embedding-004 將 query_text 轉為 768 維向量

  使用 MongoDB Aggregation Pipeline $vectorSearch：
  {
    "$vectorSearch": {
      "index": "datasheet_vector_index",
      "path": "embedding",
      "queryVector": <768-dim float array>,
      "numCandidates": 100,
      "limit": 10,
      "filter": { "product_pn": { "$in": candidate_pns } }
    }                ↑ pre-filter：只在 Hard Filter 子集內搜尋
  }

  → 返回 cosine 相似度最高的 10 個 Datasheet chunk
  → 同一次 Pipeline 可用 $project 附帶 vectorSearchScore

  OUTPUT：10 個 chunk（含 text、product_pn、source、vectorSearchScore）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼ top10_chunks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STAGE 4：LLM Re-ranking（Gemini）

  INPUT：使用者問題 + 10個候選型號摘要（來自 MongoDB）
  Gemini 為每個候選型號評分（0~10）：
  [
    { "product_pn": "EKI-7xxx", "score": 9,
      "reason": "完整支援IEC61850，Wide Temp -40~75°C" },
    { "product_pn": "EKI-6xxx", "score": 6,
      "reason": "支援IEC61850但僅optional，非完整" },
    ...
  ]

  → 按 score 排序，取 top-3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼ top3_pns
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STAGE 5：報告生成（Gemini）

  INPUT：
    - 使用者問題
    - 對話歷史 history（上下文理解）
    - top-3 型號的完整 product_specs（從 MongoDB product_specs 撈取）
    - top-3 對應的 Datasheet chunk 原文（來自 MongoDB datasheet_chunks）

  Gemini 根據真實規格資料生成回答
  → 格式：Markdown（含表格、清單、推薦理由）
  → 語言：繁體中文
  → 必須有根據，禁止幻覺

  OUTPUT：
  {
    "answer": "## 鐵路場景推薦型號\n...",
    "referenced_models": ["EKI-7xx", "EKI-6xx", "EKI-5xx"],
    "sources": ["Datasheet片段1...", "片段2...", "片段3..."]
  }
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        │
        ▼
前端 Chatbot 渲染：
  ✅ Markdown 回答（含型號推薦表格）
  ✅ 參考型號徽章（referenced_models）
  ✅ 可展開的規格原文來源（sources）
```

---

## 四、各層元件詳細設計

### 4.1 資料維護層 — Google Sheets

#### 工作表結構

| Tab | 維護者 | 每列代表 | 關鍵欄位 |
|---|---|---|---|
| `Ind SW` | PM / RD 硬體組 | 一台工業型設備 | product_pn, software_series, firmware_ver, application |
| `Train SW` | PM / RD 硬體組 | 一台車載型設備 | product_pn, software_series, firmware_ver, application |
| `SW Specs` | SW 軟體組 | 一個系列 × 一個 fw 版本 | software_series, firmware_ver, 各功能三態值 |

#### 三態值規範

| Google Sheet 顯示 | 語意 | MongoDB 存入 |
|---|---|---|
| `●` | 完整內建支援 | `"full"` |
| `○` | 還在開發 (In Development) | `"in_development"` |
| `-` | 不支援 | `"no"` |
| 空白 | 尚未填寫 | `""` → 視為 WARN |

#### Application 標準值清單（需 PM 確認鎖定）

| 值 | 適用場景 |
|---|---|
| `Industrial` | 一般工廠、製造業 |
| `Smart Factory` | 智慧工廠 / OT 網路 |
| `Substation` | 電力變電站 |
| `Rolling Stock` | 鐵路車廂 |
| `Trackside` | 鐵路軌旁設備 |
| `General Purpose` | 通用型，無特定場景 |

> ⚠️ **此清單一旦鎖定不可隨意增加**，新增需走正式變更流程（影響：Sheet 下拉、MongoDB Index、前端 UI、RAG Query Expansion 對應表）

---

### 4.2 資料庫層 — MongoDB

#### Collection 設計（三層架構）

**`hardware_specs`** — 一份文件 = 一台設備的硬體規格
```json
{
  "product_pn": "EKI-7720G-4F1-AE",
  "model_name": "EKI-7720G",
  "software_series": "EKI-7700",
  "firmware_ver": "1.03.XX",
  "application": "Industrial",
  "lifecycle": "Active",
  "filter": {
    "application": "Industrial",
    "function": "Managed",
    "port_count": 8,
    "has_poe": false,
    "has_fiber": true,
    "temp_grade": "Wide"
  },
  "hardware": {
    "ports": { "rj45_100m": 0, "rj45_gige": 4, "fiber_gige": 4 },
    "poe": { "poe_gige": 0, "power_budget_w": 0 },
    "power": { "input_voltage": "12~48 VDC" },
    "environment": { "op_temp": "-40~75°C", "temp_grade": "Wide" }
  }
}
```

**`software_specs`** — 一份文件 = 一系列 × 一 fw 版本
```json
{
  "_id": "EKI-7700::1.03.XX",
  "software_series": "EKI-7700",
  "firmware_ver": "1.03.XX",
  "is_latest": true,
  "software": {
    "l2_switching": { "vlan_802_1q": "full", "rstp_802_1w": "full" },
    "redundancy":   { "xring_pro": "full", "erps_g8032": "full" },
    "security":     { "ieee_802_1x": "full", "iec_62443_4_2": "optional" },
    "management":   { "snmp_v3": "full", "profinet": "optional" },
    "vertical_market": { "ieee_1588v2_ptp": "full", "iec_61850": "no" }
  }
}
```

**`product_specs`** — 禁止手動編輯，由同步腳本自動合併
```json
{
  "product_pn": "EKI-7720G-4F1-AE",
  "software_series": "EKI-7700",
  "firmware_ver": "1.03.XX",
  "is_latest": true,
  "lifecycle": "Active",
  "filter": { /* 完整複製自 hardware_specs.filter */ },
  "hardware": { /* 完整複製自 hardware_specs.hardware */ },
  "software": { /* 完整複製自 software_specs.software */ },
  "_synced_at": "2026-04-17T10:30:00Z"
}
```

#### MongoDB Index 設計

```python
# 選型工具主要篩選欄位（Compound Index）
db.product_specs.create_index([
    ("filter.application", 1),
    ("filter.function",    1),
    ("filter.port_count",  1),
    ("filter.has_poe",     1),
    ("filter.temp_grade",  1),
], name="idx_filter_compound")

# 快速過濾輔助 Index
db.product_specs.create_index("lifecycle",       name="idx_lifecycle")
db.product_specs.create_index("software_series", name="idx_sw_series")
db.product_specs.create_index("firmware_ver",    name="idx_fw_ver")
db.product_specs.create_index("is_latest",       name="idx_is_latest")
```

---

### 4.3 向量搜尋層 — MongoDB Atlas Vector Search

> **架構調整說明**：原規劃使用獨立的 ChromaDB 服務，現改為利用 **MongoDB Atlas 原生向量搜尋**能力，將 Datasheet chunk 存入同一個 Atlas 實例，透過 `$vectorSearch` aggregation stage 執行語意搜尋。

#### 為何改用 Atlas Vector Search？

| 比較面向 | ChromaDB（原方案） | Atlas Vector Search（新方案） |
|---|---|---|
| **系統複雜度** | 需額外部署、維護獨立服務 | 同一個 Atlas 連線，無需額外服務 |
| **pre-filter 整合** | `where` 條件需單獨維護 | `$vectorSearch.filter` 與 MongoDB query 語法一致 |
| **安全性** | 需額外設定防火牆/認證 | 共用 Atlas 帳號、IP Whitelist、VPC |
| **擴展性** | 本地部署有上限 | Atlas M10+ 自動擴展，全託管 |
| **成本** | 需額外伺服器 | Atlas M10 起步已包含 Vector Search |
| **缺點** | — | **需要 Atlas M10 以上方案**（M0 免費層不支援）；embedding 維度固定後需重建 index |

> ⚠️ **前置條件**：Atlas 叢集需升至 **M10 以上**才能建立 Vector Search Index。如目前使用 M0 免費層，需確認可接受升級費用，或評估保留 ChromaDB 的替代方案。

#### 資料建置流程

```
PDF Datasheet
     ↓
pdfplumber / pypdf2 → Markdown 文字
     ↓
清洗處理：
  • 移除頁首/頁尾、版權聲明
  • 表格轉可讀文字
  • 移除重複段落
     ↓
Chunking：500 tokens / chunk，重疊 50 tokens
     ↓
embed_chunks.py：
  ① Gemini text-embedding-004 生成向量（768 維）
  ② upsert 寫入 MongoDB datasheet_chunks collection
  ③ 增量模式：已存在 chunk_id 則跳過（by chunk_id upsert）
```

#### `datasheet_chunks` Collection Schema

```json
{
  "_id":        "EKI-7720G-chunk-003",
  "chunk_id":   "EKI-7720G-chunk-003",
  "product_pn": "EKI-7720G",
  "model_name": "EKI-7720G",
  "source":     "datasheet_EKI-7720G.md",
  "chunk_idx":  3,
  "text":       "EKI-7720G supports IEC 61850 with optional license...",
  "embedding":  [0.012, -0.843, 0.231, ...]  // 768-dim float array
}
```

#### Atlas Search Index 定義（需在 Atlas UI 或 API 建立）

```json
{
  "name": "datasheet_vector_index",
  "type": "vectorSearch",
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 768,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "product_pn"
    }
  ]
}
```

> **注意**：`product_pn` 必須同時宣告為 `"type": "filter"` 欄位，`$vectorSearch` 的 `filter` 參數才能正常運作。

#### embed_chunks.py 核心邏輯

```python
def embed_and_upsert(chunks: list[dict]):
    for chunk in chunks:
        # 已存在則跳過（增量模式）
        if db.datasheet_chunks.find_one({"_id": chunk["chunk_id"]}):
            continue

        # Gemini Embedding
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=chunk["text"]
        )
        chunk["embedding"] = result["embedding"]  # list[float], len=768
        chunk["_id"] = chunk["chunk_id"]

        db.datasheet_chunks.insert_one(chunk)
```

#### $vectorSearch 查詢範例（Stage 3 使用）

```python
def vector_search_in_subset(query_vector: list[float], candidate_pns: list[str], top_k: int = 10):
    pipeline = [
        {
            "$vectorSearch": {
                "index": "datasheet_vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": top_k * 10,  # 建議為 limit 的 10 倍
                "limit": top_k,
                "filter": { "product_pn": { "$in": candidate_pns } }  # pre-filter
            }
        },
        {
            "$project": {
                "_id": 0,
                "chunk_id": 1,
                "product_pn": 1,
                "text": 1,
                "source": 1,
                "score": { "$meta": "vectorSearchScore" }
            }
        }
    ]
    return list(db.datasheet_chunks.aggregate(pipeline))
```

> **設計關鍵**：`filter.product_pn.$in` 將向量搜尋範圍限制在 Hard Filter 的候選子集內，與 ChromaDB 方案的 `where` 條件功能等效，且語法一致性更好（全部都是 MongoDB query 語法）。

---

### 4.4 RAG 後端服務 — FastAPI

#### 端點設計

```
POST /api/chat
Request Body:
{
  "message": "str",
  "context": {
    "selected_models": ["EKI-7720G-4F1-AE", ...],
    "filters": { "type": "managed", "portnum": 8 }
  },
  "history": [{ "role": "user/assistant", "content": "str" }]
}

Response:
{
  "answer": "## Markdown 格式回答...",
  "referenced_models": ["EKI-7720G", "EKI-7710E"],
  "sources": ["chunk原文片段1", "片段2", "片段3"]
}
```

#### 異常處理設計

| 情境 | 處理方式 |
|---|---|
| Stage 1：Gemini 回傳非 JSON | strip Markdown wrapper，retry 一次，失敗則回傳空 filter |
| Stage 2：Hard Filter 無結果 | 直接回傳「找不到符合條件型號」，不執行後續 Stage |
| Stage 3：$vectorSearch 0 結果 | 退回純 MongoDB 摘要，跳過 Re-ranking |
| Stage 3：Atlas M10 未升級 | Vector Search Index 不可用 → 需確認 Atlas 方案等級 |
| Stage 5：Gemini API timeout | 回傳錯誤訊息，建議使用者縮短問題 |

---

### 4.5 選型後端服務 — FastAPI 實作規範 (取代 Flask)

為了簡化架構，提昇開發體驗與效能，**前端篩選 API 已統一整合至 FastAPI，與 RAG Chatbot 共用服務。**

#### 開發方向與程式碼品質要求

1. **Pydantic 強型別驗證**
   - 定義明確的 Request / Response Schema（例如 `SubmitProdRequest`, `ProductItemResponse`）。
   - 對於 `portnum` 與 `type` 實作 validator：確保型別正確與合法範圍（如 `"Managed", "Unmanaged"`），遇到無效值會被 FastAPI 自帶的機制拋出 400 Bad Request 錯誤。

2. **MongoDB 單例模式 (Singleton Pattern)**
   - 資料庫連線在 FastAPI `lifespan` ( startup 階段) 建立一次，整個 App 生命週期內共用 `MongoClient`，絕不在每個 API Request 內重建連線，優化效能。
   
3. **優雅的條件轉換設計 (Dict & Callable Mapping)**
   - 拋棄冗長的 `if/elif` 串接判斷，改用 `Map` (Dictionary) 搭配 Callable 函數來處理 76 項功能條件的 MongoDB Filter 構建。
   - 範例架構：
     ```python
     CONDITION_MAPPING = {
       "vlan_802_1q": lambda v: {"software.l2_switching.vlan_802_1q": {"$in": ["full", "in_development"]}},
       "has_poe": lambda v: {"filter.has_poe": True}
     }
     ```

4. **將運算推向資料庫層 (Query Layer)**
   - 基本的過濾（`Function`、`Port_Numbers`），以及進階的 `items`，全部組裝成單一的 `{"$match": {...}}`，讓 MongoDB 進行篩選。
   - 撈取產品時使用 `$in` 來比對相關查詢，絕對禁止在 Python 端寫雙重迴圈 (`for` 迴圈內呼叫 DB) 過濾。

5. **系統防禦與錯誤處理**
   - 加入全域的 Exception Handler 擷取 `PyMongoError`，紀錄 Log 後統整包裝為易懂的 500 錯誤。
   - 配置 FastAPI 自帶的 `CORSMiddleware`。
   - 要求所有新增的 Python 檔案需包含清楚的**繁體中文註解**描述其特定意圖與實作模式。

---

### 4.6 前端介面

#### Chatbot Context 同步機制（核心設計）

```javascript
// 硬體篩選結果 → Chatbot context 的資料流
function submitItems() {
    fetch('/api/submitProdType', { body: JSON.stringify({...}) })
    .then(res => res.json())
    .then(data => {
        renderTable(data.products);                             // ① 更新表格
        acquiredModels = data.products.map(p => p.prod_name);  // ② 更新 acquiredModels
        updateContextBar();                                     // ③ Chatbot 立即感知
    });
}

function updateContextBar() {
    const models = [...new Set([...selectedItems, ...acquiredModels])];
    contextBar.textContent = models.length > 0
        ? `AI 已鎖定分析：${models.join('、')}（共${models.length}個型號）`
        : "尚未鎖定任何型號，AI 將在全庫搜尋";
}

// 送出 Chat 時打包完整 payload
function sendMessage() {
    const payload = {
        message: userInput.value,
        context: {
            selected_models: [...new Set([...selectedItems, ...acquiredModels])],
            filters: { type: mgmtType.value, portnum: numInput.value }
        },
        history: chatHistory.slice(-12)
    };
    fetch('http://RAG_HOST:8000/api/chat', { body: JSON.stringify(payload) });
}
```

---

### 4.7 開發環境與套件版本控管 — uv

> **架構設計說明**：為了確保多名開發者（API、爬蟲腳本開發）以及未來 CI/CD 執行時的 Python 環境與套件版本完全同步，本專案全面導入 **[uv](https://github.com/astral-sh/uv)** 取代傳統的 `pip` 與 `requirements.txt`。

#### 為什麼選擇 uv？
1. **極速套件解析與安裝**：使用 Rust 開發，安裝速度為傳統 pip 的數十倍，大幅降低環境建置時間。
2. **單一工具管理**：同時取代 `pyenv`, `virtualenv`, `pip`, `pip-tools` 的職能。
3. **精確的版本鎖定**：透過 `uv.lock` 確實鎖定所有子相依套件版本，徹底消除「我的電腦上可以跑」的環境不一致問題。

#### 環境同步流程
```bash
# 1. 首次建置環境（讀取 pyproject.toml 與 uv.lock，並自動建立 .venv）
uv sync

# 2. 新增套件（例如新增 FastAPI）
uv add fastapi

# 3. 執行腳本（無需手動啟動虛擬環境）
uv run scripts/sync_specs_to_mongo.py
```
> **要求**：所有 Python 開發者都必須將專案根目錄的 `uv.lock` 與 `pyproject.toml` 納入 Git 版控。開發過程中不允許直接使用 `pip install`。

---

## 五、RAG Pipeline 深度設計

### 5.1 為何採用 Hard Filter 優先策略

```
❌ 純語意搜尋的問題：
   「支援IEC61850的寬溫型號」
   → 向量相似度可能找到描述「IEC61850是什麼」的說明性chunk
   → 而不是真正支援此功能的型號spec
   → 語意漂移（Semantic Drift）

✅ 本系統的解法：
   先用關鍵字/結構化條件從MongoDB精確篩出支援iec_61850的型號集合
   → 向量搜尋只在這個子集內執行
   → 100%確保回傳的型號確實支援該功能
   → 語意搜尋負責「哪個型號描述最詳細、最符合使用場景」
```

### 5.2 關鍵字意圖解析的 Prompt 設計

```python
INTENT_PROMPT = """
你是 Advantech 工業交換機選型助理。
請從使用者問題中**精確抽取**結構化條件，只抽取問題中明確提到的條件，不可推斷。
回傳純 JSON（不加任何 Markdown 包裹）：
{
  "filter": {
    "application": null,        // 只能填："Industrial"/"Rolling Stock"/"Substation"/"Smart Factory"/"Trackside"/"General Purpose"/null
    "function": null,           // 只能填："Managed"/"Unmanaged"/null
    "has_poe": null,            // true/false/null
    "temp_grade": null,         // "Wide"/"Normal"/null（Wide = 寬溫/工業級溫度）
    "port_count_min": null      // 整數/null
  },
  "software_requirements": [],  // 從已知功能名稱選：["iec_61850","profinet","mrp_iec62439_2","ieee_1588v2_ptp","snmp_v3","ieee_802_1x"]
  "semantic_query": ""          // 無法結構化的剩餘語意，給 Atlas Vector Search 做向量搜尋用
}

使用者問題：{user_query}
"""
```

### 5.3 軟體功能 MongoDB Query 展開

由於 MongoDB 不支援 `software.*.feature` 萬用字元路徑，需展開為 `$or`：

```python
SW_CATEGORIES = ["l2_switching", "redundancy", "security", "management", "vertical_market"]

def build_sw_filter(software_requirements: list[str]) -> dict:
    """將軟體功能需求展開為 MongoDB $or 條件"""
    conditions = []
    for feat in software_requirements:
        for category in SW_CATEGORIES:
            conditions.append({
                f"software.{category}.{feat}": {"$in": ["full", "optional"]}
            })
    return {"$or": conditions} if conditions else {}
```

### 5.4 Re-ranking Prompt 設計

```python
RERANK_PROMPT = """
你是工業交換機選型專家。根據使用者需求，對以下候選型號評分（0~10）。
評分標準：
  - 10分：完全符合所有要求
  - 7~9分：符合主要要求，次要需求部分符合
  - 4~6分：符合部分要求
  - 1~3分：只符合基本條件

回傳純 JSON 陣列（不加 Markdown 包裹）：
[{"product_pn": "...", "score": 8, "reason": "50字以內的理由"}]

使用者需求：{user_query}
候選型號規格摘要：{candidates_json}
"""
```

### 5.5 報告生成 Prompt 設計

```python
REPORT_PROMPT = """
你是 Advantech 工業交換機選型 AI 助手。
請根據以下**真實規格資料**回答使用者問題。

規則：
1. 只能引用以下規格資料中存在的資訊，禁止推斷或捏造規格
2. 回答使用**繁體中文**，格式使用 **Markdown**
3. 推薦型號時必須說明具體理由（對應哪個規格符合需求）
4. 如果規格資料不足以回答問題，請明確說明「資料不足」

使用者問題：{user_query}

對話上下文（最近12輪）：
{history}

最相關型號規格（top-3，已由 AI 評分排序）：
{top3_specs_json}

相關 Datasheet 原文片段：
{datasheet_chunks}
"""
```

---

## 六、開發階段規劃

### 開發優先順序

```
F0  ★★★  資料格式確認（Application清單鎖定、欄位規格書）  ← 所有後續的前置依賴
 ↓
F1  ★★★  Google Sheet 建置（三個Tab + 公式 + 下拉 + 條件格式）
 ↓
F2  ★★★  Sync腳本（expand_series / mark_latest / validate / upsert）
 ↓
F3  ★★   選型API（Flask串接MongoDB）              ─┐
F4  ★★★  RAG AI助理（FastAPI，五階段Pipeline）     ├── 可平行開發
F7  ★★   Atlas Vector Search Index建置與維護      ─┘
 ↓
F5  ★★   前端整合（Application篩選 + context同步確認）
 ↓
F6  ★    規格比對頁（最後開發，獨立功能）
 ↓
F8  ★★   驗證、SOP、維運文件（貫穿全程）
```

### 分段驗收閘門

| Gate | 時機 | 驗收標準 |
|---|---|---|
| **G0** | F0 完成 | Application 標準值清單書面鎖定，欄位規格書各角色確認 |
| **G1** | F1 完成 | Sheet 三個 Tab 可手動填入，firmware_ver 下拉連動，Service Account 可讀 |
| **G2** | F2 完成 | `validation_report.json` 無 ERROR，三層 Collection 資料正確，Index 建立 |
| **G3** | F3 完成 | API 回傳正確型號，`prod_name` 欄位存在，前端表格正確渲染 |
| **G4** | F4 完成 | RAG 五階段流程全通，AI 回答有規格依據，referenced_models 正確顯示 |
| **G5** | F5 完成 | 端對端流程：篩選 → contextBar → Chatbot → 正確回答（限縮在鎖定型號） |

### 週次路線圖

```
Week 1
  ├── [F0] Application 標準值清單確認（最優先）
  ├── [F0] 欄位規格書，各角色確認
  ├── [F0] 使用 uv init 建立 Python 環境與 pyproject.toml，並提交版控
  └── [F1] Google Sheet 三個 Tab + 公式 + 條件格式 + firmware_ver

Week 2
  ├── [F1] Service Account 設定，gspread 讀取測試
  ├── [F8] PM/RD 填入初始資料
  └── [F2] Sync 腳本：expand_series / mark_latest / validate / upsert → G2

Week 3
  ├── [F3] Flask 選型 API 串接 MongoDB → G3
  ├── [F4] RAG：意圖解析 + Hard Filter + Atlas Vector Search
  └── [F7] Atlas Search Index 建立 + embed_chunks.py 增量更新測試

Week 4
  ├── [F4] Re-ranking + 報告生成 → G4
  ├── [F5] 前端 Application 篩選 + 端對端整合 → G5
  └── [F8] SOP 文件化

Month 2
  ├── [F6] spec_viewer.html 規格比對頁
  ├── [F7] Datasheet 補充 + Atlas Vector Search Index 重建（需要時）
  └── 壓力測試 + 效能調優（numCandidates 參數調整）

未來規劃
  ├── Sync 腳本定期排程（cron / Cloud Scheduler）
  ├── MongoDB Schema Validation 強化
  └── Admin UI 評估
```

---

## 七、風險評估與對策

| 風險 | 影響 | 對策 |
|---|---|---|
| Application 標準值未及時鎖定 | 高：Block 所有後續 Epic | F0 為 Week 1 最高優先，設 G0 閘門 |
| Gemini 意圖解析 JSON 格式錯誤 | 中：RAG 失敗 | Prompt 強調「不加 Markdown」，加 strip/retry 保護 |
| Atlas M10 以下方案不支援 Vector Search | 高：Stage 3 完全不可用 | 確認 Atlas 叢集等級，M0 需升級才能建 Vector Search Index |
| $vectorSearch filter 欄位未宣告 | 高：pre-filter 失效，搜尋全庫 | Index JSON 中 product_pn 必須同時宣告 `"type": "filter"` |
| embedding 維度改變需重建 Index | 中：Index 與資料不相容 | 鎖定 text-embedding-004（768 維），變更需重建 Index + 重跑 embed |
| MongoDB soft 功能路徑萬用字元 | 中：篩選結果不正確 | 展開為 $or 條件，已有對策（D8） |
| 前端 prod_name vs prod_model 混用 | 高：Chatbot context 型號錯誤 | 在 G3 Gate 明確驗收 prod_name 欄位 |
| Token 超限（history 過長） | 中：API 報錯 | 前端 slice(-12)，後端再次確認長度 |

---

## 八、設計決策紀錄

| ID | 決策 | 狀態 | 說明 |
|---|---|---|---|
| D1 | 三態值以 `"full"/"optional"/"no"` 存儲，不轉布林 | ✅ 確認 | 保留「選配」語意，布林無法表達三態 |
| D2 | 資料維護透過 Google Sheets，不建 Admin UI | ✅ 確認 | 降低開發成本，非工程師可操作 |
| D3 | SW Series 複合名在腳本自動展開 | ✅ 確認 | 降低 PM 維護複雜度，PM 不需手動拆分 |
| D4 | `(software_series, firmware_ver)` 為 software_specs 複合主鍵 | ✅ 確認 | 保留不同 fw 版本的規格差異 |
| D5 | Hard Filter 優先於向量搜尋 | ✅ 確認 | 避免語意漂移，確保軟體功能 100% 召回精準 |
| D6 | 向量搜尋限制在 Hard Filter 候選子集內 | ✅ 確認 | `$vectorSearch.filter.product_pn.$in` 是關鍵 |
| D7 | LLM Re-ranking 作為第四層 | ✅ 確認 | 向量相似度不等於業務相關性，LLM 補足語意判斷 |
| D8 | 軟體功能 MongoDB 查詢展開為多個 `$or` 條件 | ✅ 確認 | MongoDB 萬用字元路徑不適用此場景 |
| D9 | Chatbot 感知篩選結果（selected_models context） | ✅ 確認 | AI 回答範圍聚焦在業務已初篩的型號 |
| D10 | 向量資料庫由 ChromaDB 改為 MongoDB Atlas Vector Search | ✅ 確認 | 統一資料庫平台，降低維運複雜度；需確認 Atlas M10+ 方案 |
| D11 | Embedding 模型鎖定 Gemini text-embedding-004（768 維） | ✅ 確認 | 維度鎖定後 Index 不可更改維度，需重建整個 Index |
| D12 | 採用 uv 進行 Python 環境控管 | ✅ 確認 | 取代標準 pip / requirements.txt，透過 uv.lock 保證跨環境執行完全一致，並且安裝極快 |

---

*文件維護：每次架構決策變更後請更新「設計決策紀錄」章節，更新頂部版本號與日期。*
