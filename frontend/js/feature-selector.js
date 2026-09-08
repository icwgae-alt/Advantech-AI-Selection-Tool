/* ═══════════════════════════════════════════════════════════
   Advantech Switch Selection Tool — Feature Selector Logic
   ═══════════════════════════════════════════════════════════

   維護說明：
   ┌─────────────────────────────────────────────────────────┐
   │  新增 DB「子功能」  → 不需改任何程式碼，自動同步        │
   │  新增 DB「大分類」  → 在對應 Group 的 dbCategories 加一行│
   │  新增「大分類卡片」 → 在 FS_GROUPS 陣列加一個 object    │
   └─────────────────────────────────────────────────────────┘
   ═══════════════════════════════════════════════════════════ */

// ================================================================
// FS_GROUPS — 大分類定義（唯一需要人工維護的區塊）
//
// 欄位說明：
//   id          : 唯一識別碼
//   label       : 顯示在卡片上的中文名稱
//   icon        : 卡片圖示
//   color       : 左邊框與強調色（CSS color 值）
//   dbCategories: 對應後端 DB 的 category 名稱陣列
//                 （需與 sw_index.py 輸出的【分類】名稱完全一致）
// ================================================================
const FS_GROUPS = [
    {
        id: 'net2', label: 'Layer 2 Switching', icon: '⬡', color: '#4a9eff',
        dbCategories: [
            'VLAN(IEEE 802.1Q)',
            'Spanning Tree',
            'Link Aggregation LACP (IEEE 802.3ad)',
            'Loop Control',
            'Flow Control (IEEE 802.3x)',
            'GARP-GVRP   GARP-GMRP',
            'MRP',
            'IEC 62439',
            'IEC 62439-2 MRP'
        ]
    },
    {
        id: 'net3', label: 'Layer 3 Routing', icon: '⇄', color: '#3ec99a',
        dbCategories: [
            'Routing Protocol',
            'IGMP Snooping v1/v2/v3',
            'MLD Snooping',
            'NAT',
            'NAT Throughput',
            'L3 Table',
            'IPv6',
            'DNS - Client  DNS - Server'
        ]
    },
    {
        id: 'security', label: 'Security', icon: '⛨', color: '#f87171',
        dbCategories: [
            'Access Control List (ACL)',
            'DoS Attack Prevention',
            'CPU Protection',
            'IP Security - IP Source Guard/DHCP Snooping/ARP Spoofing Prevention',
            'IEEE 802.1X',
            'Remote Authentication - RADIUS/TACACS+',
            'Firewall',
            'VPN',
            'Port Security',
            'Security Protocol',
            'Password Management',
            'Trusted Host',
            'User Account',
            'Certification'
        ]
    },
    {
        id: 'qos', label: 'QoS / Flow Control', icon: '⇅', color: '#fbbf24',
        dbCategories: [
            'QoS IEEE 802.1p Based CoS  QoS IP TOS / Precedence  QoS DSCP based CoS',
            'Port Rate Limit',
            'Port Storm Control',
            'Scheduling',
            'sFlow',
            'Green Ethernet (IEEE 802.3az EEE)'
        ]
    },
    {
        id: 'redundancy', label: 'Redundancy / Ring', icon: '↻', color: '#a78bfa',
        dbCategories: [
            'ERPS(G.8032)',
            'X-Ring Elite',
            'X-Ring Pro'
        ]
    },
    {
        id: 'tsn', label: 'Time Sync / TSN', icon: '◷', color: '#34d399',
        dbCategories: [
            'IEEE 1588v2',
            'TSN',
            'NTP Client  NTP Server  SNTP Client',
            'IEC 61850'
        ]
    },
    {
        id: 'mgmt', label: 'Management', icon: '⚙', color: '#94a3b8',
        dbCategories: [
            'WEB GUI',
            'Command Line Interface',
            'SNMP-SNMPv1/v2c/v3/Trap',
            'DHCP - Client  DHCP - Server  DHCP Relay  DHCP Option 82',
            'System Log',
            'SMTP',
            'System Notice',
            'LLDP(IEEE 802.1ab)',
            'IP Management',
            'Upload / Download Method',
            'Configuration Management',
            'Firmware Management',
            'Boot Management',
            'IXM',
            'Memory Protection',
            'Storage Protection',
            'Standard MIB',
            'Private MIB',
            'RMONv1'
        ]
    },
    {
        id: 'oam', label: 'OAM / Diagnostics', icon: '◎', color: '#38bdf8',
        dbCategories: [
            'OAM - IEEE 802.1ag CFM',
            'OAM - IEEE 802.3ah',
            'Edge OAM',
            'Port Mirroring  RSPAN-Remote Switched Port Analysis',
            'Reserved Multicast',
            'Multicast Table',
            'Diagnostic'
        ]
    },
    {
        id: 'industrial', label: 'Industrial / Railway', icon: '⚡', color: '#f472b6',
        dbCategories: [
            'Industrial Protocol - Modbus TCP',
            'Industrial Service Express',
            'ITxPT',
            'IEC 61375-2-3 TRDP',
            'IEC 61375-2-5 TTDP'
        ]
    },
    {
        // Port_RJ45_GbE/100M、Port_Fiber_GbE/10G、Port_M12_GbE、Port_MultiGiga（特定接頭+特定速度組合）
        // 與 Wizard 的 Max Port Speed 概念重疊，透過 FS_HIDDEN_FEATURES 隱藏；Has_PoE/Has_Fiber/Has_RJ-45
        // 雖然跟 Wizard 的 PoE Required / Interface Type 是同一個 key，但保留在此卡片方便一次瀏覽。
        // 隱藏後這張卡不再涉及「速度」，改名為 Port Type / Connector。
        id: 'portspeed', label: 'Port Type / Connector', icon: '⚡', color: '#06b6d4',
        dbCategories: [
            'Port Feature',    // Has_PoE, Has_Fiber, Has_RJ-45
            'Connector Type'   // 隱藏速度組合後，實際為 Port_M12_Any（M12 Connector）, Port_Bypass（LAN Bypass）
        ]
    },
    {
        id: 'power', label: 'Power Input', icon: '⏻', color: '#f59e0b',
        dbCategories: [
            'Power Input'  // Pwr_DC, Pwr_AC, Pwr_12V, Pwr_24V, Pwr_High_Voltage
        ]
    },
    {
        id: 'certifications', label: 'Certifications', icon: '🛡', color: '#22c55e',
        dbCategories: [
            'Certifications'  // Cert_UL, Cert_LVD, Cert_IEC61850, Cert_NEMA, Cert_EN50155, Cert_EMark, Cert_ITxPT
        ]
    },
    {
        // Speed_100M/GbE/10G 已隱藏（與 Wizard 的 Max Port Speed 重複），目前只剩 Temp_Wide。
        id: 'hw', label: 'Hardware Specs', icon: '◈', color: '#64748b',
        dbCategories: [
            'Hardware Feature'  // Temp_Wide
        ]
    },
    // ── 未來新增大分類，在此加入 object ──
];

