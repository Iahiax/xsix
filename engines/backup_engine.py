import os
import json
import io
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

def get_drive_service():
    """تهيئة خدمة Google Drive بأمان باستخدام المتغيرات البيئية"""
    try:
        service_account_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}"))
        creds = Credentials.from_service_account_info(service_account_info, scopes=['https://www.googleapis.com/auth/drive'])
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"خطأ في تهيئة Google Drive: {e}")
        return None

def save_version_to_drive(version_name: str, update_type: str):
    """حفظ نسخة من المشروع في مجلد منظم في Google Drive"""
    service = get_drive_service()
    if not service:
        return "فشل الاتصال بـ Google Drive"

    try:
        # 1. البحث عن المجلد الرئيسي أو إنشاؤه
        folder_name = "UTI_Mega_System_Backups"
        # (كود مبسط للبحث عن المجلد، افتراضياً سننشئه إذا لم يوجد)
        
        # 2. إنشاء ملف نصي أو مضغوط يحتوي على حالة النظام والكود
        file_content = f"Version: {version_name}\nType: {update_type}\nStatus: Successful Deployment"
        fh = io.BytesIO(file_content.encode('utf-8'))
        
        file_metadata = {
            'name': f"UTI_Backup_{version_name}.txt",
            'mimeType': 'text/plain'
            # 'parents': [folder_id] # يمكن إضافة معرف المجلد هنا
        }
        
        media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        return file.get('webViewLink')
    except Exception as e:
        return f"خطأ في الحفظ: {str(e)}"

def get_version_history():
    """جلب سجل الإصدارات لعرضه في واجهة Gradio"""
    # محاكاة لبيانات يتم جلبها من Drive
    return [
        ["v2.1700000000", "2023-10-25 14:00", "ناجح", "https://drive.google.com/..."],
        ["v2.1699999999", "2023-10-24 10:00", "ناجح", "https://drive.google.com/..."],
        ["v1.0.0", "2023-10-01 08:00", "أساسي", "https://drive.google.com/..."]
    ]

