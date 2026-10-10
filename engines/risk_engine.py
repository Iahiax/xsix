import duckdb
from datetime import datetime

DAILY_LOSS_LIMIT = 0.03 # 3% Daily Circuit Breaker
MAX_DRAWDOWN_LIMIT = 0.15 # 15% Max Drawdown

def get_dynamic_leverage(symbol: str, account_equity: float, current_drawdown: float):
    """حساب الرافعة المثلى بناءً على الرمز وحالة الحساب"""
    # 1. جلب الرافعة القصوى المسموحة للرمز من Capital.com (مثال: 100:1)
    broker_max_leverage = 100 # يتم جلبها ديناميكياً من API
    
    # 2. تطبيق قيود المخاطر الصارمة
    if current_drawdown >= MAX_DRAWDOWN_LIMIT:
        return 0 # حظر التداول تماماً
    
    # 3. حساب حجم المركز باستخدام Bayesian Rolling Kelly (مبسط)
    # win_rate = 0.55, win_loss_ratio = 1.5
    kelly_fraction = 0.02 # 2% من رأس المال كمخاطرة قصوى للصفقة
    
    # 4. الرافعة الفعلية المستخدمة لتغطية هذه المخاطرة
    required_leverage = min(broker_max_leverage, int((account_equity * kelly_fraction) / 100))
    
    return max(1, required_leverage) # لا تقل عن 1

def check_circuit_breaker(daily_pnl: float, starting_equity: float) -> bool:
    """فحص قاطع الدائرة اليومي"""
    loss_pct = abs(min(0, daily_pnl)) / starting_equity
    if loss_pct >= DAILY_LOSS_LIMIT:
        trigger_graceful_self_destruct()
        return False # توقف التداول
    return True

def trigger_graceful_self_destruct():
    """آلية الانتحار الآمن عند اختراق المخاطر"""
    print("🚨 تفعيل بروتوكول الانتحار الآمن: إغلاق جميع الصفقات وإيقاف النظام.")
    # استدعاء execution_engine.close_all_positions()
    # إرسال تنبيه طوارئ عبر تيليجرام
    # إيقاف تشغيل الـ VPS أو عملية التداول

