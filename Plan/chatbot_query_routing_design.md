# Chatbot Query Routing 設計方案

## 問題核心

使用者問題千變萬化，不能全部用同一條 RAG Pipeline 處理。
目前的 5-Stage Pipeline 是為「應用情境型」設計的，但實際上有三種截然不同的問題類型。

---

## 三種問題類型分析

### Type A：應用情境型（Scenario Query）

**特徵**：描述使用場景、環境需求、應用目的，尋求推薦。

**範例：**
- 「我需要在鐵路車廂部署，要支援 IEC61850，寬溫，有哪些推薦？」
- 「工廠自動化環境，需要支援 PROFINET 的 Managed Switch」
- 「要部署在戶外變電站，防護等級要高，有沒有合適的型號？」

**問題本質**：用戶**不知道**要選哪個型號，需要 AI 幫他縮小範圍並推薦。

**最佳處理方式**：現有的完整 5-Stage Pipeline
```
Intent Parse → Hard Filter → Vector Search → Re-rank → Report Gen
```

---

### Type B：規格查詢 / 指定型號型（Model-Specific Query）

**特徵**：使用者**已知道**型號，想了解特定規格或比較兩個型號。

**兩個子類型：**

**B1 — 單一型號規格查詢**
- 「EKI-7720G 支援 IEC61850 嗎？」
- 「EKI-5526I-MB 的最大 PoE 功率是多少？」
- 「EKI-9528E 的工作溫度範圍？」

**B2 — 多型號比較查詢**
- 「幫我比較 EKI-7720G 和 EKI-7710E 的差異」
- 「EKI-5528 和 EKI-5526 哪個比較適合鐵路場景？」

**問題本質**：用戶**已鎖定型號**，需要精確規格資料，不需要廣泛搜索。

**最佳處理方式**：跳過 Stage 1-2，直接查 MongoDB 結構化資料
```
跳過 Hard Filter → 指定型號 Vector Search → 結構化規格讀取 → 直接回答/比較表
```

---

### Type C：片面問題型（Vague / Ambiguous Query）

**特徵**：問題資訊嚴重不足，無法執行任何有意義的搜索。

**範例：**
- 「有什麼好的交換機？」
- 「幫我選一個」
- 「哪個比較好？」（沒有任何上下文）
- 「推薦一款」

**問題本質**：用戶不知道自己要什麼，AI 需要反問引導，而不是亂猜。

**最佳處理方式**：直接回傳引導式追問，完全不走 RAG Pipeline
```
產生 Clarification Questions → 直接回傳引導訊息
```

---

## 設計方案：Query Router（查詢路由器）

在現有 5-Stage 之前，新增一個 **Stage 0：Query Classification**。

```
使用者問題
     │
     ▼
┌─────────────────────────────────┐
│  Stage 0: Query Router          │
│  (LLM 快速分類，< 1 秒)          │
│                                 │
│  回傳：                          │
│  {                              │
│    query_type: A | B | C        │
│    specified_models: [...]      │
│    missing_info: [...]          │
│    confidence: 0.0~1.0         │
│  }                              │
└────────────┬────────────────────┘
             │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
 Type A     Type B    Type C
全 5-Stage  規格查詢   反問引導
Pipeline    Pipeline   Response
```

---

## Stage 0：Query Classifier 的 Prompt 設計

```python
CLASSIFY_PROMPT = """
你是 Advantech 工業交換機 Chatbot 的問題分類器。
請分析使用者問題，判斷屬於哪種查詢類型，回傳純 JSON。

分類規則：
- "scenario"：描述應用場景/環境/需求，尋求型號推薦（不知道要選哪個）
- "model_specific"：問題中明確提到具體型號（如 EKI-7720G），要查規格或比較
- "vague"：問題資訊嚴重不足，無法理解用戶真正需求

回傳格式（純 JSON，不加 Markdown）：
{
  "query_type": "scenario" | "model_specific" | "vague",
  "specified_models": [],   // 若 query_type=model_specific，填入使用者提到的型號列表
  "missing_info": [],       // 若 query_type=vague，列出缺少的關鍵資訊，從以下選：
                            // "application"（使用場景）、"function"（Managed/Unmanaged）、
                            // "port_count"（Port 數量）、"features"（需要哪些功能）
  "confidence": 0.0         // 分類信心值 0.0~1.0
}

使用者問題：{user_query}

對話歷史摘要（如果有）：{history_summary}
"""
```

