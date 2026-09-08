# Feature Selector 整合實作計畫（最終版）

## 架構說明（先讀這個）

「邏輯不放 HTML」≠「所有東西都放在同一個 HTML 檔案」。三層分離如下：

```
select_ui_with_options_claude.html   ← HTML 骨架（Modal 結構嵌在這）
css/feature-selector.css             ← 樣式（獨立 CSS 檔）
js/feature-selector.js               ← 邏輯（獨立 JS 檔）
```

主頁 HTML 裡**不會有任何 `<script>` 邏輯**，只有 HTML 標籤。
所有互動都在 `feature-selector.js` 裡執行，透過 `<script src="...">` 引用。

---

## 最終檔案架構

```
frontend/
├── select_ui_with_options_claude.html  ← [MODIFY] 主頁（加 Modal 骨架 + 引用新 JS/CSS）
├── feature-selector.html               ← 保留為設計草稿，不上線
├── css/
│   ├── style.css                       ← 現有，不動
│   └── feature-selector.css           ← [NEW] Feature Selector 專用樣式
└── js/
    ├── scenes.js                       ← 現有，不動
    ├── app.js                          ← [MODIFY] 加事件綁定 + applyFeatureSelector()
    └── feature-selector.js            ← [NEW] Feature Selector 所有邏輯
```

---

## 🔧 未來維護指南（重要）

### 情境 A：DB 新增一個「子功能」（最常見）
> 例如：Google Sheet 新增了「VLAN QinQ Plus」這個功能

**不需要改任何程式碼。**
Server 重啟後，`load_dynamic_mappings_if_needed()` 自動掃描到新功能，
Feature Selector 開啟時會自動出現在對應的大分類卡片下。

---

### 情境 B：DB 新增一個「全新大分類」（偶爾）
> 例如：Google Sheet 新增了「TSN Advanced」這個全新 category

**需要修改一個地方：**

📄 `frontend/js/feature-selector.js` → `FS_GROUPS` 陣列

找到最相關的 Group，在 `dbCategories` 裡加一行：

```javascript
// 修改前
{ id:'tsn', label:'時間同步 / TSN', ...,
  dbCategories:['IEEE 1588v2', 'TSN', 'NTP Client  NTP Server  SNTP Client'] },

// 修改後（加入新 category）
{ id:'tsn', label:'時間同步 / TSN', ...,
  dbCategories:['IEEE 1588v2', 'TSN', 'NTP Client  NTP Server  SNTP Client',
                'TSN Advanced'] },   // ← 加這一行
```

> [!NOTE]
> 如果找不到合適的 Group，也可以不加。
> 新 category 會自動出現在「其他（未分類）」灰色卡片，
> 提醒 PM 決定要歸屬到哪個 Group。

---

### 情境 C：新增或修改「大分類卡片」本身
> 例如：要把「OAM / 診斷協定」改名，或新增一個「雲端管理」大分類

**需要修改一個地方：**

📄 `frontend/js/feature-selector.js` → `FS_GROUPS` 陣列

```javascript
// 修改大分類名稱
{ id:'oam', label:'OAM / 診斷協定',  // ← 改這裡
  icon:'◎', color:'#38bdf8', ... }

// 新增大分類（加在陣列最後）
{ id:'cloud', label:'雲端管理', icon:'☁', color:'#60a5fa',
  dbCategories:['Cloud Connect', 'Remote Management'] }
```

---

### 情境 D：調整 Modal 的版面或按鈕文字

**需要修改兩個地方：**

- 版面結構 → 📄 `select_ui_with_options_claude.html`（Modal 的 HTML 骨架區）
- 樣式調整 → 📄 `css/feature-selector.css`

---

### 情境 E：調整套用篩選的行為（例如：套用後自動送出查詢）

📄 `js/app.js` → `applyFeatureSelector()` 函數

---

## 各步驟改動

### Step 1：修改後端（1 行）

📄 `app/api/selection.py`

```python
@router.get("/searchProdType", response_model=List[SearchFeatureItem])
def search_product_features(q: str = ""):
    try:
        load_dynamic_mappings_if_needed()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB mapping init error: {str(e)}")

    # 空白查詢：回傳全部（Feature Selector 初始化用）
    if not q:
        return SEARCHABLE_ITEMS

    query_lower = q.lower()
    results = [
        item for item in SEARCHABLE_ITEMS
        if query_lower in item.label.lower() or query_lower in item.category.lower()
    ]
    return results[:20]
```

