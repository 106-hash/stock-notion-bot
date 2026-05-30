"""
한국 주식 주도섹터 → 노션 자동 업데이트 스크립트
매일 장 마감 후 실행 (GitHub Actions 또는 로컬 스케줄러)
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import FinanceDataReader as fdr
from pykrx import stock
import time

# ─────────────────────────────────────────
# 설정 (환경변수로 관리)
# ─────────────────────────────────────────
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DAILY_DB_ID  = os.environ.get("NOTION_DAILY_DB_ID")
WEEKLY_DB_ID = os.environ.get("NOTION_WEEKLY_DB_ID")
MONTHLY_DB_ID = os.environ.get("NOTION_MONTHLY_DB_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# ─────────────────────────────────────────
# KRX 섹터 코드 매핑 (KOSPI 업종)
# ─────────────────────────────────────────
SECTOR_MAP = {
    "음식료품": "001",
    "섬유의복": "002",
    "종이목재": "003",
    "화학": "004",
    "의약품": "005",
    "비금속광물": "006",
    "철강금속": "007",
    "기계": "008",
    "전기전자": "009",
    "의료정밀": "010",
    "운수장비": "011",
    "유통업": "012",
    "전기가스업": "013",
    "건설업": "014",
    "운수창고": "015",
    "통신업": "016",
    "금융업": "017",
    "은행": "018",
    "증권": "019",
    "보험": "020",
    "서비스업": "021",
}

# ─────────────────────────────────────────
# 데이터 수집 함수
# ─────────────────────────────────────────

def get_today_str():
    """오늘 날짜 (장 마감 후 실행 기준)"""
    today = datetime.now()
    # 토/일이면 금요일로
    if today.weekday() == 5:
        today -= timedelta(days=1)
    elif today.weekday() == 6:
        today -= timedelta(days=2)
    return today.strftime("%Y%m%d")


def get_sector_data(date_str: str) -> list[dict]:
    """pykrx로 KOSPI 업종별 등락률 + 거래대금 수집"""
    print(f"[{date_str}] 섹터 데이터 수집 중...")
    sectors = []

    for sector_name, sector_code in SECTOR_MAP.items():
        try:
            # 업종 OHLCV
            df = stock.get_index_ohlcv(date_str, date_str, f"1{sector_code.zfill(3)}")
            if df.empty:
                continue

            row = df.iloc[-1]
            change_pct = row.get("등락률", 0)
            trade_value = row.get("거래대금", 0)  # 원 단위

            sectors.append({
                "sector": sector_name,
                "change_pct": round(float(change_pct), 2),
                "trade_value_bn": round(float(trade_value) / 1e8, 1),  # 억원
            })
            time.sleep(0.3)  # API 과부하 방지

        except Exception as e:
            print(f"  [{sector_name}] 수집 실패: {e}")

    # 상승률 내림차순 정렬
    sectors.sort(key=lambda x: x["change_pct"], reverse=True)
    return sectors


def get_top_stocks_in_sector(sector_name: str, date_str: str, top_n: int = 5) -> str:
    """해당 섹터 상위 종목 이름 리스트 반환"""
    try:
        # pykrx 업종별 종목 시세
        code = SECTOR_MAP.get(sector_name)
        if not code:
            return "-"

        df = stock.get_index_portfolio_deposit_file(f"1{code.zfill(3)}")
        if df.empty:
            return "-"

        tickers = df.index.tolist()[:20]  # 상위 20개만 조회
        results = []

        for ticker in tickers:
            try:
                ohlcv = stock.get_market_ohlcv(date_str, date_str, ticker)
                if ohlcv.empty:
                    continue
                chg = ohlcv["등락률"].iloc[-1]
                name = stock.get_market_ticker_name(ticker)
                results.append((name, round(float(chg), 2)))
                time.sleep(0.1)
            except:
                continue

        results.sort(key=lambda x: x[1], reverse=True)
        top = results[:top_n]
        return ", ".join([f"{n}({c:+.1f}%)" for n, c in top])

    except Exception as e:
        print(f"  종목 수집 실패 [{sector_name}]: {e}")
        return "-"


def get_week_range():
    """이번 주 월~오늘 범위"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def get_month_range():
    """이번 달 1일~오늘"""
    today = datetime.now()
    first = today.replace(day=1)
    return first.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def aggregate_sector_period(start: str, end: str) -> list[dict]:
    """기간 누적 수익률 + 거래대금 합산"""
    print(f"[{start}~{end}] 기간 집계 중...")
    agg = {}

    for sector_name, sector_code in SECTOR_MAP.items():
        try:
            df = stock.get_index_ohlcv(start, end, f"1{sector_code.zfill(3)}")
            if df.empty:
                continue

            # 기간 수익률 = (마지막 종가 / 첫 번째 시가 - 1) * 100
            open_price = df["시가"].iloc[0]
            close_price = df["종가"].iloc[-1]
            period_return = ((close_price - open_price) / open_price) * 100

            total_trade = df["거래대금"].sum() / 1e8  # 억원 합산

            agg[sector_name] = {
                "sector": sector_name,
                "change_pct": round(float(period_return), 2),
                "trade_value_bn": round(float(total_trade), 1),
            }
            time.sleep(0.3)

        except Exception as e:
            print(f"  [{sector_name}] 기간 집계 실패: {e}")

    result = list(agg.values())
    result.sort(key=lambda x: x["change_pct"], reverse=True)
    return result


