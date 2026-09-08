# 更新日誌 (Changelog)

本文件記錄專案的重要變更，最新異動置頂。

---

## 2026-07-16

### Chatbot Pipeline：Type B 併入主流程，結構化欄位改為單一資料來源
- **移除「Type B 直接跳過 Hard Filter」的特判分支**（[app/api/chat.py](app/api/chat.py)）：不論型號是訊息文字
  偵測到、前端已篩選帶入，還是完全沒有型號，一律先進 Stage 0 解析範圍，再走完整 Stage 1（意圖解析）→ Stage 2
  （Hard Filter）→ Stage 3（語意搜尋）→ Stage 5（報告生成）。改善此前「已知型號問結構化規格（如 port 數）」跟
  「全庫篩選同一規格」會因為路徑不同各自算出不同答案的問題。
- **新增文字型號模糊解析成精確 `product_pn`**（[app/rag/hard_filter.py](app/rag/hard_filter.py) 的
  `resolve_text_models_to_pns()`）：使用者訊息裡打的型號常是不含地區/包裝後綴的基礎型號，透過家族前綴比對解析成
  資料庫實際存在的精確 PN 縮限 Hard Filter 範圍；完全無法解析時直接誠實回覆「查無此型號」，不再默默退回全庫搜尋。
- **`answer_from_chunks`（Type B 向量搜尋）降級為測試用**：僅保留給 `CHAT_TEST_MODE=vector_search` 除錯模式使用，
  不再是正式請求路徑。

### 移除 `application` 結構化欄位（chatbot / 選型工具 / 資料同步管線全面下架）
現有資料沒有可靠對應「應用場景」的 tag，容易把描述性語句（如「電廠」「電力系統」）誤判成不存在的結構化值，
導致明明有候選型號卻查出 0 筆；決定不再以應用場景做結構化區分，`Application` 欄位整條管線全面移除：
- **意圖解析／結構化篩選**：[app/rag/intent_parser.py](app/rag/intent_parser.py) 的 `IntentFilter` 移除
  `application` 欄位與 `VALID_APPLICATIONS` 白名單；[app/rag/hard_filter.py](app/rag/hard_filter.py) 的
  `build_mongo_filter()` 不再套用 `hardware.Application` 條件。
- **LLM 可見輸出**：[app/rag/report_generator.py](app/rag/report_generator.py) 的 `_summarize_doc()` 不再把
  `hardware.Application` 塞進傳給 LLM 的結構化規格摘要（修正實測發現的殘留洩漏——LLM 會把這個欄位原樣寫進回答
  變成「Application: 電力系統」）；查無結果的診斷說明 prompt 也移除對應欄位。
- **資料同步管線**：[scripts/fetch_hardware_specs.py](scripts/fetch_hardware_specs.py) 在來源就把 `Application`
  欄位從 Google Sheet DataFrame 排除，不再寫進 `data/hardware_specs_raw.json`；
  [scripts/sync_specs_to_mongo.py](scripts/sync_specs_to_mongo.py)、[scripts/sync_all.py](scripts/sync_all.py)
  寫入 MongoDB 前加防呆 `pop`，避免舊版 raw json 殘留值被同步進去。
- **選型工具篩選功能**：[app/models/selection.py](app/models/selection.py)、
  [app/api/selection.py](app/api/selection.py) 移除 `SubmitProdRequest.application` 篩選欄位、
  `hardware.Application` 查詢條件、`prod_application` 顯示欄位；
  [scripts/sw_index.py](scripts/sw_index.py) 移除 Application 分類的 facet 選單邏輯。
- **前端「Scene Verified」徽章一併移除**：[frontend/js/app.js](frontend/js/app.js)、
  [frontend/js/scenes.js](frontend/js/scenes.js)、[frontend/css/style.css](frontend/css/style.css) 移除
  依賴 `prod_application` 關鍵字比對才會顯示的場景驗證徽章（`appKeywords` / `pb-scene-verified`），避免欄位
  停止同步後徽章永遠不顯示的死程式碼；`index.html` 對應 cache-busting 版號一併調整。

### 修正
- **無結構化條件時，Stage 5 摘要用的是資料庫原始順序**（[app/api/chat.py](app/api/chat.py)）：問題完全沒有結構化
  條件時，Hard Filter 幾乎等於回傳整個型號庫，`top_docs` 原本直接取 MongoDB 回傳順序前 15 筆，跟問題不一定相關。
  新增 `_has_structured_condition()` / `_top_docs_from_semantic_chunks()`：這種情況下改用 Stage 3 語意搜尋命中
  （已依相關性排序）的型號反查回完整規格文件，讓「結構化規格摘要」跟「語意片段」是同一批相關型號。

