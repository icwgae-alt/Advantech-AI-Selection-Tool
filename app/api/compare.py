"""
app/api/compare.py
POST /api/compare-summary — Compare Panel AI 總結端點

輸入：{ "product_pns": ["EKI-7428G", "EKI-7312"] }
輸出：{ "summary": "## Key Differences\n..." }
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.rag.compare_summary import generate_compare_summary

router = APIRouter()


class CompareSummaryRequest(BaseModel):
    product_pns: list[str] = Field(..., description="比較清單中的型號 PN（2~5 台）")


class CompareSummaryResponse(BaseModel):
    summary: str


@router.post("/compare-summary", response_model=CompareSummaryResponse)
def compare_summary(req: CompareSummaryRequest) -> CompareSummaryResponse:
    summary = generate_compare_summary(req.product_pns)
    return CompareSummaryResponse(summary=summary)
