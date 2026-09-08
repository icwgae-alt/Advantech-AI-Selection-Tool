/* ═══════════════════════════════════════════════════════════
   Advantech Switch Selection Tool — Product Comparison Module
   ═══════════════════════════════════════════════════════════

   架構說明：
   ┌─────────────────────────────────────────────────────────┐
   │  可擴充設計 (CMP_SECTIONS)                               │
   │  每個 Section 描述一組規格欄位，新增比較維度只需:         │
   │  1. 在 CMP_SECTIONS 陣列新增一個 section object          │
   │  2. 在 item → value 提取函式 (extractValue) 加上對應邏輯 │
   │  無需修改渲染引擎或差異計算邏輯。                         │
   └─────────────────────────────────────────────────────────┘

   公開介面（供 app.js 使用）：
   - compareToggle(pid)         → 勾選/取消勾選一台產品
   - compareReset()             → 清除全部比較狀態（Reset All 時呼叫）
   - compareOnNewResults()      → 搜尋新結果時重置（因卡片 DOM 重建）
   - setCompareBaseline(idx)    → 設定基準欄（onclick 用）
   - toggleCompareDiff()        → 切換「只看差異」模式（onclick 用）
   ═══════════════════════════════════════════════════════════ */



// ─────────────────────────────────────────────
// 常數設定
// ─────────────────────────────────────────────
const CMP_MAX = 5;    // 最多同時比較幾台

// ─────────────────────────────────────────────
// 規格欄位定義（可擴充的核心設定）
// ─────────────────────────────────────────────
const CMP_SECTIONS = [
    {
        id: 'basic',
        label: 'Basic Info',
        fields: [
            { id: 'model',       label: 'Model Name',           type: 'str', extract: i => i.prod_model || '' },
            { id: 'type',        label: 'Management',        type: 'str', extract: i => i.prod_type || '' },
            { id: 'portnum',     label: 'Total Ports',          type: 'num', extract: i => i.prod_portnum || 0 },
            { id: 'temp_range',  label: 'Temp Range',         type: 'str', extract: i => (i.prod_temp_range || '—').trim() },
            { id: 'power',       label: 'Power Input',        type: 'str', extract: i => (i.prod_power_input || '—').trim() },
            { id: 'mounting',    label: 'Mounting Type',      type: 'str', extract: i => (i.prod_mounting || '—').trim() },
        ]
    },
    {
        id: 'ports',
        label: 'Port Specification',
        fields: [
            { id: 'rj_100',         label: 'RJ-45 10/100M',        type: 'num', extract: i => i.prod_rj_100 || 0 },
            { id: 'rj_giga',        label: 'RJ-45 GbE',             type: 'num', extract: i => i.prod_rj_giga || 0 },
            { id: 'poe_rj_100',     label: 'PoE RJ-45 100M',        type: 'num', extract: i => i.prod_poe_rj_100 || 0 },
            { id: 'poe_rj_giga',    label: 'PoE RJ-45 GbE',         type: 'num', extract: i => i.prod_poe_rj_giga || 0 },
            { id: 'fiber_100',      label: 'Fiber 100M',             type: 'num', extract: i => i.prod_fiber_100 || 0 },
            { id: 'fiber_giga',     label: 'Fiber GbE (SFP)',        type: 'num', extract: i => i.prod_fiber_giga || 0 },
            { id: 'fiber_10g',      label: 'Fiber 10G (SFP+)',       type: 'num', extract: i => i.prod_fiber_10g || 0 },
            { id: 'rj_combo',       label: 'RJ-45 / SFP Combo',     type: 'num', extract: i => i.prod_rj_100_combo || 0 },
            { id: 'm12_100',        label: 'M12 D-code 100M',        type: 'num', extract: i => i.prod_m12_100 || 0 },
            { id: 'm12_giga',       label: 'M12 X-code GbE',         type: 'num', extract: i => i.prod_m12_giga || 0 },
            { id: 'm12_multi',      label: 'M12 X-code Multi-Giga',  type: 'num', extract: i => i.prod_m12_multi_giga || 0 },
            { id: 'poe_m12_100',    label: 'PoE M12 D-code',         type: 'num', extract: i => i.prod_poe_m12_100 || 0 },
            { id: 'poe_m12_giga',   label: 'PoE M12 X-code',         type: 'num', extract: i => i.prod_poe_m12_giga || 0 },
            { id: 'poe_standard',   label: 'PoE Standard',            type: 'str', extract: i => (i.prod_poe_standard || '—').trim() },
            { id: 'poe_budget',     label: 'PoE Budget (W)',          type: 'str', extract: i => (i.prod_poe_budget || '—').trim() },
            { id: 'bypass_100',     label: 'LAN Bypass D-code',       type: 'num', extract: i => i.prod_bypass_m12_100 || 0 },
            { id: 'bypass_giga',    label: 'LAN Bypass X-code',       type: 'num', extract: i => i.prod_bypass_m12_giga || 0 },
        ]
    },
    {
        id: 'fiber',
        label: 'Fiber Specification',
        fields: [
            { id: 'fiber_type', label: 'Fiber Slot Type', type: 'str', extract: i => (i.prod_fiber_type || '—').trim() },
            { id: 'fiber_conn', label: 'Fixed Connector', type: 'str', extract: i => (i.prod_fiber_conn || '—').trim() },
        ]
    },
    {
        id: 'certifications',
        label: 'Certifications',
        fields: [
            { id: 'certs', label: 'Certifications', type: 'str', extract: i => (i.prod_certifications || '—').trim() },
        ]
    },
];