> [!NOTE]
> 現有搜尋框在 `query.length === 0` 時不呼叫 API，此改動對現有行為無影響。

---

### Step 2：新增 `css/feature-selector.css`

Modal 外框 + Feature Selector 內部所有樣式。
從 `feature-selector.html` 的 `<style>` 區塊抽出，色票改用主頁的 CSS 變數。

```css
/* Modal 外框 */
#fs-modal-overlay {
  display: none; position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.55); align-items: center; justify-content: center;
}
#fs-modal-overlay.open { display: flex; }
#fs-modal-container {
  background: var(--bg-primary); border-radius: 12px;
  width: min(920px,95vw); max-height: 85vh;
  display: flex; flex-direction: column; overflow: hidden;
}
/* ... 其餘 Feature Selector 內部樣式 ... */
```

---

### Step 3：新增 `js/feature-selector.js`

**GROUPS 定義（唯一需要人工維護的區塊，集中在檔案最上方）：**

```javascript
// ================================================================
// FS_GROUPS — 大分類定義
// 維護規則：
//   - 新增「子功能」→ 不需改這裡，DB 自動同步
//   - 新增「大分類 category」→ 在對應 Group 的 dbCategories 加一行
//   - 新增「大分類卡片」→ 在此陣列加一個 object
// ================================================================
const FS_GROUPS = [
  { id:'net2',       label:'二層交換',        icon:'⬡', color:'#4a9eff',
    dbCategories:[
      'VLAN(IEEE 802.1Q)',
      'Spanning Tree (IEEE 802.1D STP)  Spanning Tree(IEEE 802.1w RSTP)  Spanning Tree(IEEE 802.1s MSTP)',
      'Link Aggregation LACP (IEEE 802.3ad)', 'Loop Control', 'Flow Control', 'MRP'
    ]},
  { id:'net3',       label:'三層路由',        icon:'⇄', color:'#3ec99a',
    dbCategories:[
      'Routing Protocol', 'IGMP Snooping v1/v2/v3', 'MLD Snooping',
      'NAT', 'NAT Throughput', 'L3 Table', 'IPv6'
    ]},
  { id:'security',   label:'安全防護',        icon:'⛨', color:'#f87171',
    dbCategories:[
      'ACL', 'DoS Prevention',
      'IP Security - IP Source Guard/DHCP Snooping/ARP Spoofing Prevention',
      'IEEE 802.1X', 'Remote Authentication - RADIUS/TACACS+',
      'Port Security', 'Security Protocol',
      'Password Management', 'Trusted Host', 'User Account'
    ]},
  { id:'qos',        label:'QoS / 流量控制',  icon:'⇅', color:'#fbbf24',
    dbCategories:[
      'QoS IEEE 802.1p Based CoS  QoS IP TOS / Precedence  QoS DSCP based CoS',
      'Port Rate Limit', 'Port Storm Control', 'Scheduling', 'sFlow'
    ]},
  { id:'redundancy', label:'備援 / 環型網路', icon:'↻', color:'#a78bfa',
    dbCategories:[ 'ERPS', 'X-Ring Elite', 'X-Ring Pro' ]},
  { id:'tsn',        label:'時間同步 / TSN',  icon:'◷', color:'#34d399',
    dbCategories:[ 'IEEE 1588v2', 'TSN', 'NTP Client  NTP Server  SNTP Client' ]},
  { id:'mgmt',       label:'管理 / 維運',     icon:'⚙', color:'#94a3b8',
    dbCategories:[
      'WEB GUI', 'SNMP-SNMPv1/v2c/v3/Trap', 'DHCP',
      'System Log', 'SMTP', 'System Notice', 'LLDP(IEEE 802.1ab)',
      'IP Management', 'Upload / Download Method', 'IXM',
      'Memory Protection', 'Storage Protection',
      'Standard MIB', 'Private MIB', 'RMONv1'  // MIB 歸入管理/維運
    ]},
  { id:'oam',        label:'OAM / 診斷協定',  icon:'◎', color:'#38bdf8',
    dbCategories:[
      'OAM - IEEE 802.1ag CFM', 'OAM - IEEE 802.3ah',
      'Port Mirroring  RSPAN-Remote Switched Port Analysis',
      'Reserved Multicast', 'Multicast Table'
    ]},
  { id:'industrial', label:'工業 / 軌道協定', icon:'⚡', color:'#f472b6',
    dbCategories:[ 'Industrial Protocol - Modbus TCP', 'Industrial Service Express', 'ITxPT' ]},
  { id:'hw',         label:'硬體規格',         icon:'□', color:'#a8a29e',
    dbCategories:[ 'Hardware Feature', 'Application' ]},
];

// ================================================================
// 以下為運作邏輯，一般維護不需修改
// ================================================================

let fsData = {};       // { gid: { dbCat: [{label, key}] } }
let fsSelected = {};   // { dbKey: label }
let fsActiveGid = null;
let fsReady = false;

async function fsInit() { ... }      // 呼叫 API、分配資料到 FS_GROUPS
function fsToggleItem(...) { ... }   // 勾選單一功能
function fsToggleCat(...) { ... }    // 全選/取消一個 dbCategory
function fsToggleCard(...) { ... }   // 展開/收合大分類卡片
function fsGetSelected() { ... }     // 回傳選取的 [{key, label}]，供 app.js 使用
function openFeatureSelector() { ... }
function closeFeatureSelector() { ... }
function fsRender() { ... }
function fsRenderChips() { ... }
function fsRenderGrid() { ... }      // 包含「其他（未分類）」卡片
function fsRenderSub() { ... }
function fsRenderSearch() { ... }    // 前端過濾，無 API 呼叫
```

