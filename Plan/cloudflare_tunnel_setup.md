# Cloudflare Tunnel + GitHub Pages 部署指南

## 架構說明

```
瀏覽器 → GitHub Pages (靜態前端)
              ↓ API 呼叫
    https://your-tunnel.your-domain.com  (Cloudflare Tunnel 公開 URL)
              ↓ 加密隧道
    內部電腦 FastAPI :8000 → MongoDB (本機)
```

---

## 步驟一：安裝 Cloudflare Tunnel（內部電腦）

### 1. 下載 cloudflared
前往 https://github.com/cloudflare/cloudflared/releases 下載 Windows 版：
- 下載 `cloudflared-windows-amd64.msi` 並安裝

### 2. 登入 Cloudflare 帳號
```powershell
cloudflared tunnel login
```
瀏覽器會開啟，選擇你的 Cloudflare 網域授權（需有 Cloudflare 帳號，免費方案即可）。

### 3. 建立 Tunnel
```powershell
cloudflared tunnel create advantech-selection-tool
```
記下輸出的 Tunnel ID（格式如：`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）

### 4. 建立設定檔
在 `%USERPROFILE%\.cloudflared\config.yml` 建立以下內容：
```yaml
tunnel: <你的 Tunnel ID>
credentials-file: C:\Users\<你的使用者名稱>\.cloudflared\<Tunnel ID>.json

ingress:
  - hostname: selection-tool.your-domain.com   # 改為你的網域
    service: http://localhost:8000
  - service: http_status:404
```

### 5. 設定 DNS 路由
```powershell
cloudflared tunnel route dns advantech-selection-tool selection-tool.your-domain.com
```

### 6. 啟動 Tunnel
```powershell
cloudflared tunnel run advantech-selection-tool
```

### 7. （選用）設為 Windows 服務，開機自動啟動
```powershell
cloudflared service install
```

---

## 步驟二：更新前端設定

編輯 `frontend/js/config.js`，填入你的 Tunnel URL：
```js
const CLOUDFLARE_API_URL = 'https://selection-tool.your-domain.com';
```

---

## 步驟三：設定 GitHub Pages

1. 將專案推到 GitHub repo（注意 `.env` 等機敏檔案不要推）
2. 到 GitHub repo → Settings → Pages
3. Source 選 **Deploy from a branch**
4. Branch 選 `master`，Folder 選 `/frontend`
5. 儲存後等約 1 分鐘，網址會顯示在 Pages 設定頁

---

## 步驟四：確認後端 CORS

`app/main.py` 目前 `allow_origins=["*"]` 已允許所有來源，功能上沒問題。
若要收緊安全性，可改為：
```python
allow_origins=[
    "http://localhost:8000",
    "https://<your-github-username>.github.io",
],
```

---

## 注意事項

| 項目 | 說明 |
|------|------|
| 電腦需保持開機 | Tunnel 在電腦關機後會斷線，前端 API 呼叫會失敗 |
| Cloudflare 免費方案限制 | 無流量上限限制，但有每分鐘 1000 次 request 的速率限制（正常使用不會觸及） |
| API 沒有認證 | 任何人知道 Tunnel URL 都能呼叫 API，建議後續加入 token 驗證 |
| `.env` 不要推到 GitHub | API Key、MongoDB URI 等機敏資訊絕對不要進 repo |

---

## 快速測試

Tunnel 啟動後，直接在瀏覽器開啟：
```
https://selection-tool.your-domain.com/api/selection
```
若回傳 JSON 資料（即使是空陣列）代表 Tunnel 正常運作。
