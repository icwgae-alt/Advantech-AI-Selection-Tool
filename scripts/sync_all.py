"""
sync_all.py — 一鍵同步所有 Google Sheet 資料

執行順序：
  Step 1: 登入 Google Sheets（只登入一次）
  Step 2: 擷取硬體規格 (Ind. SW / Train SW)  → data/hardware_specs_raw.json
  Step 3: 擷取軟體規格 (SW Version)           → data/software_specs_raw.json
  Step 4: 擷取 SFP 模組清單 (SFP)            → frontend/data/sfp_modules.json
  Step 5: 合併 HW + SW → 寫入 MongoDB

策略：任一步驟失敗即中斷，等問題解決後重跑。

用法：
  uv run python scripts/sync_all.py
"""

import sys
import os
import json
import time

sys.stdout.reconfigure(encoding='utf-8')

# ── 確保從專案根目錄執行，讓各模組可以正確載入 configs/.env ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv('configs/.env')

import gspread

# ── 從既有腳本匯入核心函式（不重複造輪子）─────────────────────
from scripts.fetch_hardware_specs import fetch_hardware_data, process_hardware
from scripts.fetch_sw_specs import fetch_and_parse_sw_sheet
from scripts.sync_specs_to_mongo import get_db, infer_series_from_pn

# ── SFP 解析邏輯（從 fetch_sfp_modules.py 移植為函式形式）──────
import re as _re

def _parse_speed(raw):
    r = raw.strip().lower()
    if not r:
        return None
    if 'copper' in r:
        return 'copper'
    if '10 gbps' in r or '10gbps' in r:
        return '10G'
    if '1.25' in r or '1000' in r:
        return '1G'
    if '100' in r:
        return '100M'
    return r

def _parse_mode_cat_bidi(raw_mode):
    m = raw_mode.strip().lower()
    if m == 'copper':
        return ('any', 'copper', False)
    if 'bi-directional' in m or 'bidi' in m:
        return ('single-mode', 'fiber', True)
    if 'multi' in m:
        return ('multi-mode', 'fiber', False)
    if 'single' in m:
        return ('single-mode', 'fiber', False)
    return (m, 'fiber', False)

def _parse_connector(raw_conn):
    c = raw_conn.strip()
    if not c:
        return ''
    c_low = c.lower()
    if 'rj45' in c_low or 'rj-45' in c_low:
        return 'RJ45'
    if 'lc' in c_low:
        return 'LC'
    if 'sc' in c_low:
        return 'SC'
    return c

def _parse_duplex(raw_conn):
    c = raw_conn.strip().lower()
    if 'simplex' in c:
        return 'simplex'
    if 'duplex' in c:
        return 'duplex'
    return ''

def fetch_sfp_modules(gc):
    """從 Google Sheet 的 SFP 分頁擷取模組清單，回傳 list of dict。"""
    GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID', '')
    ws   = gc.open_by_key(GOOGLE_SHEET_ID).worksheet('SFP')
    data = ws.get_all_values()

    rows = data[2:]  # Row 0: merged header groups, Row 1: column headers, Row 2+: data
    COL_SPEED, COL_PART, COL_MODE = 0, 1, 2
    COL_DIST, COL_CONN, COL_WAVE  = 4, 5, 9

    modules = []
    current_speed = None

    for row in rows:
        part = row[COL_PART].strip() if len(row) > COL_PART else ''
        if not part or part.startswith('*'):
            continue

        speed_raw   = row[COL_SPEED].strip() if len(row) > COL_SPEED else ''
        speed_clean = ' '.join(speed_raw.split())
        if speed_clean:
            current_speed = _parse_speed(speed_clean)

        mode_raw = row[COL_MODE].strip() if len(row) > COL_MODE else ''
        dist     = row[COL_DIST].strip() if len(row) > COL_DIST else ''
        conn_raw = row[COL_CONN].strip() if len(row) > COL_CONN else ''
        wave     = row[COL_WAVE].strip() if len(row) > COL_WAVE else ''
        wave     = '' if wave.startswith('#') else wave

        mode, cat, bidi = _parse_mode_cat_bidi(mode_raw)
        conn   = _parse_connector(conn_raw)
        duplex = _parse_duplex(conn_raw)

        pair = ''
        if bidi:
            if 'TX' in part.upper():
                pair = part.replace('TX', 'RX')
            elif 'RX' in part.upper():
                pair = part.replace('RX', 'TX')

        modules.append({
            'part':   part,
            'speed':  current_speed,
            'cat':    cat,
            'mode':   mode,
            'bidi':   bidi,
            'pair':   pair,
            'conn':   conn,
            'duplex': duplex,
            'dist':   dist,
            'wave':   wave,
        })

    return modules


