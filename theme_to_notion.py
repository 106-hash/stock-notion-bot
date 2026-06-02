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
                # 거래대금 단위 추가 (네이버는 억원 단위)
                try:
                    trade_num = float(trade_val.replace(",","").strip())
                    if trade_num >= 10000:
                        trade_str = f"{trade_num/10000:.1f}조"
                    else:
                        trade_str = f"{trade_num:.0f}억"
                except:
                    trade_str = trade_val or "-"
                results.append({
                    "theme":       name,
                    "change_pct":  round(change_f, 2),
                    "trade_value": trade_str,
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
        # type_5 테이블만 탐색 (네이버 종목 리스트 전용 클래스)
        for table in soup.select("table.type_5"):
            for row in table.select("tr"):
                cols = row.select("td")
                if len(cols) < 4:
                    continue
                try:
                    name = cols[0].get_text(strip=True)
                    # 종목명 엄격 필터: 2~10자, 숫자로 시작 안함, 헤더 제외
                    skip_words = ["종목명", "현재가", "전일비", "등락률", "거래량", "거래대금"]
                    if not name or name in skip_words:
                        continue
                    if not (1 < len(name) <= 10):
                        continue
                    if name[0].isdigit():
                        continue

                    # 등락률은 cols[2] 또는 %가 있는 셀에서 추출
                    chg_text = ""
                    for col in cols[1:5]:
                        txt = col.get_text(strip=True)
                        if "%" in txt and len(txt) < 10:
                            chg_text = txt
                            break
                    if not chg_text:
                        continue

                    chg = float(
                        chg_text.replace("%","").replace("+","")
                        .replace(",","").replace("▲","").replace("▼","-")
                        .replace(" ","").strip()
                    )
                    stocks.append((name, chg))
                except:
                    continue

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

def format_trade(val: str) -> str:
    """거래대금 쉼표 포맷 (예: 1554.5 → 1,554.5)"""
    try:
        num = float(str(val).replace(",", ""))
        return f"{num:,.1f}"
    except:
        return str(val)

def notion_send(db_id, label, rank, theme, stocks_str, tag):
    props = {
        "테마명":      {"title":     [{"text": {"content": theme["theme"]}}]},
        "날짜":        {"rich_text": [{"text": {"content": label}}]},
        "순위":        {"number":    rank},
        "상승률(%)":   {"number":    theme["change_pct"]},
        "거래대금":    {"rich_text": [{"text": {"content": format_trade(theme["trade_value"])}}]},
        "구성종목":    {"rich_text": [{"text": {"content": stocks_str}}]},
        "구분":        {"select":    {"name": tag}},
    }
    res = notion_curl("POST", "/v1/pages", {"parent": {"database_id": db_id}, "properties": props})
    if res.get("object") == "error":
        print(f"  노션 오류: {res.get('message', '')}")

def cleanup_old_data(db_id: str, keep_days: int = 5):
    """오래된 테마 데이터 삭제 (최근 5일치 유지)"""
    try:
        res = notion_curl("POST", f"/v1/databases/{db_id}/query", {"page_size": 100})
        pages = res.get("results", [])
        if not pages:
            return

        labels = set()
        for p in pages:
            label = p["properties"].get("날짜", {}).get("rich_text", [{}])
            if label:
                labels.add(label[0].get("plain_text", ""))

        dates = sorted(set([l[:10] for l in labels if l]), reverse=True)
        keep_dates = set(dates[:keep_days])
        delete_count = 0

        for p in pages:
            label = p["properties"].get("날짜", {}).get("rich_text", [{}])
            if label:
                lbl = label[0].get("plain_text", "")
                if lbl[:10] not in keep_dates:
                    notion_delete(p["id"])
                    delete_count += 1
                    time.sleep(0.2)

        if delete_count:
            print(f"  {delete_count}개 오래된 데이터 삭제 완료")
    except Exception as e:
        print(f"  삭제 중 오류: {e}")

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

    cleanup_old_data(THEME_DB_ID, keep_days=5)
    print(f"\n✅ 완료! 15개 테마 업데이트")

if __name__ == "__main__":
    main()
