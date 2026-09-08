// ─────────────────────────────────────────────────────────────
// Cloudflare Tunnel 設定
// 部署到 GitHub Pages 時，請將下方 URL 改為實際的 Tunnel 位址
// 格式：https://your-subdomain.your-domain.com
// 本機開發時此值不會被使用（detectApiBase 優先判斷 localhost）
// ─────────────────────────────────────────────────────────────
const CLOUDFLARE_API_URL = 'https://api.namecheapest.cc';

// ─────────────────────────────────────────────────────────────
// Chatbot 功能開關
// 外部發布版本（icwgae-alt）建議設為 false 關閉聊天機器人；
// 內部版本（jim6501）維持 true。
// ─────────────────────────────────────────────────────────────
const ENABLE_CHATBOT = false;
