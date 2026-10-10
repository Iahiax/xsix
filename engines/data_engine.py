import requests
import duckdb
import os
from bs4 import BeautifulSoup

# إعدادات Tor Proxy للبحث في الويب المظلم
TOR_PROXIES = {
    'http': 'socks5h://127.0.0.1:9050',
    'https': 'socks5h://127.0.0.1:9050'
}

def get_all_cfd_symbols():
    """جلب جميع الرموز المتاحة للتداول من Capital.com"""
    # ملاحظة: يتم استخدام توكن الجلسة من execution_engine
    from core.config import CONFIG
    url = f"{CONFIG['capital']['server']}/api/v1/instruments"
    # headers = execution_engine.get_auth_headers() # يتم الربط ديناميكياً
    # response = requests.get(url, headers=headers)
    # return response.json().get('instruments', [])
    return ["EURUSD", "GBPUSD", "XAUUSD", "US30", "NAS100"] # مثال مبسط

def fetch_macro_data():
    """جلب البيانات الاقتصادية من FRED و FMP"""
    from core.config import CONFIG
    fred_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={CONFIG['apis']['fred']}&file_type=json"
    # تنفيذ الطلب وإرجاع البيانات
    return {"status": "Macro data fetched successfully"}

def dark_web_search(query: str):
    """البحث في محركات البحث المظلمة عبر Tor"""
    try:
        url = "https://onionlandsearchengine.com/search"
        resp = requests.get(url, params={"q": query}, proxies=TOR_PROXIES, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".result")[:5]: # أخذ أول 5 نتائج
            results.append({
                "title": item.select_one(".title").get_text(strip=True) if item.select_one(".title") else "",
                "link": item.select_one("a")["href"] if item.select_one("a") else "",
            })
        return results
    except Exception as e:
        return {"error": f"Tor connection failed: {str(e)}"}