---

### Step 4：修改主頁 HTML（加 Modal 骨架 + 引用）

📄 `select_ui_with_options_claude.html`

```html
<!-- Step 3 搜尋框下方，加觸發按鈕 -->
<button id="advancedFilterBtn" type="button">⊞ 進階功能瀏覽</button>

<!-- </body> 前加 Modal -->
<div id="fs-modal-overlay">
  <div id="fs-modal-container">
    <div id="fs-modal-header">
      <span>⊞ 進階功能篩選</span>
      <button id="fs-modal-close">✕</button>
    </div>
    <div id="fs-modal-body">
      <div id="fs-chip-bar"><span id="fs-chip-hint">尚未選取任何功能</span></div>
      <div class="fs-search-wrap">
        <input type="text" id="fs-search" placeholder="搜尋功能… (例：VLAN、PoE、TSN)">
        <span id="fs-s-clear">×</span>
      </div>
      <div id="fs-cat-grid"></div>
      <div id="fs-sub-area"></div>
    </div>
    <div id="fs-modal-footer">
      <button id="fs-cancel-btn">取消</button>
      <button id="fs-apply-btn">套用篩選條件</button>
    </div>
  </div>
</div>

<!-- 引用（放在 app.js 之前） -->
<link rel="stylesheet" href="/frontend/css/feature-selector.css">
<script src="/frontend/js/feature-selector.js"></script>
<script src="/frontend/js/scenes.js"></script>
<script src="/frontend/js/app.js"></script>
```

---

### Step 5：修改 `js/app.js`（加事件綁定）

```javascript
// 事件綁定（加在初始化區塊，無 inline onclick）
document.getElementById('advancedFilterBtn')
  .addEventListener('click', openFeatureSelector);
document.getElementById('fs-modal-close')
  .addEventListener('click', closeFeatureSelector);
document.getElementById('fs-cancel-btn')
  .addEventListener('click', closeFeatureSelector);
document.getElementById('fs-apply-btn')
  .addEventListener('click', applyFeatureSelector);
document.getElementById('fs-modal-overlay')
  .addEventListener('click', e => {
    if (e.target.id === 'fs-modal-overlay') closeFeatureSelector();
  });

// 橋接：Feature Selector → 主頁 selectedItemsMap
function applyFeatureSelector() {
  fsGetSelected().forEach(({ key, label }) => {
    selectedItemsMap[key] = label;
  });
  renderSelected();
  closeFeatureSelector();
}
```

---

## 實作順序

- `[ ]` Step 1：修改 `selection.py`（空白查詢回傳全部）
- `[ ]` Step 2：新增 `css/feature-selector.css`
- `[ ]` Step 3：新增 `js/feature-selector.js`（含完整邏輯）
- `[ ]` Step 4：修改 `select_ui_with_options_claude.html`（加按鈕、Modal、引用）
- `[ ]` Step 5：修改 `js/app.js`（加事件綁定與橋接函數）
- `[ ]` Step 6：端對端測試
