"""
app/rag/datasheet_expert.py
Type B（型號規格查詢）用：呼叫外部 Advantech Product Expert API。

【設計重點】
- 使用者問題若明確提到型號（見 model_detector.py），直接把原問題丟給外部 API，
  換取比 MongoDB 結構化欄位更完整的 Datasheet 內容問答（含 whitepaper / manual 等來源）。
- 對應 Plan/chatbot_query_routing_design.md 的 Type B 規格查詢流程，
  以外部服務取代自建的 MongoDB + 向量搜尋 Pipeline。
- 呼叫失敗（timeout / 非 200）一律拋出 RuntimeError，由 chat.py 接住並 fallback
  回原本 3-Stage Pipeline，不中斷使用者體驗。
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path="configs/.env")

PRODUCT_API_URL = os.getenv("PRODUCT_API_URL")
PRODUCT_API_KEY = os.getenv("PRODUCT_API_KEY")
PRODUCT_API_TIMEOUT = float(os.getenv("PRODUCT_API_TIMEOUT", "120"))


def ask_product_expert(query: str) -> str:
    """
    呼叫 Product Expert API，回傳純文字回答。
    失敗時拋出 RuntimeError，由呼叫端決定 fallback 策略。
    """
    if not PRODUCT_API_URL or not PRODUCT_API_KEY:
        raise RuntimeError("PRODUCT_API_URL / PRODUCT_API_KEY 未設定，請檢查 configs/.env")

    clean_query = " ".join(query.split()).strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "x-api-key": PRODUCT_API_KEY,
    }

    try:
        response = httpx.post(
            PRODUCT_API_URL,
            json={"text": clean_query},
            headers=headers,
            timeout=httpx.Timeout(PRODUCT_API_TIMEOUT, connect=30.0),
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Product Expert API 逾時（{PRODUCT_API_TIMEOUT}s）") from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Product Expert API 回傳錯誤狀態碼：{exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Product Expert API 呼叫失敗：{exc}") from exc

    result = response.json()
    text = result.get("text", "")
    if not text:
        raise RuntimeError("Product Expert API 回傳內容為空")
    return text
