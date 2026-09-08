/* ═══════════════════════════════════════════════════════════
   SFP Selector — 光纖模組選型邏輯
   ═══════════════════════════════════════════════════════════ */

// ── 全域模組快取 ─────────────────────────────────────────────
let SFP_MODULES = null;

async function loadSfpModules() {
    if (SFP_MODULES !== null) return SFP_MODULES;
    try {
        const base = (typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE : '';
        const res = await fetch(`${base}/frontend/data/sfp_modules.json`);
        SFP_MODULES = await res.json();
    } catch (e) {
        console.warn('[SFP] 無法載入 sfp_modules.json', e);
        SFP_MODULES = [];
    }
    return SFP_MODULES;
}

// ── 速度判斷：從設備 port 欄位推導出 SFP 速度群組 ───────────
function getDeviceSfpSlots(item) {
    const slots = [];
    const f100 = parseInt(item.prod_fiber_100 || 0);
    const fgiga = parseInt(item.prod_fiber_giga || 0);
    const fge_combo = parseInt(item.prod_fiber_ge_combo || 0);
    const rj_combo = parseInt(item.prod_rj_100_combo || 0);
    const f10g = parseInt(item.prod_fiber_10g || 0);

    if (f100 > 0) slots.push({ speed: '100M', count: f100, combo: false });
    if (fgiga > 0) slots.push({ speed: '1G', count: fgiga, combo: false });
    
    // 取 Combo 埠的最大值，避免 Fiber Combo 與 RJ45 Combo 重複計算
    const comboCount = Math.max(fge_combo, rj_combo);
    if (comboCount > 0) slots.push({ speed: '1G', count: comboCount, combo: true });
    
    if (f10g > 0) slots.push({ speed: '10G', count: f10g, combo: false });
    return slots;
}

// ── 主入口：SFP 選型面板（非同步，tab 切換時呼叫）─────────────
async function buildSfpPaneAsync(item, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // 清除載入中的樣式（避免繼承 padding 與斜體）
    container.classList.remove('sfp-loading');

    const ft   = (item.prod_fiber_type || '').trim();
    const conn = (item.prod_fiber_conn || '').trim();

    // ── 無 Fiber port ────────────────────────────────────────
    if (!checkHasSfp(item)) {
        container.innerHTML = `
            <div class="sfp-no-fiber">
                <span class="sfp-icon">🔌</span>
                <span>No fiber port on this device</span>
            </div>`;
        return;
    }

    // ── 固定接頭（非 SFP 插槽）──────────────────────────────
    if (ft && ft !== 'SFP' && ft !== 'SFP+') {
        const modeLabel = ft === 'Multi-mode' ? 'Multi-mode (OM1/OM2)' : 'Single-mode (G.652)';
        const connLabel = conn ? `${conn} Connector` : 'Refer to datasheet';
        const recLabel = ft === 'Multi-mode'
            ? 'Suggest using OM1 or OM2 multi-mode patch cord.'
            : 'Suggest using G.652 single-mode patch cord.';
        const typeTitle = `${ft}${conn ? ' ' + conn : ''}`;
        container.innerHTML = `
            <div class="sfp-fixed-info">
                <div class="sfp-fixed-title">
                    <span class="sfp-icon">🔌</span>
                    ${typeTitle} Fixed Connector — No SFP module required
                </div>
                <div class="sfp-fixed-rows">
                    <div class="sfp-fixed-row">
                        <span class="sfp-fixed-label">Fiber Mode</span>
                        <span class="sfp-fixed-val">${modeLabel}</span>
                    </div>
                    <div class="sfp-fixed-row">
                        <span class="sfp-fixed-label">Connector</span>
                        <span class="sfp-fixed-val">${connLabel}</span>
                    </div>
                    <div class="sfp-fixed-row">
                        <span class="sfp-fixed-label">Recommendation</span>
                        <span class="sfp-fixed-val" style="color:var(--text-main)">${recLabel}</span>
                    </div>
                </div>
            </div>`;
        return;
    }

    // ── SFP 插槽 ─────────────────────────────────────────────
    const modules = await loadSfpModules();
    const slots   = getDeviceSfpSlots(item);

    if (slots.length === 0) {
        container.innerHTML = `<div class="sfp-no-fiber"><span class="sfp-icon">⚠️</span><span>No SFP slot data found</span></div>`;
        return;
    }

    let html = `<div class="sfp-slots-wrap">`;
    for (const slot of slots) {
        const matching  = modules.filter(m => m.speed === slot.speed);
        const displayFt = ft || 'SFP';

        html += `
        <div class="sfp-speed-group">
            <div class="port-total-row" style="margin-bottom: 12px;">
                <span class="port-total-num">${slot.count}</span>
                <span class="port-total-label">${displayFt} ${slot.speed} Slots</span>
            </div>
            ${buildSfpCategoryGrid(matching, slot.speed, containerId)}
        </div>`;
    }
    html += `</div>`;
    container.innerHTML = html;
}

// ── 依速度建構四個分類 ────────────────────────────────────────
function buildSfpCategoryGrid(modules, speed, containerId) {
    const categories = [
        { key: 'mm', label: 'Multi-mode', sublabel: 'Multi-mode (OM1/OM2)', color: 'mm', items: modules.filter(s => s.cat === 'fiber' && s.mode === 'multi-mode' && !s.bidi) },
        { key: 'sm', label: 'Single-mode', sublabel: 'Single-mode (G.652)', color: 'sm', items: modules.filter(s => s.cat === 'fiber' && s.mode === 'single-mode' && !s.bidi) },
        { key: 'bidi', label: 'BiDi', sublabel: 'Single-strand BiDi (Pair)', color: 'bidi', items: modules.filter(s => s.cat === 'fiber' && s.bidi) },
        { key: 'copper', label: 'Copper', sublabel: 'SFP to RJ45', color: 'copper', items: modules.filter(s => s.cat === 'copper') }
    ];

    const activeCats = categories
        .map(c => ({ ...c, items: c.items }))
        .filter(cat => cat.items.length > 0);

    if (activeCats.length === 0) return `<div class="sfp-no-fiber" style="padding:12px 10px;font-size:11px;">No compatible modules</div>`;

    let html = `<div class="sfp-acc-group">`;
    for (const cat of activeCats) {
        const cardId = `sfp-card-${containerId}-${speed}-${cat.key}`;
        const tagHtml = `<span class="sfp-acc-tag sfp-acc-tag-${cat.color}">${cat.label}</span>`;
        
        html += `
        <div class="sfp-acc-item" id="${cardId}">
            <button class="sfp-acc-hdr" onclick="sfpToggleCard('${cardId}')">
                <div class="sfp-acc-left">
                    ${tagHtml}
                    <span class="sfp-acc-title">${cat.sublabel}</span>
                    <span class="sfp-acc-count">${cat.items.length} items</span>
                </div>
                <span class="sfp-acc-arrow" id="${cardId}-chevron">&#8964;</span>
            </button>
            <div class="sfp-acc-body" id="${cardId}-body">
                <div class="sfp-sgrid">
                    ${buildSfpModuleRows(cat.items, cat.key === 'bidi')}
                </div>
            </div>
        </div>`;
    }
    html += `</div>`;
    return html;
}

// ── 模組列表（Accordion 內部 Grid）─────────────────────────
function buildSfpModuleRows(modules, isBidi) {
    return modules.map(s => {
        const mTag = s.cat === "copper"
            ? `<span class="sfp-tag sfp-tag-cu">Copper</span>`
            : s.mode === "multi-mode" ? `<span class="sfp-tag sfp-tag-mm">Multi-mode</span>` : `<span class="sfp-tag sfp-tag-sm">Single-mode</span>`;
        const bTag = s.bidi ? `<span class="sfp-tag sfp-tag-bidi">BiDi</span>` : "";
        const connTag = `<span class="sfp-tag sfp-tag-neu">${s.conn}</span>`;
        const duplexTag = s.duplex ? `<span class="sfp-tag sfp-tag-neu">${s.duplex}</span>` : "";
        
        // 研華官網搜尋連結（以型號自動組合）
        const advUrl = `https://www.advantech.com/en/search?q=${encodeURIComponent(s.part)}`;
        
        return `<a class="sfp-scard" href="${advUrl}" target="_blank" rel="noopener noreferrer"
            title="View on Advantech website: ${s.part}">
            <div class="sfp-spart-row">
                <div class="sfp-spart">${s.part}</div>
                <span class="sfp-ext-icon">&#8599;</span>
            </div>
            <div class="sfp-smeta">${mTag}${bTag}${connTag}${duplexTag}</div>
            <div class="sfp-sdet">${s.dist}${s.wave ? " &nbsp;·&nbsp; λ " + s.wave : ""}</div>
            ${s.note ? `<div class="sfp-sdet">${s.note}</div>` : ""}
            ${s.bidi ? `<div class="sfp-spair">Pair: ${s.pair}</div>` : ""}
        </a>`;
    }).join("");
}

// ── 卡片開關 ─────────────────────────────────────────────────
function sfpToggleCard(cardId) {
    const body = document.getElementById(`${cardId}-body`);
    const card = document.getElementById(cardId);
    if (!body || !card) return;
    const hdr = card.querySelector('.sfp-acc-hdr');
    
    const isOpen = body.classList.toggle('open');
    if (hdr) hdr.classList.toggle('open', isOpen);
    card.classList.toggle('is-open', isOpen);
}

// ── 切換設備時重置所有卡片至收合狀態 ─────────────────────────
function sfpResetAllAccordions() {
    document.querySelectorAll('.sfp-acc-body').forEach(el => {
        el.classList.remove('open');
    });
    document.querySelectorAll('.sfp-acc-hdr').forEach(el => {
        el.classList.remove('open');
    });
    document.querySelectorAll('.sfp-acc-item').forEach(el => {
        el.classList.remove('is-open');
    });
}