// ─────────────────────────────────────────────
// 狀態
// ─────────────────────────────────────────────
let _compareSet = new Set();   // pid 集合，如 'pc-0', 'pc-3'
let _aiSummaryText = '';       // 最近一次 AI summary 的原始 Markdown 文字
let _baselineIdx = 0;          // 目前基準欄的 index
let _diffOnly = false;         // 是否只顯示差異列

// ─────────────────────────────────────────────
// 公開：切換勾選
// ─────────────────────────────────────────────
function compareToggle(pid) {
    if (_compareSet.has(pid)) {
        _compareSet.delete(pid);
    } else {
        if (_compareSet.size >= CMP_MAX) {
            _showToast(`Can compare up to ${CMP_MAX} products`);
            const cb = document.getElementById(`cmp-cb-${pid}`);
            if (cb) cb.checked = false;
            return;
        }
        _compareSet.add(pid);
    }
    _updateCheckboxVisual(pid);
    _renderBar();
}

// ─────────────────────────────────────────────
// 公開：查詢某 pid 是否在比較清單中
// ─────────────────────────────────────────────
function compareIsSelected(pid) {
    return _compareSet.has(pid);
}

// ─────────────────────────────────────────────
// 公開：清除所有比較狀態（Reset All 時呼叫）
// ─────────────────────────────────────────────
function compareReset() {
    _compareSet.clear();
    _baselineIdx = 0;
    _diffOnly = false;
    document.querySelectorAll('.cmp-cb-wrap.checked').forEach(btn => btn.classList.remove('checked'));
    _renderBar();
    _closePanel();
}

// ─────────────────────────────────────────────
// 公開：搜尋新結果時呼叫（DOM 重建，舊 pid 失效）
// ─────────────────────────────────────────────
function compareOnNewResults() {
    _compareSet.clear();
    _baselineIdx = 0;
    _diffOnly = false;
    _renderBar();
    _closePanel();
}

// ─────────────────────────────────────────────
// 公開：設定基準欄（產品標頭點擊時呼叫）
// ─────────────────────────────────────────────
function setCompareBaseline(idx) {
    _baselineIdx = idx;
    const items = [..._compareSet].map(pid =>
        window._sfpItemCache && window._sfpItemCache[pid]
    ).filter(Boolean);
    if (items.length < 1) return;
    _rebuildTable(items);
}

