/* ═══════════════════════════════════════════════════════════
   i18n.js — 介面文字語言切換（English / 日本語）
   ─────────────────────────────────────────────────────────
   範圍：僅涵蓋 UI 介面文字（標題、按鈕、空狀態提示）。
   維持英文不翻譯：排序選單、Filter Tag 前綴字、Chatbot、
   技術/型號/認證用語（RJ-45、M12、SPE、PoE、UL、IEC 61850…）、
   Managed(All) 等管理類型按鈕、產品規格欄位名稱。
   ═══════════════════════════════════════════════════════════ */

const I18N_DICT = {
    en: {
        mgmtTypeLabel: 'Management Type',
        totalPortCountLabel: 'Total Port Count',
        maxPortSpeedLabel: 'Max Port Speed',
        poeSectionLabel: 'PoE',
        interfaceTypeLabel: 'Interface Type',
        certificationsLabel: 'Certifications (Optional)',
        searchInventoryLabel: 'Search Inventory',
        searchProductItemsPlaceholder: 'Search product items…',

        deviceConfiguration: 'Device Configuration',
        selectionSummary: 'Selection Summary',
        filterConditions: 'Filter Conditions',
        chosenItems: 'Chosen Items',
        acquiredProductInfo: 'Acquired Product Information',

        findMatchingProducts: 'Find Matching Products',
        resetAll: 'Reset All',

        viewList: 'List',
        viewTable: 'Table',
        cardListTooltip: 'Card List',
        tableViewTooltip: 'Table View',
        columns: 'Columns',
        exportCsv: 'Export CSV',
        exportCsvTooltip: 'Download full table as CSV',
        selectColumnsToDisplay: 'Select columns to display',

        advancedFilter: 'Advanced Filter',
        advancedFeaturesFilter: 'Advanced Features Filter',
        searchFeaturesPlaceholder: 'Search features... (e.g. VLAN, PoE, STP, TSN)',
        noFeaturesSelected: 'No features selected',
        cancel: 'Cancel',
        applyFilter: 'Apply Filter',

        noFiltersAppliedYet: 'No filters applied yet',
        zeroResultHintCulprit: '⚠ No products found. The highlighted condition(s) are newly added and may be causing this.',
        zeroResultHintBroaden: '⚠ No products found. The highlighted condition(s) may be causing this. Please broaden your search criteria.',

        tabPort: 'Port',
        tabSpecs: 'Specs',
        tabSfpGuide: 'SFP Guide',
        goToProductPage: 'Go to Product Page',

        tierLabel: 'Tier',
    },
    ja: {
        mgmtTypeLabel: '管理タイプ',
        totalPortCountLabel: '合計ポート数',
        maxPortSpeedLabel: '最大ポート速度',
        poeSectionLabel: 'PoE',
        interfaceTypeLabel: 'インターフェースタイプ',
        certificationsLabel: '認証（任意）',
        searchInventoryLabel: '在庫検索',
        searchProductItemsPlaceholder: '製品を検索…',

        deviceConfiguration: 'デバイス設定',
        selectionSummary: '選定サマリー',
        filterConditions: 'フィルター条件',
        chosenItems: '選択済み項目',
        acquiredProductInfo: '取得した製品情報',

        findMatchingProducts: '該当製品を検索',
        resetAll: 'すべてリセット',

        viewList: 'リスト',
        viewTable: 'テーブル',
        cardListTooltip: 'カードリスト表示',
        tableViewTooltip: 'テーブル表示',
        columns: '列設定',
        exportCsv: 'CSV エクスポート',
        exportCsvTooltip: 'テーブル全体を CSV でダウンロード',
        selectColumnsToDisplay: '表示する列を選択',

        advancedFilter: '詳細フィルター',
        advancedFeaturesFilter: '詳細機能フィルター',
        searchFeaturesPlaceholder: '機能を検索... (例: VLAN, PoE, STP, TSN)',
        noFeaturesSelected: '機能が選択されていません',
        cancel: 'キャンセル',
        applyFilter: 'フィルターを適用',

        noFiltersAppliedYet: 'フィルター未適用',
        zeroResultHintCulprit: '⚠ 該当する製品がありません。ハイライトされた条件が新しく追加されたため、原因の可能性があります。',
        zeroResultHintBroaden: '⚠ 該当する製品がありません。ハイライトされた条件が原因の可能性があります。検索条件を広げてください。',

        tabPort: 'ポート',
        tabSpecs: '仕様',
        tabSfpGuide: 'SFPガイド',
        goToProductPage: '製品ページへ',

        tierLabel: '階層',
    }
};

const I18N_STORAGE_KEY = 'adv_lang';
let currentLang = (function () {
    try {
        return localStorage.getItem(I18N_STORAGE_KEY) || 'en';
    } catch {
        return 'en';
    }
})();

// 翻譯查詢：key 找不到就退回英文，英文也沒有就顯示 key 本身（方便除錯）
function T(key) {
    return (I18N_DICT[currentLang] && I18N_DICT[currentLang][key]) || I18N_DICT.en[key] || key;
}

// 套用目前語言到所有帶 data-i18n* 屬性的元素
function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = T(el.getAttribute('data-i18n'));
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = T(el.getAttribute('data-i18n-placeholder'));
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = T(el.getAttribute('data-i18n-title'));
    });
    document.querySelectorAll('.lang-switch-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.lang === currentLang);
    });
}

// 切換語言：存 localStorage、套用靜態文字、廣播事件讓其他模組重繪動態內容
function setLang(lang) {
    if (!I18N_DICT[lang] || lang === currentLang) return;
    currentLang = lang;
    try { localStorage.setItem(I18N_STORAGE_KEY, lang); } catch { /* ignore：無痕模式等情境 */ }
    applyI18n();
    document.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
}

document.addEventListener('DOMContentLoaded', applyI18n);
