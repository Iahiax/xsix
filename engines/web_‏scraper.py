import requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode

class GoogleScraper:
    def __init__(self, lang="ar", country="sa", timeout=10):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        })
        self.lang = lang
        self.country = country
        self.timeout = timeout

    def search(self, query: str, num: int = 10):
        params = {"q": query, "num": num, "hl": self.lang, "gl": self.country}
        url = f"https://www.google.com/search?{urlencode(params)}"
        resp = self.session.get(url, timeout=self.timeout)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        results = []
        for g in soup.select("div.g"):
            title_el = g.select_one("h3")
            link_el = g.select_one("a")
            snippet_el = g.select_one("div.VwiC3b")
            if link_el and title_el:
                results.append({
                    "title": title_el.get_text(strip=True),
                    "link": link_el.get("href"),
                    "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else ""
                })
        return results

def dark_web_search(query: str, engine="onionland"):
    """البحث في الويب المظلم عبر شبكة Tor المدمجة في Kali Linux"""
    proxies = {'http': 'socks5h://127.0.0.1:9050', 'https': 'socks5h://127.0.0.1:9050'}
    try:
        if engine == "onionland":
            url = "https://onionlandsearchengine.com/search"
            resp = requests.get(url, params={"q": query}, proxies=proxies, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            return [{"title": i.select_one(".title").get_text(strip=True) if i.select_one(".title") else "",
                     "link": i.select_one("a")["href"] if i.select_one("a") else ""} 
                    for i in soup.select(".result")[:5]]
        elif engine == "ahmia":
            url = "https://ahmia.fi/search/"
            resp = requests.get(url, params={"q": query, "format": "json"}, proxies=proxies, timeout=15)
            return resp.json().get("results", [])[:5]
    except Exception as e:
        return [{"error": f"Tor connection failed: {str(e)}. تأكد من تشغيل 'sudo systemctl start tor' على الـ VPS."}]

