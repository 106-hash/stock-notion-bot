"""
KRX 공식 REST API → 노션 자동 업데이트
인증 없이 사용 가능한 공개 API
"""

import os
import json
import subprocess
import time
import requests
from datetime import datetime, timedelta

NOTION_TOKEN  = os.environ.get("NOTION_TOKEN", "")
DAILY_DB_ID   = os.environ.get("NOTION_DAILY_DB_ID", "")
WEEKLY_DB_ID  = os.environ.get("NOTION_WEEKLY_DB_ID", "")
MONTHLY_DB_ID = os.environ.get("NOTION_MONTHLY_DB_ID", "")

KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT05001.cmd",
    "Content-Type": "application/x-www-form-urlencoded",
}

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

def notion_send(db_id, label, rank, sector, tag):
    props = {
        "섹터명":       {"title":     [{"text": {"content": sector["sector"]}}]},
        "날짜":         {"rich_text": [{"text": {"content": label}}]},
        "순위":         {"number":    rank},
        "상승률(%)":    {"number":    sector["change_pct"]},
        "거래대금(억)": {"number":    sector["trade_value_bn"]},
        "관련종목":     {"rich_text": [{"text": {"content": "-"}}]},
        "구분":         {"select":    {"name": tag}},
    }
    res = notion_curl("POST", "/v1/pages", {"parent": {"database_id": db_id}, "properties": props})
    if res.get("object") == "error":
        print(f"  노션 오류: {res.get('message', '')}")

# ─────────────────────────────────────────
# KRX REST API 데이터 수집
# ─────────────────────────────────────────
def get_krx_sectors(date_str: str, market: str = "STK") -> list:
    """KRX 공식 API로 업종 지수 수집 (STK=KOSPI, KSQ=KOSDAQ)"""
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    data = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT05001",
        "mktId": market,
        "trdDd": date_str,
        "share": "1",
        "money": "1",
        "csvxls_isNo": "false",
    }
    mkt_name = "KOSPI" if market == "STK" else "KOSDAQ"

    try:
        res = requests.post(url, headers=KRX_HEADERS, data=data, timeout=15)
        if res.status_code != 200:
            print(f"  [{mkt_name}] KRX API 오류: {res.status_code}")
            return []

        result = res.json()
        rows = result.get("OutBlock_1", [])
        if not rows:
            print(f"  [{mkt_name}] 데이터 없음")
            return []

        sectors = []
        for row in rows:
            try:
                name     = row.get("IDX_NM", "").strip()
                chg_rt   = row.get("FLUC_RT", "0").replace(",", "").strip()
                trd_val  = row.get("ACC_TRDVAL", "0").replace(",", "").strip()

                if not name or name in ["업종명", "-"]:
                    continue

                chg  = round(float(chg_rt), 2)
                trade = round(float(trd_val) / 1e8, 1)

                sectors.append({
                    "sector":        f"[{mkt_name}] {name}",
                    "change_pct":    chg,
                    "trade_value_bn": trade,
                })
            except:
                continue

        print(f"  [{mkt_name}] {len(sectors)}개 업종 수집")
        return sectors

    except Exception as e:
        print(f"  [{mkt_name}] 실패: {e}")
        return []

# ─────────────────────────────────────────
# 날짜 유틸
# ─────────────────────────────────────────
def get_recent_trading_date():
    today = datetime.now()
    for i in range(7):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
    return today.strftime("%Y%m%d")

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
        notion_send(db_id, label, rank, s, tag)
        time.sleep(0.4)

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    today   = get_recent_trading_date()
    slot    = get_time_slot()
    d_label = f"{today[:4]}-{today[4:6]}-{today[6:]} ({slot})"
    w_label = get_week_label()
    m_label = get_month_label()

    print(f"\n오늘: {today} / 슬롯: {slot}")

    kospi  = get_krx_sectors(today, "STK")
    kosdaq = get_krx_sectors(today, "KSQ")
    all_sectors = sorted(kospi + kosdaq, key=lambda x: x["change_pct"], reverse=True)

    if not all_sectors:
        print("업종 데이터 없음. 종료.")
        return

    print(f"\n{'='*50}\n[일간] {d_label}\n{'='*50}")
    clear_and_upload(DAILY_DB_ID, d_label, all_sectors, "일간")

    print(f"\n{'='*50}\n[주간] {w_label}\n{'='*50}")
    clear_and_upload(WEEKLY_DB_ID, w_label, all_sectors, "주간")

    print(f"\n{'='*50}\n[월간] {m_label}\n{'='*50}")
    clear_and_upload(MONTHLY_DB_ID, m_label, all_sectors, "월간")

    print("\n✅ 완료!")

if __name__ == "__main__":
    main()
