"""
app/api/chat.py
POST /api/chat — RAG Chatbot 端點（情境推薦組合式 Pipeline，Stage 1-2-3-5 一律執行）

Pipeline：
  Stage 0：model_detector  — 偵測問題是否明確提到型號（EKI-/ADAM-），連同前端已篩選型號
                              一起解析成精確 product_pn（見 hard_filter.resolve_text_models_to_pns），
                              縮小 Stage 2 的搜尋範圍。不再跳過後續 Stage——結構化欄位一律
                              以 Hard Filter 為準，避免「已知型號」跟「全庫篩選」兩條路徑
                              對同一個規格算出不同答案。
  Stage 1：intent_parser  — 自然語言 → 結構化條件 JSON + 剩餘語意描述（semantic_query）（Gemini Flash）
  Stage 2：hard_filter    — MongoDB Hard Filter → 候選型號（結構化條件零風險篩選，
                              範圍已被 Stage 0 解析出的 product_pn 縮限）
  Stage 3：semantic_query 非空時，在 Stage 2 候選子集內對 Datasheet Chunk 做語意搜尋
            （重用 vector_search.py 的 search_datasheet_chunks，範圍限制在候選 PN 內，
            避免語意漂移——這是決策 D5：Hard Filter 優先於向量搜尋）
  Stage 5：report_generator — 候選規格 + Stage 3 語意片段 → Markdown 回答（Gemini Flash）

Stage 0 → 1 → 2 → 3 → 5 皆為同一次查詢的連續步驟（不是互斥路由），
每個階段的結果摘要記錄在 ChatResponse.steps，供前端顯示篩選軌跡。

Phase 1 不包含：
  Stage 4（Re-ranking） → Phase 2 實作

【vector_search.py / answer_from_chunks 現況】
answer_from_chunks() 不再是正式請求路徑（不再有「Type B 直接跳過 Hard Filter」的特判分支），
只保留給 CHAT_TEST_MODE=vector_search 測試模式使用，供單獨評估自建向量搜尋的品質。
datasheet_expert.py（外部 Product Expert API，黑盒、無 sources）同樣只在
CHAT_TEST_MODE=datasheet_api 底下供評估可靠度，不會出現在正式請求路徑上。

【CHAT_TEST_MODE 測試開關】
.env 設 CHAT_TEST_MODE 時，原本的 3-Stage Pipeline（Stage 1/2/5）整個停用，方便單獨測試新串接的
元件，不受 MongoDB / intent_parser 等既有流程影響。測試完把這個變數改回空值或刪除即可還原。
可用值：
  "datasheet_api" — 所有訊息一律直接打 Datasheet Product Expert API（外部黑盒服務，評估用）
  "vector_search" — 所有訊息一律直接對 EKI_DataSheet_Chunks 做向量搜尋 + LLM 生成回答（自建 Stage 3）
"""

import os
from fastapi import APIRouter, HTTPException
from app.models.chat import ChatRequest, ChatResponse, PipelineStep, SourceChunk
from app.rag.intent_parser import (
    parse_intent,
    IntentResult,
    merge_known_constraints,
    intent_to_known_constraints,
)
from app.rag.hard_filter import (
    run_hard_filter,
    diagnose_empty_result,
    resolve_text_models_to_pns,
    TOP_N_FOR_REPORT,
)
from app.rag.report_generator import generate_report, generate_no_match_explanation
from app.rag.model_detector import detect_models
from app.rag.datasheet_expert import ask_product_expert
from app.rag.vector_search import answer_from_chunks, search_datasheet_chunks

router = APIRouter()

CHAT_TEST_MODE = os.getenv("CHAT_TEST_MODE", "").strip().lower()


