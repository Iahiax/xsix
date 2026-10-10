import requests
import json
from core.config import CONFIG

SESSION_DATA = {"cst": None, "xst": None}

def login():
    """تسجيل الدخول والحصول على توكنات الجلسة"""
    url = f"{CONFIG['capital']['server']}/api/v1/session"
    payload = {
        "identifier": CONFIG['capital']['email'],
        "password": CONFIG['capital']['password'],
        "encryptedPassword": False
    }
    headers = {
        "X-CAP-API-KEY": CONFIG['capital']['api_key'],
        "Content-Type": "application/json"
    }
    r = requests.post(url, headers=headers, data=json.dumps(payload))
    if r.status_code == 200:
        SESSION_DATA["cst"] = r.headers.get("CST")
        SESSION_DATA["xst"] = r.headers.get("X-SECURITY-TOKEN")
        return True
    return False

def get_auth_headers():
    return {
        "CST": SESSION_DATA["cst"],
        "X-SECURITY-TOKEN": SESSION_DATA["xst"],
        "Content-Type": "application/json",
        "X-CAP-API-KEY": CONFIG['capital']['api_key']
    }

def place_order(symbol: str, side: str, size: float):
    """تنفيذ الصفقة مع فحص المخاطر أولاً"""
    from engines import risk_engine
    
    # فحص قاطع الدائرة
    if not risk_engine.check_circuit_breaker(0, 10000): # أرقام افتراضية للتوضيح
        return {"error": "Circuit Breaker Activated. Trading Halted."}
    
    headers = get_auth_headers()
    url = f"{CONFIG['capital']['server']}/api/v1/positions/otc"
    
    payload = {
        "epic": symbol,
        "expiry": "DFB",
        "direction": side,
        "size": size,
        "level": None, # Market Order
        "orderType": "MARKET",
        "timeInForce": "EXECUTE_AND_ELIMINATE",
        "forceOpen": "true"
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    return response.json()