// TODO(暫時): 軟體規格資料尚未確認完成，Advanced Filter 先只顯示硬體相關卡片。
// 待軟體規格資料確認無誤後，把 FS_SOFTWARE_HIDDEN 改回 false 即可恢復顯示所有卡片。
// 注意：這裡只影響「卡片顯示」與「模態框內搜尋」，不影響 FS_GROUPS 本身或資料載入/分類邏輯。
const FS_SOFTWARE_HIDDEN = true;
// 'portspeed'（Port Type / Connector）已移除：內容（PoE/Fiber/RJ-45/M12）跟左側 Wizard 的
// PoE 與 Interface Type 篩選重複，保留在 Advanced Filter 容易讓使用者混淆重複設定同一條件。
const FS_HARDWARE_GROUP_IDS = new Set(['power', 'certifications', 'hw']);
const FS_VISIBLE_GROUPS = FS_SOFTWARE_HIDDEN
    ? FS_GROUPS.filter(g => FS_HARDWARE_GROUP_IDS.has(g.id))
    : FS_GROUPS;

// ================================================================
// FS_HIDDEN_FEATURES — 不在選擇器中顯示的功能（簡化 UI 用）
// Port_RJ45_*/Port_Fiber_*/Port_M12_GbE/Port_MultiGiga（特定接頭+特定速度組合）與
// Speed_100M/GbE/10G（整機最大速度）皆與左側 Wizard 的「Max Port Speed」概念重複，
// 在 Advanced Filter 中重複出現只會造成混淆，故隱藏（後端查詢邏輯不受影響，Wizard 仍可正常送出這些 key）。
// Port Type / Connector 卡片因此只保留 M12 Connector 與 LAN Bypass 兩種「連接器類型」。
// ================================================================
const FS_HIDDEN_FEATURES = new Set([
    'Port_RJ45_GbE', 'Port_RJ45_100M', 'Port_Fiber_GbE', 'Port_Fiber_10G',
    'Port_M12_GbE', 'Port_MultiGiga',
    'Speed_100M', 'Speed_GbE', 'Speed_10G'
]);

