"""
app/rag/vector_search.py
Stage 3（測試中）：Datasheet Chunk 向量搜尋。

【設計重點】
- Chunk 資料在同一個 Atlas cluster 底下、但是獨立的 DB（Adv_Ind_Switch），
  跟主要的 product_specs（advantech_ind_sw_tool）分開，透過共用的 Database.client 存取，不另開連線。
- 目前只接 EKI_DataSheet_Chunks（1070 筆、vector_index 已 READY、embedding 3072 維）。
  Sales_Kit_Chunks 目前是空集合、沒有建向量索引，直接查會報錯，先不接。
- Embedding 模型沿用 configs/.env 的 EMBEDDING_MODEL（gemini-embedding-2-preview，3072 維），
  跟現有索引維度一致。

【型號命名對不上的問題】
主資料庫（product_specs）的型號是完整料號，帶地區/包裝後綴，例如 "EKI-2525I-LA-AE"；
但 Datasheet Chunk 存的 model_name 是不含後綴的基礎型號，例如 "EKI-2525I-LA"。
兩邊精確重疊率極低（265 筆主資料只有 10 筆能精確對上 chunk 的 207 個型號）。
若用主資料庫的完整 PN 直接 $in 查 chunk，幾乎都是 0 筆。
解法：_expand_to_chunk_models() 用「前綴比對」把主資料庫 PN 對應回 chunk 實際存在的基礎型號名稱。
若對應後仍然 0 筆（該型號的 Datasheet 尚未收錄向量資料），明確回覆「查無資料」，
不能再默默退回全庫搜尋——那樣會讓使用者以為 AI 回答的是他篩選範圍內的型號，實際上早已跑出範圍。
"""

import os
from google import genai
from app.database import Database
from app.llm_gateway import get_gateway
from app.models.chat import SourceChunk

CHUNKS_DB_NAME = "Adv_Ind_Switch"
CHUNKS_COLLECTION = "EKI_DataSheet_Chunks"
VECTOR_INDEX_NAME = "vector_index"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-2-preview")

_embed_client: genai.Client | None = None
_chunk_model_names_cache: list[str] | None = None


def _get_embed_client() -> genai.Client:
    global _embed_client
    if _embed_client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY 未設定，請檢查 configs/.env")
        _embed_client = genai.Client(api_key=api_key)
    return _embed_client


def _embed_query(text: str) -> list[float]:
    client = _get_embed_client()
    result = client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
    return result.embeddings[0].values


def _get_chunk_model_names() -> list[str]:
    """取得 EKI_DataSheet_Chunks 裡實際存在的 model_name 清單（快取，避免每次查詢都 distinct）。"""
    global _chunk_model_names_cache
    if _chunk_model_names_cache is None:
        chunks_db = Database.client[CHUNKS_DB_NAME]
        _chunk_model_names_cache = list(chunks_db[CHUNKS_COLLECTION].distinct("model_name"))
    return _chunk_model_names_cache


def _expand_to_chunk_models(target_models: list[str]) -> tuple[list[str], list[str]]:
    """
    把主資料庫的完整型號 PN 對應到 Datasheet Chunk 實際存在的型號名稱，處理兩種方向的落差：

    方向 1（PN 比 chunk 型號長）：主資料庫 PN 帶地區/包裝後綴，如 "EKI-2525I-LA-AE"，
    chunk 存的是不含後綴的基礎型號 "EKI-2525I-LA"。比對：PN 以 "chunk 型號 + '-'" 開頭。
    同一個 PN 可能同時是多個 chunk 型號的有效前綴（例如 "EKI-2525I" 和 "EKI-2525I-LA"
    都是不同的實體型號），此時只取「最長、最精確」的那一個，避免誤帶入不相關的型號。

    方向 2（PN 比 chunk 型號短）：使用者只打了基礎型號（如 "EKI-7720G"），沒帶完整配置後綴，
    但 chunk 存的是更細的變體（"EKI-7720G-4F"、"EKI-7720G-4FI"、"EKI-7720G-4FPI"）。
    比對：chunk 型號以 "PN + '-'" 開頭，這種情況下同一個 PN 底下的所有變體都算數（不像方向 1
    只取最長，因為使用者的基礎型號本來就涵蓋整個系列，不是單一實體）。

    回傳 (matched_chunk_models, uncovered_pns)：uncovered_pns 是完全對不到 chunk 資料的原始 PN，
    代表該型號尚無 Datasheet 向量資料（不是不支援某功能，是根本沒收錄），呼叫端需要明確告知使用者。
    """
    chunk_models = _get_chunk_model_names()
    matched = set()
    uncovered = []
    for pn in target_models:
        normalized = pn.strip().upper().replace("/", "-")

        # 方向 1：PN 更精確 → 只取最長前綴
        specific_candidates = [
            chunk_model for chunk_model in chunk_models
            if normalized == chunk_model.strip().upper()
            or normalized.startswith(chunk_model.strip().upper() + "-")
        ]
        if specific_candidates:
            matched.add(max(specific_candidates, key=len))
            continue

        # 方向 2：PN 是基礎型號 → 該系列底下所有變體都算
        family_candidates = [
            chunk_model for chunk_model in chunk_models
            if chunk_model.strip().upper().startswith(normalized + "-")
        ]
        if family_candidates:
            matched.update(family_candidates)
        else:
            uncovered.append(pn)
    return list(matched), uncovered


