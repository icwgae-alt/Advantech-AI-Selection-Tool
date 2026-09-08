import os
import certifi
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from dotenv import load_dotenv

load_dotenv("configs/.env")

MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "advantech_ind_sw_tool")

class Database:
    client: MongoClient = None
    db = None

    @classmethod
    def connect_db(cls):
        """建立 MongoDB 單例連線，於 App 啟動時呼叫"""
        if not MONGO_URI:
            raise ValueError("MONGO_URI not set in environment variables")

        try:
            ca = certifi.where()
            cls.client = MongoClient(
                MONGO_URI,
                tlsCAFile=ca,
                tlsAllowInvalidCertificates=True,
                serverSelectionTimeoutMS=10000,
                tls=True,
                retryWrites=True
            )
            cls.client.admin.command('ping')
            cls.db = cls.client[MONGO_DB_NAME]
            print(f"[OK] Connected to MongoDB: {MONGO_DB_NAME}")
        except PyMongoError as e:
            print(f"[WARN] MongoDB connection failed (SSL or network issue): {e}")
            # 於測試階段暫不拋出 exception，確保 App 至少能啟動讓使用者看到 API 文件
            # raise e

    @classmethod
    def close_db(cls):
        """關閉連線，於 App 關閉時呼叫"""
        if cls.client:
            cls.client.close()
            print("[OK] MongoDB connection closed")

    @classmethod
    def get_db(cls):
        """
        取得資料庫實例。
        若啟動時連線失敗（如 SSL 問題），會嘗試自動重連一次。
        """
        if cls.db is None:
            print("[INFO] Database not initialized, attempting reconnect...")
            cls.connect_db()
        if cls.db is None:
            raise ConnectionError("MongoDB connection failed. Check network or MONGO_URI setting.")
        return cls.db
