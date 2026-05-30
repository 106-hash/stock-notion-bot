"""
한국 주식 주도섹터 → 노션 자동 업데이트
pykrx 최신 버전 기준으로 작성
"""

import os
import requests
import time
from datetime import datetime, timedelta
from pykrx import stock

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────
NOTION_TOKEN  = os.environ.get("NOTION_TOKEN", "")
DAILY_DB_ID   = os.environ.get("NOTION_DAILY_DB_ID", "")
WEEKLY_DB_ID  = os.environ.get("NOTION_WEEKLY_DB_ID", "")
MONTHLY_DB_ID = os.environ.get("NOTION_MONTHLY_DB_ID", "")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ─────────────────────────────────────────
# KRX 업종 인덱스 코드 (pykrx 최신 기준)
# ─────────────────────────────────────────
SECTOR_CODES = {
    "음식료품":   "1001",
    "섬유의복":   "1002",
    "종이목재":   "1003",
    "화학":       "1004",
    "의약품":     "1005",
    "비금속광물": "1006",
    "철강금속":   "1007",
    "기계":       "1008",
    "전기전자":   "1009",
    "의료정밀":   "1010",
    "운수장비":   "1011",
    "유통업":     "1012",
    "전기가스업": "1013",
    "건설업":     "1014",
    "운수창고":   "1015",
    "통신업":     "1016",
    "금융업":     "1017",
    "은행":       "1018",
    "증권":       "1019",
    "보험":       "1020",
    "서비스업":   "1021",
}

# ─────────────────────────────────────────
# 날짜 유틸
# ─────────────────────────────────────────
def get_today_str():
    today = datetime.now()
    if today.weekday() == 5:
        today -= timedelta(days=1)
    elif today.weekday() == 6:
        today -= timedelta(days=2)
    return today.strftime("%Y%m%d")

def get_week_range():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y%m%d"), today.strftime("%Y%m%d")

def get_month_range():
    today = datetime.now()
    return today.replace(day=1).strftime("%Y%m%d"), today.strftime("%Y%m%d")

def get_time_slot():
    hour = datetime.utcnow().hour + 9
    if hour >= 24:
        hour -= 24
    return "오전 10시" if hour < 13 else "오후 3시"

# ─────────────────────────────────────────
# 데이터 수집
# ─────────────────────────────────────────
def get_sector_data(start: str, end: str) -> list:
    results = []
    for name, code in SECTOR_CODES.items():
        try:
            df = stock.get_index_ohlcv(start, end, code)
            if df is None or df.empty:
                continue
            open_p  = df["시가"].iloc[0]
            close_p = df["종가"].iloc[-1]
            trade   = df["거래대금"].sum() / 1e8
            if open_p == 0:
                continue
            change = round((close_p - open_p) / open_p * 100, 2)
            results.append({
                "sector": name,
                "change_pct": change,
                "trade_value_bn": round(float(trade), 1),
            })
            time.sleep(0.3)
        except Exception as e:
            print(f"  [{name}] 실패: {e}")
    results.sort(key=lambda x: x["change_pct"], reverse=True)
    return results

def get_top_stocks(sector_name: str, date_str: str, top_n: int = 5) -> str:
    try:
        code = SECTOR_CODES.get(sector_name)
        if not code:
            return "-"
        tickers = stock.get_index_portfolio_deposit_file(code)
        if tickers is None or len(tickers) == 0:
            return "-"
        items = []
        for ticker in list(tickers)[:15]:
            try:
                df = stock.get_market_ohlcv(date_str, date_str, ticker)
                if df is None or df.empty:
                    continue
                chg  = df["등락률"].iloc[-1]
                nm   = stock.get_market_ticker_name(ticker)
                items.append((nm, round(float(chg), 2)))
                time.sleep(0.1)
            except:
                continue
        items.sort(key=lambda x: x[1], reverse=True)
        return ", ".join([f"{n}({c:+.1f}%)" for n, c in items[:top_n]]) or "-"
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
        res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        return res.json().get("results", [])
    except Exception as e:
        print(f"  쿼리 실패: {e}")
        return []

def notion_delete(page_id: str):
    try:
        requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS,
            json={"archived": True},
            timeout=10,
        )
    except:
        pass

def notion_create(db_id: str, label: str, rank: int, sector: dict, stocks_str: str, tag: str):
    url = "https://api.notion.com/v1/pages"
    props = {
        "섹터명":      {"title":     [{"text": {"content": sector["sector"]}}]},
        "날짜":        {"rich_text": [{"text": {"content": label}}]},
        "순위":        {"number":    rank},
        "상승률(%)":   {"number":    sector["change_pct"]},
        "거래대금(억)":{"number":    sector["trade_value_bn"]},
        "관련종목":    {"rich_text": [{"text": {"content": stocks_str}}]},
        "구분":        {"select":    {"name": tag}},
    }
    try:
        res = requests.post(url, headers=HEADERS, json={"parent": {"database_id": db_id}, "properties": props}, timeout=10)
        if res.status_code not in (200, 201):
            print(f"  노션 오류 {res.status_code}: {res.text[:100]}")
    except Exception as e:
        print(f"  노션 전송 실패: {e}")

def clear_and_upload(db_id: str, label: str, sectors: list, tag: str, with_stocks: bool, today: str):
    for page in notion_query(db_id, label):
        notion_delete(page["id"])
    for rank, s in enumerate(sectors[:10], 1):
        stocks_str = get_top_stocks(s["sector"], today, 5) if with_stocks else "-"
        print(f"  [{rank}위] {s['sector']} {s['change_pct']:+.2f}% | {s['trade_value_bn']}억 | {stocks_str}")
        notion_create(db_id, label, rank, s, stocks_str, tag)
        time.sleep(0.4)

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    today   = get_today_str()
    slot    = get_time_slot()
    now     = datetime.now()
    d_label = f"{today[:4]}-{today[4:6]}-{today[6:]} ({slot})"
    w_label = f"{now.year}-W{now.isocalendar()[1]:02d}"
    m_label = now.strftime("%Y-%m")

    print(f"\n오늘: {today} / 슬롯: {slot}")

    # 일간
    print(f"\n{'='*50}\n[일간] {d_label}\n{'='*50}")
    daily = get_sector_data(today, today)
    if daily:
        clear_and_upload(DAILY_DB_ID, d_label, daily, "일간", True, today)
    else:
        print("일간 데이터 없음")

    # 주간
    ws, we = get_week_range()
    print(f"\n{'='*50}\n[주간] {w_label} ({ws}~{we})\n{'='*50}")
    weekly = get_sector_data(ws, we)
    if weekly:
        clear_and_upload(WEEKLY_DB_ID, w_label, weekly, "주간", False, today)
    else:
        print("주간 데이터 없음")

    # 월간
    ms, me = get_month_range()
    print(f"\n{'='*50}\n[월간] {m_label} ({ms}~{me})\n{'='*50}")
    monthly = get_sector_data(ms, me)
    if monthly:
        clear_and_upload(MONTHLY_DB_ID, m_label, monthly, "월간", False, today)
    else:
        print("월간 데이터 없음")

    print("\n✅ 완료!")

if __name__ == "__main__":
    main()