> **設計關鍵**：要把 `history_summary` 傳進去！
> 例如前一輪用戶說「我要部署在工廠」，這一輪問「有幾個 Port？」
> Router 需要知道上下文才能判斷這不是 vague query。

---

## 各 Query Type 的完整處理流程

### Type A — 情境型（現有 5-Stage，微調）

```
Stage 1: Intent Parse（Gemini Flash）
  → 抽出 filter + software_requirements + semantic_query

Stage 2: Hard Filter（MongoDB）
  → 若 selected_models 非空（前端已篩選）→ 在其中過濾
  → 若 selected_models 為空 → 全庫搜尋

Stage 3: Vector Search（Atlas）
  → 在 Hard Filter 候選型號的 chunks 中語意搜尋

Stage 4: Re-ranking（Gemini）
  → 從候選型號中選出 top-3

Stage 5: Report Gen（Gemini）
  → 生成推薦報告（Markdown 表格 + 推薦理由）
```

**何時進入此流程的判斷條件：**
- `query_type == "scenario"` 即走此流程，不需要額外判斷

---

### Type B — 規格/型號指定型（新增 Pipeline）

```
Stage B1: 型號驗證
  → 從 classifier 取得 specified_models
  → 在 MongoDB product_specs 驗證型號是否存在
  → 若型號不存在 → 回傳「找不到此型號，請確認料號是否正確」
  → 若只找到部分 → 列出找到的型號，說明未找到的

Stage B2: 結構化規格讀取
  → 直接 find({ model_name: { $in: specified_models } })
  → 取得完整 hardware + software specs

Stage B3: 語意補充（Vector Search）
  → 在指定型號的 chunks 中搜尋使用者問題的相關文字段落
  → 目的：找到 product_specs 之外的說明性文字（如應用場景描述）

Stage B4: 直接回答/比較表
  → 若單一型號：直接回答特定規格問題
  → 若多型號：生成規格比較表（Markdown 表格）
```

**單一型號規格回答範例：**
```
## EKI-7720G — IEC61850 支援狀態

| 功能 | 支援狀態 |
|------|---------|
| IEC 61850 | ✅ Full 完整支援 |
| IEEE 1588v2 PTP | ✅ Full 完整支援 |
| MRP (IEC 62439-2) | ⭕ Optional（需授權） |

📌 **結論**：EKI-7720G 完整支援 IEC61850，適合變電站/鐵路場景。
```

**多型號比較表範例：**
```
## EKI-7720G vs EKI-7710E 規格比較

| 規格項目 | EKI-7720G | EKI-7710E |
|---------|-----------|-----------|
| Port 數量 | 8 GbE + 4 SFP | 8 FE + 4 SFP |
| 工作溫度 | -40~75°C (Wide) | -10~60°C (Normal) |
| IEC 61850 | ✅ Full | ❌ 不支援 |
| 管理類型 | Managed | Managed |
| 適用場景 | 鐵路/變電站 | 一般工業 |

💡 **推薦**：若需要寬溫+IEC61850，選 EKI-7720G；若一般工廠使用且預算有限，EKI-7710E 足夠。
```

---

### Type C — 片面問題型（引導式追問）

**不走任何 RAG，直接根據 missing_info 生成追問。**

```python
CLARIFICATION_TEMPLATES = {
    "application": "請問這個交換機主要用在什麼環境？\n"
                   "（例如：工廠自動化、鐵路車廂、變電站、一般辦公室...）",
    
    "function":    "請問您需要的是 Managed（可管理型，支援 VLAN/QoS/冗餘）"
                   "還是 Unmanaged（即插即用，不需設定）交換機？",
    
    "port_count":  "請問大概需要幾個網路 Port？\n"
                   "（例如：8 Port、16 Port、24 Port）",
    
    "features":    "請問有沒有特別需要的功能？\n"
                   "（例如：PoE 供電、寬溫、特定通訊協定如 PROFINET/IEC61850...）",
}
```

**生成策略：只問最重要的 1~2 個問題，不要一次問太多。**

