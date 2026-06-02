"""네이버 모바일 API URL 탐색 스크립트"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json, text/plain, */*",
}

urls = [
    "https://m.stock.naver.com/api/index/domestic/group",
    "https://m.stock.naver.com/api/index/domestic/industryGroup",
    "https://m.stock.naver.com/api/index/kospi/industryGroup",
    "https://m.stock.naver.com/api/index/kospi/group",
    "https://m.stock.naver.com/api/stocks/industryGroup",
    "https://m.stock.naver.com/api/stocks/industry",
    "https://m.stock.naver.com/api/index/domestic/groups",
    "https://m.stock.naver.com/domestic/index/KOSPI/industryGroup",
]

for url in urls:
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        ct = res.headers.get("Content-Type", "")
        print(f"[{res.status_code}] {url}")
        if res.status_code == 200:
            print(f"  내용(100자): {res.text[:100]}")
    except Exception as e:
        print(f"[ERR] {url}")
