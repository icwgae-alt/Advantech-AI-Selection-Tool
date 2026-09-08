"""
app/rag/rfq_matcher.py
RFQ 逐項判級：查找（deterministic）+ 批次判級（LLM）。

【設計重點】
- 查找與判級分開執行：同一 category 底下所有需求項目的原始資料先查完、彙整成一批，
  再一次性交給 LLM 判級，避免每條需求各打一次 LLM（見討論：批次依據是「同一查詢
  來源／category」，讓同一批項目彼此語意相關，LLM 判斷時上下文一致）。
- 目前只支援軟體/協定類需求（對應 product_specs.software.{category} 欄位）。
  硬體數值類需求（port數/溫度/電源等）應走純規則比對，不需要 LLM，尚未實作於此檔。
- Target model 為單一 product_pn；多型號比對由呼叫端對每個型號各呼叫一次
  verdict_by_category。
"""

from dataclasses import dataclass
from typing import Literal

from app.database import Database
from app.llm_gateway import get_gateway
from app.rag.vector_search import search_datasheet_chunks

Verdict = Literal["full", "partial", "none", "unknown"]


@dataclass
class RfqRequirement:
    item_no: str            # RFQ 原始編號，如 "4.2"
    category: str           # 對應 product_specs.software 的分類名稱，如 "VLAN(IEEE 802.1Q)"
    requirement_text: str   # 需求原文


@dataclass
class RfqVerdictResult:
    item_no: str
    verdict: Verdict
    evidence: str


def _fetch_software_spec(product_pn: str, category: str) -> dict | None:
    """
    查單一型號在指定軟體分類底下的原始欄位值。查無此型號或該分類回傳 None。

    category 可能含有 "." 字元（如 "VLAN(IEEE 802.1Q)"），projection 若用
    f"software.{category}" 會被 MongoDB dot-notation 誤解為巢狀路徑分隔符而查不到
    （同一問題見 app/api/selection.py 頂部註解），因此整個 software 欄位一次撈回，
    改在 Python 端用 category 當 key 索引，不經過 dot-notation。
    """
    db = Database.get_db()
    doc = db.product_specs.find_one(
        {"product_pn": product_pn},
        {"software": 1},
    )
    if not doc:
        return None
    return doc.get("software", {}).get(category)


def _build_verdict_prompt(
    product_pn: str,
    items: list[RfqRequirement],
    specs_by_item: dict[str, dict | None],
) -> str:
    """把同一批需求 + 各自查到的原始資料組成一個 prompt，要求 LLM 一次回傳整批判級結果。"""
    blocks = []
    for req in items:
        spec = specs_by_item.get(req.item_no)
        spec_str = "（查無此型號的相關規格資料）" if spec is None else str(spec)
        blocks.append(f"[{req.item_no}] 需求：{req.requirement_text}\n查到資料：{spec_str}")
    items_str = "\n\n".join(blocks)

    return f"""你是規格比對助手，正在幫型號 {product_pn} 比對 RFQ 需求。
請針對以下每條需求，只依「查到資料」判斷符合程度，不可推測資料庫沒有的規格。

回傳純 JSON array（不加 Markdown 包裹、不加說明文字），每筆格式：
{{"item_no": "...", "verdict": "full|partial|none|unknown", "evidence": "..."}}

verdict 規則：
- full：查到資料完全滿足需求
- partial：查到資料部分滿足（例如支援但數值未達需求門檻，或複合需求只滿足部分子項）
- none：查到資料明確不滿足
- unknown：查無此型號的相關規格資料，無法判斷（不可用 none 代替沒查到的情況）

{items_str}
"""


def verdict_batch(product_pn: str, items: list[RfqRequirement]) -> list[RfqVerdictResult]:
    """
    對同一批需求（建議同一 category）做批次判級。
    查找失敗或 LLM 呼叫失敗都不中斷流程，整批標記 unknown，讓使用者知道要人工確認。
    """
    if not items:
        return []

    specs_by_item = {req.item_no: _fetch_software_spec(product_pn, req.category) for req in items}
    prompt = _build_verdict_prompt(product_pn, items, specs_by_item)

    try:
        gateway = get_gateway()
        raw = gateway.call_json("rfq_verdict", prompt)
    except Exception as e:
        print(f"[RfqMatcher] LLM 判級失敗，整批標記 unknown：{e}")
        return [
            RfqVerdictResult(item_no=req.item_no, verdict="unknown", evidence=f"LLM 呼叫失敗：{e}")
            for req in items
        ]

    if not isinstance(raw, list):
        print(f"[RfqMatcher] LLM 回傳格式非預期（非 array），整批標記 unknown。raw={raw}")
        return [
            RfqVerdictResult(item_no=req.item_no, verdict="unknown", evidence="LLM 回傳格式錯誤")
            for req in items
        ]

    results_by_item = {r.get("item_no"): r for r in raw if isinstance(r, dict)}
    output: list[RfqVerdictResult] = []
    for req in items:
        r = results_by_item.get(req.item_no)
        if not r:
            output.append(RfqVerdictResult(item_no=req.item_no, verdict="unknown", evidence="LLM 未回傳此項目結果"))
            continue
        verdict = r.get("verdict")
        if verdict not in ("full", "partial", "none", "unknown"):
            verdict = "unknown"
        output.append(RfqVerdictResult(item_no=req.item_no, verdict=verdict, evidence=r.get("evidence", "")))
    return output