def _resolve_target_models(message: str, context_models: list[str]) -> tuple[list[str], bool]:
    """
    決定這次查詢要鎖定哪些型號。
    優先用訊息裡明確提到的型號；訊息沒提到才 fallback 用前端已篩選的型號（Stage 1 選型結果）。
    回傳 (target_models, from_context)：from_context=True 代表型號是從前端篩選帶入，
    不是使用者自己打的，呼叫外部 API 時需要把型號名稱寫進 query 文字裡才看得到。
    """
    models_in_text = detect_models(message)
    if models_in_text:
        return models_in_text, False
    if context_models:
        return context_models, True
    return [], False


def _build_datasheet_query(message: str, target_models: list[str], from_context: bool) -> str:
    """
    Product Expert API 是無狀態服務，看不到網站前端的篩選狀態，
    型號是從 context 帶入時（使用者沒有在訊息裡打型號），需明確寫進 query 文字。
    """
    if from_context and target_models:
        models_str = "、".join(target_models)
        return f"（使用者已在網站篩選出以下型號：{models_str}）\n{message}"
    return message


def _has_structured_condition(intent: IntentResult, selected_models: list[str]) -> bool:
    """
    判斷這次 Hard Filter 查詢是否有實質縮小範圍的條件，而不是只排除 EOL。
    沒有任何結構化條件、也沒有型號範圍時，Hard Filter 會回傳近乎整個型號庫，
    這種情況下 all_docs 的原始 DB 順序跟使用者問題無關，top_docs 需要另外處理。
    """
    f = intent.filter
    return bool(
        selected_models
        or f.function
        or f.has_poe is not None
        or f.temp_grade
        or f.port_count_min
        or intent.software_requirements
    )


