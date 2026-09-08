import os
import json
import gspread
import pandas as pd
from dotenv import load_dotenv

load_dotenv("configs/.env")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "configs/credentials.json")

def fetch_hardware_data(gc, tab_name):
    print(f"讀取分頁: {tab_name} ...")
    try:
        worksheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(tab_name)
        data = worksheet.get_all_values()
        # Find header index dynamically by looking for 'Model Name' and 'Product PN'
        header_idx = -1
        for i, row in enumerate(data):
            if "Model Name" in row and "Product PN" in row:
                header_idx = i
                break
        
        if header_idx == -1:
            print(f"⚠️ 找不到 {tab_name} 的表頭，預設使用 index 3")
            header_idx = 3
            
        headers = data[header_idx]
        
        # Make headers unique to avoid pandas warnings
        seen = {}
        unique_headers = []
        for h in headers:
            # 移除換行符號，並將多餘的空白壓縮為單一空白
            h = " ".join(h.replace('\n', ' ').split()).strip()
            if h == "":
                h = "Unnamed"
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)
                
        df = pd.DataFrame(data[header_idx + 1:], columns=unique_headers)
        
        # Drop rows where 'Product PN' is empty
        if 'Product PN' in df.columns:
            df = df[df['Product PN'].str.strip() != ""]
            
        return df
    except gspread.exceptions.WorksheetNotFound:
        print(f"❌ 找不到分頁: {tab_name}")
        return pd.DataFrame()
    except Exception as e:
        print(f"❌ 讀取 {tab_name} 發生錯誤: {e}")
        return pd.DataFrame()

def forward_fill_columns(df, cols_to_ffill):
    """向下填充合併儲存格的空白欄位"""
    for col in cols_to_ffill:
        if col in df.columns:
            df[col] = df[col].replace("", pd.NA)
            df[col] = df[col].ffill()
            df[col] = df[col].fillna("")
    return df

def process_hardware(df):
    """硬體資料清理"""
    if df.empty:
        return []
    # 填充合併儲存格
    cols_to_fill = ["Function", "Model Name", "Software Series", "Type"]
    df = forward_fill_columns(df, cols_to_fill)
    
    # 針對 Input Voltage 統一符號 (將波浪號 ~ 轉為減號 -)
    input_voltage_col = next((col for col in df.columns if "Input Voltage" in col), None)
    if input_voltage_col:
        df[input_voltage_col] = df[input_voltage_col].astype(str).str.replace("~", "-", regex=False)

    # Application 欄位不再同步（決策：不以應用場景做結構化區分，選型工具與 chatbot
    # 都不使用這個欄位），直接在來源排除，不寫進 hardware_specs_raw.json
    if "Application" in df.columns:
        df = df.drop(columns=["Application"])

    return df.to_dict(orient="records")

def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    if not GOOGLE_SHEET_ID:
        print("⚠️ 尚未設定 GOOGLE_SHEET_ID，請先在 .env 中設定此值。")
        return

    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        print(f"⚠️ 找不到 Google API 憑證檔案 {GOOGLE_CREDENTIALS_PATH}")
        print("請確定已將 Service Account 的 JSON 檔案放置在專案目錄下。")
        return

    print("🔑 登入 Google Sheets API...")
    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)

    # 擷取兩個硬體規格的分頁
    df_ind = fetch_hardware_data(gc, "Ind. SW")
    df_train = fetch_hardware_data(gc, "Train SW")

    print(f"📊 Ind. SW 取得 {len(df_ind)} 筆, Train SW 取得 {len(df_train)} 筆資料")
    print("🔄 正在進行合併儲存格展開與清理...")
    
    # 為了後續寫入資料庫方便處理，也可以將兩者合併並加上 source_type 標籤
    # 這裡先輸出成原始整理用的 dict 格式，裡面分別有兩個 array
    result = {
        "industrial_sw": process_hardware(df_ind),
        "train_sw": process_hardware(df_train)
    }

    # 輸出整理好的硬體規格檔案
    output_dir = "data"
    output_path = os.path.join(output_dir, "hardware_specs_raw.json")
    os.makedirs(output_dir, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ 硬體規格已成功清理並儲存到: {output_path}")

if __name__ == "__main__":
    main()