def verdict_by_category(product_pn: str, requirements: list[RfqRequirement]) -> list[RfqVerdictResult]:
    """
    主要入口：把整批需求依 category 分組，逐 category 呼叫 verdict_batch，彙整所有結果。
    分組後每個 category 對應一次 LLM 呼叫（見設計討論：以「同一查詢來源」切批）。
    """
    groups: dict[str, list[RfqRequirement]] = {}
    for req in requirements:
        groups.setdefault(req.category, []).append(req)

    results: list[RfqVerdictResult] = []
    for category, items in groups.items():
        results.extend(verdict_batch(product_pn, items))
    return results


# =============================================================================
# Datasheet 語意搜尋 fallback：查無結構化資料（software/hardware 皆查不到）的需求，
# 改用 EKI_DataSheet_Chunks 向量搜尋補查，查到的原文片段一樣批次交給 LLM 判級。
# 目前只有 EKI 系列有 Datasheet 向量資料（見 vector_search.py），非 EKI 型號呼叫這裡
# 會透過 search_datasheet_chunks 的 uncovered 回傳，最終仍標記 unknown，不會誤判。
# =============================================================================

def _build_datasheet_verdict_prompt(
    product_pn: str,
    items: list[RfqRequirement],
    chunks_by_item: dict[str, list[dict]],
) -> str:
    """把同一批需求 + 各自查到的 Datasheet 原文片段組成一個 prompt，一次回傳整批判級結果。"""
    blocks = []
    for req in items:
        chunks = chunks_by_item.get(req.item_no) or []
        if not chunks:
            chunk_str = "（查無相關 Datasheet 片段）"
        else:
            chunk_str = "\n".join(f"  - {c.get('content', '')}" for c in chunks)
        blocks.append(f"[{req.item_no}] 需求：{req.requirement_text}\nDatasheet 相關片段：\n{chunk_str}")
    items_str = "\n\n".join(blocks)

    return f"""你是規格比對助手，正在幫型號 {product_pn} 比對 RFQ 需求。
以下每條需求都查無結構化規格資料，改用 Datasheet 原文片段（語意搜尋取得，可能不精確）判斷。
只根據片段內容判斷，片段沒提到或講不清楚就標 unknown，不可自行推測或腦補資料庫沒有的規格。

回傳純 JSON array（不加 Markdown 包裹、不加說明文字），每筆格式：
{{"item_no": "...", "verdict": "full|partial|none|unknown", "evidence": "..."}}

{items_str}
"""


def verdict_batch_datasheet(product_pn: str, items: list[RfqRequirement]) -> list[RfqVerdictResult]:
    """
    對查無結構化資料的需求，改用 Datasheet 語意搜尋 + 批次 LLM 判級。
    每條需求的查詢文字不同，向量搜尋無法像 verdict_batch 一樣共用同一次查詢結果，
    所以查找階段仍是每條各打一次 search_datasheet_chunks；但判級階段一樣批次成一次 LLM 呼叫。
    """
    if not items:
        return []

    chunks_by_item: dict[str, list[dict]] = {}
    for req in items:
        try:
            chunks, _uncovered = search_datasheet_chunks(req.requirement_text, [product_pn], limit=5)
        except Exception as e:
            print(f"[RfqMatcher] Datasheet 語意搜尋失敗（{req.item_no}）：{e}")
            chunks = []
        chunks_by_item[req.item_no] = chunks

    prompt = _build_datasheet_verdict_prompt(product_pn, items, chunks_by_item)

    try:
        gateway = get_gateway()
        raw = gateway.call_json("rfq_verdict", prompt)
    except Exception as e:
        print(f"[RfqMatcher] Datasheet 判級 LLM 呼叫失敗，整批標記 unknown：{e}")
        return [
            RfqVerdictResult(item_no=req.item_no, verdict="unknown", evidence=f"LLM 呼叫失敗：{e}")
            for req in items
        ]

    if not isinstance(raw, list):
        return [
            RfqVerdictResult(item_no=req.item_no, verdict="unknown", evidence="LLM 回傳格式錯誤")
            for req in items
        ]

    results_by_item = {r.get("item_no"): r for r in raw if isinstance(r, dict)}
    output: list[RfqVerdictResult] = []
    for req in items:
        r = results_by_item.get(req.item_no)
        if not r:
            output.append(RfqVerdictResult(item_no=req.item_no, verdict="unknown", evidence="LLM 未回傳此項目結果"))
            continue
        verdict = r.get("verdict")
        if verdict not in ("full", "partial", "none", "unknown"):
            verdict = "unknown"
        output.append(RfqVerdictResult(item_no=req.item_no, verdict=verdict, evidence=r.get("evidence", "")))
    return output
