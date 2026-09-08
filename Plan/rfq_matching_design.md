# RFQ 需求逐項比對功能 — 設計規劃

## 背景與目的

業務/工程收到客戶的 RFQ(Request for Quotation)文件時，格式常常不一致(Excel/PDF/Word 都有可能)，
需要把文件裡每一條技術需求逐條跟公司產品規格比對，判斷「完全符合 / 部分符合 / 不符合」，
目前是靠人工逐條核對。本功能目標是把這個比對流程自動化，輸出結構化的逐項比對報告，
並附上判斷依據，讓使用者可以快速核可或抽查，而不是要全部重新查一次。

---

## 與既有專案高度複用 — 這不是從零重建的功能

RFQ 比對功能之所以評估可行、且能快速做出可驗證的原型，關鍵在於**大部分底層能力都是現成的**，
不需要重新開發資料庫、篩選邏輯或 LLM 呼叫層。這也是「直接嵌在本專案、不另開新專案」的核心理由。

| 複用的既有能力 | 來源 | RFQ 功能怎麼用 |
|---|---|---|
| **軟體功能結構化資料庫** | `product_specs.software.*`（MongoDB）、`data/software_specs_raw.json` | 直接查詢比對 VLAN/SNMP/ACL 等協定需求，不用重建一份新的軟體規格資料 |
| **硬體規格結構化資料庫** | `product_specs.hardware.*` | 直接查詢比對 port 數、溫度、電源等數值需求 |
| **Hard Filter 篩選邏輯** | [app/rag/hard_filter.py](../app/rag/hard_filter.py) | Stage 2 候選型號預篩直接複用，不用重寫一套篩選規則 |
| **Datasheet 向量搜尋** | [app/rag/vector_search.py](../app/rag/vector_search.py)`.search_datasheet_chunks()` | 結構化資料查無對應欄位時的 fallback，原封不動呼叫既有函式 |
| **LLM Gateway 呼叫層** | [app/llm_gateway.py](../app/llm_gateway.py) | 統一 retry/限流/用量記錄，只加了一個新的 `"rfq_verdict"` task，沒有重寫呼叫邏輯 |
| **「合法清單約束」防呆模式** | [app/rag/intent_parser.py](../app/rag/intent_parser.py) 的 `software_requirements` 驗證邏輯 | Stage 1b 分類時，hardware/software 的分類結果一樣限制在資料庫真實存在的欄位/分類清單內，沿用同一套設計思路 |
| **MongoDB dot-notation 特殊字元處理經驗** | [app/api/selection.py](../app/api/selection.py) 開頭註解記錄的坑 | 避免重蹈覆轍（`rfq_matcher.py` 開發過程中一度踩到同一個問題，靠這份既有記錄才快速定位原因） |

**價值**：這代表 RFQ 比對功能真正要新開發的，只有「檔案解析」「需求分類/拆解」「判級 prompt 設計」
「業務條款比對」這幾塊，其餘規格查詢與比對的地基（資料庫、篩選、語意搜尋、LLM 呼叫層）完全不用重做，
大幅降低開發與維護成本，也代表功能上線後的資料一致性有保障（跟既有選型工具、Chatbot 共用同一份資料來源，
不會出現「RFQ 比對說支援，選型工具卻查不到」這種兩邊資料不同步的問題）。

---

## 整體 Pipeline

```
RFQ 檔案（格式不一）
    │
    ▼
Stage 1a：格式別抽取（deterministic）
    → Excel/PDF/Word 各自解析，統一輸出「一行一項」的原始文字清單
    │
    ▼
Stage 1b：LLM 需求分類
    → 拆解複合需求成 atomic 項目，判斷每項屬於 hardware / software / business / unknown
    → RfqRequirement { item_no, category, requirement_text, type }
    │
    ▼
Stage 2：候選型號預篩 + 人工勾選
    → 用 RFQ 粗條件（產品類別、port 數、介面型態）複用既有 hard_filter 縮小候選範圍
    → 使用者從候選中勾選要逐項比對的目標型號（不自動選「最像的一台」）
    │
    ▼
Stage 3：分流比對 + 批次判級
    → 依 type 分流到不同比對引擎，同一批（同 category）彙整後一次性交給 LLM 判級
    → RfqVerdictResult { item_no, verdict: full/partial/none/unknown, evidence }
    │
    ▼
輸出比對報告（逐項對照表 + 摘要）
```