def _run_vector_search(query_vector: list[float], model_names: list[str], limit: int) -> list[dict]:
    chunks_db = Database.client[CHUNKS_DB_NAME]
    stage = {
        "$vectorSearch": {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": limit * 10,
            "limit": limit,
        }
    }
    if model_names:
        stage["$vectorSearch"]["filter"] = {"model_name": {"$in": model_names}}

    pipeline = [
        stage,
        {
            "$project": {
                "_id": 0,
                "model_name": 1,
                "file_source": 1,
                "content": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]
    return list(chunks_db[CHUNKS_COLLECTION].aggregate(pipeline))


def search_datasheet_chunks(
    query: str, model_names: list[str] | None = None, limit: int = 8
) -> tuple[list[dict], list[str]]:
    """
    對 EKI_DataSheet_Chunks 做語意搜尋。
    回傳 (chunks, uncovered_pns)：
      uncovered_pns 是 model_names 裡完全對不到任何 chunk 資料的原始 PN（可能為空清單），
      呼叫端須明確告知使用者「這些型號沒有資料」，不能誤導成「這些型號不符合條件」。
    model_names 為 None 或空清單時，視為使用者沒有鎖定範圍，直接做全庫語意搜尋，uncovered_pns 一律為 []。

    型號範圍已知時，動態拉高 limit（每型號平均 ~5-6 個 chunk，乘以安全係數），
    確保「哪些型號符合 X」這類列舉型問題不會因為固定 limit=8 的排序截斷而漏掉本來有資料的型號。
    """
    query_vector = _embed_query(query)

    if model_names:
        chunk_models, uncovered = _expand_to_chunk_models(model_names)
        if not chunk_models:
            return [], uncovered
        effective_limit = min(max(limit, len(chunk_models) * 6), 80)
        return _run_vector_search(query_vector, chunk_models, effective_limit), uncovered

    return _run_vector_search(query_vector, [], limit), []


def _build_chunk_answer_prompt(user_query: str, chunks: list[dict]) -> str:
    context = "\n\n".join(
        f"--- [Datasheet Reference {i+1}] (Model: {c.get('model_name','')}, "
        f"Source: {c.get('file_source','')}) ---\n{c.get('content','')}"
        for i, c in enumerate(chunks)
    )
    return f"""You are the Advantech Industrial Switch Selection AI Assistant.
Answer the user's question using ONLY the Datasheet reference chunks below.
Do not invent specification values. Cite the model name for every claim you make.
If the question asks "which models" or "list all" that satisfy some condition, check EVERY
distinct model that appears in the reference chunks below and include every one that qualifies —
do not silently omit any model present in the references.

=== Datasheet Reference Chunks ===
{context}

=== User Question ===
{user_query}
"""


def answer_from_chunks(
    user_query: str, model_names: list[str] | None = None, limit: int = 8
) -> tuple[str, list[str], list[SourceChunk]]:
    """
    主要入口：語意搜尋 Datasheet chunk → 生成回答。
    回傳 (answer, referenced_models, sources)。
    """
    chunks, uncovered = search_datasheet_chunks(user_query, model_names, limit)

    if not chunks:
        if uncovered:
            models_str = "、".join(uncovered)
            answer = (
                f"您篩選的型號（{models_str}）目前沒有收錄 Datasheet 向量資料，"
                "無法針對這些型號回答此問題。建議確認型號是否正確，或改問一般規格問題。"
            )
            return answer, [], []
        return "No relevant datasheet content found.", [], []

    prompt = _build_chunk_answer_prompt(user_query, chunks)
    gateway = get_gateway()
    answer = gateway.call("report", prompt)

    if uncovered:
        models_str = "、".join(uncovered)
        answer += (
            f"\n\n⚠️ 另外，您篩選的型號中有以下幾款目前沒有收錄 Datasheet 向量資料，"
            f"無法確認是否符合：{models_str}"
        )

    referenced_models = list(dict.fromkeys(c["model_name"] for c in chunks if c.get("model_name")))
    sources = [
        SourceChunk(
            model=c.get("model_name", ""),
            content=c.get("content", ""),
            distance=round(1 - c.get("score", 0.0), 4),
        )
        for c in chunks
    ]
    return answer, referenced_models, sources