// ─────────────────────────────────────────────
// 公開：切換「只看差異」模式
// ─────────────────────────────────────────────
function toggleCompareDiff() {
    _diffOnly = !_diffOnly;
    const btn = document.getElementById('cmp-diff-btn');
    if (btn) btn.classList.toggle('active', _diffOnly);
    document.querySelectorAll('#cmp-panel .cmp-row-same').forEach(tr => {
        tr.classList.toggle('cmp-row-hidden', _diffOnly);
    });
}

// ─────────────────────────────────────────────
// 內部：更新單一卡片 checkbox 視覺
// ─────────────────────────────────────────────
function _updateCheckboxVisual(pid) {
    const btn = document.getElementById(`cmp-cb-btn-${pid}`);
    if (!btn) return;
    const checked = _compareSet.has(pid);
    btn.classList.toggle('checked', checked);
}

// ─────────────────────────────────────────────
// 渲染：底部浮動 Compare Bar
// ─────────────────────────────────────────────
function _renderBar() {
    let bar = document.getElementById('cmp-bar');
    if (!bar) return;

    const count = _compareSet.size;

    if (count === 0) {
        bar.classList.remove('visible');
        document.getElementById('prodList').style.paddingBottom = '';
        return;
    }

    const chips = [..._compareSet].map(pid => {
        const item = window._sfpItemCache && window._sfpItemCache[pid];
        const label = item ? item.prod_model : pid;
        return `<span class="cmp-bar-chip">${label}
                    <span class="cmp-bar-chip-x" onclick="compareToggle('${pid}')">×</span>
                </span>`;
    }).join('');

    bar.innerHTML = `
        <div class="cmp-bar-inner">
            <span class="cmp-bar-label">
                <span class="cmp-bar-count">${count}</span> selected
            </span>
            <div class="cmp-bar-chips">${chips}</div>
            <div class="cmp-bar-actions">
                <button class="cmp-bar-btn" onclick="openComparePanel()"
                    title="View / Compare">
                    ⇄ View / Compare
                </button>
                <button class="cmp-bar-clear" onclick="compareReset()">Clear</button>
            </div>
        </div>`;

    bar.classList.add('visible');
    document.getElementById('prodList').style.paddingBottom = '70px';
}

// ─────────────────────────────────────────────
// 開啟比較側拉面板
// ─────────────────────────────────────────────
function openComparePanel() {
    if (_compareSet.size < 1) return;

    const items = [..._compareSet].map(pid =>
        window._sfpItemCache && window._sfpItemCache[pid]
    ).filter(Boolean);

    if (items.length < 1) {
        _showToast('Products not found, please search again');
        return;
    }

    // 重置面板狀態
    _baselineIdx = 0;
    _diffOnly = false;

    _buildPanel(items);

    const panel = document.getElementById('cmp-panel');
    if (panel) panel.classList.add('open');
}

// ─────────────────────────────────────────────
// 關閉比較側拉面板（保留勾選狀態）
// ─────────────────────────────────────────────
function _closePanel() {
    const panel = document.getElementById('cmp-panel');
    if (panel) panel.classList.remove('open');
}

function closeComparePanel() {
    _closePanel();
}

