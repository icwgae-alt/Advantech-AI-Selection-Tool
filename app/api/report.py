# Report API router (generates PDF via reportlab)
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List
from app.database import Database
from app.report_generator import generate_selection_report


router = APIRouter()


class ExportReportRequest(BaseModel):
    product_pns: List[str]             # 使用者選擇的產品 PN，例如 ["EKI-7720G-4F-AE"]
    criteria: dict = {}                # SubmitProdRequest 的內容，保留給未來使用
    ai_summary: str = ""               # 比較面板已生成的 AI Summary，直接帶入 PDF


@router.post("/exportReport")
def export_report(req: ExportReportRequest):
    if not req.product_pns:
        raise HTTPException(status_code=400, detail="No products selected")
    if len(req.product_pns) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 products allowed")

    db = Database.get_db()

    # 撈出產品資料
    products = list(db.product_specs.find(
        {"product_pn": {"$in": req.product_pns}},
        {"_id": 0}                     # 不回傳 MongoDB _id
    ))

    if not products:
        raise HTTPException(status_code=404, detail="Products not found")

    # 依照使用者選擇的順序排序
    pn_order = {pn: i for i, pn in enumerate(req.product_pns)}
    products.sort(key=lambda p: pn_order.get(p.get("product_pn", ""), 99))

    # 產生 PDF
    try:
        pdf_bytes = generate_selection_report(products, req.criteria, req.ai_summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="selection_report.pdf"',
            "Content-Type": "application/pdf",
        },
    )