// ── 運作邏輯 ────────────────────────────────────────────────────

let fsData = {};
let fsSelected = {};
let fsActiveGid = null;
let fsSearchQ = '';
let fsReady = false;

async function fsInit() {
    const needsReinit = FS_GROUPS.some(g => !(g.id in fsData));
    if (fsReady && !needsReinit) { fsRender(); return; }
    if (needsReinit) { fsReady = false; fsData = {}; }

    const loadingEl = document.getElementById('fs-cat-grid');
    if (loadingEl) loadingEl.innerHTML = '<div style="color:var(--text-muted);font-size:0.85rem;padding:20px 0">Loading features...</div>';

    try {
        const items = await fetch(`${API_BASE}/api/searchProdType?q=`).then(r => r.json());
        _fsDistributeItems(items);
        fsReady = true;
        fsRender();
    } catch (e) {
        console.error("Fetch API error:", e);
        if (loadingEl) loadingEl.innerHTML = '<div style="color:#b91c1c;font-size:0.85rem;padding:20px 0">⚠ Failed to load features, please try again</div>';
    }
}

const FS_LABEL_TRANSLATIONS = {
    '具備 PoE 供電': 'Has PoE',
    '具備光纖 Port (任一速度)': 'Has Fiber Port',
    '具備 RJ-45 Port (任一速度)': 'Has RJ-45 Port',
    '具備光纖 Port（任一速度）': 'Has Fiber Port',
    '具備 RJ-45 Port（任一速度）': 'Has RJ-45 Port',
    'RJ-45 GbE (含 Combo)': 'RJ-45 GbE (incl. Combo)',
    'RJ-45 GbE（含 Combo）': 'RJ-45 GbE (incl. Combo)',
    'RJ-45 100M (Fast Ethernet)': 'RJ-45 100M (Fast Ethernet)',
    'RJ-45 100M（Fast Ethernet）': 'RJ-45 100M (Fast Ethernet)',
    'Fiber GbE (SFP)': 'Fiber GbE (SFP)',
    'Fiber GbE（SFP）': 'Fiber GbE (SFP)',
    'Fiber 10G (SFP+)': 'Fiber 10G (SFP+)',
    'Fiber 10G（SFP+）': 'Fiber 10G (SFP+)',
    'M12 接頭': 'M12 Connector',
    'M12 任一接頭': 'Any M12 Connector',
    'M12 GbE (X-code)': 'M12 GbE (X-code)',
    'M12 GbE（X-code）': 'M12 GbE (X-code)',
    'Multi-Giga (2.5/5/10G M12)': 'Multi-Giga (2.5/5/10G M12)',
    'Multi-Giga（2.5/5/10G M12）': 'Multi-Giga (2.5/5/10G M12)',
    'LAN Bypass': 'LAN Bypass',
    'DC 供電': 'DC Power Input',
    'AC 供電': 'AC Power Input',
    '支援 12V（最低 ≤12V）': '12V Support (Min ≤12V)',
    '支援 24V（最低 ≤24V）': '24V Support (Min ≤24V)',
    '高壓供電（≥48V）': 'High Voltage Power (≥48V)',
    'Temp Wide': 'Wide Operating Temp.',
    'Train': 'Train',
    '智慧工廠': 'Smart Factory',
    '車載系統, 軌道沿線, 智慧工廠': 'Vehicle System, Trackside, Smart Factory',
    '軌道沿線': 'Trackside',
    '電力系統': 'Power System',
    '車載系統': 'Vehicle System'
};

