"""
app/models/selection.py
Pydantic Request/Response 強型別定義
"""
from typing import List, Optional
from pydantic import BaseModel, Field


# =========================================================================
# Request Models（前端送進來的資料結構）
# =========================================================================

class SubmitProdRequest(BaseModel):
    """
    /api/submitProdType POST 的請求體。
    items: 使用者選取的特徵 key 清單（格式：category|||feat_key 或 硬體key）
    type:  管理類型過濾，"Managed" / "Unmanaged" / "ALL"
    portnum: 埠數下限（含），-1 代表不限
    portnum_max: 埠數上限（含），-1 代表不限
    """
    items: List[str] = Field(default=[], description="選取的特徵 key 清單")
    type: str = Field(default="ALL", description="Managed / Unmanaged / ALL")
    portnum: int = Field(default=-1, description="埠數下限（含），-1 不限")
    portnum_max: int = Field(default=-1, description="埠數上限（含），-1 不限")


# =========================================================================
# Response Models（後端回傳的資料結構）
# =========================================================================

class SearchFeatureItem(BaseModel):
    """
    /api/searchProdType 即時搜尋的回傳項目。
    label:    顯示在下拉選單的文字
    key:      前端儲存並回傳的唯一識別碼（category|||feat_key 格式）
    category: 所屬分類（用來在下拉選單中顯示分群）
    """
    label: str
    key: str
    category: str


class ProductItemResponse(BaseModel):
    """
    /api/submitProdType 回傳清單中的每一筆產品資料。
    對應前端表格各欄位。
    """
    prod_name: str              # 產品 PN（Product Number）
    prod_model: str             # 型號名稱（Model Name）
    prod_type: str              # 管理類型（Managed / Unmanaged）
    prod_portnum: int           # 總埠數
    prod_rj_100: int            # RJ-45 10/100M 埠數
    prod_rj_giga: int           # RJ-45 Gigabit 埠數
    prod_rj_100_combo: int      # RJ-45 Combo 埠數
    prod_fiber_100: int         # Fiber 100M 埠數
    prod_fiber_giga: int        # Fiber Gigabit 埠數
    prod_fiber_ge_combo: int    # Fiber GE Combo 埠數
    prod_fiber_10g: int = 0    # Fiber 10G 埠數
    prod_w_n: str               # 溫度等級（Wide / Normal）
    prod_poe_rj_100: int = 0    # PoE RJ-45 100M 埠數
    prod_poe_rj_giga: int = 0   # PoE RJ-45 GbE 埠數
    prod_m12_100: int = 0       # M12 D-code 埠數
    prod_m12_giga: int = 0      # M12 X-code 埠數
    prod_m12_multi_giga: int = 0 # Eth Multi-Giga (X-code) 埠數
    prod_poe_m12_100: int = 0   # PoE (D-code) 埠數
    prod_poe_m12_giga: int = 0  # PoE (X-code) 埠數
    prod_bypass_m12_100: int = 0 # LAN Bypass 10/100M (D-code)
    prod_bypass_m12_giga: int = 0 # LAN Bypass Gigabit (X-code)
    prod_poe_standard: str = ""  # PoE 標準（如 IEEE 802.3af/at/bt）
    prod_poe_budget: str = ""    # PoE 總功率預算（如 "240W"）
    prod_power_input: str = "—" # 電源輸入電壓範圍 (如 12-48VDC)
    prod_temp_range: str = "—"  # 工作溫度範圍 (如 -40 ~ 75C)
    prod_fiber_type: str = ""   # 光纖接口類型（SFP / SFP+ / Multi-mode / Single-mode / SC / 空白）
    prod_fiber_conn: str = ""   # 固定接頭規格（SC / ST / 空白）
    prod_certifications: str = "" # 認證清單（逗號分隔，如 CE, FCC, UL...）
    prod_mounting: str = ""     # 安裝方式（如 DIN-Rail, Rack Mount...）
    prod_url: str = ""          # 產品頁 URL；空字串時前端自動組合官網搜尋連結
    prod_description: str = "" # 產品描述（DB Description 欄位）


class SubmitProdResponse(BaseModel):
    """
    /api/submitProdType 的完整回傳體。
    """
    products: List[ProductItemResponse] = []
