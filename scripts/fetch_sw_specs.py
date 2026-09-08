import os
import json
import gspread
import pandas as pd
import re
from dotenv import load_dotenv

load_dotenv("configs/.env")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "configs/credentials.json")

def expand_series_name(raw_name):
    """
    解析合併的型號名稱，例如 'EKI-5700 with Realtech/7400/7700/9200/9500'
    轉為 ['EKI-5700', 'EKI-7400', 'EKI-7700', 'EKI-9200', 'EKI-9500']
    """
    if not raw_name or not isinstance(raw_name, str):
        return []
        
    # 清理換行與括號內的備註
    name = re.sub(r'\(.*?\)', '', raw_name)
    name = name.replace('\n', ' ').strip()
    
    # 尋找前綴，通常是 EKI-
    prefix_match = re.search(r'(EKI-\d{2}00)', name)
    prefix = "EKI-" if prefix_match else ""
    
    # 用斜線或空格等可能的分割字元
    # 常見格式："EKI-5700 with Realtech/7400/7700"
    # 我們找到所有的四位數 (結尾通常是00)
    models = re.findall(r'(EKI-\d{4}|\d{4})', name)
    
    expanded = []
    for m in models:
        clean_m = m.strip()
        if clean_m.isdigit() and len(clean_m) == 4:
            expanded.append(f"EKI-{clean_m}")
        elif clean_m.startswith("EKI-"):
            expanded.append(clean_m)
            
    # 如果 regex 沒抓到，至少回傳自己（清理後）
    if not expanded and name:
        return [name]
        
    return list(dict.fromkeys(expanded)) # 移除重複保留順序

def normalize_value(val):
    val = val.strip()
    
    # 一般的單一狀態轉換
    if val == "●":
        return "full"
    elif val == "○":
        return "in_development"
    elif val == "-":
        return "no"
    elif val == "":
        return "no"
    return val

def fetch_and_parse_sw_sheet(gc):
    print("讀取分頁: SW Dead Pool ...")
    try:
        worksheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("SW Dead Pool")
        data = worksheet.get_all_values()
    except Exception as e:
        print(f"❌ 讀取 SW Dead Pool 發生錯誤: {e}")
        return []

    if len(data) < 15:
        print("資料列數過少，可能格式錯誤。")
        return []

    # 1. 橫向清理 Headers (Row 0: Series, Row 11: Firmware)
    series_row = data[0]
    fw_row = data[11]

    # Forward-fill series horizontally
    current_series = ""
    for idx in range(len(series_row)):
        # Exclude col 0 and 1 which are Category and Item
        if idx < 2:
            continue
        val = series_row[idx].strip()
        if val != "":
            current_series = val
        else:
            series_row[idx] = current_series # forward fill
            
    # 同理，Firmware 也有可能是水平合併儲存格（多個型號共用同一個 f/w 版本）
    current_fw = ""
    for idx in range(len(fw_row)):
        if idx < 2:
            continue
        val = fw_row[idx].strip()
        if val != "":
            current_fw = val
        else:
            fw_row[idx] = current_fw # forward fill
            
    # 建立需要提取的欄位 Index (只要有 Firmware 的就算一欄)
    col_mappings = [] # list of dict { "col_idx": x, "raw_series": "", "fw": "", "expanded_series": [] }
    for col_idx in range(2, len(series_row)):
        raw_series = series_row[col_idx]
        fw = fw_row[col_idx].strip()
        
        # 即使 Firmware 為空也應該保留，可能只是 PM 忘了填寫
        if not fw:
            fw = "Unknown"
            
        expanded = expand_series_name(raw_series)
        col_mappings.append({
            "col_idx": col_idx,
            "raw_series": raw_series,
            "firmware_ver": fw,
            "expanded_series": expanded
        })

    # 2. 直向清理 Feature Categories (Col 0)
    # 從 Row 13 開始是細項
    features_start_idx = 13
    current_category = ""
    
    # 初始化每個 mapping 欄位的 software 字典
    for m in col_mappings:
        m["software"] = {}

    print("🔄 正在展開合併儲存格與解析軟體特徵矩陣...")
    for row_idx in range(features_start_idx, len(data)):
        row = data[row_idx]
        if not any(row): # 空列
             continue
             
        cat = row[0].replace('\n', ' ').strip()
        item = row[1].replace('\n', ' ').strip()
        
        # 直向 forward-fill category
        if cat != "":
            current_category = cat
        else:
            cat = current_category
            
        if item == "":
            continue # 如果 Item 為空，代表只是大類標題列
            
        # 遍歷所有有效欄位提取值
        for m in col_mappings:
            c_idx = m["col_idx"]
            val_raw = row[c_idx] if c_idx < len(row) else ""
            
            keys_to_assign = []
            vals_to_assign = []
            
            # 如果發現標題有斜線 (例如 Backup / Restore)
            if "/" in item and ("/" in val_raw or val_raw.strip() in ["-", "", "●", "○"]):
                item_parts = [p.strip() for p in item.split("/")]
                if "/" in val_raw:
                    val_parts = [p.strip() for p in val_raw.split("/")]
                else:
                    # 如果原標題有斜線，但值卻是單一的 "-"，則自動分配給全體
                    val_parts = [val_raw.strip()] * len(item_parts)
                    
                if len(item_parts) == len(val_parts):
                    keys_to_assign = item_parts
                    vals_to_assign = val_parts
                else:
                    keys_to_assign = [item]
                    vals_to_assign = [val_raw]
            else:
                keys_to_assign = [item]
                vals_to_assign = [val_raw]
            
            if cat not in m["software"]:
                m["software"][cat] = {}
                
            for k, v in zip(keys_to_assign, vals_to_assign):
                m["software"][cat][k] = normalize_value(v)

    # 3. 展開為多筆記錄 (因為一個 raw_series 可能對應多個型號)
    final_records = []
    for m in col_mappings:
        for series_name in m["expanded_series"]:
            record_id = f"{series_name}::{m['firmware_ver']}"
            final_records.append({
                "_id": record_id,
                "software_series": series_name,
                "raw_series_name": m["raw_series"], # Keep for debug
                "firmware_ver": m["firmware_ver"],
                "software": m["software"]
            })
            
    return final_records

def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    if not GOOGLE_SHEET_ID:
        print("⚠️ 尚未設定 GOOGLE_SHEET_ID，請先在 configs/.env 中設定此值。")
        return

    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        print(f"⚠️ 找不到 Google API 憑證檔案 {GOOGLE_CREDENTIALS_PATH}")
        return

    print("🔑 登入 Google Sheets API...")
    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)

    sw_specs = fetch_and_parse_sw_sheet(gc)
    
    # 輸出整理好的軟體規格檔案
    output_dir = "data"
    output_path = os.path.join(output_dir, "software_specs_raw.json")
    os.makedirs(output_dir, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sw_specs, f, ensure_ascii=False, indent=2)

    print(f"✅ 軟體規格已成功清理提取！共產出 {len(sw_specs)} 筆系列版本定義。")
    print(f"📁 檔案已存至: {output_path}")

if __name__ == "__main__":
    main()