function _fsDistributeItems(items) {
    const catToGid = {};
    FS_GROUPS.forEach(g => {
        fsData[g.id] = {};
        g.dbCategories.forEach(cat => {
            catToGid[cat] = g.id;
            fsData[g.id][cat] = [];
        });
    });

    fsData['other'] = {};

    items.forEach(item => {
        if (FS_HIDDEN_FEATURES.has(item.key)) return;
        const gid = catToGid[item.category];
        
        let displayLabel = item.label;
        if (FS_LABEL_TRANSLATIONS[displayLabel]) {
            displayLabel = FS_LABEL_TRANSLATIONS[displayLabel];
        }

        if (gid) {
            fsData[gid][item.category].push({ label: displayLabel, key: item.key });
        } else {
            if (!fsData['other'][item.category]) fsData['other'][item.category] = [];
            fsData['other'][item.category].push({ label: displayLabel, key: item.key });
        }
    });
}

function fsToggleItem(key, label, gid, checked) {
    if (checked) {
        fsSelected[key] = { label, gid };
    } else {
        delete fsSelected[key];
    }
    fsRenderChips();
    const cat = _fsFindCatByKey(gid, key);
    if (cat) _fsUpdateSelAllBtn(gid, cat);
}

function fsToggleCat(gid, cat) {
    const items = (fsData[gid] || {})[cat] || [];
    const allSelected = items.every(i => fsSelected[i.key]);
    items.forEach(i => {
        if (allSelected) {
            delete fsSelected[i.key];
        } else {
            fsSelected[i.key] = { label: i.label, gid };
        }
    });
    fsRender();
}

function fsToggleCard(gid) {
    fsActiveGid = (fsActiveGid === gid) ? null : gid;
    fsSearchQ = '';
    const searchEl = document.getElementById('fs-search');
    if (searchEl) { searchEl.value = ''; }
    const clearEl = document.getElementById('fs-s-clear');
    if (clearEl) clearEl.style.display = 'none';
    fsRender();
}

function fsRemoveGroupChip(gid) {
    Object.keys(fsSelected).forEach(key => {
        if (fsSelected[key].gid === gid) delete fsSelected[key];
    });
    fsRender();
}

function fsRemoveCatChip(gid, cat) {
    const items = (fsData[gid] || {})[cat] || [];
    items.forEach(i => delete fsSelected[i.key]);
    fsRender();
}

function _fsGetGroup(gid) { return FS_GROUPS.find(g => g.id === gid); }

function _fsFindCatByKey(gid, key) {
    const groupData = fsData[gid] || {};
    return Object.keys(groupData).find(cat => groupData[cat].some(i => i.key === key));
}

function _fsCatSelCount(gid, cat) {
    return ((fsData[gid] || {})[cat] || []).filter(i => fsSelected[i.key]).length;
}

function _fsGrpSelCount(gid) {
    return Object.keys(fsSelected).filter(k => fsSelected[k].gid === gid).length;
}

