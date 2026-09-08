"""
app/rag/model_detector.py
簡單規則判斷使用者問題是否明確提到型號（Type B 型號規格查詢的路由依據）。

【設計重點】
- 目前資料庫（data/hardware_specs_raw.json）型號 PN 只有 "EKI-" / "ADAM-" 兩種前綴，
  以此縮小 regex 誤判範圍，避免把一般英文縮寫誤判為型號。
- 這是 P0 版本的簡單規則判斷，之後若要更準確可升級為 Plan/chatbot_query_routing_design.md
  規劃的 LLM Query Router（Stage 0）。
"""

import re

_MODEL_PATTERN = re.compile(r"\b(EKI|ADAM)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)


def detect_models(message: str) -> list[str]:
    """
    從使用者問題中偵測明確提到的型號 PN。
    回傳去重後的大寫型號清單（依出現順序），沒有偵測到則回傳空清單。
    """
    seen = set()
    models = []
    for match in _MODEL_PATTERN.finditer(message):
        pn = match.group(0).upper()
        if pn not in seen:
            seen.add(pn)
            models.append(pn)
    return models