def _top_docs_from_semantic_chunks(
    all_docs: list[dict], semantic_chunks: list[dict], limit: int
) -> list[dict]:
    """
    沒有結構化條件時，all_docs[:limit] 只是 MongoDB 原始順序（近似插入順序），
    跟使用者問題不一定相關；Stage 3 語意搜尋命中的型號才是真正跟問題相關、
    且已依相關性排序的結果。這裡把命中的型號反查回 all_docs 裡對應的完整規格文件，
    讓塞給 LLM 的「結構化規格摘要」跟「語意片段」是同一批型號，不會各答各的。

    chunk 的 model_name 可能是不含地區/包裝後綴的基礎型號（跟 hard_filter.
    resolve_text_models_to_pns 要處理的命名落差是同一個問題），比對規則對稱：
    精確相等，或 product_pn 以 "model_name + '-'" 開頭。
    """
    ordered_docs: list[dict] = []
    seen_pns: set[str] = set()
    for chunk in semantic_chunks:
        model_name = (chunk.get("model_name") or "").strip().upper()
        if not model_name:
            continue
        for doc in all_docs:
            pn = doc.get("product_pn", "").strip().upper()
            if not pn or pn in seen_pns:
                continue
            if pn == model_name or pn.startswith(model_name + "-"):
                ordered_docs.append(doc)
                seen_pns.add(pn)
        if len(ordered_docs) >= limit:
            break
    return ordered_docs[:limit]


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """
    RAG Chatbot 主端點。
    接收使用者問題 + 前端 context，執行 3-Stage Pipeline，回傳 Markdown 回答。
    """
    context_models = req.context.selected_models or []

    # ── 測試模式：原本 3-Stage Pipeline 整個停用，一律直接打 Datasheet API ──
    if CHAT_TEST_MODE == "datasheet_api":
        target_models, from_context = _resolve_target_models(req.message, context_models)
        query = _build_datasheet_query(req.message, target_models, from_context)
        print(f"\n[Chatbot] (CHAT_TEST_MODE=datasheet_api) 使用者問題: {req.message}")
        print(f"[Chatbot] 目標型號: {target_models}（來源: {'前端選型' if from_context else '訊息文字'}）\n")
        try:
            answer = ask_product_expert(query)
        except RuntimeError as e:
            answer = f"⚠️ Datasheet API 呼叫失敗：{e}"
        return ChatResponse(
            answer=answer,
            referenced_models=target_models,
            sources=[],
        )

    # ── 測試模式：原本 3-Stage Pipeline 整個停用，一律直接對 Datasheet Chunk 做向量搜尋 ──
    if CHAT_TEST_MODE == "vector_search":
        target_models, _ = _resolve_target_models(req.message, context_models)
        print(f"\n[Chatbot] (CHAT_TEST_MODE=vector_search) 使用者問題: {req.message}")
        print(f"[Chatbot] 目標型號（過濾優先，無結果會退回全庫搜尋）: {target_models}\n")
        try:
            answer, referenced_models, sources = answer_from_chunks(req.message, target_models)
        except Exception as e:
            answer, referenced_models, sources = f"⚠️ 向量搜尋測試模式失敗：{e}", [], []
        return ChatResponse(
            answer=answer,
            referenced_models=referenced_models,
            sources=sources,
        )

    # ── Stage 0：型號偵測 ───────────────────────────────────────────────────
    # 問題明確提到型號，或前端已篩選型號 → 把它們解析成精確 product_pn，
    # 縮小 Hard Filter 的搜尋範圍（不再跳過 Stage 1-2，見決策紀錄：結構化欄位
    # 必須永遠以 Hard Filter 為準，向量搜尋只補充敘述性內容，避免同一個規格
    # 兩條路徑各自算出不同答案）。
    target_models, from_context = _resolve_target_models(req.message, context_models)
    selected_models: list[str] = []
    if target_models:
        if from_context:
            # 前端篩選帶入的型號已經是精確 PN，直接用
            selected_models = target_models
        else:
            # 訊息文字裡的型號可能是不含後綴的基礎型號，需模糊解析成精確 product_pn
            resolved_pns, uncovered = resolve_text_models_to_pns(target_models)
            if not resolved_pns:
                models_str = "、".join(uncovered)
                print(f"[Chatbot] 訊息型號無法解析為資料庫內任何 product_pn: {uncovered}")
                return ChatResponse(
                    answer=f"資料庫中查無型號「{models_str}」，請確認型號是否正確。",
                    referenced_models=[],
                    sources=[],
                    known_constraints=req.context.known_constraints,
                )
            selected_models = resolved_pns
        print(f"[Chatbot] 目標型號解析: {target_models} → {selected_models}（來源: {'前端選型' if from_context else '訊息文字'}）")

    # ── Stage 1：意圖解析 ──────────────────────────────────────────────────
    # 失敗時 parse_intent 回傳空 IntentResult，後續走全庫搜尋
    intent = parse_intent(req.message)

    # 併入跨輪次累積的已知限制條件（見決策：Option B 結構化條件累積，取代單純截斷對話歷史）。
    # 這一輪訊息明確提到的欄位優先，沒提到的欄位才 fallback 用累積條件。
    intent = merge_known_constraints(intent, req.context.known_constraints)

    # 印出意圖解析結果供除錯與觀察
    print(f"\n[Chatbot] 使用者問題: {req.message}")
    print(f"[Chatbot] 解析意圖（已併入累積條件）: {intent}\n")

    # ── Stage 2：MongoDB Hard Filter ──────────────────────────────────────
    # all_docs：全部符合型號（供 referenced_models 完整顯示）
    # top_docs：前 15 筆（傳給 LLM 做詳細分析）
    all_docs, top_docs = run_hard_filter(intent, selected_models)

    # 若完全沒有候選型號 → 不做全庫語意搜尋 fallback（避免把不同條件各自符合的型號混在一起，
    # 誤導成「有型號同時符合」），改用診斷查詢讓 LLM 講出具體是哪個條件造成衝突
    if not all_docs:
        diagnosis = diagnose_empty_result(intent, selected_models)
        print(f"[Chatbot] Stage 2 Hard Filter 0 筆，診斷資料: {diagnosis}")
        answer = generate_no_match_explanation(req.message, intent, diagnosis)
        # 這輪合併後的條件查無結果 → 不鎖進累積狀態（避免使用者被卡在一個永遠查不到東西的
        # 累積條件組合裡），原樣把舊的 known_constraints 送回，讓使用者能換個說法重試。
        return ChatResponse(
            answer=answer,
            referenced_models=[],
            sources=[],
            steps=[],
            known_constraints=req.context.known_constraints,
        )

    all_pns = [doc.get("product_pn", "") for doc in all_docs if doc.get("product_pn")]
    steps = [
        PipelineStep(
            stage="Hard Filter（硬體規格篩選）",
            summary=f"套用結構化條件後，找到 {len(all_pns)} 個候選型號",
            models=all_pns,
        )
    ]
    print(f"[Chatbot] Stage 2 Hard Filter 候選: {len(all_pns)} 個型號")

    # ── Stage 3：語意搜尋（僅在 Hard Filter 候選子集內進行，避免語意漂移）────
    # 決策 D5：Hard Filter 先確保結構化條件 100% 精準，語意搜尋只在已合格的候選裡
    # 找相關 Datasheet 原文，補充結構化欄位answer不到的描述性內容。
    # semantic_query 為空（問題已完全結構化）時跳過這個階段。
    semantic_chunks: list[dict] = []
    if intent.semantic_query.strip():
        try:
            semantic_chunks, _ = search_datasheet_chunks(intent.semantic_query, all_pns, limit=8)
        except Exception as e:
            print(f"[Chatbot] Stage 3 語意搜尋失敗，略過（不影響 Stage 5）：{e}")
        if semantic_chunks:
            matched_models = list(dict.fromkeys(
                c["model_name"] for c in semantic_chunks if c.get("model_name")
            ))
            steps.append(PipelineStep(
                stage="Semantic Search（語意比對）",
                summary=(
                    f"在候選型號中比對「{intent.semantic_query}」，"
                    f"找到 {len(semantic_chunks)} 個相關規格片段"
                ),
                models=matched_models,
            ))
            print(f"[Chatbot] Stage 3 語意搜尋命中: {len(semantic_chunks)} 個片段（{matched_models}）")
        else:
            print("[Chatbot] Stage 3 語意搜尋查無相關片段（候選型號可能沒有 Datasheet 向量資料）")

    # 沒有結構化條件時，Hard Filter 幾乎等於回傳整個型號庫，top_docs 只是 DB 原始順序，
    # 跟問題不一定相關。改用 Stage 3 語意搜尋命中的型號（已依相關性排序）反查回完整規格文件，
    # 讓「結構化規格摘要」跟「語意片段」在 Stage 5 是同一批型號，不會各答各的。
    if semantic_chunks and not _has_structured_condition(intent, selected_models):
        refined_top_docs = _top_docs_from_semantic_chunks(all_docs, semantic_chunks, TOP_N_FOR_REPORT)
        if refined_top_docs:
            print(
                f"[Chatbot] 無結構化條件，top_docs 改用語意搜尋命中的 "
                f"{len(refined_top_docs)} 個型號（原為 DB 原始順序前 {len(top_docs)} 筆）"
            )
            top_docs = refined_top_docs

    # ── Stage 5：報告生成 ─────────────────────────────────────────────────
    history = [h.model_dump() for h in req.history]
    answer, referenced_models = generate_report(
        user_query=req.message,
        history=history,
        top_docs=top_docs,
        total_count=len(all_docs),
        semantic_chunks=semantic_chunks,
    )

    sources = [
        SourceChunk(
            model=c.get("model_name", ""),
            content=c.get("content", ""),
            distance=round(1 - c.get("score", 0.0), 4),
        )
        for c in semantic_chunks
    ]

    return ChatResponse(
        answer=answer,
        referenced_models=all_pns,  # 顯示全部符合型號的 PN（不只 top_docs）
        sources=sources,
        steps=steps,
        known_constraints=intent_to_known_constraints(intent),
    )
