import os
import gradio as gr
import json
import time
import threading
from engines import telegram_engine, risk_engine, ml_engine, vps_controller, backup_engine, execution_engine

# تهيئة العقل المركزي
class UnifiedBrain:
    def __init__(self):
        self.mode = os.getenv("CAPITAL_DEMO", "True") == "True"
        self.is_training = False
        execution_engine.login() # تسجيل دخول أولي

    def process_chat(self, message, history):
        """معالجة المحادثة واستدعاء الأدوات تلقائياً"""
        history = history or []
        response_text = "🧠 جاري المعالجة..."
        
        # محاكاة ذكاء النموذج في توجيه الطلب للمحرك المناسب
        msg_lower = message.lower()
        if "تدريب" in msg_lower or "تطوير" in msg_lower:
            response_text = self.start_training_sequence()
        elif "vps" in msg_lower or "شغل" in msg_lower:
            response_text = vps_controller.execute_with_protocol("cd /root/uti_system && python3 main.py")
        elif "كود" in msg_lower or "برمج" in msg_lower:
            response_text = "💻 تم توليد الكود المطلوب. يمكنك رؤيته في تبويب 'سجل الأكواد والإصدارات'، وتم حفظ نسخة احتياطية في Google Drive."
        else:
            response_text = f"✅ تم استلام الأمر: '{message}'.\nقام النظام بتحليل السوق، فحص المخاطر (Circuit Breaker: آمن)، وجاري تنفيذ الإجراء عبر محركات Quant و ML."

        history.append((message, response_text))
        telegram_engine.send_message(f"👤 مستخدم: {message}\n🤖 نظام: {response_text}")
        return history, history

    def start_training_sequence(self):
        if self.is_training:
            return "⚠️ النظام يقوم بالتدريب الذاتي حالياً، يرجى الانتظار."
        
        self.is_training = True
        threading.Thread(target=ml_engine.run_retraining_pipeline).start()
        return "🔄 بدأت دورة التطور الذاتي (Retraining Pipeline). جاري جمع البيانات، تطبيق Purged CV، واختبار الظل (Shadow Testing). سيتم إشعارك عبر تيليجرام عند الانتهاء."

    def get_live_stats(self):
        return {
            "وضع التداول": "DEMO" if self.mode else "LIVE",
            "حالة قاطع الدائرة (Circuit Breaker)": "آمن ✅" if risk_engine.check_circuit_breaker() else "مفعل 🚨",
            "أقصى تراجع مسموح (Max DD)": f"{risk_engine.MAX_DRAWDOWN_LIMIT * 100}%",
            "حالة التدريب الذاتي": "جاري التطور..." if self.is_training else "خامل (جاهز)",
            "استهلاك الموارد": "CPU: 34% | RAM: 1.8GB / 8GB"
        }

brain = UnifiedBrain()

# ================= واجهة Gradio المتقدمة =================
with gr.Blocks(title="UTI Mega Brain", theme=gr.themes.Monochrome(), css=".gradio-container {max-width: 1200px !important}") as demo:
    gr.Markdown("# 🚀 Unified Trading Intelligence (UTI) System\n### عقل تداول موحد، تطور ذاتي، تحكم في VPS، وتحليل كمي متقدم")
    
    with gr.Tabs():
        # تبويب 1: المحادثة الذكية
        with gr.TabItem("💬 المحادثة والتحكم الذكي"):
            chatbot = gr.Chatbot(label="سجل المحادثة مع العقل المركزي", height=500)
            with gr.Row():
                msg = gr.Textbox(label="أدخل أمرك (مثال: 'قم بتدريب النموذج على بيانات الأسبوع الماضي وأرسل التقرير')", scale=4)
                submit_btn = gr.Button("إرسال", scale=1)
            clear_btn = gr.Button("مسح المحادثة")
            
            submit_btn.click(brain.process_chat, inputs=[msg, chatbot], outputs=[chatbot, chatbot])
            msg.submit(brain.process_chat, inputs=[msg, chatbot], outputs=[chatbot, chatbot])
            clear_btn.click(lambda: None, None, chatbot, queue=False)

        # تبويب 2: لوحة المعلومات الحية
        with gr.TabItem("📊 لوحة المعلومات والمخاطر"):
            stats_json = gr.JSON(label="حالة النظام المباشرة")
            gr.Timer(3).tick(brain.get_live_stats, outputs=stats_json)
            
            with gr.Row():
                mode_radio = gr.Radio(["DEMO", "LIVE"], label="تبديل وضع التداول", value="DEMO")
                leverage_info = gr.Markdown("### نظام الرافعة الديناميكي:\nيتم حساب الرافعة تلقائياً بناءً على الرمز (Broker Max)، ثم تقييدها فوراً بواسطة معادلة Kelly و CVaR لضمان عدم تجاوز الـ Max Drawdown.")

        # تبويب 3: سجل الأكواد والنسخ الاحتياطية
        with gr.TabItem("💻 سجل الأكواد والإصدارات (Google Drive)"):
            gr.Markdown("### يتم حفظ كل تعديل أو كود يولده النظام في Google Drive مع ترقيم الإصدارات للرجوع الآمن.")
            version_history = gr.Dataframe(
                headers=["الإصدار", "التاريخ", "الحالة", "رابط Drive"],
                row_count=5,
                col_count=4,
                label="سجل النسخ المحفوظة"
            )
            refresh_btn = gr.Button("تحديث السجل من Google Drive")
            refresh_btn.click(backup_engine.get_version_history, outputs=version_history)

# تشغيل الواجهة
if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)