// ─────────────────────────────────────────────
// 核心：建立比較面板完整內容
// ─────────────────────────────────────────────
function _buildPanel(items) {
    const panel = document.getElementById('cmp-panel');
    if (!panel) return;

    const headerHtml = `
        <div class="cmp-panel-header">
            <div class="cmp-panel-title">
                <span class="cmp-panel-icon">⇄</span>
                Compare Specs
                <span class="cmp-panel-count">${items.length} items</span>
            </div>
            <div class="cmp-panel-actions">
                <button class="cmp-panel-dl" onclick="downloadCompareCSV()" title="Download CSV">📥 CSV</button>
                <button class="cmp-panel-dl" onclick="downloadComparePDF()" title="Download PDF">📥 PDF</button>
                <button class="cmp-panel-close" onclick="closeComparePanel()">✕</button>
            </div>
        </div>`;

    const aiSummaryHtml = `
        <div id="cmp-ai-summary">
            <div class="cmp-ai-header">
                <span class="cmp-ai-icon">🤖</span>
                <span class="cmp-ai-title">AI Analysis</span>
            </div>
            <div id="cmp-ai-content" class="cmp-ai-loading">
                <span class="cmp-ai-dot"></span>
                <span class="cmp-ai-dot"></span>
                <span class="cmp-ai-dot"></span>
            </div>
        </div>`;

    const { html: tableHtml, diffCount } = _buildTable(items);

    const toolbarHtml = `
        <div class="cmp-toolbar">
            <button class="cmp-diff-btn" id="cmp-diff-btn" onclick="toggleCompareDiff()">
                ⊟ Differences only
            </button>
            <span class="cmp-diff-count" id="cmp-diff-count">${diffCount} difference${diffCount !== 1 ? 's' : ''}</span>
        </div>`;

    panel.innerHTML = headerHtml + `
        <div class="cmp-panel-body">
            ${aiSummaryHtml}
            ${toolbarHtml}
            <div id="cmp-table-container">${tableHtml}</div>
        </div>`;

    const pns = items.map(i => i.prod_name).filter(Boolean);
    _fetchAiSummary(pns);
}

// ─────────────────────────────────────────────
// 只重建表格區（切換基準欄時使用）
// ─────────────────────────────────────────────
function _rebuildTable(items) {
    const container = document.getElementById('cmp-table-container');
    if (!container) return;
    const { html, diffCount } = _buildTable(items);
    container.innerHTML = html;

    const countEl = document.getElementById('cmp-diff-count');
    if (countEl) countEl.textContent = `${diffCount} difference${diffCount !== 1 ? 's' : ''}`;

    // 恢復 diff-only 狀態
    if (_diffOnly) {
        document.querySelectorAll('#cmp-panel .cmp-row-same').forEach(tr => {
            tr.classList.add('cmp-row-hidden');
        });
    }
}