function _fsGrpTotal(gid) {
    return Object.values(fsData[gid] || {}).reduce((s, arr) => s + arr.length, 0);
}

function _fsUpdateSelAllBtn(gid, cat) {
    const items = (fsData[gid] || {})[cat] || [];
    const allSel = items.length > 0 && items.every(i => fsSelected[i.key]);
    document.querySelectorAll(`.fs-sel-all-btn[data-gid="${gid}"][data-cat="${CSS.escape(cat)}"]`).forEach(btn => {
        btn.textContent = allSel ? 'Deselect All' : 'Select All';
        btn.classList.toggle('on', allSel);
    });
}

function fsGetCategoryGroupLabel(dbCat) {
    const g = FS_GROUPS.find(group => group.dbCategories.includes(dbCat));
    return g ? g.label : 'Other';
}

function fsGetSelected() {
    return Object.entries(fsSelected).map(([key, val]) => {
        const g = _fsGetGroup(val.gid);
        const displayLabel = g ? `[${g.label}] ${val.label}` : val.label;
        return { key, label: displayLabel };
    });
}

function openFeatureSelector() {
    document.getElementById('fs-modal-overlay').classList.add('open');
    fsInit();
}

function closeFeatureSelector() {
    document.getElementById('fs-modal-overlay').classList.remove('open');
}

function fsReset() {
    fsSelected = {};
    fsActiveGid = null;
    fsSearchQ = '';
    const searchEl = document.getElementById('fs-search');
    if (searchEl) searchEl.value = '';
    const clearEl = document.getElementById('fs-s-clear');
    if (clearEl) clearEl.style.display = 'none';
    if (fsReady) fsRender();
}

function fsRender() {
    fsRenderChips();
    if (fsSearchQ) {
        _fsHideGrid();
        fsRenderSearch();
    } else {
        fsRenderGrid();
        fsRenderSub();
    }
}

function fsRenderChips() {
    const bar = document.getElementById('fs-chip-bar');
    const hint = document.getElementById('fs-chip-hint');
    if (!bar) return;

    bar.querySelectorAll('.fs-chip').forEach(c => c.remove());

    const catMap = {};
    Object.entries(fsSelected).forEach(([key, val]) => {
        const cat = _fsFindCatByKey(val.gid, key) || 'Other';
        if (!catMap[`${val.gid}|||${cat}`]) catMap[`${val.gid}|||${cat}`] = [];
        catMap[`${val.gid}|||${cat}`].push({ key, label: val.label, gid: val.gid });
    });

    const hasAny = Object.keys(catMap).length > 0;
    if (hint) hint.style.display = hasAny ? 'none' : '';

    Object.entries(catMap).forEach(([composite, items]) => {
        const [gid, cat] = composite.split('|||');
        const g = _fsGetGroup(gid);
        const color = g ? g.color : '#999';
        const total = ((fsData[gid] || {})[cat] || []).length;
        const selCount = items.length;
        const catLabel = selCount >= total ? cat : `${cat} (${selCount}/${total})`;

        const chip = document.createElement('div');
        chip.className = 'fs-chip';
        chip.style.borderLeftColor = color;
        chip.innerHTML =
            `<span class="fs-chip-grp" style="color:${color}">${g ? g.label : 'Other'}</span>` +
            `<span>${catLabel}</span>` +
            `<span class="fs-chip-x" title="Remove all from this category">×</span>`;
        chip.querySelector('.fs-chip-x').addEventListener('click', () => fsRemoveCatChip(gid, cat));
        bar.appendChild(chip);
    });
}

