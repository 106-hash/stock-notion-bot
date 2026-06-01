"""
네이버 금융 테마 → 노션 자동 업데이트
"""

import os
import json
import subprocess
import time
from datetime import datetime
from bs4 import BeautifulSoup
import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
THEME_DB_ID  = os.environ.get("NOTION_THEME_DB_ID", "")

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

def notion_curl(method, path, payload=None):
    url = f"https://api.notion.com{path}"
    body = json.dumps(payload, ensure_ascii=False) if payload else "{}"
    cmd = [
        "curl", "-s", "-X", method, url,
        "-H", f"Authorization: Bearer {NOTION_TOKEN}",
        "-H", "Notion-Version: 2022-06-28",
        "-H", "Content-Type: application/json",
        "--data-binary", "@-"
    ]
    try:
        result = subprocess.run(cmd, input=body.encode("utf-8"), capture_output=True, timeout=15)
        return json.loads(result.stdout.decode("utf-8"))
    except Exception as e:
        print(f"  curl 오류: {e}")
        return {}

def get_time_slot():
    hour = (datetime.utcnow().hour + 9) % 24
    return "오전 10시" if hour < 13 else "오후 3시"

def get_naver_themes():
    results = []
    try:
        res = requests.get("https://finance.naver.com/sise/theme.naver", headers=WEB_HEADERS, timeout=10)
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
    """테마 상세페이지에서 구성종목 + 등락률 수집"""
    if not link:
        return "-"
    try:
        res = requests.get(f"https://finance.naver.com{link}", headers=WEB_HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        stocks = []
        # 종목 테이블: class="type_5" 또는 "type_2"
        for table in soup.select("table.type_5, table.type_2, table"):
            for row in table.select("tr"):
                cols = row.select("td")
                if len(cols) < 2:
                    continue
                try:
                    name = cols[0].get_text(strip=True)
                    # 등락률 찾기 (% 포함된 셀)
                    chg_text = ""
                    for col in cols[1:]:
                        txt = col.get_text(strip=True)
                        if "%" in txt:
                            chg_text = txt
                            break
                    if not name or not chg_text:
                        continue
                    chg = float(chg_text.replace("%","").replace("+","").replace(",","").replace("▲","").replace("▼","-").strip())
                    # 종목명 필터: 한글/영문 포함, 너무 길지 않은 것
                    if 1 < len(name) < 15 and not name.startswith("종목"):
                        stocks.append((name, chg))
                except:
                    continue
            if stocks:
                break

        stocks.sort(key=lambda x: x[1], reverse=True)
        top = stocks[:top_n]
        return ", ".join([f"{n}({c:+.1f}%)" for n, c in top]) if top else "-"
    except Exception as e:
        return "-"

def notion_query(db_id, label):
    res = notion_curl("POST", f"/v1/databases/{db_id}/query",
        {"filter": {"property": "날짜", "rich_text": {"equals": label}}})
    return res.get("results", [])

def notion_delete(page_id):
    notion_curl("PATCH", f"/v1/pages/{page_id}", {"archived": True})

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
    res = notion_curl("POST", "/v1/pages", {"parent": {"database_id": db_id}, "properties": props})
    if res.get("object") == "error":
        print(f"  노션 오류: {res.get('message', '')}")

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
        stocks_str = get_theme_stocks(theme["link"], top_n=5)
        print(f"  [{rank}위] {theme['theme']} {theme['change_pct']:+.2f}% | {stocks_str}")
        notion_send(THEME_DB_ID, label, rank, theme, stocks_str, "일간")
        time.sleep(0.5)

    print(f"\n✅ 완료! 15개 테마 업데이트")

if __name__ == "__main__":
    main()
