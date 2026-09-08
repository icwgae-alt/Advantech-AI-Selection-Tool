"""
app/rag/hard_filter.py
Stage 2：根據 IntentResult 和前端 context 組裝 MongoDB query，查詢候選型號。

【設計重點】
- 複用 selection.py 的 make_sw_expr_query（避免重複維護查詢邏輯）
- 若前端有 selected_models，則優先限縮在此範圍內
- 全部符合的型號都回傳（不設上限），讓 report_generator 決定取幾筆做詳細分析
- 回傳 (all_docs, top_docs)：
    all_docs  → 所有符合型號（供 referenced_models 顯示用）
    top_docs  → 前 N 筆完整規格（供 LLM 生成詳細回答用）
"""

from typing import Optional
from app.database import Database
from app.rag.intent_parser import IntentResult, IntentFilter
from app.api.selection import (
    DYNAMIC_SW_MAPPINGS,
    make_sw_expr_query,
    SW_SUPPORTED_VALUES,
    base_hardware_mappings,
)

# 傳給 LLM 做詳細分析的最大型號數（避免 prompt 過長）
TOP_N_FOR_REPORT = 15

_product_pn_cache: list[str] | None = None


def _get_all_product_pns() -> list[str]:
    """取得 product_specs 裡所有 product_pn（快取，避免每次查詢都 distinct）。"""
    global _product_pn_cache
    if _product_pn_cache is None:
        db = Database.get_db()
        _product_pn_cache = list(db.product_specs.distinct("product_pn"))
    return _product_pn_cache


def resolve_text_models_to_pns(text_models: list[str]) -> tuple[list[str], list[str]]:
    """
    把使用者訊息文字裡偵測到的型號字串解析成 product_specs 實際存在的精確 product_pn。

    使用者打字通常是不含地區/包裝後綴的基礎型號（例如 "EKI-2525I"），但 product_specs
    的 product_pn 是完整料號（例如 "EKI-2525I-LA-AE"）。比對規則：
    - 完全相等 → 直接算
    - product_pn 以 "使用者輸入 + '-'" 開頭 → 算同一個系列底下的變體，全部收進來
      （不像 vector_search._expand_to_chunk_models 只取最長前綴，這裡每個 product_pn
      都是獨立的實體型號，只要屬於使用者講的系列就都該當候選型號）

    回傳 (matched_pns, uncovered)：uncovered 是完全比對不到任何 product_pn 的原始輸入，
    代表資料庫裡沒有這個型號，呼叫端需要明確告知使用者，不能默默退回全庫搜尋。
    """
    all_pns = _get_all_product_pns()
    matched = set()
    uncovered = []
    for name in text_models:
        normalized = name.strip().upper().replace("/", "-")
        candidates = [
            pn for pn in all_pns
            if pn.strip().upper() == normalized
            or pn.strip().upper().startswith(normalized + "-")
        ]
        if candidates:
            matched.update(candidates)
        else:
            uncovered.append(name)
    return list(matched), uncovered


# 部分軟體功能分類同時也是 hardware.Certifications 的勾選項（見 selection.py 的 Cert_* 條目），
# 但兩個欄位的資料填寫進度可能不同步（例如某型號軟體功能已填 IEC 61850，但 Certifications
# 欄位還沒補上）。比對這些分類時，兩個欄位任一符合都算數，避免因為資料落差漏掉型號。
# key 為軟體分類名稱，value 為套用在 hardware.Certifications 上的 regex（沿用 selection.py 同款寫法）。
CERT_CATEGORY_TO_HARDWARE_REGEX = {
    "IEC 61850": "IEC61850",
    "ITxPT": "ITxPT",
}