function fsRenderGrid() {
    const el = document.getElementById('fs-cat-grid');
    if (!el) return;
    el.style.display = 'grid';

    const allGroups = [...FS_VISIBLE_GROUPS];
    const hasOther = Object.values(fsData['other'] || {}).some(arr => arr.length > 0);

    el.innerHTML = allGroups.map(g => {
        const selCount = _fsGrpSelCount(g.id);
        const total = _fsGrpTotal(g.id);
        const hasSel = selCount > 0;
        const isActive = fsActiveGid === g.id;
        const cntTxt = hasSel ? `${selCount}/${total} items` : `${total} items`;
        const cntColor = hasSel ? `color:${g.color};font-weight:700` : '';
        const borderStyle = isActive
            ? `border-left-color:${g.color};border-color:${g.color};`
            : `border-left-color:${g.color};`;

        return `<div class="fs-cat-card${isActive ? ' active' : ''}${hasSel ? ' has-sel' : ''}"
                     data-gid="${g.id}" style="${borderStyle}">
            <span class="fs-cat-icon" style="color:${g.color}">${g.icon}</span>
            <div class="fs-cat-name">${g.label}</div>
            <div class="fs-cat-cnt" style="${cntColor}">${cntTxt}</div>
        </div>`;
    }).join('') + (hasOther ? _fsOtherCardHTML() : '');

    el.querySelectorAll('.fs-cat-card').forEach(card => {
        card.addEventListener('click', () => fsToggleCard(card.dataset.gid));
    });
}

function _fsOtherCardHTML() {
    const total = Object.values(fsData['other'] || {}).reduce((s, arr) => s + arr.length, 0);
    const isActive = fsActiveGid === 'other';
    return `<div class="fs-cat-card uncategorized${isActive ? ' active' : ''}" data-gid="other"
                 style="border-left-color:#aab;">
        <span class="fs-cat-icon" style="color:#aab">⚠</span>
        <div class="fs-cat-name">Other (Uncategorized)</div>
        <div class="fs-cat-cnt">${total} items</div>
    </div>`;
}

function _fsHideGrid() {
    const el = document.getElementById('fs-cat-grid');
    if (el) el.style.display = 'none';
}

/** 渲染展開的子功能清單 */
function fsRenderSub() {
    const el = document.getElementById('fs-sub-area');
    if (!el) return;

    if (!fsActiveGid) { el.style.display = 'none'; return; }
    el.style.display = 'block';

    const isOther = fsActiveGid === 'other';
    const g = isOther ? null : _fsGetGroup(fsActiveGid);
    const groupData = fsData[fsActiveGid] || {};
    const total = Object.values(groupData).reduce((s, arr) => s + arr.length, 0);
    const color = g ? g.color : '#aab';
    const label = g ? g.label : 'Other (Uncategorized)';

    let html = `<div class="fs-sub-grp-title" style="color:${color}">
        ${label}
        <span class="fs-sub-grp-total">${total} items</span>
    </div>`;

    if (isOther) {
        html += `<div class="fs-uncategorized-notice">
            ⚠ The following features are uncategorized. Please update the configuration if needed.
            <code>frontend/js/feature-selector.js</code> <code>FS_GROUPS</code>.
        </div>`;
    }

    html += _fsSubHTML(fsActiveGid, groupData);
    el.innerHTML = html;
    _fsBindSubEvents(el, fsActiveGid);
}

/** 產生子功能 HTML */
function _fsSubHTML(gid, groupData) {
    const g = _fsGetGroup(gid);
    const color = g ? g.color : '#aab';
    let html = '';

    Object.entries(groupData).forEach(([cat, items]) => {
        if (!items.length) return;
        const allSel = items.every(i => fsSelected[i.key]);
        const selCount = _fsCatSelCount(gid, cat);

        html += `<div class="fs-sub-hdr">
            <span class="fs-sub-hdr-name" style="color:${color}">${cat}</span>
            <button class="fs-sel-all-btn${allSel ? ' on' : ''}"
                    data-gid="${gid}" data-cat="${cat.replace(/"/g, '&quot;')}">
                ${allSel ? 'Deselect All' : 'Select All'}
            </button>
        </div>`;

        const gidBadge = {
            hw:          { label: 'HW',  cls: 'fs-hw-badge' },
            application: { label: 'APP', cls: 'fs-hw-badge fs-app-badge' }
        };
        items.forEach(item => {
            const uid = 'fs_' + Math.random().toString(36).slice(2);
            const checked = !!fsSelected[item.key];
            const badge = gidBadge[gid];
            html += `<div class="fs-feat-row">
                <input type="checkbox" id="${uid}" ${checked ? 'checked' : ''}
                    data-gid="${gid}" data-key="${item.key}"
                    data-label="${item.label.replace(/"/g, '&quot;')}"
                    style="accent-color:${color}">
                <label for="${uid}">${item.label}</label>
                ${badge ? `<span class="${badge.cls}">${badge.label}</span>` : ''}
            </div>`;
        });
    });

    return html;
}

