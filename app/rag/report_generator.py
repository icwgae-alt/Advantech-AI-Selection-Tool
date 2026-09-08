"""
app/rag/report_generator.py
Stage 5：根據候選型號規格生成自然語言回答。

【設計重點】
- 透過 LLM Gateway 呼叫 Gemini Flash
- 傳入的規格資料只取 top_docs（15 筆以內），避免 prompt 過長
- 規格只摘要必要欄位，避免傳入整份 MongoDB 文件（太多雜訊）
- LLM 禁止捏造數值，所有規格必須來自傳入的資料
- semantic_chunks（選填）：Stage 3 在 Hard Filter 候選子集內做語意搜尋找到的 Datasheet
  原文片段，補充結構化欄位之外的描述性內容（例如應用場景描述），讓答案有更豐富的佐證依據
- 回傳 (answer_markdown, referenced_models)
"""

import json
from app.llm_gateway import get_gateway


# ── 規格欄位摘要（只取前端表格用到的欄位，避免 prompt 過載）──────────────
def _summarize_doc(doc: dict) -> dict:
    """從 MongoDB 文件中抽取關鍵欄位，生成精簡摘要傳給 LLM。"""
    hw = doc.get("hardware", {})
    sw = doc.get("software", {})

    # 軟體功能：只列出 "full" 或 "optional" 的項目
    sw_supported = {}
    for category, features in sw.items():
        if isinstance(features, dict):
            supported = {
                k: v for k, v in features.items()
                if v in ("full", "optional")
            }
            if supported:
                sw_supported[category] = supported

    return {
        "product_pn":   doc.get("product_pn", ""),
        "model_name":   doc.get("model_name", hw.get("Model Name", "")),
        "function":     hw.get("Function", ""),
        "port_numbers": hw.get("Port Numbers", ""),
        "temp_grade":   hw.get("Temp Grade", ""),
        "lifecycle":    hw.get("PLM Lifecycle", ""),
        "software":     sw_supported,
        # Port 細節 (動態抓取非零的連接埠資訊，支援 Train SW 與 Ind SW)
        "ports": {
            k: v for k, v in hw.items()
            if any(keyword in k for keyword in ["RJ-45", "Fiber", "PoE", "Combo", "D-code", "X-code", "10G", "100M"])
            and "驗證" not in k
            and v not in (0, "0", "", None, "None")
        }
    }


def _build_report_prompt(
    user_query: str,
    history: list[dict],
    top_docs: list[dict],
    total_count: int,
    semantic_chunks: list[dict] | None = None,
) -> str:
    """建構報告生成的 Prompt。"""

    # 規格摘要 JSON
    summaries = [_summarize_doc(doc) for doc in top_docs]
    specs_json = json.dumps(summaries, ensure_ascii=False, indent=2)

    # 對話歷史（最多 6 輪，避免 token 過長）
    history_text = ""
    if history:
        history_text = "\n".join(
            f"{'User' if h['role'] == 'user' else 'AI'}: {h['content']}"
            for h in history[-6:]
        )

    # 超過 TOP_N 時的提醒文字
    overflow_note = ""
    if total_count > len(top_docs):
        overflow_note = (
            f"\n(Note: There are a total of {total_count} matching models. "
            f"The analysis below covers the top {len(top_docs)} models. "
            f"For the full list, please refer to the 'Referenced Models' section.)"
        )

    # Stage 3 語意搜尋找到的 Datasheet 原文片段（選填，補充結構化欄位之外的描述性內容）
    semantic_section = ""
    if semantic_chunks:
        chunks_text = "\n\n".join(
            f"--- [Datasheet Excerpt {i+1}] (Model: {c.get('model_name','')}) ---\n{c.get('content','')}"
            for i, c in enumerate(semantic_chunks)
        )
        semantic_section = f"""

=== Additional Datasheet Excerpts (semantically relevant to the descriptive part of the question, within the already-qualified candidates above) ===
{chunks_text}
"""

    return f"""You are the Advantech Industrial Switch Selection AI Assistant.
Please answer the user's question based on the following **real specification data**.{overflow_note}

Rules for answering:
1. You may only reference the information provided in the specification data below. **Do not infer or invent specification values.**
2. Please reply in English and use standard Markdown formatting.
3. If the user's question is unrelated to industrial switches, politely guide them back to product selection.

=== Specification Data ===
{specs_json}
{semantic_section}
=== Conversation History ===
{history_text}

=== Current Question ===
{user_query}
"""


def generate_report(
    user_query: str,
    history: list[dict],
    top_docs: list[dict],
    total_count: int,
    semantic_chunks: list[dict] | None = None,
) -> tuple[str, list[str]]:
    """
    主要入口：生成 Markdown 格式回答。

    回傳：
      answer (str)             — Markdown 回答
      referenced_models (list) — 本次分析的型號 PN 清單
    """
    referenced_models = [
        doc.get("product_pn", doc.get("model_name", ""))
        for doc in top_docs
    ]

    if not top_docs:
        return "No matching models found. Please try relaxing your search criteria.", []

    prompt = _build_report_prompt(user_query, history, top_docs, total_count, semantic_chunks)

    try:
        gateway = get_gateway()
        answer = gateway.call("report", prompt)
    except RuntimeError as e:
        # LLM 限流或失敗 → 回傳友善錯誤訊息
        answer = f"⚠️ AI service is temporarily unavailable: {e}"

    return answer, referenced_models


def _build_no_match_prompt(user_query: str, intent, diagnosis: dict) -> str:
    """建構「查無結果」說明的 Prompt，用診斷資料讓 LLM 講出具體衝突點，而不是空泛的制式訊息。"""
    conditions_json = json.dumps({
        "function": intent.filter.function,
        "has_poe": intent.filter.has_poe,
        "temp_grade": intent.filter.temp_grade,
        "port_count_min": intent.filter.port_count_min,
        "software_requirements": intent.software_requirements,
    }, ensure_ascii=False)
    diagnosis_json = json.dumps(diagnosis, ensure_ascii=False)

    return f"""You are the Advantech Industrial Switch Selection AI Assistant.
The user's search returned ZERO matching models. Explain why, based ONLY on the diagnostic data below.
Do not invent product details or specification values not present in the data.

=== Extracted Search Conditions ===
{conditions_json}

=== Diagnostic Data ===
{diagnosis_json}
Field meanings:
- software_only_count: how many models support the requested software feature(s) when ignoring all
  hardware conditions.
- hardware_only_count: how many models match the hardware conditions alone, ignoring the software
  requirement(s).

=== User's Original Question ===
{user_query}

Write a short, helpful explanation (2-4 sentences) of why no models matched. If the diagnostic data reveals
a specific conflicting condition, state it plainly. Suggest what the user could relax or clarify next.
Reply in the same language the user used.
"""


def generate_no_match_explanation(user_query: str, intent, diagnosis: dict) -> str:
    """
    Hard Filter 回傳 0 筆時的說明生成。
    回傳一段自然語言解釋，取代原本寫死的「No matching models found」制式訊息。
    LLM 呼叫失敗時 fallback 回原本的制式訊息，不中斷使用者體驗。
    """
    prompt = _build_no_match_prompt(user_query, intent, diagnosis)
    try:
        gateway = get_gateway()
        return gateway.call("report", prompt)
    except RuntimeError:
        return "No matching models found. Please try relaxing your search criteria or adjusting your description."
