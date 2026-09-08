import re
from fastapi import APIRouter, HTTPException
from typing import List, Dict
from app.database import Database
from app.models.selection import SubmitProdRequest, SubmitProdResponse, ProductItemResponse, SearchFeatureItem

router = APIRouter()

# =========================================================================
# 【維護性設計】硬體進階條件對應表（Dict + Callable）
# 由於 software category key 中含有 "." 字元（如 "VLAN(IEEE 802.1Q)"），
# MongoDB dot-notation 會將 "." 誤解為路徑分隔符，導致查詢失敗。
# 解決方案：軟體查詢改用 $expr + $getField，硬體查詢沿用 dot-notation。
# =========================================================================
base_hardware_mappings = {

    "Has_PoE": lambda: {"$or": [
        {"hardware.PoE RJ-45 100M": {"$regex": "^[1-9]"}},
        {"hardware.PoE RJ-45 GbE": {"$regex": "^[1-9]"}},
        {"hardware.PoE (D-code)": {"$regex": "^[1-9]"}},
        {"hardware.PoE (X-code)": {"$regex": "^[1-9]"}}
    ]},
    # 明確排除所有具備 PoE 供電的型號（與 Has_PoE 條件互斥，供 PoE 篩選的 "Non-PoE" 選項使用）
    "No_PoE": lambda: {"$nor": [
        {"hardware.PoE RJ-45 100M": {"$regex": "^[1-9]"}},
        {"hardware.PoE RJ-45 GbE": {"$regex": "^[1-9]"}},
        {"hardware.PoE (D-code)": {"$regex": "^[1-9]"}},
        {"hardware.PoE (X-code)": {"$regex": "^[1-9]"}}
    ]},
    "Has_Fiber": lambda: {"$or": [
        {"hardware.Fiber 100M": {"$regex": "^[1-9]"}},
        {"hardware.Fiber Gigabit": {"$regex": "^[1-9]"}},
        {"hardware.Fiber GE Combo": {"$regex": "^[1-9]"}},
        {"hardware.Fiber 10G": {"$regex": "^[1-9]"}}
    ]},
    "Has_RJ-45": lambda: {"$or": [
        {"hardware.RJ-45 10/100M": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 Gigabit": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 Combo": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 10GbE": {"$regex": "^[1-9]"}}
    ]},
    "Temp_Wide": lambda: {"hardware.Temp Grade": {"$in": ["Wide", "wide", "T", "Wide Temp"]}},

    # 電源輸入條件
    "Pwr_DC": lambda: {
        "hardware.Input Voltage": {
            "$regex": "VDC|vdc",
            "$options": "i"
        }
    },
    "Pwr_AC": lambda: {
        "hardware.Input Voltage": {
            "$regex": "VAC|AC",
            "$options": "i"
        }
    },
    "Pwr_12V": lambda: {
        "hardware.Input Voltage": {
            "$regex": r"^(([1-9]|1[012])\s*(-|~|\s))",
            "$options": "i"
        }
    },
    "Pwr_24V": lambda: {
        "hardware.Input Voltage": {
            "$regex": r"^(([1-9]|1[0-9]|2[0-4])\s*(-|~|\s))",
            "$options": "i"
        }
    },
    "Pwr_High_Voltage": lambda: {
        "hardware.Input Voltage": {
            "$regex": r"48.*V|72.*V|96.*V|110.*V|220.*V|HV",
            "$options": "i"
        }
    },

    # 網口速度與接頭
    "Port_RJ45_GbE": lambda: {"$or": [
        {"hardware.RJ-45 Gigabit": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 Combo": {"$regex": "^[1-9]"}}
    ]},
    "Port_RJ45_100M": lambda: {"hardware.RJ-45 10/100M": {"$regex": "^[1-9]"}},
    "Port_Fiber_GbE": lambda: {"$or": [
        {"hardware.Fiber Gigabit": {"$regex": "^[1-9]"}},
        {"hardware.Fiber GE Combo": {"$regex": "^[1-9]"}}
    ]},
    "Port_Fiber_10G": lambda: {"hardware.Fiber 10G": {"$regex": "^[1-9]"}},
    "Port_M12_Any": lambda: {"$or": [
        {"hardware.Eth 10/100M (D-code)": {"$regex": "^[1-9]"}},
        {"hardware.Eth Gigabit (X-code)": {"$regex": "^[1-9]"}},
        {"hardware.Eth Multi-Giga (X-code)": {"$regex": "^[1-9]"}}
    ]},
    "Port_M12_GbE": lambda: {"hardware.Eth Gigabit (X-code)": {"$regex": "^[1-9]"}},
    # TODO: SPE (Single Pair Ethernet) 資料庫目前無對應欄位，此條件永遠 0 筆結果（佔位）。
    # 待資料庫補上 SPE 相關欄位後，把下方欄位名稱換成實際欄位即可啟用。
    "Port_SPE_Any": lambda: {"hardware.SPE": {"$regex": "^[1-9]"}},
    "Port_MultiGiga": lambda: {"$or": [
        {"hardware.Eth Multi-Giga (X-code)": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 10GbE": {"$regex": "^[1-9]"}}
    ]},
    "Port_Bypass": lambda: {"$or": [
        {"hardware.LAN Bypass 10/100M (D-code)": {"$regex": "^[1-9]"}},
        {"hardware.LAN Bypass Gigabit (X-code)": {"$regex": "^[1-9]"}}
    ]},

    # Max Port Speed filters
    "Speed_100M": lambda: {"$or": [
        {"hardware.RJ-45 10/100M": {"$regex": "^[1-9]"}},
        {"hardware.Fiber 100M": {"$regex": "^[1-9]"}},
        {"hardware.Eth 10/100M (D-code)": {"$regex": "^[1-9]"}}
    ]},
    "Speed_GbE": lambda: {"$or": [
        {"hardware.RJ-45 Gigabit": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 Combo": {"$regex": "^[1-9]"}},
        {"hardware.Fiber Gigabit": {"$regex": "^[1-9]"}},
        {"hardware.Fiber GE Combo": {"$regex": "^[1-9]"}},
        {"hardware.Fiber 10G": {"$regex": "^[1-9]"}},
        {"hardware.Eth Gigabit (X-code)": {"$regex": "^[1-9]"}},
        {"hardware.Eth Multi-Giga (X-code)": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 10GbE": {"$regex": "^[1-9]"}}
    ]},
    "Speed_10G": lambda: {"$or": [
        {"hardware.Fiber 10G": {"$regex": "^[1-9]"}},
        {"hardware.Eth Multi-Giga (X-code)": {"$regex": "^[1-9]"}},
        {"hardware.RJ-45 10GbE": {"$regex": "^[1-9]"}}
    ]},

    # Certifications filters (regex match within comma-separated string)
    "Cert_UL":      lambda: {"hardware.Certifications": {"$regex": "UL",       "$options": "i"}},
    "Cert_LVD":     lambda: {"hardware.Certifications": {"$regex": "LVD",      "$options": "i"}},
    "Cert_IEC61850":lambda: {"hardware.Certifications": {"$regex": "IEC61850", "$options": "i"}},
    "Cert_NEMA":    lambda: {"hardware.Certifications": {"$regex": "NEMA",     "$options": "i"}},
    "Cert_EN50155": lambda: {"hardware.Certifications": {"$regex": "EN 50155", "$options": "i"}},
    "Cert_EMark":   lambda: {"hardware.Certifications": {"$regex": "E-Mark",   "$options": "i"}},
    "Cert_ITxPT":   lambda: {"hardware.Certifications": {"$regex": "ITxPT",    "$options": "i"}},
}

# 三態值中合法的「有支援」值
SW_SUPPORTED_VALUES = ["full",  "optional"] #"in_development" 先拿掉，算是尚不支援
# 三態值欄位允許的所有值（排除非三態值字串如 "256", "8K"）
SW_VALID_VALUES = set(SW_SUPPORTED_VALUES + ["no", ""])

# =========================================================================
# 【動態快取設計】
# DYNAMIC_SW_MAPPINGS: 用於查詢，格式 { "item_key": {"category": "...", "feat_key": "..."} }
# SEARCHABLE_ITEMS:   用於前端搜尋清單回傳。
#
# 關鍵設計：採用 "category|||feat_key" 作為唯一的 item_key。
# 為什麼用 "|||"？
# 1. 它是自訂分隔符（膠帶），把分類與功能捆在一起傳給前端。
# 2. 避開 "." 字元：分類名（如 802.1Q）若含點，用 "." 分隔會導致 MongoDB 路徑解析錯誤。
# 3. 唯一性：此符號極少出現在規格書中，拆解時非常安全。
# =========================================================================
DYNAMIC_SW_MAPPINGS: Dict[str, Dict[str, str]] = {}
SEARCHABLE_ITEMS: List[SearchFeatureItem] = []


def make_sw_expr_query(category: str, feat_key: str) -> dict:
    """
    使用 MongoDB $expr + $getField 建構軟體功能查詢。
    可正確處理 category/feat_key 中含有 "." 等特殊字元的情況（dot-notation 無法處理）。
    """
    return {
        "$expr": {
            "$in": [
                {
                    "$getField": {
                        "field": feat_key,
                        "input": {
                            "$getField": {
                                "field": category,
                                "input": "$software"
                            }
                        }
                    }
                },
                SW_SUPPORTED_VALUES
            ]
        }
    }


def load_dynamic_mappings_if_needed():
    """
    從資料庫動態掃描所有軟體功能，建立搜尋對應表（快取於記憶體）。
    高維護性：無需手動維護 65 項功能清單，Google Sheet 新增欄位即自動感知。
    """
    if SEARCHABLE_ITEMS:
        return

    db = Database.get_db()
    sample_doc = db.product_specs.find_one({"software": {"$exists": True, "$ne": {}}})
    if not sample_doc:
        return

    sw_data = sample_doc.get("software", {})

    # 載入手動定義的硬體進階條件
    POWER_KEY_LABELS = {
        "Pwr_DC":           "DC Power Input",
        "Pwr_AC":           "AC Power Input",
        "Pwr_12V":          "12V Support (Min ≤12V)",
        "Pwr_24V":          "24V Support (Min ≤24V)",
        "Pwr_High_Voltage": "High Voltage Power (≥48V)",
    }
    PORT_SPEED_KEY_LABELS = {
        "Port_RJ45_GbE":  "RJ-45 GbE (incl. Combo)",
        "Port_RJ45_100M": "RJ-45 100M (Fast Ethernet)",
        "Port_Fiber_GbE": "Fiber GbE (SFP)",
        "Port_Fiber_10G": "Fiber 10G (SFP+)",
        "Port_M12_Any":   "Any M12 Connector",
        "Port_M12_GbE":   "M12 GbE (X-code)",
        "Port_MultiGiga": "Multi-Giga (2.5/5/10G M12)",
        "Port_Bypass":    "LAN Bypass",
        "Port_SPE_Any":   "Any SPE Connector (T1)"
    }
    PORT_FEATURE_KEY_LABELS = {
        "Has_PoE":        "Has PoE",
        "No_PoE":         "No PoE",
        "Has_Fiber":      "Has Fiber Port",
        "Has_RJ-45":      "Has RJ-45 Port"
    }
    CERT_KEY_LABELS = {
        "Cert_UL":       "UL",
        "Cert_LVD":      "LVD",
        "Cert_IEC61850": "IEC 61850",
        "Cert_NEMA":     "NEMA",
        "Cert_EN50155":  "EN 50155",
        "Cert_EMark":    "E-Mark",
        "Cert_ITxPT":    "ITxPT",
    }

    for hd_key in base_hardware_mappings.keys():
        if hd_key in POWER_KEY_LABELS:
            SEARCHABLE_ITEMS.append(SearchFeatureItem(
                label=POWER_KEY_LABELS[hd_key],
                key=hd_key,
                category="Power Input"
            ))
        elif hd_key in PORT_SPEED_KEY_LABELS:
            SEARCHABLE_ITEMS.append(SearchFeatureItem(
                label=PORT_SPEED_KEY_LABELS[hd_key],
                key=hd_key,
                category="Connector Type"
            ))
        elif hd_key in PORT_FEATURE_KEY_LABELS:
            SEARCHABLE_ITEMS.append(SearchFeatureItem(
                label=PORT_FEATURE_KEY_LABELS[hd_key],
                key=hd_key,
                category="Port Feature"
            ))
        elif hd_key in CERT_KEY_LABELS:
            SEARCHABLE_ITEMS.append(SearchFeatureItem(
                label=CERT_KEY_LABELS[hd_key],
                key=hd_key,
                category="Certifications"
            ))
        else:
            SEARCHABLE_ITEMS.append(SearchFeatureItem(
                label=hd_key.replace("_", " "),
                key=hd_key,
                category="Hardware Feature"
            ))

    # 動態展開所有軟體功能：
    # 這裡採「資料驅動」設計，程式會自動掃描 MongoDB 中的文件結構。
    # 優點：未來 Google Sheet 新增功能分類，不需修改後端代碼，重啟即自動支援。
    for category, features in sw_data.items():
        if not isinstance(features, dict):
            continue
        for feat_key, feat_val in features.items():
            # 【重要過濾邏輯】
            # 只加入「三態值」欄位（如 full/optional/no/in_development）。
            # 會跳過「純數值」或描述性欄位（如 "Max. Groups": "256" 或 "8K"）。
            # 這是因為選型工具主要是找「有無支援該功能」，而非搜尋特定數據。
            if feat_val not in SW_VALID_VALUES:
                continue

            # 封裝：將分類與功能名稱用 ||| 捆在一起
            item_key = f"{category}|||{feat_key}"
            DYNAMIC_SW_MAPPINGS[item_key] = {"category": category, "feat_key": feat_key}
            SEARCHABLE_ITEMS.append(SearchFeatureItem(
                label=feat_key,
                key=item_key,
                category=category
            ))


# TODO(暫時): 軟體規格資料尚未確認完成，Search Inventory 快速搜尋先只顯示硬體特徵。
# 待軟體規格資料確認無誤後，把下面 SEARCH_INVENTORY_HARDWARE_ONLY 改回 False（或直接刪除相關判斷）即可恢復。
SEARCH_INVENTORY_HARDWARE_ONLY = True
HARDWARE_ONLY_CATEGORIES = {"Power Input", "Connector Type", "Port Feature", "Hardware Feature", "Certifications"}


@router.get("/searchProdType", response_model=List[SearchFeatureItem])
def search_product_features(q: str = ""):
    """
    即時搜尋 API：模糊比對所有軟硬體特徵（大小寫不敏感），供前端產生下拉選單。
    """
    try:
        load_dynamic_mappings_if_needed()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB mapping init error: {str(e)}")

    # 空白查詢：回傳全部（Feature Selector / Advanced Filter 初始化用，一次載入後前端自行過濾）
    # 注意：Advanced Filter 走的是這個分支，不受下方硬體限定影響。
    if not q:
        return SEARCHABLE_ITEMS

    query_lower = q.lower()
    results = [
        item for item in SEARCHABLE_ITEMS
        if (not SEARCH_INVENTORY_HARDWARE_ONLY or item.category in HARDWARE_ONLY_CATEGORIES)
        and (query_lower in item.label.lower() or query_lower in item.category.lower())
    ]
    return results[:20]


@router.post("/submitProdType", response_model=SubmitProdResponse)
def submit_product_selection(req: SubmitProdRequest):
    """
    條件篩選 API：從 product_specs 篩出符合軟硬體條件的產品。
    所有過濾均在 MongoDB 層執行（$and 組合），不在 Python 端做迴圈過濾。
    """
    db = Database.get_db()

    try:
        load_dynamic_mappings_if_needed()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection error: {str(e)}")

    print(f"[submitProdType] items={req.items}, type={req.type}, portnum={req.portnum}, portnum_max={req.portnum_max}")

    # Step 1：組裝基本硬體條件（直接對應資料庫原始欄位）
    and_conditions = [
        {"hardware.PLM Lifecycle": {"$not": {"$regex": "(eol|phase out|inactivate)", "$options": "i"}}}
    ]

    if req.type != "ALL":
        type_lower = req.type.lower()
        if type_lower == "unmanaged":
            # Function 中含有 "unmanage"（不區分大小寫）即視為 Unmanaged
            and_conditions.append({"hardware.Function": {"$regex": "unmanage", "$options": "i"}})
        elif type_lower == "l3_managed" or type_lower == "l3 managed":
            # 含有 L3 且含有 manage，但不含 unmanage
            and_conditions.append({"hardware.Function": {"$regex": "manage", "$options": "i"}})
            and_conditions.append({"hardware.Function": {"$regex": "l3", "$options": "i"}})
            and_conditions.append({"hardware.Function": {"$not": re.compile("unmanage", re.IGNORECASE)}})
        elif type_lower == "l2_managed" or type_lower == "l2 managed":
            # 含有 manage，但不含 unmanage，且不含 L3 (只寫 Managed 或 L2 Managed 都歸類為 L2)
            and_conditions.append({"hardware.Function": {"$regex": "manage", "$options": "i"}})
            and_conditions.append({"hardware.Function": {"$not": re.compile("unmanage", re.IGNORECASE)}})
            and_conditions.append({"hardware.Function": {"$not": re.compile("l3", re.IGNORECASE)}})
        elif type_lower == "managed":
            # 相容原本的 "managed" 查詢，不區分 L2/L3，全都要
            and_conditions.append({"hardware.Function": {"$regex": "manage", "$options": "i"}})
            and_conditions.append({"hardware.Function": {"$not": re.compile("unmanage", re.IGNORECASE)}})
        else:
            # 其他將來新增的類型維持精確比對
            and_conditions.append({"hardware.Function": req.type})

    if req.portnum != -1:
        # Port Numbers 在 DB 中以字串儲存，使用 $expr + $toInt 做 >= 比較
        and_conditions.append({
            "$expr": {
                "$gte": [
                    {"$toInt": {"$ifNull": ["$hardware.Port Numbers", "0"]}},
                    req.portnum
                ]
            }
        })

    if req.portnum_max != -1:
        and_conditions.append({
            "$expr": {
                "$lte": [
                    {"$toInt": {"$ifNull": ["$hardware.Port Numbers", "0"]}},
                    req.portnum_max
                ]
            }
        })

    # Step 2：組裝軟硬體特徵條件
    for requested_key in req.items:
        if requested_key in DYNAMIC_SW_MAPPINGS:
            # 軟體功能處理：
            # 1. 將組合鍵拆解回原始的 category 與 feat_key。
            # 2. 使用 $expr + $getField 避開 MongoDB dot-notation 對特殊字元的限制。
            mapping = DYNAMIC_SW_MAPPINGS[requested_key]
            and_conditions.append(make_sw_expr_query(mapping["category"], mapping["feat_key"]))
        elif requested_key in base_hardware_mappings:
            # 硬體進階條件：直接用 dict 合併
            and_conditions.append(base_hardware_mappings[requested_key]())
        # 未知 key 直接跳過，不中斷查詢

    # Step 3：組合為單一 $and 查詢，一次打給 MongoDB
    final_query = {"$and": and_conditions} if len(and_conditions) > 1 else and_conditions[0]

    try:
        matched_products = list(db.product_specs.find(final_query))
    except Exception as e:
        print(f"DB Query Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to query products from database.")

    # Step 4：映射資料庫欄位至前端顯示格式
    def safe_int(v):
        if not v:
            return 0
        try:
            return int(str(v).strip())
        except (ValueError, TypeError):
            return 0

    response_items = []
    for doc in matched_products:
        hw = doc.get("hardware", {})
        response_items.append(ProductItemResponse(
            prod_name=doc.get("product_pn", "Unknown"),
            prod_model=doc.get("model_name", hw.get("Model Name", "Unknown")),
            prod_type=hw.get("Function", "Unknown"),
            prod_portnum=safe_int(hw.get("Port Numbers")),
            prod_rj_100=safe_int(hw.get("RJ-45 10/100M")),
            prod_rj_giga=safe_int(hw.get("RJ-45 Gigabit")),
            prod_rj_100_combo=safe_int(hw.get("RJ-45 Combo")),
            prod_fiber_100=safe_int(hw.get("Fiber 100M")),
            prod_fiber_giga=safe_int(hw.get("Fiber Gigabit")),
            prod_fiber_ge_combo=safe_int(hw.get("Fiber GE Combo")),
            prod_fiber_10g=safe_int(hw.get("Fiber 10G")),
            prod_w_n=hw.get("Temp Grade", "Normal"),
            prod_poe_rj_100=safe_int(hw.get("PoE RJ-45 100M")),
            prod_poe_rj_giga=safe_int(hw.get("PoE RJ-45 GbE")),
            prod_m12_100=safe_int(hw.get("Eth 10/100M (D-code)")),
            prod_m12_giga=safe_int(hw.get("Eth Gigabit (X-code)")),
            prod_m12_multi_giga=safe_int(hw.get("Eth Multi-Giga (X-code)")),
            prod_poe_m12_100=safe_int(hw.get("PoE (D-code)")),
            prod_poe_m12_giga=safe_int(hw.get("PoE (X-code)")),
            prod_bypass_m12_100=safe_int(hw.get("LAN Bypass 10/100M (D-code)")),
            prod_bypass_m12_giga=safe_int(hw.get("LAN Bypass Gigabit (X-code)")),
            prod_poe_standard=str(hw.get("PoE Standard") or "").strip(),
            prod_poe_budget=str(hw.get("Power Budget (W)") or "").strip(),
            prod_power_input=str(hw.get("Input Voltage") or "—").strip(),
            prod_temp_range=str(hw.get("Op Temp Range") or hw.get("Temp Grade") or "—").strip(),
            prod_fiber_type=str(hw.get("Fiber Type") or "").strip(),
            prod_fiber_conn=str(hw.get("Fiber Connector") or "").strip(),
            prod_certifications=str(hw.get("Certifications") or "").strip(),
            prod_mounting=str(hw.get("Type") or "").strip(),
            prod_url=str(hw.get("prod_url") or hw.get("URL") or "").strip(),
            prod_description=str(hw.get("Description") or "").strip(),
        ))

    return SubmitProdResponse(products=response_items)