// ─────────────────────────────────────────────
// AI Summary 取得
// ─────────────────────────────────────────────
async function _fetchAiSummary(pns) {
    _aiSummaryText = '';
    const contentEl = document.getElementById('cmp-ai-content');
    if (!contentEl || !pns.length) return;

    try {
        const apiBase = typeof API_BASE !== 'undefined' ? API_BASE : '';
        const resp = await fetch(`${apiBase}/api/compare-summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ product_pns: pns }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        _aiSummaryText = data.summary;
        contentEl.classList.remove('cmp-ai-loading');
        if (typeof marked !== 'undefined') {
            contentEl.innerHTML = marked.parse(data.summary);
        } else {
            contentEl.textContent = data.summary;
        }
    } catch (err) {
        contentEl.classList.remove('cmp-ai-loading');
        contentEl.innerHTML = `<span style="color:#999;font-size:13px;">⚠️ AI analysis unavailable: ${err.message}</span>`;
    }
}

// ─────────────────────────────────────────────
// 核心：建立比較表格 HTML，回傳 { html, diffCount }
// ─────────────────────────────────────────────
function _buildTable(items) {
    const colCount = items.length;
    let diffCount = 0;

    // ── 產品型號標頭列（可點擊切換基準）──
    let headerRow = `<tr class="cmp-header-row">
        <th class="cmp-label-col cmp-th-sticky">Specs</th>`;
    items.forEach((item, idx) => {
        const prodUrl = item.prod_url ||
            `https://www.advantech.com/en/search?q=${encodeURIComponent(item.prod_model)}`;
        const isBaseline = idx === _baselineIdx;
        headerRow += `
        <th class="cmp-prod-col ${isBaseline ? 'cmp-prod-baseline' : ''}"
            onclick="setCompareBaseline(${idx})"
            title="Click to set as baseline">
            <div class="cmp-prod-header">
                <a class="cmp-prod-name" href="${prodUrl}" target="_blank" rel="noopener noreferrer"
                   onclick="event.stopPropagation()"
                   title="View on Advantech website">
                    ${item.prod_model} <span class="cmp-ext-icon">↗</span>
                </a>
                <div class="cmp-prod-pn">${item.prod_name || ''}</div>
                ${isBaseline ? '<div class="cmp-baseline-label">Baseline</div>' : ''}
            </div>
        </th>`;
    });
    headerRow += '</tr>';

    // ── 各 Section 的資料列 ──
    let bodyRows = '';

    CMP_SECTIONS.forEach(section => {
        const visibleFields = section.fields.filter(field => {
            const vals = items.map(item => field.extract(item));
            if (field.type === 'num') return vals.some(v => v > 0);
            else return vals.some(v => v && v !== '—' && v !== '');
        });

        if (visibleFields.length === 0) return;

        bodyRows += `<tr class="cmp-section-row">
            <td class="cmp-section-label cmp-label-col" colspan="${colCount + 1}">
                ${section.label}
            </td>
        </tr>`;

        visibleFields.forEach(field => {
            const vals = items.map(item => field.extract(item));
            const isDiff = _hasDiff(vals, field.type);
            if (isDiff) diffCount++;

            let rowClass = 'cmp-data-row';
            if (!isDiff) rowClass += ' cmp-row-same';

            bodyRows += `<tr class="${rowClass}">
                <td class="cmp-label-col cmp-field-label">${field.label}</td>`;

            vals.forEach((v, colIdx) => {
                const { display, cellClass } = _formatCell(v, field.type, vals, isDiff, colIdx);
                bodyRows += `<td class="cmp-data-cell ${cellClass}">${display}</td>`;
            });

            bodyRows += '</tr>';
        });
    });

    const html = `
        <div class="cmp-table-wrap">
            <table class="cmp-table">
                <thead>${headerRow}</thead>
                <tbody>${bodyRows}</tbody>
            </table>
        </div>
        <div class="cmp-legend">
            <span class="cmp-leg-item"><span class="cmp-leg-dot cmp-leg-best"></span>Best value</span>
            <span class="cmp-leg-item"><span class="cmp-leg-dot cmp-leg-low"></span>Lower value</span>
            <span class="cmp-leg-item"><span class="cmp-leg-dot cmp-leg-diff"></span>Differs from baseline</span>
            <span class="cmp-leg-item cmp-leg-same-item"><span class="cmp-leg-dot cmp-leg-same"></span>Same</span>
        </div>`;

    return { html, diffCount };
}

// ─────────────────────────────────────────────
// 工具：判斷一列中是否有差異
// ─────────────────────────────────────────────
function _hasDiff(vals, type) {
    if (vals.length <= 1) return false;
    const normalized = vals.map(v =>
        type === 'num' ? (v || 0) : String(v || '—').trim().toLowerCase()
    );
    return !normalized.every(v => v === normalized[0]);
}

// ─────────────────────────────────────────────
// 工具：格式化單一格，回傳 { display, cellClass }
//   三色語意：
//   - 數字：最高值 → cmp-cell-best（綠）；低於最高 → cmp-cell-low（橙）
//   - 字串：與基準不同 → cmp-cell-diff（藍）
//   - 基準欄本身永遠不加色
// ─────────────────────────────────────────────
function _formatCell(val, type, allVals, isDiff, colIdx) {
    const isBaseline = colIdx === _baselineIdx;

    if (type === 'num') {
        const n = val || 0;
        const display = n === 0
            ? '<span class="cmp-val-zero">—</span>'
            : `<span class="cmp-val-num">${n}</span>`;

        let cellClass = '';
        if (isDiff && !isBaseline && n > 0) {
            const maxVal = Math.max(...allVals.map(v => v || 0));
            cellClass = n === maxVal ? 'cmp-cell-best' : 'cmp-cell-low';
        }
        return { display, cellClass };

    } else {
        const s = String(val || '—').trim();
        let display = '';

        if (s === '—' || s === '') {
            display = '<span class="cmp-val-zero">—</span>';
        } else if (s === '✓' || s === 'V') {
            display = '<span class="cmp-val-check">✓</span>';
        } else if (s === 'X' || s === 'x') {
            display = '<span class="cmp-val-cross">X</span>';
        } else {
            display = `<span class="cmp-val-str">${s}</span>`;
        }

        let cellClass = '';
        if (isDiff && !isBaseline) {
            const baseVal = String(allVals[_baselineIdx] || '—').trim().toLowerCase();
            if (s.toLowerCase() !== baseVal) cellClass = 'cmp-cell-diff';
        }
        return { display, cellClass };
    }
}

