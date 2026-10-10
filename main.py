import uvicorn
import subprocess
import os
from core.chat_backend import app as chat_app
from engines import execution_engine

def startup_sequence():
    print("🚀 بدء تشغيل نظام UTI الموحد...")
    print("🔐 تسجيل الدخول إلى Capital.com...")
    if execution_engine.login():
        print("✅ تم تسجيل الدخول بنجاح.")
    else:
        print("❌ فشل تسجيل الدخول. تحقق من بيانات .env")
    
    print("🌐 تشغيل واجهة Chat UI وبروتوكول MCP على المنفذ 8000...")

if __name__ == "__main__":
    startup_sequence()
    # تشغيل FastAPI مع دعم إعادة التحميل التلقائي
    uvicorn.run("core.chat_backend:app", host="0.0.0.0", port=8000, reload=True)