/** 綁定子功能區域的事件 */
function _fsBindSubEvents(el, gid) {
    el.querySelectorAll('.fs-sel-all-btn').forEach(btn => {
        btn.addEventListener('click', () => fsToggleCat(btn.dataset.gid, btn.dataset.cat));
    });
    el.querySelectorAll('input[type=checkbox]').forEach(cb => {
        cb.addEventListener('change', () => {
            fsToggleItem(cb.dataset.key, cb.dataset.label, cb.dataset.gid, cb.checked);
        });
    });
}

/** 渲染搜尋結果（前端過濾，無 API 呼叫） */
function fsRenderSearch() {
    const sub = document.getElementById('fs-sub-area');
    if (!sub) return;
    sub.style.display = 'block';

    const q = fsSearchQ;
    let html = '';
    let hasAny = false;

    const searchTargets = [
        ...FS_VISIBLE_GROUPS.map(g => ({ g, data: fsData[g.id] || {} })),
        { g: { id: 'other', label: 'Other (Uncategorized)', color: '#aab', icon: '⚠' }, data: fsData['other'] || {} }
    ];

    searchTargets.forEach(({ g, data }) => {
        const matchedCats = {};
        Object.entries(data).forEach(([cat, items]) => {
            const matchedItems = items.filter(i =>
                i.label.toLowerCase().includes(q) ||
                cat.toLowerCase().includes(q) ||
                g.label.toLowerCase().includes(q)
            );
            if (matchedItems.length) matchedCats[cat] = matchedItems;
        });

        if (!Object.keys(matchedCats).length) return;
        hasAny = true;
        html += `<div class="fs-sr-grp-hdr" style="color:${g.color}">
            ${g.icon}&nbsp; ${g.label}
        </div>`;
        html += _fsSubHTML(g.id, matchedCats);
    });

    sub.innerHTML = hasAny ? html : '<div class="fs-no-result">No matching results</div>';
    if (hasAny) {
        _fsBindSubEvents(sub, null);
        // 搜尋結果中的事件需逐一綁定
        sub.querySelectorAll('input[type=checkbox]').forEach(cb => {
            cb.addEventListener('change', () => {
                fsToggleItem(cb.dataset.key, cb.dataset.label, cb.dataset.gid, cb.checked);
            });
        });
        sub.querySelectorAll('.fs-sel-all-btn').forEach(btn => {
            btn.addEventListener('click', () => fsToggleCat(btn.dataset.gid, btn.dataset.cat));
        });
    }
}

// ── 搜尋框事件（在 DOMContentLoaded 後由 app.js 綁定） ──────────
// 以下函數供外部呼叫，不直接綁定 DOM
function fsOnSearchInput(val) {
    fsSearchQ = val.trim().toLowerCase();
    const clearEl = document.getElementById('fs-s-clear');
    if (clearEl) clearEl.style.display = fsSearchQ ? 'block' : 'none';
    if (fsReady) fsRender();
}

function fsOnSearchClear() {
    const searchEl = document.getElementById('fs-search');
    if (searchEl) searchEl.value = '';
    fsSearchQ = '';
    const clearEl = document.getElementById('fs-s-clear');
    if (clearEl) clearEl.style.display = 'none';
    if (fsReady) fsRender();
}
