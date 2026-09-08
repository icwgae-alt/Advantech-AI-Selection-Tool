"""
app/rag/compare_summary.py
Compare Panel AI 總結生成器。

輸入：比較清單中的 2~5 台型號 PN
輸出：Markdown 格式總結（主要差異 + 各型號優勢場景 + 選型建議）

與 report_generator.py 的差異：
- 無需 Intent Parser（輸入就是固定的型號清單）
- Prompt 固定為「找差異、指優勢、給推薦」格式
- 不帶對話歷史
"""

import json
from app.llm_gateway import get_gateway
from app.rag.report_generator import _summarize_doc


def _build_compare_prompt(docs: list[dict]) -> str:
    summaries = [_summarize_doc(doc) for doc in docs]
    specs_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    model_names = ", ".join(d.get("product_pn", "") for d in docs)

    return f"""You are the Advantech Industrial Switch Selection AI Assistant.
The user has selected {len(docs)} models for comparison: {model_names}.

Based ONLY on the specification data below, provide a concise comparison summary in this exact structure:

## Key Differences
Summarize the most important specification differences in 3-5 bullet points. Focus on port count, PoE support, temperature grade, management type, and certifications.

## Recommendation
Give a clear recommendation. If the models serve different needs, explain when to choose each one. If one is clearly superior for general use, recommend it with reasons.

Rules:
- Only reference values from the specification data. Do not invent or infer values.
- Reply in English using standard Markdown.
- Keep the total response under 300 words.

=== Specification Data ===
{specs_json}
"""


def generate_compare_summary(product_pns: list[str]) -> str:
    """
    主要入口：根據型號 PN 清單從 DB 查詢規格，生成比較總結。
    回傳 Markdown 字串。
    """
    from app.database import Database

    if not product_pns:
        return "No models selected for comparison."

    db = Database.get_db()
    docs = list(db.product_specs.find({"product_pn": {"$in": product_pns}}))

    if not docs:
        return "Could not retrieve specification data for the selected models."

    # 依照傳入順序排列（保持使用者選取順序）
    pn_order = {pn: i for i, pn in enumerate(product_pns)}
    docs.sort(key=lambda d: pn_order.get(d.get("product_pn", ""), 99))

    prompt = _build_compare_prompt(docs)

    try:
        gateway = get_gateway()
        return gateway.call("report", prompt) 
    except RuntimeError as e:
        return f"⚠️ AI service temporarily unavailable: {e}"
