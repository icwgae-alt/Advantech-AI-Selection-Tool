/* ═══════════════════════════════════════════════════════════
   Scene Templates — 應用場景模板定義
   ─────────────────────────────────────────────────────────
   維護說明：
   - 每個場景的 conditions 陣列，每筆帶 key / value
   - 所有條件預設皆為可由使用者自由移除
   - UNSUPPORTED_CONDITION_KEYS: DB 欄位尚未就緒的 key，
     只做顯示用 tag，不加入 API 查詢（待認證欄位確認後移除）
   ═══════════════════════════════════════════════════════════ */

const UNSUPPORTED_CONDITION_KEYS = ['certifications'];

const SCENE_TEMPLATES = [
    {
        id: 'railway',
        label: 'Railway',
        icon: '🚆',
        description: 'EN 50155 · −40°C',
        conditions: [
            { key: 'mgmtType', value: 'managed' },
            { key: 'certifications', value: ['EN50155'] },
            { key: 'tempGrade', value: 'wide' },
        ]
    },
    {
        id: 'power',
        label: 'Power System',
        icon: '⚡',
        description: 'IEC 61850 · Ring',
        conditions: [
            { key: 'mgmtType', value: 'managed' },
            { key: 'certifications', value: ['IEC61850'] },
            { key: 'tempGrade', value: 'wide' },
        ]
    },
    {
        id: 'factory',
        label: 'Smart Factory',
        icon: '🏭',
        description: 'PoE',
        conditions: [
            { key: 'poe', value: true },
            { key: 'mgmtType', value: 'managed' }
        ]
    },
    {
        id: 'maritime',
        label: 'Maritime',
        icon: '⚓',
        description: 'IEC 60945 · Anti-Corrosion',
        conditions: [
            { key: 'mgmtType', value: 'managed' },
            { key: 'certifications', value: ['IEC60945'] },
            { key: 'tempGrade', value: 'wide' },
        ]
    }
];

// ─────────────────────────────────────────────
// 條件 key → 前端顯示標籤
// ─────────────────────────────────────────────
function getConditionDisplayLabel(cond) {
    switch (cond.key) {
        case 'mgmtType':
            const lblMap = { 'managed': 'Managed (All) SW', 'l2_managed': 'L2 Managed SW', 'l3_managed': 'L3 Managed SW', 'unmanaged': 'Unmanaged SW' };
            return lblMap[cond.value] || 'Unmanaged SW';
        case 'numPorts':
            return `≥${cond.value} Port`;
        case 'poe':
            return 'PoE Support';
        case 'tempGrade':
            return 'Wide Temp (−40°C)';
        case 'certifications':
            return `${cond.value.join(' / ')}`;
        default:
            return cond.key;
    }
}