---

## 三類需求分流設計

RFQ 需求不能用同一套邏輯比對，依內容分成三類，個別處理：

| 類型 | 範例 | 比對對象 | 是否需要 LLM |
|---|---|---|---|
| **hardware** | Port 數量、溫度範圍、電源輸入、認證(Certifications) | `product_specs.hardware.*` 結構化欄位 | 數值比對可規則化，複合描述才需要 LLM |
| **software** | VLAN、SNMP、ACL、RADIUS 等協定/管理功能 | `product_specs.software.{category}` | 需要（欄位值需語意判斷是否滿足需求） |
| **business** | 保固年限、EOL/EOS 承諾、交期 | 公司自訂的商務條款設定（非產品資料庫） | 多數可規則化，模糊描述才需要 LLM |
| **unknown** | 資料庫查無對應欄位/分類的需求（如 MEF CE2.0、RFC2544） | 先查軟體/硬體欄位皆無 → fallback 查 Datasheet 語意搜尋 | 是 |

**分類防呆機制**：LLM 判斷 type/category 時，hardware 與 software 的合法值都**限制在資料庫實際存在的欄位/分類清單內**（動態查詢取得，不寫死），選不到就誠實標記 `unknown`，不允許 LLM 自創一個資料庫沒有的分類名稱。

---

## 判級批次設計

**查找（deterministic）與判級（LLM）分開執行**：同一 category 底下所有需求項目的原始資料先查完彙整，
再一次性交給 LLM 判級，避免每條需求各打一次 LLM。

以範例 BOQ（93 列、約 55 條需求、11 個 section）估算：
- 純規則比對（hardware 數值/類別型）：約 21 條，完全不需要 LLM
- 需要 LLM 判級的 section：約 6 個 → **約 7 次 LLM 呼叫**跑完全份 RFQ，而不是 55 次逐條呼叫

---

## Datasheet 語意搜尋 Fallback

當 hardware/software 結構化資料都查不到對應欄位時（例如 MEF CE2.0、SFP DDM 這類協定/認證，
資料庫完全沒有收錄），改用既有的 Datasheet 向量搜尋（`EKI_DataSheet_Chunks`）查詢原文片段，
查到的片段一併批次交給 LLM 判級，而不是直接放棄標記 `unknown`。

**限制**：目前 Datasheet 向量資料與軟體規格資料庫**都只涵蓋 11 個 EKI 系列**，
其他產品線（如 iMC、ADAM）目前無法透過結構化或語意搜尋比對，只能標記 `unknown`。

---

## 判級輸出格式與 evidence 規則

不論走哪一條比對路徑，`RfqVerdictResult` 一律要附 `evidence`，不能只給 verdict：

- 軟體結構化比對 → evidence 是查到的原始欄位值
- Datasheet 語意搜尋 → evidence 是引用的原文片段/摘要
- 硬體規則比對 → evidence 是「需求門檻 vs 查到的實際值」的確定性字串
- 查無資料 → evidence 誠實寫「查無此型號的相關規格資料」，不可硬湊理由

**原因**：使用者要拿報告直接跟客戶對答，沒有依據等於還要自己回頭查一次驗證 AI 判得對不對，
報告就沒有省到力；有依據才能快速抽查、也才敢信任較武斷的 full/none 判級。

---

## 架構決策

- **RFQ 比對功能直接嵌在本專案**，不另開新專案 —— 重度依賴既有的 `hard_filter` / `software_specs` /
  `vector_search` 邏輯，拆成獨立專案反而要重複處理資料存取層。
- 候選型號縮限流程刻意保留人工勾選這一步，不讓系統自動選定目標型號，保留業務判斷空間。

---

## 已驗證的原型進度

### `app/rag/rfq_matcher.py`（已實作）

- `verdict_batch()` / `verdict_by_category()`：軟體/協定類需求的批次判級，已對真實型號
  `EKI-7428G-4CA-AE` 驗證（VLAN、RADIUS 需求判級正確，能抓出「支援但數值未達門檻」的 partial 情況）
