from datetime import datetime, timedelta

from tools import (
    FILE_TOOLS,
    STOCK_TOOLS,
    ALL_TOOLS,
    get_current_price,
    get_historical_ohlcv,
    get_financial_metrics,
    get_company_disclosures,
)


def print_title(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


ticker = "AAPL"

today = datetime.now()

start_date = (
    today
    - timedelta(days=30)
).strftime("%Y-%m-%d")

end_date = today.strftime(
    "%Y-%m-%d"
)


print_title(
    "0. Tool 등록 상태"
)

print(
    "FILE_TOOLS:",
    len(FILE_TOOLS),
)

print(
    "STOCK_TOOLS:",
    len(STOCK_TOOLS),
)

print(
    "ALL_TOOLS:",
    len(ALL_TOOLS),
)


print_title(
    "1. 현재 주가 조회"
)

result = get_current_price.invoke(
    {
        "symbol": ticker
    }
)

print(result)


print_title(
    "2. 과거 OHLCV 조회"
)

result = get_historical_ohlcv.invoke(
    {
        "symbol": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "timeframe": "day",
    }
)

print(result)


print_title(
    "3. 재무지표 조회"
)

result = get_financial_metrics.invoke(
    {
        "ticker": ticker,
        "period": "annual",
    }
)

print(result)


print_title(
    "4. 최근 뉴스 조회"
)

result = get_company_disclosures.invoke(
    {
        "ticker": ticker
    }
)

print(result)


print()
print("=" * 70)
print("모든 테스트 완료")
print("=" * 70)
