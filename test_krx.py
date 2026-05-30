"""pykrx에서 실제로 사용 가능한 업종 코드 확인"""
from pykrx import stock

# 사용 가능한 인덱스 목록 전체 출력
tickers = stock.get_index_ticker_list(market="KOSPI")
print("KOSPI 인덱스 목록:")
for t in tickers:
    name = stock.get_index_ticker_name(t)
    print(f"  코드: {t} | 이름: {name}")