- `verdict_batch_datasheet()`：Datasheet 語意搜尋 fallback，已驗證能查到結構化資料完全沒有的規格
  （例如 Auto-negotiation 直接從 Datasheet 原文命中，判定 full）
- 過程中修正一個 MongoDB 查詢 bug：category 名稱含 "."（如 `"VLAN(IEEE 802.1Q)"`）不可用於
  dot-notation projection，改成整個 `software` 欄位撈回、Python 端索引

### Stage 1b 需求分類（PoC 驗證，尚未併入正式程式碼）

拿範例 BOQ 55 條需求實測分類，修正 2 個問題：
1. hardware 分類需比照 software 加上「合法欄位清單」約束，避免標記 hardware 卻查無對應欄位
2. 法規認證項目（RoHS/WEEE/NEBS/SIRIM/MCMC）應歸類 hardware（對應 Certifications 欄位），非 business

**已知限制**：LLM 分類非 100% 穩定，同一份需求跑兩次可能有邊界項目結果不同，上線前需評估是否要
跑兩次取交集或加入人工覆核機制。

**分類灰色地帶：兩種不同性質的「認證」不可混為一談。**
`hardware.Certifications` 欄位的實際內容（如 `"UL61010, LVD62368"`、`"EN 50155"`）是**安全/EMC/環保法規類認證**，
由驗證機構核發的合格標章（RoHS、WEEE、NEBS、SIRIM、UL、CE、FCC、EN50155 等）。
但像 **MEF CE2.0** 這種是 **網路協定一致性認證**（MEF Forum 針對 Carrier Ethernet 服務行為核發），
**RFC2544/Y.1564** 更明確只是**效能測試方法論**、連認證都稱不上 —— 這兩者跟 Certifications 欄位裝的東西
性質不同，不可歸類進去，應維持 `unknown`。分類 prompt 已明確寫入這個區分規則，避免僅靠 LLM 語意相似度
判斷（"認證" 這個詞面上相似但實際指涉完全不同的東西）導致誤歸類。

---

## 已知風險

1. **Datasheet fallback 的 `none` 判斷可能是「缺席推論」**（原文列了其他標準但沒列這條，不等於明確講不支援），
   信心弱於原文明講不支援的情況，建議標記低信心或保守降級為 `unknown`。
2. **軟體規格與 Datasheet 資料都只涵蓋 EKI 系列**，PoC/上線初期範圍需限定在此，其他產品線需求會全部落在 unknown。
3. **需求拆解準確度是最大風險點**：複合需求拆錯會讓比對結果整條錯，不建議完全自動化上線，需要人工抽查機制。

---

## 尚未實作項目（Roadmap）

- [ ] Stage 1a：RFQ 檔案解析（Excel/PDF/Word → 統一的原始文字清單），含合併儲存格、章節辨識
- [ ] Stage 1b：需求分類 prompt 正式併入程式碼（目前只有 PoC 腳本）
- [ ] Stage 2：候選型號預篩 UI（複用 `hard_filter`，供使用者勾選目標型號）
- [ ] Stage 3：硬體數值類的規則比對引擎（免 LLM，但一樣要附 evidence）
- [ ] Stage 3：business 類型的判級邏輯（比對公司自訂商務條款設定，目前完全沒有實作）
- [ ] 把 `verdict_by_category()`（結構化）與 `verdict_batch_datasheet()`（語意搜尋）整合成單一入口：
      查無結構化資料時自動 fallback 到 Datasheet 搜尋，目前是兩個函式分開呼叫
- [ ] `app/api/rfq.py` API 端點 + `app/models/rfq.py` Pydantic schema
- [ ] 比對報告輸出格式（逐項對照表 + 摘要，是否需要匯出 Excel/PDF）

---

## 相關檔案

- 判級邏輯原型：[app/rag/rfq_matcher.py](../app/rag/rfq_matcher.py)
- LLM 任務設定：[app/llm_gateway.py](../app/llm_gateway.py)（`TASK_MODELS["rfq_verdict"]`）
- 複用的既有模組：[app/rag/hard_filter.py](../app/rag/hard_filter.py)、[app/rag/vector_search.py](../app/rag/vector_search.py)