```
使用者：「有什麼好的交換機？」

missing_info = ["application", "function", "port_count", "features"]

→ 優先問最關鍵的 2 個（application + function）：

Chatbot 回覆：
「您好！為了推薦最適合的型號，我需要了解幾個基本需求：

1. **使用環境**：這個交換機主要用在哪裡？
   （工廠、鐵路車廂、變電站、一般辦公室...）

2. **管理需求**：需要可設定管理功能（如 VLAN、冗餘）嗎？
   還是只需要即插即用的設備？

有了這些資訊，我可以幫您精準推薦適合的型號！」
```

---

## 邊界情況處理

### 情況 1：前端已篩選型號 + 片面問題

```
用戶：「哪個比較好？」
前端 context：selected_models = ["EKI-7720G", "EKI-7710E"]
```

**處理方式**：Router 應該偵測到 context 中有 `selected_models`，
此時即使問題 vague，也可以做**比較**，自動走 Type B2 流程。

```python
# 在 Router 判斷前先檢查
if len(context.selected_models) >= 2 and query_is_vague:
    # 直接走比較流程
    return route_to_comparison(context.selected_models)
elif len(context.selected_models) == 1 and query_is_vague:
    # 展示這個型號的詳細資訊
    return route_to_single_model_detail(context.selected_models[0])
```

### 情況 2：多輪對話中的 vague 問題

```
第1輪：「我要部署在鐵路車廂」
第2輪：「有推薦嗎？」（看起來是 vague，但其實有上下文）
```

**處理方式**：Router 需接收 `history_summary`，
此時「有推薦嗎？」結合歷史語境，應判斷為 Type A（情境型），
semantic_query 繼承上一輪的應用情境。

### 情況 3：信心值低（Ambiguous）

```
用戶：「EKI 系列有哪些適合寬溫的？」
```

這介於 A 和 B 之間——提到了型號前綴但不是完整型號。
confidence 可能只有 0.6。

**處理方式**：`confidence < 0.7` 時，走 Type A（更保險），
但在 Hard Filter 中加入 `model_name: { $regex: "^EKI" }` 的額外條件。

---

## 實作建議：新增 `query_router.py`

```python
# app/rag/query_router.py

@dataclass
class RouteResult:
    query_type: str          # "scenario" | "model_specific" | "vague"
    specified_models: list   # 使用者提到的型號
    missing_info: list       # vague 時缺少的資訊
    confidence: float        # 分類信心值

def classify_query(user_query: str, context: dict, history: list) -> RouteResult:
    """
    Stage 0：快速分類使用者問題類型。
    使用 Gemini Flash（不是 Pro）保持低延遲。
    """
    # 1. 如果 context 已有 selected_models，優先考慮這個資訊
    if context.get("selected_models"):
        # 有鎖定型號的情況下，簡化分類邏輯
        ...
    
    # 2. 呼叫 LLM 分類
    history_summary = _summarize_history(history[-4:])  # 只看最近4輪
    prompt = CLASSIFY_PROMPT.format(
        user_query=user_query,
        history_summary=history_summary
    )
    result = gateway.call_json("classify", prompt)
    return RouteResult(**result)


def route(user_query: str, context: dict, history: list) -> str:
    """
    主入口：分類 → 路由到對應 Handler。
    回傳：formatted Markdown answer
    """
    route_result = classify_query(user_query, context, history)
    
    if route_result.query_type == "model_specific":
        return handle_model_specific(user_query, route_result.specified_models, context)
    
    elif route_result.query_type == "vague":
        # 特殊情況：前端有鎖定型號時，不走追問流程
        if context.get("selected_models"):
            return handle_model_specific(user_query, context["selected_models"], context)
        return handle_vague(route_result.missing_info)
    
    else:  # scenario（含 confidence 低的情況）
        return handle_scenario(user_query, context, history)
```

---

## 優先順序建議

考量到開發時間成本，建議按以下順序實作：

| 優先級 | 功能 | 原因 |
|--------|------|------|
| P0 | Type A（情境型）完整 5-Stage | 這是主流程，已有架構 |
| P1 | Type C（片面型）追問 | 成本低，但體驗差距大 |
| P2 | Type B1（單一型號規格查詢） | 高頻使用場景 |
| P3 | Type B2（多型號比較） | 較複雜，但用戶很愛用 |
| P4 | Confidence + 歷史語境邊界處理 | 精緻化，放最後 |

> **實作 P0 + P1 就已經讓使用者體驗大幅提升**，P2/P3 再逐步疊加。