---

## 2026-07-15

### Chatbot Type B：新增型號規格問答（向量搜尋 / Datasheet API 兩條路線）
- **自建向量搜尋成為正式路徑**（[app/rag/vector_search.py](app/rag/vector_search.py)）：使用者問題明確提到型號、或前端已篩選型號時，
  對 Datasheet Chunk（`Adv_Ind_Switch.EKI_DataSheet_Chunks`，MongoDB Atlas `$vectorSearch`）做語意搜尋，回傳的
  `sources` 欄位（型號、相似度、完整原文）第一次被真正填入，前端可核對 AI 引用的原文是否精準。
- **外部 Datasheet Product Expert API 整合**（[app/rag/datasheet_expert.py](app/rag/datasheet_expert.py)、
  [app/rag/model_detector.py](app/rag/model_detector.py)）：串接 Advantech 內部 presalesbot 服務作為備選方案，
  目前僅供可靠度評估（`CHAT_TEST_MODE=datasheet_api`），未進入正式路由，因為是外部黑盒、無法提供可驗證的
  `sources` 引用。
- **路由邏輯**（[app/api/chat.py](app/api/chat.py)）：Type B 優先呼叫向量搜尋；只有型號來自前端已選型號（`hard_filter`
  可用精確 PN 篩選）才 fallback 回原本 3-Stage Pipeline，型號是使用者在文字裡打的且查無資料時直接誠實回覆，
  避免 fallback 撈出全庫近 250 筆不相關型號、答非所問。
- **新增 `CHAT_TEST_MODE` 測試開關**（`configs/.env`）：可強制單一路徑（`datasheet_api` / `vector_search`）測試，
  不受既有 3-Stage Pipeline 影響。

### 修正
- **型號命名比對不完整**（[app/rag/vector_search.py](app/rag/vector_search.py)）：主資料庫 PN 帶地區/包裝後綴
  （`EKI-2525I-LA-AE`），Datasheet Chunk 存的是不含後綴的基礎型號（`EKI-2525I-LA`），原邏輯只處理「PN 比 chunk
  型號長」的方向；使用者只打基礎型號（`EKI-7720G`）時完全查無資料。新增反方向比對：基礎型號會抓出該系列
  底下所有變體（`EKI-7720G-4F`/`-4FI`/`-4FPI`）。
- **向量搜尋 `limit` 排序截斷漏型號**（[app/rag/vector_search.py](app/rag/vector_search.py)）：型號範圍已知時，
  固定 `limit=8` 會讓「哪些型號符合 X」這類列舉型問題因排序沒進前 8 名而漏掉本來有資料的型號。改為型號範圍已知時
  動態拉高 limit（型號數 ×6，上限 80）；查無資料的型號也會在回答裡明確列出，不再靜默略過。
- **LLM 回答被莫名截斷**（[app/llm_gateway.py](app/llm_gateway.py)）：`gemini-2.5-flash` 的思考 token
  （`thoughts_token_count`）跟輸出 token 共用 `max_output_tokens` 額度，context 一大就把答案截斷在奇怪的地方。
  加 `thinking_config.thinking_budget=0` 關閉思考模式、額度由 4096 拉到 8192，此修正影響全專案所有 LLM 呼叫
  （intent_parser / report_generator 也受益），非僅本次新功能。

### Chatbot 前端：浮動視窗改版
- **面板改為可拖曳、可縮放的浮動視窗**（[frontend/index.html](frontend/index.html)、
  [frontend/css/style.css](frontend/css/style.css)、[frontend/js/app.js](frontend/js/app.js)）：取代原本貼右側的
  固定側欄，抓標題列拖曳移動位置、抓右下角把手縮放大小，位置/大小記憶存 localStorage。
- **並排顯示 AI 回答與參考原文片段**：新增獨立的「AI 參考的原廠規格片段」欄位，取代原本每則訊息下方
  `max-height:150px` 的收合區塊，方便核對 AI 引用內容是否精準。
- **左右欄可自由調整比例、可完全收合**：中間新增可拖曳分隔線（`#chatColResizer`，寬度記憶、有最小寬度保護），
  標題列新增 📑 按鈕可完全收起參考片段區、對話區補滿全寬，再點一次恢復記憶寬度。
- **修正視窗縮小時面板跑出可視範圍的 bug**：新增 `resize` 事件監聽即時夾住面板位置/大小，避免瀏覽器視窗縮小後
  按鈕點不到。

