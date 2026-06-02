"""
네이버 모바일 API → 노션 업종 섹터 자동 업데이트
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json, text/plain, */*",
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
        "상승률":    {"number":    sector["change_pct"]},
        "거래대금(억)": {"number":    sector["trade_value_bn"]},
        "관련종목":     {"rich_text": [{"text": {"content": "-"}}]},
        "구분":         {"select":    {"name": tag}},
    }
    res = notion_curl("POST", "/v1/pages", {"parent": {"database_id": db_id}, "properties": props})
    if res.get("object") == "error":
        print(f"  노션 오류: {res.get('message', '')}")

# ─────────────────────────────────────────
# 네이버 모바일 API로 업종 데이터 수집
# ─────────────────────────────────────────
def get_all_sectors() -> list:
    """네이버 모바일 API로 전체 업종 수집"""
    url = "https://m.stock.naver.com/api/stocks/industry"
    results = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        print(f"  상태: {res.status_code}")

        if res.status_code != 200:
            print(f"  실패: {res.status_code}")
            return []

        data = res.json()
        groups = data.get("groups", [])
        print(f"  {len(groups)}개 업종 발견")

        for group in groups:
            try:
                name  = group.get("name", "")
                chg   = float(group.get("changeRate", 0))

                # 거래대금 필드 탐색
                trade_raw = (
                    group.get("tradingValue") or
                    group.get("accumulatedTradingValue") or
                    group.get("accTradingValue") or
                    group.get("tradePrice") or 0
                )
                trade    = float(trade_raw)
                trade_bn = round(trade / 1e8, 1)

                # 디버그: 첫 번째 항목 필드 출력
                if name == groups[0].get("name", ""):
                    print(f"  [디버그] 첫 항목 키: {list(group.keys())}")

                if not name:
                    continue

                results.append({
                    "sector":         name,
                    "change_pct":     round(chg, 2),
                    "trade_value_bn": trade_bn,
                })
            except:
                continue

    except Exception as e:
        print(f"  실패: {e}")

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
        notion_send(db_id, label, rank, s, tag)
        time.sleep(0.4)

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    today   = datetime.now().strftime("%Y%m%d")
    slot    = get_time_slot()
    d_label = f"{today[:4]}-{today[4:6]}-{today[6:]} ({slot})"
    w_label = get_week_label()
    m_label = get_month_label()

    print(f"\n오늘: {today} / 슬롯: {slot}")

    sectors = get_all_sectors()

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
