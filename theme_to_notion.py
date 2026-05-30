"""
네이버 금융 테마 → 노션 자동 업데이트
매일 오전 10시, 오후 3시 실행
"""

import os
import requests
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
NOTION_TOKEN  = os.environ.get("NOTION_TOKEN", "")
THEME_DB_ID   = os.environ.get("NOTION_THEME_DB_ID", "")

HEADERS_NOTION = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

HEADERS_WEB = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

# ─────────────────────────────────────────
# 네이버 금융 테마 크롤링
# ─────────────────────────────────────────
def get_naver_themes() -> list:
    """네이버 금융 테마 목록 + 등락률 + 거래대금 수집"""
    url = "https://finance.naver.com/sise/theme.naver"
    results = []

    try:
        res = requests.get(url, headers=HEADERS_WEB, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        table = soup.select_one("table.type_1")
        if not table:
            print("테마 테이블을 찾을 수 없음")
            return []

        rows = table.select("tr")
        for row in rows:
            cols = row.select("td")
            if len(cols) < 4:
                continue
            try:
                name      = cols[0].get_text(strip=True)
                change    = cols[1].get_text(strip=True)
                trade_val = cols[3].get_text(strip=True)

                if not name or name == "테마":
                    continue

                # 등락률 숫자 변환
                change_clean = change.replace("%", "").replace("+", "").replace(",", "").strip()
                if not change_clean or change_clean == "-":
                    continue
                change_float = float(change_clean)

                results.append({
                    "theme": name,
                    "change_pct": round(change_float, 2),
                    "trade_value": trade_val if trade_val else "-",
                    "link": cols[0].select_one("a")["href"] if cols[0].select_one("a") else "",
                })
            except Exception as e:
                continue

        results.sort(key=lambda x: x["change_pct"], reverse=True)
        print(f"  총 {len(results)}개 테마 수집 완료")
        return results

    except Exception as e:
        print(f"  테마 수집 실패: {e}")
        return []


def get_theme_stocks(link: str, top_n: int = 5) -> str:
    """테마 상세 페이지에서 상위 종목 수집"""
    if not link:
        return "-"
    try:
        url = f"https://finance.naver.com{link}"
        res = requests.get(url, headers=HEADERS_WEB, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        rows = soup.select("table.type_1 tr")
        stocks = []
        for row in rows:
            cols = row.select("td")
            if len(cols) < 3:
                continue
            try:
                name   = cols[0].get_text(strip=True)
                change = cols[2].get_text(strip=True).replace("%", "").replace("+", "").strip()
                if not name or not change or change == "-":
                    continue
                stocks.append((name, float(change)))
            except:
                continue

        stocks.sort(key=lambda x: x[1], reverse=True)
        return ", ".join([f"{n}({c:+.1f}%)" for n, c in stocks[:top_n]]) or "-"

    except Exception as e:
        print(f"  종목 수집 실패: {e}")
        return "-"


# ─────────────────────────────────────────
# 노션 API
# ─────────────────────────────────────────
def notion_query(db_id: str, label: str) -> list:
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    payload = {"filter": {"property": "날짜", "rich_text": {"equals": label}}}
    try:
        res = requests.post(url, headers=HEADERS_NOTION, json=payload, timeout=10)
        return res.json().get("results", [])
    except:
        return []

def notion_delete(page_id: str):
    try:
        requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS_NOTION,
            json={"archived": True},
            timeout=10,
        )
    except:
        pass

def notion_create(db_id: str, label: str, rank: int, theme: dict, stocks_str: str, tag: str):
    url = "https://api.notion.com/v1/pages"
    props = {
        "테마명":      {"title":     [{"text": {"content": theme["theme"]}}]},
        "날짜":        {"rich_text": [{"text": {"content": label}}]},
        "순위":        {"number":    rank},
        "상승률(%)":   {"number":    theme["change_pct"]},
        "거래대금":    {"rich_text": [{"text": {"content": theme["trade_value"]}}]},
        "구성종목":    {"rich_text": [{"text": {"content": stocks_str}}]},
        "구분":        {"select":    {"name": tag}},
    }
    try:
        res = requests.post(
            url,
            headers=HEADERS_NOTION,
            json={"parent": {"database_id": db_id}, "properties": props},
            timeout=10,
        )
        if res.status_code not in (200, 201):
            print(f"  노션 오류 {res.status_code}: {res.text[:100]}")
    except Exception as e:
        print(f"  노션 전송 실패: {e}")


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def get_time_slot():
    hour = datetime.utcnow().hour + 9
    if hour >= 24:
        hour -= 24
    return "오전 10시" if hour < 13 else "오후 3시"

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

    # 기존 같은 슬롯 데이터 삭제
    for page in notion_query(THEME_DB_ID, label):
        notion_delete(page["id"])

    # 상위 15개 테마 저장
    top_themes = themes[:15]
    for rank, theme in enumerate(top_themes, 1):
        print(f"  [{rank}위] {theme['theme']} {theme['change_pct']:+.2f}% | {theme['trade_value']}")
        stocks_str = get_theme_stocks(theme["link"], top_n=5)
        notion_create(THEME_DB_ID, label, rank, theme, stocks_str, "일간")
        time.sleep(0.5)

    print(f"\n✅ 완료! {len(top_themes)}개 테마 업데이트")

if __name__ == "__main__":
    main()