# ── Sync to MongoDB（從 sync_specs_to_mongo.py 移植）─────────────
from pymongo import UpdateOne

def sync_to_mongo(hw_raw, sw_raw):
    """將硬體、軟體規格 JOIN 後批次寫入 MongoDB。"""
    db = get_db()
    if db is None:
        raise RuntimeError("無法連線至 MongoDB，請確認 MONGO_URI 設定正確。")

    MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'advantech_ind_sw_tool')
    print(f"   🔌 成功連線至 MongoDB Database: {MONGO_DB_NAME}")

    # 寫入 software_specs
    db.software_specs.create_index(
        [("software_series", 1), ("firmware_ver", 1)], unique=True
    )
    sw_updates = [
        UpdateOne({"_id": sw["_id"]}, {"$set": sw}, upsert=True)
        for sw in sw_raw
    ]
    if sw_updates:
        db.software_specs.bulk_write(sw_updates)
    print(f"   ✅ software_specs 已同步 {len(sw_updates)} 筆")

    # 寫入 hardware_specs 並進行 JOIN
    hw_list = hw_raw.get("industrial_sw", []) + hw_raw.get("train_sw", [])
    hw_updates      = []
    product_inserts = []
    failed_merges   = []

    for hw in hw_list:
        pn = hw.get("Product PN", "").strip()
        if not pn:
            continue

        # Application 不再同步為結構化欄位；防呆處理舊版 hardware_specs_raw.json
        # 仍殘留這個 key 的情況（正常情況下 fetch_hardware_specs.py 已經在來源排除）
        hw.pop("Application", None)

        hw["_id"] = pn
        hw_updates.append(UpdateOne({"_id": pn}, {"$set": hw}, upsert=True))

        hw_sw_series = hw.get("Software Series", "").strip()
        hw_fw_ver    = hw.get("Firmware Version", "").strip()
        is_inferred  = False

        if not hw_sw_series or not hw_fw_ver:
            hw_sw_series = infer_series_from_pn(pn)
            available_series = [s["software_series"] for s in sw_raw]
            if hw_sw_series not in available_series:
                hw_sw_series = "EKI-5500"
            if hw_sw_series:
                matching_sws = [s for s in sw_raw if s["software_series"] == hw_sw_series]
                if matching_sws:
                    matching_sws.sort(key=lambda x: str(x.get("firmware_ver", "")), reverse=True)
                    hw_fw_ver   = matching_sws[0]["firmware_ver"]
                    is_inferred = True

        matched_sw = next(
            (s for s in sw_raw if s["software_series"] == hw_sw_series and s["firmware_ver"] == hw_fw_ver),
            None
        )

        if matched_sw:
            product_doc = {
                "_id": pn,
                "product_pn": pn,
                "model_name": hw.get("Model Name", ""),
                "software_mapped_series": hw_sw_series,
                "software_mapped_fw": hw_fw_ver,
                "is_inferred": is_inferred,
                "hardware": hw,
                "software": matched_sw.get("software", {})
            }
            product_inserts.append(UpdateOne({"_id": pn}, {"$set": product_doc}, upsert=True))
        else:
            failed_merges.append({"pn": pn, "tried_series": hw_sw_series, "tried_fw": hw_fw_ver})

    if hw_updates:
        db.hardware_specs.bulk_write(hw_updates)
    print(f"   ✅ hardware_specs 已同步 {len(hw_updates)} 筆")

    if product_inserts:
        db.product_specs.create_index([("product_pn", 1)])
        db.product_specs.create_index([("model_name", 1)])
        db.product_specs.bulk_write(product_inserts)
    print(f"   ✅ product_specs JOIN 完成：成功 {len(product_inserts)} 筆，失敗 {len(failed_merges)} 筆")

    # 輸出驗證報告
    report = {
        "success_merges": [u._filter["_id"] for u in product_inserts],
        "failed_merges":  failed_merges
    }
    report_path = "data/validation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"   📁 驗證報告已輸出至: {report_path}")

    return len(product_inserts), len(failed_merges)


# ══════════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════════

def run_step(step_num, total, description, fn):
    """執行單一步驟，失敗時拋出例外（Fail-Fast）。"""
    print(f"\n{'─'*60}")
    print(f"  Step {step_num}/{total} — {description}")
    print(f"{'─'*60}")
    t0 = time.time()
    result = fn()
    elapsed = time.time() - t0
    print(f"  ✅ 完成（耗時 {elapsed:.1f}s）")
    return result