def build_mongo_filter(
    intent: IntentResult,
    selected_models: list[str],
) -> dict:
    """
    根據意圖解析結果 + 前端已鎖定的型號，組裝 MongoDB $and 查詢。

    優先順序：
    1. 排除 EOL / Phase Out 型號
    2. 若 selected_models 非空 → 限縮在此清單內（前端已篩過）
    3. 套用 intent.filter 的硬體條件
    4. 套用 intent.software_requirements 的軟體條件
    """
    and_conditions = [
        {"hardware.PLM Lifecycle": {"$not": {"$regex": "(eol|phase out|inactivate)", "$options": "i"}}}
    ]

    # 前端已鎖定的型號 → 限縮搜尋範圍
    if selected_models:
        and_conditions.append({"product_pn": {"$in": selected_models}})

    f = intent.filter

    # 管理類型
    if f.function:
        and_conditions.append({"hardware.Function": f.function})

    # PoE 篩選（複用 base_hardware_mappings）
    if f.has_poe is True:
        and_conditions.append(base_hardware_mappings["Has_PoE"]())
    elif f.has_poe is False:
        # 明確不需要 PoE → 排除所有有 PoE 的型號
        poe_cond = base_hardware_mappings["Has_PoE"]()
        and_conditions.append({"$nor": [poe_cond]})

    # 溫度等級
    if f.temp_grade == "Wide":
        and_conditions.append(base_hardware_mappings["Temp_Wide"]())
    elif f.temp_grade == "Normal":
        and_conditions.append(
            {"hardware.Temp Grade": {"$nin": ["Wide", "wide", "T", "Wide Temp"]}}
        )

    # Port 數量（大於等於）
    if f.port_count_min:
        and_conditions.append({
            "$expr": {
                "$gte": [
                    {"$toInt": {"$ifNull": ["$hardware.Port Numbers", "0"]}},
                    f.port_count_min
                ]
            }
        })

    # 軟體功能條件（複用 make_sw_expr_query）
    for feat_key in intent.software_requirements:
        # 情境 1：如果 LLM 抽取出來的是「大分類 (Category)」 (例如 "IEC 61850")
        # 代表使用者想要該分類下的任一功能，我們用 $or 包起來
        features_in_cat = [
            mapping["feat_key"]
            for mapping in DYNAMIC_SW_MAPPINGS.values()
            if mapping["category"] == feat_key
        ]
        if features_in_cat:
            sw_or = [make_sw_expr_query(feat_key, fk) for fk in features_in_cat]
            cert_regex = CERT_CATEGORY_TO_HARDWARE_REGEX.get(feat_key)
            if cert_regex:
                sw_or.append({"hardware.Certifications": {"$regex": cert_regex, "$options": "i"}})
            and_conditions.append({"$or": sw_or} if len(sw_or) > 1 else sw_or[0])
            continue
            
        # 情境 2：如果 LLM 抽取出來的是「具體功能 (Feature)」 (例如 "GOOSE Subscriber")
        matched_categories = [
            mapping["category"]
            for mapping in DYNAMIC_SW_MAPPINGS.values()
            if mapping["feat_key"] == feat_key
        ]
        if matched_categories:
            # 同一個 feat_key 可能存在於多個 category（用 $or）
            sw_or = [
                make_sw_expr_query(cat, feat_key)
                for cat in matched_categories
            ]
            and_conditions.append({"$or": sw_or} if len(sw_or) > 1 else sw_or[0])

    return {"$and": and_conditions} if len(and_conditions) > 1 else and_conditions[0]


def run_hard_filter(
    intent: IntentResult,
    selected_models: list[str],
) -> tuple[list[dict], list[dict]]:
    """
    執行 MongoDB 查詢，回傳 (all_docs, top_docs)。

    all_docs：所有符合型號的文件（完整列表，供 referenced_models 顯示）
    top_docs：前 TOP_N_FOR_REPORT 筆（傳給 LLM 做詳細分析，避免 prompt 過長）
    """
    db = Database.get_db()
    query = build_mongo_filter(intent, selected_models)

    try:
        all_docs = list(db.product_specs.find(query))
    except Exception as e:
        print(f"[HardFilter] MongoDB 查詢失敗：{e}")
        return [], []

    top_docs = all_docs[:TOP_N_FOR_REPORT]
    return all_docs, top_docs


def diagnose_empty_result(intent: IntentResult, selected_models: list[str]) -> dict:
    """
    Hard Filter 全部條件合併查詢回傳 0 筆時的輔助診斷。
    分別「只套軟體需求」跟「只套硬體篩選條件」各自查一次，藉此判斷是哪個面向造成衝突
    ——兩者結構化條件各自都查得到東西，合在一起卻是空集合。
    這個結果會餵給 LLM 生成有根據的「查無結果」說明，而不是空泛的制式訊息。
    """
    db = Database.get_db()
    diagnosis: dict = {}

    if intent.software_requirements:
        sw_only = IntentResult(filter=IntentFilter(), software_requirements=intent.software_requirements)
        sw_query = build_mongo_filter(sw_only, selected_models)
        try:
            diagnosis["software_only_count"] = db.product_specs.count_documents(sw_query)
        except Exception as e:
            print(f"[HardFilter] 診斷查詢（軟體需求）失敗：{e}")
            diagnosis["software_only_count"] = 0

    has_hw_filter = any([
        intent.filter.function, intent.filter.has_poe,
        intent.filter.temp_grade, intent.filter.port_count_min,
    ])
    if has_hw_filter:
        hw_only = IntentResult(filter=intent.filter, software_requirements=[])
        hw_query = build_mongo_filter(hw_only, selected_models)
        try:
            diagnosis["hardware_only_count"] = db.product_specs.count_documents(hw_query)
        except Exception as e:
            print(f"[HardFilter] 診斷查詢（硬體條件）失敗：{e}")
            diagnosis["hardware_only_count"] = 0

    return diagnosis