### 設定與依賴
- `configs/.env` / `.env.example`：新增 `PRODUCT_API_URL/KEY/TIMEOUT`、`CHAT_TEST_MODE`（原散落在
  `Datasheet/.env` 的設定已合併並刪除該檔）。
- `pyproject.toml`：補上 `httpx` 為直接依賴（原僅為 `google-genai` 的間接依賴，現被 `datasheet_expert.py` 直接
  import）。

---

## 2026-07-09

### Table View 版面密度優化
- **凍結表頭 + 列高壓縮**：表格改為固定高度、內部捲動，並修正表頭 sticky 失效的問題（[style.css](frontend/css/style.css)、[table-view.css](frontend/css/table-view.css)）；整體列高壓縮，一屏可看更多筆資料。
- **Mgmt / Certifications 欄位改版**（[app.js](frontend/js/app.js)）：管理類型改以縮寫徽章（U/L2/L3/L2-M/L3-M）顯示於型號名稱旁；Certifications 改為獨立可開關欄位（取代原本的 Application 欄）。
- **欄位群組改用整欄底色**：RJ-45 / Fiber / M12 欄位群以底色區分取代邊框線，窄欄位標題可顯示縮寫（shortLabel）。

### 修正
- **軟體規格合併 fallback 邏輯錯誤**（[scripts/sync_specs_to_mongo.py](scripts/sync_specs_to_mongo.py)）：
  硬體規格表若沒有填寫 `Software Series` / `Firmware Version`，且從 PN 推導出的系列在軟體規格表中找不到對應資料時，
  原本會強制 fallback 套用一個寫死、完全不相關的系列（`EKI-5500`）的完整軟體功能表，導致例如
  `EKI-2710E-2CI-A`（真實硬體規格為 Unmanaged）被錯誤附加上 VLAN / SNMP / CLI 等 managed 功能。
  現在改為：找不到真正對應的軟體系列時，`software` 欄位留空，不再套用不相關資料；硬體資料仍正常寫入
  `product_specs`，產品不會從選型工具中消失。

### AI 對比摘要
- **移除「Best Fit Scenarios」段落**（[app/rag/compare_summary.py](app/rag/compare_summary.py)）：目前不規劃此段落，AI
  比較摘要僅保留「Key Differences」與「Recommendation」。

### Table View / Search Inventory / Advanced Filter 調整
- **移除 Application 欄位與分類**：Table View 的 App 欄位、Search Inventory 快速搜尋、Advanced Filter 均不再提供
  依「應用場景」（Application）篩選，相關後端動態分類與查詢邏輯一併移除（[app/api/selection.py](app/api/selection.py)、
  [frontend/js/app.js](frontend/js/app.js)）。
- **Search Inventory 暫時僅顯示硬體規格**：軟體規格資料尚未確認完成，快速搜尋文字框先只回傳硬體類特徵（Power
  Input / Connector Type / Port Feature / Hardware Feature / Certifications），可透過
  `SEARCH_INVENTORY_HARDWARE_ONLY` 旗標（[app/api/selection.py](app/api/selection.py)）一鍵恢復。
- **Advanced Filter 卡片重新分類**（[frontend/js/feature-selector.js](frontend/js/feature-selector.js)）：
  - 同樣因軟體規格尚未確認，暫時只顯示硬體相關卡片（`FS_SOFTWARE_HIDDEN` 旗標控制，之後可一鍵恢復顯示全部）。
  - 原本雜亂的「Hardware Specs」catch-all 拆分為四張語意清楚的卡片：
    - **Port Type / Connector**：PoE / Fiber / RJ-45 有無、M12 Connector、LAN Bypass。
    - **Power Input**：DC / AC / 12V / 24V / High Voltage。
    - **Certifications**：UL / LVD / IEC 61850 / NEMA / EN 50155 / E-Mark / ITxPT（新增獨立分類，後端
      category 由散落在 `Hardware Feature` 改為獨立的 `Certifications`）。
    - **Hardware Specs**：暫時僅保留 Temp_Wide，日後有新雜項硬體條件再擴充。
  - 移除與左側 Wizard 步驟重複的項目：`Port_RJ45_GbE/100M`、`Port_Fiber_GbE/10G`、`Port_M12_GbE`、
    `Port_MultiGiga`、`Speed_100M/GbE/10G`（皆與 Wizard 的 Max Port Speed 概念重疊），避免同一條件在兩處都能設定。
  - 後端 `Port Speed` 分類更名為 `Connector Type`，更準確反映隱藏速度相關項目後的實際內容。

---
