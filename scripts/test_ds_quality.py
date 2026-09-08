"""
比較現有純結構化資料 vs 加入 DS 內容的 chatbot 回答品質
測試型號：EKI-7706E-2F
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm_gateway import get_gateway
from app.database import Database
from app.rag.report_generator import _summarize_doc
import json

Database.connect_db()
db = Database.get_db()
gateway = get_gateway()

# ── 取出 EKI-7706E-2F 的結構化規格 ──────────────────────
doc = db.product_specs.find_one({"product_pn": "EKI-7706E-2F-AE"}) or \
      db.product_specs.find_one({"model_name": {"$regex": "EKI-7706E-2F"}})

if not doc:
    print("找不到 EKI-7706E-2F，列出可用型號：")
    for d in db.product_specs.find({}, {"product_pn":1}).limit(10):
        print(" ", d.get("product_pn"))
    sys.exit()

structured_spec = _summarize_doc(doc)
print("=== 結構化規格（MongoDB）===")
print(json.dumps(structured_spec, ensure_ascii=False, indent=2))

# ── 讀入 DS markdown ──────────────────────────────────────
ds_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "DS_md", "EKI-7706E-2F.md")
with open(ds_path, encoding="utf-8") as f:
    ds_content = f.read()

# ── 測試問題 ──────────────────────────────────────────────
QUESTIONS = [
    "Does EKI-7706E-2F support railway trackside deployment?",
    "What redundancy protocols does it support and how fast is the recovery time?",
    "Is it suitable for a substation application that requires IEC 61850?",
]

print("\n" + "="*60)
print("測試：三個問題，各跑兩次（只用結構化 vs 加入 DS）")
print("="*60)

for q in QUESTIONS:
    print(f"\n{'─'*60}")
    print(f"Q: {q}")

    # 版本 A：只用結構化資料（現有方式）
    prompt_a = f"""You are Advantech Switch Selection AI.
Answer based ONLY on this spec data:
{json.dumps(structured_spec, ensure_ascii=False)}

Question: {q}
Keep answer under 80 words."""

    ans_a = gateway.call("report", prompt_a)
    print(f"\n[A] 純結構化資料：\n{ans_a.strip()}")

    # 版本 B：加入 DS 內容
    prompt_b = f"""You are Advantech Switch Selection AI.
Answer based on the spec data and datasheet content below.

Spec data:
{json.dumps(structured_spec, ensure_ascii=False)}

Datasheet content:
{ds_content[:3000]}

Question: {q}
Keep answer under 80 words."""

    ans_b = gateway.call("report", prompt_b)
    print(f"\n[B] 加入 Datasheet：\n{ans_b.strip()}")