// ─────────────────────────────────────────────
// Toast 提示
// ─────────────────────────────────────────────
function _showToast(msg) {
    let toast = document.getElementById('cmp-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'cmp-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.remove('show'), 2800);
}

// ─────────────────────────────────────────────
// 下載：CSV
// ─────────────────────────────────────────────
function downloadCompareCSV() {
    const items = [..._compareSet].map(pid =>
        window._sfpItemCache && window._sfpItemCache[pid]
    ).filter(Boolean);
    if (items.length === 0) return;

    let csv = '﻿';
    const headers = ['Specification', ...items.map(i => i.prod_model)];
    csv += headers.map(h => `"${h}"`).join(',') + '\n';

    CMP_SECTIONS.forEach(section => {
        const visibleFields = section.fields.filter(field => {
            const vals = items.map(item => field.extract(item));
            if (field.type === 'num') return vals.some(v => v > 0);
            return vals.some(v => v && v !== '—' && v !== '');
        });
        if (visibleFields.length === 0) return;

        csv += `"${section.label}"\n`;
        visibleFields.forEach(field => {
            const row = [field.label];
            items.forEach(item => {
                let val = field.extract(item);
                if (field.type === 'num' && !val) val = '—';
                else if (field.type === 'str' && (!val || val === '')) val = '—';
                row.push(val);
            });
            csv += row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',') + '\n';
        });
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Advantech_Switch_Comparison.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ─────────────────────────────────────────────
// 下載：PDF
// ─────────────────────────────────────────────
async function downloadComparePDF() {
    if (typeof _compareSet === 'undefined' || _compareSet.size === 0) {
        _showToast("No product selected");
        return;
    }

    const pns = [..._compareSet].map(pid => {
        const item = window._sfpItemCache && window._sfpItemCache[pid];
        return item ? item.prod_name : null;
    }).filter(Boolean);

    if (pns.length === 0) {
        _showToast("Corresponding product PN not found, please search again");
        return;
    }

    let criteria = window.currentCriteria ? JSON.parse(JSON.stringify(window.currentCriteria)) : {};

    if (criteria.type) {
        let t = criteria.type.toLowerCase();
        if (t === "l2_managed" || t === "l2 managed") {
            criteria.type = "L2 Managed";
        } else if (t === "l3_managed" || t === "l3 managed") {
            criteria.type = "L3 Managed";
        } else if (t === "managed") {
            criteria.type = "Managed (L2 + L3)";
        } else if (t === "unmanaged") {
            criteria.type = "Unmanaged";
        }
    }

    try {
        _showToast("Generating PDF, please wait...");
        const aiSummary = _aiSummaryText || '';

        const res = await fetch(`${typeof API_BASE !== 'undefined' ? API_BASE : ''}/api/exportReport`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                product_pns: pns,
                criteria: criteria,
                ai_summary: aiSummary
            })
        });

        if (!res.ok) throw new Error(`Server error: ${res.status}`);

        const rawBlob = await res.blob();
        const url = URL.createObjectURL(new Blob([rawBlob], { type: 'application/pdf' }));
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.setAttribute('download', 'selection_report.pdf');
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }, 1000);
        _showToast("PDF download complete");
    } catch (err) {
        console.error(err);
        _showToast("PDF generation failed, please try again later");
    }
}
