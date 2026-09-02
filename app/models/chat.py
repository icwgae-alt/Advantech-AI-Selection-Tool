"""
app/models/chat.py
Chatbot API 的 Pydantic Request / Response 強型別定義。

設計原則：
- ChatRequest  對應前端 app.js 送出的 payload 格式
- ChatResponse 對應前端 appendMessage() 期待收到的格式
- sources 在 Phase 1 永遠回傳空陣列（Phase 2 才有 Datasheet chunk）
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# =========================================================================
# Request Models
# =========================================================================

class ChatContext(BaseModel):
    """
    前端帶入的篩選上下文。
    selected_models:   硬體篩選後鎖定的型號 PN 清單
    filters:           目前的篩選條件（type / port），供意圖解析參考
    known_constraints: 跨輪次累積的結構化限制條件（上一輪 ChatResponse.known_constraints 原樣帶回），
                       讓使用者不必每輪重複講一次「要寬溫、要 PoE」
    """
    selected_models: List[str] = Field(default=[], description="已鎖定的型號 PN 清單")
    filters: Dict[str, Any] = Field(default={}, description="目前的篩選條件")
    known_constraints: Dict[str, Any] = Field(
        default={}, description="跨輪次累積的結構化限制條件（function/has_poe/temp_grade/port_count_min/software_requirements）"
    )


class HistoryItem(BaseModel):
    """
    單筆對話歷史記錄。
    role:    "user" 或 "assistant"
    content: 對話內容文字
    """
    role: str = Field(..., description="user 或 assistant")
    content: str = Field(..., description="對話內容")


class ChatRequest(BaseModel):
    """
    POST /api/chat 的請求體。
    對應前端 sendMessage() 送出的 payload。
    """
    message: str = Field(..., description="使用者輸入的問題")
    context: ChatContext = Field(default_factory=ChatContext, description="前端篩選上下文")
    history: List[HistoryItem] = Field(default=[], description="最近 12 筆對話歷史")


# =========================================================================
# Response Models
# =========================================================================

class SourceChunk(BaseModel):
    """
    單筆 Datasheet 知識庫引用片段。
    """
    model: str = ""
    content: str = ""
    distance: float = 1.0


class PipelineStep(BaseModel):
    """
    情境推薦路徑（Hard Filter → Semantic Search → 報告生成）的單一階段執行摘要，
    供前端顯示「依步驟呈現篩選結果」的軌跡。查無候選型號時（Hard Filter 0 筆）不產生 steps。
    """
    stage: str = Field(..., description="階段名稱，例如 'Hard Filter（硬體規格篩選）'")
    summary: str = Field(..., description="這個階段的結果摘要，例如 '套用條件後找到 12 個候選型號'")
    models: List[str] = Field(default=[], description="這個階段涉及的型號 PN 清單")


class ChatResponse(BaseModel):
    """
    POST /api/chat 的回傳體。
    對應前端 appendMessage() 使用的欄位。
    """
    answer: str = Field(..., description="AI 生成的 Markdown 格式回答")
    referenced_models: List[str] = Field(
        default=[], description="本次回答中參考的型號 PN 清單"
    )
    sources: List[SourceChunk] = Field(
        default=[], description="回答引用的 Datasheet chunk 原文片段"
    )
    steps: List[PipelineStep] = Field(
        default=[], description="情境推薦路徑的階段執行軌跡（Hard Filter / Semantic Search）"
    )
    known_constraints: Dict[str, Any] = Field(
        default={},
        description="這一輪合併後的結構化限制條件，前端原樣存起來、下一輪透過 context.known_constraints 帶回",
    )
