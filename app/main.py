from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pymongo.errors import PyMongoError
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import Database
from app.api import selection
from app.api import chat
from app.api import report
from app.api import compare
from app.llm_gateway import get_gateway


_BASE = Path(__file__).parent.parent  # 專案根目錄（絕對路徑）
PICS_DIR = _BASE / "frontend/data/pics"
THUMB_DIR = _BASE / "frontend/data/pics_thumb"
THUMB_SIZE = (400, 400)


def _build_thumbnails():
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in PICS_DIR.glob("*.png"):
        dst = THUMB_DIR / src.name
        if not dst.exists():
            img = Image.open(src).convert("RGBA")
            img.thumbnail(THUMB_SIZE)
            img.save(dst, format="PNG", optimize=True)
            count += 1
    if count:
        print(f"[PICS] Generated {count} thumbnails")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App 生命週期管理：啟動時連線 MongoDB，關閉時釋放資源"""
    print("[START] FastAPI App Starting...")
    Database.connect_db()
    get_gateway()  # 預先初始化 LLM Gateway（驗證 API Key 是否設定正確）
    _build_thumbnails()
    yield
    print("[STOP] FastAPI App Shutting Down...")
    Database.close_db()


app = FastAPI(
    title="Advantech AI Selection Tool API",
    description="工業交換機智能選型 API，支援硬體/軟體條件篩選與 RAG Chatbot 查詢",
    version="1.0.0",
    lifespan=lifespan,
)

# =========================================================================
# CORS 跨域設定
# =========================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 實際部署時請改為特定網域
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================================
# 開發用：前端 JS / CSS 永遠不快取，確保修改立即生效
# =========================================================================
class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/frontend/js/") or path.startswith("/frontend/css/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)

# =========================================================================
# 全域錯誤處理：統一攔截 MongoDB 相關錯誤，避免 500 直接洩漏堆疊資訊
# =========================================================================
@app.exception_handler(PyMongoError)
async def pymongo_exception_handler(request: Request, exc: PyMongoError):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Database error: {str(exc)}"},
    )


# =========================================================================
# 掛載 API 路由
# =========================================================================
app.include_router(selection.router, prefix="/api", tags=["Selection"])
app.include_router(chat.router,      prefix="/api", tags=["Chatbot"])
app.include_router(report.router,    prefix="/api", tags=["Report"])
app.include_router(compare.router,   prefix="/api", tags=["Compare"])


@app.get("/pics/{model}")
def get_pic(model: str, full: bool = Query(False)):
    cache = {"Cache-Control": "public, max-age=86400"}
    if full:
        for ext in ("png", "jpg"):
            path = PICS_DIR / f"{model}.{ext}"
            if path.exists():
                return FileResponse(path, headers=cache)
    else:
        thumb = THUMB_DIR / f"{model}.png"
        if thumb.exists():
            return FileResponse(thumb, headers=cache)
        # fallback：原圖尚未產生縮圖（新增圖片時）
        for ext in ("png", "jpg"):
            path = PICS_DIR / f"{model}.{ext}"
            if path.exists():
                return FileResponse(path, headers=cache)
    raise HTTPException(status_code=404, detail="Photo not found")


@app.get("/")
def root():
    return FileResponse(_BASE / "frontend/index.html")

# 掛載整個 frontend 資料夾作為靜態檔案，允許存取 /frontend/xxx.html (例如開啟其他分頁)
app.mount("/frontend", StaticFiles(directory=str(_BASE / "frontend")), name="frontend")

# 讓根目錄也能直接存取 css/ js/ 等資源（供 Cloudflare Tunnel 直接存取時使用）
app.mount("/css", StaticFiles(directory=str(_BASE / "frontend/css")), name="css")
app.mount("/js",  StaticFiles(directory=str(_BASE / "frontend/js")),  name="js")
app.mount("/data", StaticFiles(directory=str(_BASE / "frontend/data")), name="data")

