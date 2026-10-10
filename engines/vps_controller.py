import paramiko
import time
import os

def execute_with_protocol(command: str) -> str:
    """تنفيذ الأوامر على segfault.net مع بروتوكول تجاوز شاشة البداية"""
    host = os.getenv("VPS_HOST", "segfault.net")
    user = os.getenv("VPS_USER", "root")
    password = os.getenv("VPS_PASSWORD", "")
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(host, username=user, password=password, port=22, timeout=10)
        
        # 1. فتح قناة تفاعلية لمحاكاة الطرفية
        channel = ssh.invoke_shell()
        time.sleep(2)
        
        # 2. إرسال Enter الأول
        channel.send('\n')
        time.sleep(2)
        
        # 3. الانتظار 63 ثانية كما هو مطلوب حرفياً
        time.sleep(63)
        
        # 4. إرسال Enter مرة أخرى لتجاوز أي موجهات عالقة
        channel.send('\n')
        time.sleep(2)
        
        # 5. تشغيل المشروع المطلوب
        channel.send(f"{command}\n")
        time.sleep(5) # انتظار بدء التنفيذ
        
        # 6. قراءة المخرجات
        output = channel.recv(4096).decode('utf-8')
        ssh.close()
        
        return f"✅ تم تنفيذ البروتوكول بنجاح على VPS.\nالمخرجات:\n{output}"
    except Exception as e:
        return f"❌ فشل اتصال VPS: {str(e)}"

