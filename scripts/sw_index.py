import os
import sys
from typing import List, Dict

# 將專案根目錄加入路徑，確保能匯入 app 模組
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Database
from app.models.selection import SearchFeatureItem

# =========================================================================
# 模擬選型工具的快取變數與邏輯
# =========================================================================
base_hardware_mappings = {
    "Has_PoE": "Hardware Feature",
    "Has_Fiber": "Hardware Feature",
    "Has_RJ-45": "Hardware Feature",
    "Temp_Wide": "Hardware Feature"
}

SW_SUPPORTED_VALUES = ["full", "optional"]
SW_VALID_VALUES = set(SW_SUPPORTED_VALUES + ["no", ""])

DYNAMIC_SW_MAPPINGS: Dict[str, Dict[str, str]] = {}
SEARCHABLE_ITEMS: List[SearchFeatureItem] = []


def load_dynamic_mappings_if_needed():
    """
    從資料庫動態掃描所有功能，模擬選型工具的初始化過程。
    """
    if SEARCHABLE_ITEMS:
        return

    db = Database.get_db()
    # 取得一個含有軟體規格的樣本作為結構參考
    sample_doc = db.product_specs.find_one({"software": {"$exists": True, "$ne": {}}})
    
    if not sample_doc:
        print("警告：資料庫中找不到任何軟體規格文件。")
        return

    # 1. 載入硬體進階條件
    for hd_key in base_hardware_mappings.keys():
        SEARCHABLE_ITEMS.append(SearchFeatureItem(
            label=hd_key.replace("_", " "),
            key=hd_key,
            category="Hardware Feature"
        ))

    # 2. 動態展開軟體功能
    sw_data = sample_doc.get("software", {})
    for category, features in sw_data.items():
        if not isinstance(features, dict):
            continue
        for feat_key, feat_val in features.items():
            # 只抓取三態值欄位
            if feat_val not in SW_VALID_VALUES:
                continue

            item_key = f"{category}|||{feat_key}"
            DYNAMIC_SW_MAPPINGS[item_key] = {"category": category, "feat_key": feat_key}
            SEARCHABLE_ITEMS.append(SearchFeatureItem(
                label=feat_key,
                key=item_key,
                category=category
            ))


def run_diagnostic():
    """
    執行診斷並列印結果
    """
    print("=" * 60)
    print("  Advantech AI Selection Tool - Feature Index Diagnostic")
    print("=" * 60)
    
    try:
        load_dynamic_mappings_if_needed()
    except Exception as e:
        print(f"錯誤：無法連線資料庫或處理資料：{e}")
        return

    if not SEARCHABLE_ITEMS:
        print("未掃描到任何功能項目。")
        return

    # 按 Category 分組顯示
    grouped_items = {}
    for item in SEARCHABLE_ITEMS:
        if item.category not in grouped_items:
            grouped_items[item.category] = []
        grouped_items[item.category].append(item.label)

    print(f"總計掃描到 {len(SEARCHABLE_ITEMS)} 個功能項，分佈在 {len(grouped_items)} 個分類中：\n")

    for category in sorted(grouped_items.keys()):
        items = grouped_items[category]
        print(f"【{category}】({len(items)} 項)")
        # 每行印 3 個功能名稱節省空間
        for i in range(0, len(items), 3):
            line = "  • " + "  • ".join(items[i:i+3])
            print(line)
        print("-" * 40)

    print("\n[完成] 診斷結束。")


if __name__ == "__main__":
    run_diagnostic()
