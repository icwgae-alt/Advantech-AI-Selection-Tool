"""
app/llm_gateway.py
統一 LLM 呼叫層 — LLM Gateway

【設計目的】
所有 RAG 元件（intent_parser、report_generator）都透過此層呼叫 Gemini，
不直接打 API。好處：
  1. 未來換模型只改這一個檔案
  2. 統一 retry / timeout 保護
  3. 統一 JSON 解析保護（strip Markdown wrapper）
  4. 集中用量追蹤（每次呼叫記錄到 logs/llm_usage.log）
  5. RPM 簡易限流（超過上限回傳 503，避免 API 配額耗盡）

【用量控管】
  - LLM_RPM_LIMIT：每分鐘最多幾次呼叫（預設 10），從 .env 讀取
  - 每次呼叫記錄 timestamp / task / model / prompt_chars 到 log 檔
"""

import os
import re
import json
import time
import logging
from collections import deque
from datetime import datetime
from typing import Any

import google.genai as genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv(dotenv_path="configs/.env")

# ── 日誌設定 ──────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
usage_logger = logging.getLogger("llm_usage")
usage_logger.setLevel(logging.INFO)
_handler = logging.FileHandler("logs/llm_usage.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
usage_logger.addHandler(_handler)


class LLMGateway:
    """
    統一 Gemini API 呼叫層。
    透過 singleton 模式在 FastAPI lifespan 初始化一次，全域共用。

    TASK_MODELS：各任務對應的模型名稱，修改模型只需改這裡。
    """

    # 各任務使用的模型（可從 .env 覆寫）
    TASK_MODELS: dict[str, str] = {
        "intent": os.getenv("INTENT_MODEL", "gemini-2.5-flash"),
        "report": os.getenv("CHAT_MODEL",   "gemini-2.5-flash"),
        "rfq_verdict": os.getenv("RFQ_VERDICT_MODEL", "gemini-2.5-flash"),
    }

    # 用量控管：RPM 上限（每分鐘最多幾次）
    RPM_LIMIT = int(os.getenv("LLM_RPM_LIMIT", "10"))

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError("GOOGLE_API_KEY 未設定，請檢查 configs/.env")
        self._client = genai.Client(api_key=api_key)

        # 滑動視窗記錄最近 60 秒內的呼叫 timestamp
        self._call_timestamps: deque[float] = deque()

    # ── RPM 限流 ──────────────────────────────────────────────────────────
    def _check_rate_limit(self):
        """
        檢查過去 60 秒內的呼叫次數是否超過 RPM_LIMIT。
        超過則拋出 RuntimeError（由 chat.py 轉換為 HTTP 503）。
        """
        now = time.time()
        # 移除 60 秒前的舊紀錄
        while self._call_timestamps and now - self._call_timestamps[0] > 60:
            self._call_timestamps.popleft()

        if len(self._call_timestamps) >= self.RPM_LIMIT:
            raise RuntimeError(
                f"LLM 呼叫頻率超過上限（{self.RPM_LIMIT} rpm），請稍後再試。"
            )
        self._call_timestamps.append(now)

    # ── 核心呼叫 ──────────────────────────────────────────────────────────
    def call(self, task: str, prompt: str, max_retries: int = 2) -> str:
        """
        呼叫 Gemini，回傳純文字回應。
        task：任務名稱（"intent" / "report"），決定使用哪個模型。
        失敗時自動 retry，最多 max_retries 次，每次間隔 1 秒。
        """
        self._check_rate_limit()

        model_name = self.TASK_MODELS.get(task, self.TASK_MODELS["report"])

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=8192,
                        # gemini-2.5-flash 的思考 token 跟輸出 token 共用 max_output_tokens 額度，
                        # 型號/context 一多，思考會把額度吃光導致答案被硬截斷（MAX_TOKENS）。
                        # 這裡是整理已知事實成 Markdown 的任務，不需要深度推理，關閉思考模式。
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    )
                )
                result = response.text

                # 記錄用量 log
                usage_logger.info(
                    f"task={task} model={model_name} "
                    f"prompt_chars={len(prompt)} output_chars={len(result)}"
                )
                return result

            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(1)

        raise RuntimeError(f"Gemini API 呼叫失敗（{max_retries+1} 次）：{last_err}")

    # ── JSON 解析保護 ──────────────────────────────────────────────────────
    def call_json(self, task: str, prompt: str) -> Any:
        """
        呼叫 Gemini 並解析 JSON 回應。
        自動 strip Markdown 代碼塊（```json ... ```），防止 Gemini 包 Markdown。
        解析失敗時回傳空 dict，不中斷流程。
        """
        raw = self.call(task, prompt)

        # 移除 ```json ... ``` 包裝
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            usage_logger.warning(f"task={task} JSON 解析失敗，回傳空 dict。raw={raw[:200]}")
            return {}


# ── Singleton 實例（由 main.py lifespan 初始化）────────────────────────────
_gateway_instance: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    """取得全域 LLMGateway 實例。"""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = LLMGateway()
    return _gateway_instance
