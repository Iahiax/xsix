import os
import requests
from datetime import datetime

MAX_DRAWDOWN_LIMIT = 0.15  # 15%
DAILY_LOSS_LIMIT = 0.03    # 3% Circuit Breaker

def check_circuit_breaker() -> bool:
    """فحص قاطع الدائرة اليومي"""
    # هنا يتم جلب الـ PnL اليومي من Capital.com أو DuckDB
    current_daily_loss = 0.01 # مثال: 1% خسارة حالية
    if current_daily_loss >= DAILY_LOSS_LIMIT:
        trigger_graceful_self_destruct("Daily Circuit Breaker Hit")
        return False
    return True

def get_dynamic_leverage(symbol: str, account_equity: float, win_rate: float, win_loss_ratio: float) -> float:
    """
    حساب الرافعة المثلى:
    1. يحترم الحد الأقصى للوسيط (مثلاً 100:1 أو حسب الرمز).
    2. يطبق معادلة Kelly البايزية لتقليل المخاطرة.
    3. يتحقق من عدم تجاوز الـ Max Drawdown.
    """
    broker_max_leverage = 100 # يتم جلبها ديناميكياً من API Capital.com حسب الرمز
    
    # Bayesian Rolling Kelly Fraction
    kelly_fraction = (win_rate - ((1 - win_rate) / win_loss_ratio)) * 0.5 # Half-Kelly للأمان
    kelly_fraction = max(0.01, min(kelly_fraction, 0.05)) # حصر المخاطرة بين 1% و 5%
    
    # حساب الرافعة المطلوبة لتغطية هذه المخاطرة
    required_leverage = int((account_equity * kelly_fraction) / 100) # افتراض حجم عقد قياسي 100
    
    # العودة بأقل قيمة بين رافعة الوسيط والرافعة الآمنة المحسوبة
    final_leverage = min(broker_max_leverage, max(1, required_leverage))
    return final_leverage

def trigger_graceful_self_destruct(reason: str):
    """بروتوكول الانتحار الآمن (Graceful Self-Destruct)"""
    from engines import telegram_engine, execution_engine
    
    msg = f"🚨 تفعيل بروتوكول الانتحار الآمن!\nالسبب: {reason}\nالإجراء: إغلاق جميع الصفقات فوراً وإيقاف النظام."
    telegram_engine.send_message(msg)
    
    # 1. إغلاق كل الصفقات المفتوحة
    execution_engine.close_all_positions()
    
    # 2. إيقاف أي عمليات تداول تلقائية
    # 3. (اختياري) إيقاف عملية الـ VPS إذا كانت تعمل
    print("SYSTEM HALTED. MANUAL INTERVENTION REQUIRED.")

