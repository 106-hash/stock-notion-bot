"""
네이버 금융 테마 → 노션 자동 업데이트
"""

import os
import json
import requests
import time
from datetime import datetime
from bs4 import BeautifulSoup

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
THEME_DB_ID  = os.environ.get("NOTION_THEME_DB_ID", "")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
}

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

def get_time_slot():
    hour = (datetime.utcnow().hour + 9) % 24
    return "오전 10시" if hour < 13 else "오후 3시"

def get_naver_themes():
    url = "https://finance.naver.com/sise/theme.naver"
    results = []
    try:
        res = requests.get(url, headers=WEB_HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.select_one("table.type_1")
        if not table:
            return []
        for row in table.select("tr"):
            cols = row.select("td")
            if len(cols) < 4:
                continue
            try:
                name      = cols[0].get_text(strip=True)
                change    = cols[1].get_text(strip=True)
                trade_val = cols[3].get_text(strip=True)
                if not name or name == "테마":
                    continue
                change_f = float(change.replace("%","").replace("+","").replace(",","").strip())
                link = cols[0].select_one("a")
                results.append({
                    "theme":       name,
                    "change_pct":  round(change_f, 2),
                    "trade_value": trade_val or "-",
                    "link":        link["href"] if link else "",
                })
            except:
                continue
        results.sort(key=lambda x: x["change_pct"], reverse=True)
        print(f"  총 {len(results)}개 테마 수집 완료")
    except Exception as e:
        print(f"  테마 수집 실패: {e}")
    return results

def get_theme_stocks(link, top_n=5):
    if not link:
        return "-"
    try:
        res = requests.get(f"https://finance.naver.com{link}", headers=WEB_HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        stocks = []
        for row in soup.select("table.type_1 tr"):
            cols = row.select("td")
            if len(cols) < 3:
                continue
            try:
                name   = cols[0].get_text(strip=True)
                change = cols[2].get_text(strip=True).replace("%","").replace("+","").strip()
                if name and change and change != "-":
                    stocks.append((name, float(change)))
            except:
                continue
        stocks.sort(key=lambda x: x[1], reverse=True)
        return ", ".join([f"{n}({c:+.1f}%)" for n, c in stocks[:top_n]]) or "-"
    except:
        return "-"

def notion_send(db_id, label, rank, theme, stocks_str, tag):
    props = {
        "테마명":      {"title":     [{"text": {"content": theme["theme"]}}]},
        "날짜":        {"rich_text": [{"text": {"content": label}}]},
        "순위":        {"number":    rank},
        "상승률(%)":   {"number":    theme["change_pct"]},
        "거래대금":    {"rich_text": [{"text": {"content": theme["trade_value"]}}]},
        "구성종목":    {"rich_text": [{"text": {"content": stocks_str}}]},
        "구분":        {"select":    {"name": tag}},
    }
    payload = {"parent": {"database_id": db_id}, "properties": props}
    # ensure_ascii=False + utf-8 인코딩으로 한글 처리
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {**NOTION_HEADERS, "Content-Type": "application/json; charset=utf-8"}
    try:
        res = requests.post("https://api.notion.com/v1/pages", headers=headers, data=body, timeout=10)
        if res.status_code not in (200, 201):
            print(f"  노션 오류 {res.status_code}: {res.text[:100]}")
    except Exception as e:
        print(f"  전송 실패: {e}")

def notion_query(db_id, label):
    payload = {"filter": {"property": "날짜", "rich_text": {"equals": label}}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {**NOTION_HEADERS, "Content-Type": "application/json; charset=utf-8"}
    try:
        res = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=headers, data=body, timeout=10)
        return res.json().get("results", [])
    except:
        return []

def notion_delete(page_id):
    body = json.dumps({"archived": True}, ensure_ascii=False).encode("utf-8")
    headers = {**NOTION_HEADERS, "Content-Type": "application/json; charset=utf-8"}
    try:
        requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=headers, data=body, timeout=10)
    except:
        pass

def main():
    now   = datetime.now()
    today = now.strftime("%Y%m%d")
    slot  = get_time_slot()
    label = f"{today[:4]}-{today[4:6]}-{today[6:]} ({slot})"

    print(f"\n{'='*50}")
    print(f"[테마] {label} 업데이트 시작")
    print('='*50)

    themes = get_naver_themes()
    if not themes:
        print("테마 데이터 없음. 종료.")
        return

    for page in notion_query(THEME_DB_ID, label):
        notion_delete(page["id"])

    for rank, theme in enumerate(themes[:15], 1):
        print(f"  [{rank}위] {theme['theme']} {theme['change_pct']:+.2f}% | {theme['trade_value']}")
        stocks_str = get_theme_stocks(theme["link"], top_n=5)
        notion_send(THEME_DB_ID, label, rank, theme, stocks_str, "일간")
        time.sleep(0.5)

    print(f"\n✅ 완료! 15개 테마 업데이트")

if __name__ == "__main__":
    main()