def main():
    GOOGLE_CREDENTIALS_PATH = os.getenv('GOOGLE_CREDENTIALS_PATH', 'configs/credentials.json')
    GOOGLE_SHEET_ID         = os.getenv('GOOGLE_SHEET_ID', '')

    print("=" * 60)
    print("  Advantech AI Selection Tool — 全資料同步")
    print("=" * 60)

    # ── 前置檢查 ──────────────────────────────────────────────────
    if not GOOGLE_SHEET_ID:
        sys.exit("❌ 尚未設定 GOOGLE_SHEET_ID，請先在 configs/.env 中設定。")
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        sys.exit(f"❌ 找不到 Google API 憑證檔案：{GOOGLE_CREDENTIALS_PATH}")

    total_steps = 5

    # ── Step 1: 登入 Google Sheets ────────────────────────────────
    gc = run_step(1, total_steps, "登入 Google Sheets API",
        lambda: gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)
    )

    # ── Step 2: 擷取硬體規格 ──────────────────────────────────────
    def step_hw():
        df_ind   = fetch_hardware_data(gc, "Ind. SW")
        df_train = fetch_hardware_data(gc, "Train SW")
        if df_ind.empty and df_train.empty:
            raise ValueError("Ind. SW 與 Train SW 分頁均讀取失敗或為空，請確認 Google Sheet 結構。")
        print(f"   📊 Ind. SW: {len(df_ind)} 筆 | Train SW: {len(df_train)} 筆")
        hw_raw = {
            "industrial_sw": process_hardware(df_ind),
            "train_sw":      process_hardware(df_train)
        }
        os.makedirs("data", exist_ok=True)
        with open("data/hardware_specs_raw.json", "w", encoding="utf-8") as f:
            json.dump(hw_raw, f, ensure_ascii=False, indent=2)
        print(f"   📁 已存至: data/hardware_specs_raw.json")
        return hw_raw

    hw_raw = run_step(2, total_steps, "擷取硬體規格 (Ind. SW / Train SW)", step_hw)

    # ── Step 3: 擷取軟體規格 ──────────────────────────────────────
    def step_sw():
        sw_raw = fetch_and_parse_sw_sheet(gc)
        if not sw_raw:
            raise ValueError("SW Version 分頁讀取失敗或解析結果為空，請確認 Google Sheet 結構。")
        os.makedirs("data", exist_ok=True)
        with open("data/software_specs_raw.json", "w", encoding="utf-8") as f:
            json.dump(sw_raw, f, ensure_ascii=False, indent=2)
        print(f"   📊 共解析 {len(sw_raw)} 筆軟體規格")
        print(f"   📁 已存至: data/software_specs_raw.json")
        return sw_raw

    sw_raw = run_step(3, total_steps, "擷取軟體規格 (SW Version)", step_sw)

    # ── Step 4: 擷取 SFP 模組 ─────────────────────────────────────
    def step_sfp():
        modules = fetch_sfp_modules(gc)
        if not modules:
            raise ValueError("SFP 分頁讀取失敗或無任何模組資料，請確認 Google Sheet 結構。")
        os.makedirs("frontend/data", exist_ok=True)
        with open("frontend/data/sfp_modules.json", "w", encoding="utf-8") as f:
            json.dump(modules, f, ensure_ascii=False, indent=2)
        print(f"   📊 共解析 {len(modules)} 筆 SFP 模組")
        print(f"   📁 已存至: frontend/data/sfp_modules.json")
        return modules

    run_step(4, total_steps, "擷取 SFP 模組清單 (SFP)", step_sfp)

    # ── Step 5: 合併寫入 MongoDB ───────────────────────────────────
    def step_mongo():
        success, failed = sync_to_mongo(hw_raw, sw_raw)
        return success, failed

    success_count, failed_count = run_step(5, total_steps, "合併 HW + SW → 寫入 MongoDB", step_mongo)

    # ── 完成摘要 ──────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("  🎉 全部同步完成！")
    print(f"     Product Specs 成功配對：{success_count} 筆")
    if failed_count > 0:
        print(f"     ⚠️  配對失敗：{failed_count} 筆（詳見 data/validation_report.json）")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 同步中斷：{e}")
        print("   請確認錯誤原因後重新執行 sync_all.py\n")
        sys.exit(1)
