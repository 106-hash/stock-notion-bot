"""
네이버 금융 업종 → 노션 자동 업데이트 (KOSPI/KOSDAQ)
매일 평일 오전 10시, 오후 3시 실행
"""

import os
import json
import subprocess
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import requests

NOTION_TOKEN  = os.environ.get("NOTION_TOKEN", "")
DAILY_DB_ID   = os.environ.get("NOTION_DAILY_DB_ID", "")
WEEKLY_DB_ID  = os.environ.get("NOTION_WEEKLY_DB_ID", "")
MONTHLY_DB_ID = os.environ.get("NOTION_MONTHLY_DB_ID", "")

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

# ─────────────────────────────────────────
# 노션 API (curl 방식)
# ─────────────────────────────────────────
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

def notion_query(db_id, label):
    res = notion_curl("POST", f"/v1/databases/{db_id}/query",
        {"filter": {"property": "날짜", "rich_text": {"equals": label}}})
    return res.get("results", [])

def notion_delete(page_id):
    notion_curl("PATCH", f"/v1/pages/{page_id}", {"archived": True})

def notion_send(db_id, label, rank, sector, stocks_str, tag):
    props = {
        "섹터명":      {"title":     [{"text": {"content": sector["sector"]}}]},
        "날짜":        {"rich_text": [{"text": {"content": label}}]},
        "순위":        {"number":    rank},
        "상승률(%)":   {"number":    sector["change_pct"]},
        "거래대금(억)":{"number":    sector["trade_value_bn"]},
        "관련종목":    {"rich_text": [{"text": {"content": stocks_str}}]},
        "구분":        {"select":    {"name": tag}},
    }
    res = notion_curl("POST", "/v1/pages", {"parent": {"database_id": db_id}, "properties": props})
    if res.get("object") == "error":
        print(f"  노션 오류: {res.get('message', '')}")

# ─────────────────────────────────────────
# 네이버 금융 업종 크롤링
# ─────────────────────────────────────────
def get_naver_sectors(market="KOSPI") -> list:
    """네이버 금융 업종 시세 크롤링"""
    mkt_code = "0" if market == "KOSPI" else "1"
    url = "https://finance.naver.com/sise/sise_sector.naver"
    headers = {
        **WEB_HEADERS,
        "Referer": "https://finance.naver.com/sise/",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    results = []

    try:
        res = requests.get(url, headers=headers, timeout=10, params={"bizType": mkt_code})
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        table = soup.select_one("table.type_1")
        if not table:
            print(f"  [{market}] 테이블 없음 (상태: {res.status_code})")
            return []

        for row in table.select("tr"):
            cols = row.select("td")
            if len(cols) < 5:
                continue
            try:
                name      = cols[0].get_text(strip=True)
                change    = cols[1].get_text(strip=True)
                trade_raw = cols[4].get_text(strip=True).replace(",", "")

                if not name or name in ["업종명", "-"]:
                    continue

                change_f = float(change.replace("%","").replace("+","").replace(",","").strip())

                # 거래대금: 억원 단위
                try:
                    trade_bn = round(float(trade_raw) / 1e8, 1)
                except:
                    trade_bn = 0.0

                results.append({
                    "sector":        f"[{market}] {name}",
                    "change_pct":    round(change_f, 2),
                    "trade_value_bn": trade_bn,
                })
            except:
                continue

        results.sort(key=lambda x: x["change_pct"], reverse=True)
        print(f"  [{market}] {len(results)}개 업종 수집")
        return results

    except Exception as e:
        print(f"  [{market}] 수집 실패: {e}")
        return []


def get_sector_stocks(sector_name: str, market="KOSPI", top_n=5) -> str:
    """업종 상세 페이지에서 상위 종목 수집"""
    # 업종명 추출 ([KOSPI] 제거)
    name = sector_name.replace("[KOSPI] ", "").replace("[KOSDAQ] ", "")
    mkt_code = "1" if market == "KOSPI" else "2"

    try:
        # 업종 검색
        url = f"https://finance.naver.com/sise/sise_sector_stock.naver?bizType={mkt_code}&sector={requests.utils.quote(name)}"
        res = requests.get(url, headers=WEB_HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        stocks = []
        for row in soup.select("table.type_2 tr, table.type_5 tr"):
            cols = row.select("td")
            if len(cols) < 3:
                continue
            try:
                sname = cols[0].get_text(strip=True)
                if not sname or len(sname) > 12 or sname in ["종목명"]:
                    continue
                for col in cols[1:5]:
                    txt = col.get_text(strip=True)
                    if "%" in txt and len(txt) < 10:
                        chg = float(txt.replace("%","").replace("+","").replace(",","").replace("▲","").replace("▼","-").strip())
                        stocks.append((sname, chg))
                        break
            except:
                continue

        stocks.sort(key=lambda x: x[1], reverse=True)
        return ", ".join([f"{n}({c:+.1f}%)" for n, c in stocks[:top_n]]) or "-"

    except:
        return "-"

# ─────────────────────────────────────────
# 날짜 유틸
# ─────────────────────────────────────────
def get_time_slot():
    hour = (datetime.utcnow().hour + 9) % 24
    return "낮 12시" if hour < 15 else "오후 3시"

def get_week_label():
    now = datetime.now()
    return f"{now.year}-W{now.isocalendar()[1]:02d}"

def get_month_label():
    return datetime.now().strftime("%Y-%m")

def clear_and_upload(db_id, label, sectors, tag, with_stocks):
    for page in notion_query(db_id, label):
        notion_delete(page["id"])
    for rank, s in enumerate(sectors[:10], 1):
        market = "KOSPI" if "KOSPI" in s["sector"] else "KOSDAQ"
        stocks_str = get_sector_stocks(s["sector"], market) if with_stocks else "-"
        print(f"  [{rank}위] {s['sector']} {s['change_pct']:+.2f}% | {s['trade_value_bn']}억")
        notion_send(db_id, label, rank, s, stocks_str, tag)
        time.sleep(0.4)

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    now   = datetime.now()
    today = now.strftime("%Y%m%d")
    slot  = get_time_slot()
    d_label = f"{today[:4]}-{today[4:6]}-{today[6:]} ({slot})"
    w_label = get_week_label()
    m_label = get_month_label()

    print(f"\n오늘: {today} / 슬롯: {slot}")

    # KOSPI + KOSDAQ 합산
    kospi  = get_naver_sectors("KOSPI")
    kosdaq = get_naver_sectors("KOSDAQ")
    all_sectors = sorted(kospi + kosdaq, key=lambda x: x["change_pct"], reverse=True)

    if not all_sectors:
        print("업종 데이터 없음. 종료.")
        return

    print(f"\n{'='*50}\n[일간] {d_label}\n{'='*50}")
    clear_and_upload(DAILY_DB_ID, d_label, all_sectors, "일간", True)

    print(f"\n{'='*50}\n[주간] {w_label}\n{'='*50}")
    clear_and_upload(WEEKLY_DB_ID, w_label, all_sectors, "주간", False)

    print(f"\n{'='*50}\n[월간] {m_label}\n{'='*50}")
    clear_and_upload(MONTHLY_DB_ID, m_label, all_sectors, "월간", False)

    print("\n✅ 완료!")

if __name__ == "__main__":
    main()
