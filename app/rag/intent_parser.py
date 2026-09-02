"""
app/rag/intent_parser.py
Stage 1：從使用者自然語言問題中抽取結構化篩選條件。

【設計重點】
- 透過 LLM Gateway 呼叫 Gemini Flash（快速、便宜）
- software_requirements 的合法值動態取自 selection.py 的快取（不重複查 DB）
- 解析失敗時回傳空 IntentResult，讓後續 Stage 2 走全庫搜尋，不中斷流程

【回傳格式（IntentResult）】
{
  "filter": {
    "function":    "Managed" | "Unmanaged" | null,
    "has_poe":     true | false | null,
    "temp_grade":  "Wide" | "Normal" | null,
    "port_count_min": 16 | null
  },
  "software_requirements": ["PROFINET", "IEC 61850"],
  "semantic_query": "鐵路車廂部署推薦"
}
"""

from typing import Optional
from dataclasses import dataclass, field

from app.llm_gateway import get_gateway
from app.api.selection import DYNAMIC_SW_MAPPINGS, load_dynamic_mappings_if_needed


# ── 意圖解析結果的資料結構 ─────────────────────────────────────────────────
@dataclass
class IntentFilter:
    function:    Optional[str]     = None  # Managed / Unmanaged
    has_poe:     Optional[bool]    = None
    temp_grade:  Optional[str]     = None  # Wide / Normal
    port_count_min: Optional[int]  = None


@dataclass
class IntentResult:
    filter: IntentFilter                    = field(default_factory=IntentFilter)
    software_requirements: list[str]        = field(default_factory=list)
    semantic_query: str                     = ""


def _get_sw_feat_keys() -> list[str]:
    """
    從 selection.py 的快取取得所有合法的軟體功能 feat_key。
    Server 啟動後第一次呼叫時才去 DB，之後全部從記憶體快取讀取。
    回傳格式如：["VLAN(IEEE 802.1Q)", "PROFINET", "IEC 61850", ...]
    """
    load_dynamic_mappings_if_needed()
    # DYNAMIC_SW_MAPPINGS 的 key 格式："{category}|||{feat_key}"
    # 只取 feat_key 部分，去重
    seen = set()
    keys = []
    for composite_key, mapping in DYNAMIC_SW_MAPPINGS.items():
        cat = mapping["category"]
        fk = mapping["feat_key"]
        
        if cat not in seen:
            seen.add(cat)
            keys.append(cat)
            
        if fk not in seen:
            seen.add(fk)
            keys.append(fk)
    return keys


def _build_intent_prompt(user_query: str, sw_feat_keys: list[str]) -> str:
    """建構意圖解析的 Prompt。"""
    sw_keys_str = ", ".join(f'"{k}"' for k in sw_feat_keys)  # 解除 60 個上限，傳入所有軟體功能

    return f"""你是 Advantech 工業交換機選型助理。
請從使用者問題中**精確抽取**結構化條件，只抽取問題中明確提到的條件，不可推斷。
回傳**純 JSON**（不加任何 Markdown 包裹、不加任何說明文字）：

{{
  "filter": {{
    "function": null,
    "has_poe": null,
    "temp_grade": null,
    "port_count_min": null
  }},
  "software_requirements": [],
  "semantic_query": ""
}}

欄位規則：
- function：只能填 "Managed" / "Unmanaged" / null
- has_poe：true / false / null（true = 有提到需要 PoE）
- temp_grade：提到「寬溫」「工業溫度」「-40°C」→ "Wide"；否則 null
- port_count_min：提到「至少 N 個 port」「N port 以上」→ 整數 N；否則 null
- software_requirements：只能從以下合法清單選取（允許模糊比對，例如使用者說 PROFINET，可對應到清單中的 PROFINET IRT），其餘一律不填：
  [{sw_keys_str}]
- semantic_query：無法結構化的剩餘語意描述，供語意搜尋使用

使用者問題：{user_query}
"""


def merge_known_constraints(intent: IntentResult, known: Optional[dict]) -> IntentResult:
    """
    把跨輪次累積的「已知限制條件」(前端 context.known_constraints) 併入這一輪剛解析出的 intent，
    讓使用者不必每輪重複講一次「要寬溫、要 PoE」。

    合併規則：這一輪訊息明確提到的欄位（non-null）優先；沒提到的欄位才 fallback 用已知條件，
    因此使用者只要在新一輪明確講出不同的值（例如「不用 PoE 了」），就能覆蓋掉舊的累積條件。
    software_requirements 用聯集去重（這一輪在前）。
    """
    known = known or {}
    f = intent.filter
    merged_filter = IntentFilter(
        function       = f.function if f.function is not None else known.get("function"),
        has_poe        = f.has_poe if f.has_poe is not None else known.get("has_poe"),
        temp_grade     = f.temp_grade if f.temp_grade is not None else known.get("temp_grade"),
        port_count_min = f.port_count_min if f.port_count_min is not None else known.get("port_count_min"),
    )
    merged_sw = list(dict.fromkeys(
        intent.software_requirements + list(known.get("software_requirements") or [])
    ))
    return IntentResult(
        filter=merged_filter,
        software_requirements=merged_sw,
        semantic_query=intent.semantic_query,
    )


def intent_to_known_constraints(intent: IntentResult) -> dict:
    """把合併後的 IntentResult 序列化成要回傳給前端、供下一輪帶回來的 known_constraints 格式。"""
    f = intent.filter
    return {
        "function": f.function,
        "has_poe": f.has_poe,
        "temp_grade": f.temp_grade,
        "port_count_min": f.port_count_min,
        "software_requirements": intent.software_requirements,
    }


def parse_intent(user_query: str) -> IntentResult:
    """
    主要入口：解析使用者問題，回傳 IntentResult。
    LLM 解析失敗時回傳空 IntentResult，讓後續 Stage 走全庫搜尋。
    """
    sw_feat_keys = _get_sw_feat_keys()
    prompt = _build_intent_prompt(user_query, sw_feat_keys)

    try:
        gateway = get_gateway()
        raw = gateway.call_json("intent", prompt)
    except Exception as e:
        # LLM 失敗（限流 / timeout）→ 回傳空 Intent，不中斷流程
        print(f"[IntentParser] LLM 呼叫失敗，走全庫搜尋：{e}")
        return IntentResult()

    # 解析 filter
    f_raw = raw.get("filter", {}) or {}
    intent_filter = IntentFilter(
        function       = f_raw.get("function"),
        has_poe        = f_raw.get("has_poe"),
        temp_grade     = f_raw.get("temp_grade"),
        port_count_min = f_raw.get("port_count_min"),
    )

    # 驗證 software_requirements 都在合法清單內
    valid_sw = set(sw_feat_keys)
    sw_reqs = [s for s in (raw.get("software_requirements") or []) if s in valid_sw]

    return IntentResult(
        filter=intent_filter,
        software_requirements=sw_reqs,
        semantic_query=raw.get("semantic_query", ""),
    )