# ─────────────────────────────────────────
# 노션 API 함수
# ─────────────────────────────────────────

def notion_create_page(database_id: str, properties: dict):
    """노션 DB에 새 페이지(행) 생성"""
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }
    res = requests.post(url, headers=HEADERS, json=payload)
    if res.status_code not in (200, 201):
        print(f"  노션 오류: {res.status_code} {res.text[:200]}")
    return res.json()


def notion_query_db(database_id: str, filter_payload: dict = None):
    """노션 DB 쿼리 (중복 체크용)"""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload = {}
    if filter_payload:
        payload["filter"] = filter_payload
    res = requests.post(url, headers=HEADERS, json=payload)
    return res.json().get("results", [])


def notion_delete_page(page_id: str):
    """기존 페이지 삭제 (중복 방지)"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    requests.patch(url, headers=HEADERS, json={"archived": True})


def delete_existing_entries(database_id: str, date_label: str, label_property: str = "날짜"):
    """같은 날짜 기존 데이터 삭제"""
    filter_payload = {
        "property": label_property,
        "rich_text": {"equals": date_label}
    }
    existing = notion_query_db(database_id, filter_payload)
    for page in existing:
        notion_delete_page(page["id"])
    if existing:
        print(f"  기존 {len(existing)}개 삭제 완료")


# ─────────────────────────────────────────
# 노션 Properties 빌더
# ─────────────────────────────────────────

def build_daily_props(date_str: str, rank: int, sector: dict, stocks_str: str) -> dict:
    date_label = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return {
        "섹터명": {"title": [{"text": {"content": sector["sector"]}}]},
        "날짜": {"rich_text": [{"text": {"content": date_label}}]},
        "순위": {"number": rank},
        "상승률(%)": {"number": sector["change_pct"]},
        "거래대금(억)": {"number": sector["trade_value_bn"]},
        "관련종목": {"rich_text": [{"text": {"content": stocks_str}}]},
        "구분": {"select": {"name": "일간"}},
    }


def build_weekly_props(week_label: str, rank: int, sector: dict) -> dict:
    return {
        "섹터명": {"title": [{"text": {"content": sector["sector"]}}]},
        "날짜": {"rich_text": [{"text": {"content": week_label}}]},
        "순위": {"number": rank},
        "상승률(%)": {"number": sector["change_pct"]},
        "거래대금(억)": {"number": sector["trade_value_bn"]},
        "관련종목": {"rich_text": [{"text": {"content": "-"}}]},
        "구분": {"select": {"name": "주간"}},
    }


def build_monthly_props(month_label: str, rank: int, sector: dict) -> dict:
    return {
        "섹터명": {"title": [{"text": {"content": sector["sector"]}}]},
        "날짜": {"rich_text": [{"text": {"content": month_label}}]},
        "순위": {"number": rank},
        "상승률(%)": {"number": sector["change_pct"]},
        "거래대금(억)": {"number": sector["trade_value_bn"]},
        "관련종목": {"rich_text": [{"text": {"content": "-"}}]},
        "구분": {"select": {"name": "월간"}},
    }


# ─────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────

def run_daily():
    today = get_today_str()
    now = datetime.now()
    hour = now.hour + 9  # UTC → KST 변환 (GitHub Actions는 UTC 기준)
    if hour >= 24:
        hour -= 24
    slot = "오전 10시" if hour < 12 else "오후 3시"
    date_label = f"{today[:4]}-{today[4:6]}-{today[6:]}"
    time_label = f"{date_label} ({slot})"

    print(f"\n{'='*50}")
    print(f"[일간] {time_label} 업데이트 시작")
    print('='*50)

    sectors = get_sector_data(today)
    if not sectors:
        print("데이터 없음. 종료.")
        return

    top_sectors = sectors[:10]

    # 같은 슬롯 기존 데이터 삭제 후 재입력
    delete_existing_entries(DAILY_DB_ID, time_label)

    for rank, sector in enumerate(top_sectors, 1):
        print(f"  [{rank}위] {sector['sector']} {sector['change_pct']:+.2f}% | {sector['trade_value_bn']}억")
        stocks_str = get_top_stocks_in_sector(sector["sector"], today, top_n=5)
        props = build_daily_props(today, rank, sector, stocks_str)
        props["날짜"]["rich_text"][0]["text"]["content"] = time_label
        notion_create_page(DAILY_DB_ID, props)
        time.sleep(0.5)

    print(f"[일간] 완료: {len(top_sectors)}개 섹터 업데이트")


def run_weekly():
    start, end = get_week_range()
    today = datetime.now()
    week_num = today.isocalendar()[1]
    week_label = f"{today.year}-W{week_num:02d}"

    print(f"\n{'='*50}")
    print(f"[주간] {week_label} 업데이트 시작")
    print('='*50)

    sectors = aggregate_sector_period(start, end)
    top_sectors = sectors[:10]

    delete_existing_entries(WEEKLY_DB_ID, week_label)

    for rank, sector in enumerate(top_sectors, 1):
        print(f"  [{rank}위] {sector['sector']} {sector['change_pct']:+.2f}%")
        props = build_weekly_props(week_label, rank, sector)
        notion_create_page(WEEKLY_DB_ID, props)
        time.sleep(0.5)

    print(f"[주간] 완료")


def run_monthly():
    start, end = get_month_range()
    today = datetime.now()
    month_label = today.strftime("%Y-%m")

    print(f"\n{'='*50}")
    print(f"[월간] {month_label} 업데이트 시작")
    print('='*50)

    sectors = aggregate_sector_period(start, end)
    top_sectors = sectors[:10]

    delete_existing_entries(MONTHLY_DB_ID, month_label)

    for rank, sector in enumerate(top_sectors, 1):
        print(f"  [{rank}위] {sector['sector']} {sector['change_pct']:+.2f}%")
        props = build_monthly_props(month_label, rank, sector)
        notion_create_page(MONTHLY_DB_ID, props)
        time.sleep(0.5)

    print(f"[월간] 완료")


if __name__ == "__main__":
    run_daily()
    run_weekly()
    run_monthly()
    print("\n✅ 모든 업데이트 완료!")
