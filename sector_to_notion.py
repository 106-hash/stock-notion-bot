"""
한국 주식 업종 섹터 → 노션 자동 업데이트
pykrx로 실제 업종 코드를 동적으로 가져와서 사용
"""

import os
import json
import subprocess
import time
from datetime import datetime, timedelta
from pykrx import stock

NOTION_TOKEN  = os.environ.get("NOTION_TOKEN", "")
DAILY_DB_ID   = os.environ.get("NOTION_DAILY_DB_ID", "")
WEEKLY_DB_ID  = os.environ.get("NOTION_WEEKLY_DB_ID", "")
MONTHLY_DB_ID = os.environ.get("NOTION_MONTHLY_DB_ID", "")

# ─────────────────────────────────────────
# 노션 API (curl)
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
        "섹터명":       {"title":     [{"text": {"content": sector["sector"]}}]},
        "날짜":         {"rich_text": [{"text": {"content": label}}]},
        "순위":         {"number":    rank},
        "상승률(%)":    {"number":    sector["change_pct"]},
        "거래대금(억)": {"number":    sector["trade_value_bn"]},
        "관련종목":     {"rich_text": [{"text": {"content": stocks_str}}]},
        "구분":         {"select":    {"name": tag}},
    }
    res = notion_curl("POST", "/v1/pages", {"parent": {"database_id": db_id}, "properties": props})
    if res.get("object") == "error":
        print(f"  노션 오류: {res.get('message', '')}")

# ─────────────────────────────────────────
# pykrx 데이터 수집
# ─────────────────────────────────────────
def get_recent_trading_date():
    """가장 최근 거래일 반환"""
    today = datetime.now()
    for i in range(7):
        d = today - timedelta(days=i)
        if d.weekday() < 5:  # 월~금
            return d.strftime("%Y%m%d")
    return today.strftime("%Y%m%d")

def get_sector_data(date_str: str) -> list:
    """pykrx로 KOSPI + KOSDAQ 업종 데이터 수집"""
    results = []

    for market in ["KOSPI", "KOSDAQ"]:
        try:
            print(f"  [{market}] 업종 코드 조회 중...")
            tickers = stock.get_index_ticker_list(market=market)
            print(f"  [{market}] {len(tickers)}개 인덱스 발견")

            for ticker in tickers:
                try:
                    name = stock.get_index_ticker_name(ticker)
                    df = stock.get_index_ohlcv(date_str, date_str, ticker)

                    if df is None or df.empty:
                        continue

                    # 컬럼 확인 후 데이터 추출
                    cols = df.columns.tolist()
                    row = df.iloc[-1]

                    # 등락률 컬럼 찾기
                    chg = 0.0
                    for col in ["등락률", "변동률", "수익률"]:
                        if col in cols:
                            chg = float(row[col])
                            break

                    # 거래대금 컬럼 찾기
                    trade = 0.0
                    for col in ["거래대금", "거래량"]:
                        if col in cols:
                            val = float(row[col])
                            trade = round(val / 1e8, 1) if col == "거래대금" else round(val / 1e6, 1)
                            break

                    results.append({
                        "sector": f"[{market}] {name}",
                        "change_pct": round(chg, 2),
                        "trade_value_bn": trade,
                    })
                    time.sleep(0.2)

                except Exception as e:
                    continue

        except Exception as e:
            print(f"  [{market}] 실패: {e}")

    results.sort(key=lambda x: x["change_pct"], reverse=True)
    print(f"  총 {len(results)}개 업종 수집 완료")
    return results

# ─────────────────────────────────────────
# 날짜 유틸
# ─────────────────────────────────────────
def get_time_slot():
    hour = (datetime.utcnow().hour + 9) % 24
    return "오전 10시" if hour < 13 else "오후 3시"

def get_week_label():
    now = datetime.now()
    return f"{now.year}-W{now.isocalendar()[1]:02d}"

def get_month_label():
    return datetime.now().strftime("%Y-%m")

def clear_and_upload(db_id, label, sectors, tag):
    for page in notion_query(db_id, label):
        notion_delete(page["id"])
    for rank, s in enumerate(sectors[:10], 1):
        print(f"  [{rank}위] {s['sector']} {s['change_pct']:+.2f}% | {s['trade_value_bn']}억")
        notion_send(db_id, label, rank, s, "-", tag)
        time.sleep(0.4)

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    now    = datetime.now()
    today  = get_recent_trading_date()
    slot   = get_time_slot()
    d_label = f"{today[:4]}-{today[4:6]}-{today[6:]} ({slot})"
    w_label = get_week_label()
    m_label = get_month_label()

    print(f"\n오늘: {today} / 슬롯: {slot}")

    sectors = get_sector_data(today)

    if not sectors:
        print("업종 데이터 없음. 종료.")
        return

    print(f"\n{'='*50}\n[일간] {d_label}\n{'='*50}")
    clear_and_upload(DAILY_DB_ID, d_label, sectors, "일간")

    print(f"\n{'='*50}\n[주간] {w_label}\n{'='*50}")
    clear_and_upload(WEEKLY_DB_ID, w_label, sectors, "주간")

    print(f"\n{'='*50}\n[월간] {m_label}\n{'='*50}")
    clear_and_upload(MONTHLY_DB_ID, m_label, sectors, "월간")

    print("\n✅ 완료!")

if __name__ == "__main__":
    main()
