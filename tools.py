from langchain.tools import tool

import subprocess
import sys
import os
import json

from datetime import datetime, timedelta
from typing import Dict, List, Union, Optional
from urllib.parse import quote
from urllib.request import urlopen, Request

import pandas as pd
import yfinance as yf


# ============================================================
# 📈 주식 정보 Tool
# ============================================================


@tool(parse_docstring=True)
def get_current_price(symbol: str) -> str:
    """특정 종목의 현재 주가 정보를 조회합니다.

    Args:
        symbol: 주식 종목 코드. 예: AAPL, MSFT, NVDA, TSLA, 005930.KS

    Returns:
        현재가, 전일 종가, 등락률, 거래량 등의 주식 정보
    """

    try:
        symbol = symbol.strip().upper()

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(symbol)}?interval=1d&range=5d"
        )

        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urlopen(req, timeout=10) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        chart = data.get("chart", {})
        result = chart.get("result")

        if not result:
            error = chart.get("error")

            return (
                f"오류: {symbol} 종목 정보를 찾을 수 없습니다.\n"
                f"세부정보: {error}"
            )

        chart_result = result[0]

        meta = chart_result.get("meta", {})

        current_price = meta.get("regularMarketPrice")
        currency = meta.get("currency", "")
        volume = meta.get("regularMarketVolume")

        # Yahoo chart meta에는 previousClose 키가 없다.
        # 5일치 종가 배열의 끝에서 두 번째 값이 전일 종가다.
        closes = (
            chart_result
            .get("indicators", {})
            .get("quote", [{}])[0]
            .get("close", [])
        )

        valid_closes = [
            close
            for close in closes
            if close is not None
        ]

        previous_close = (
            valid_closes[-2]
            if len(valid_closes) >= 2
            else meta.get("chartPreviousClose")
        )

        company_name = (
            meta.get("shortName")
            or meta.get("longName")
            or symbol
        )

        market_time = meta.get("regularMarketTime")

        change = None
        change_rate = None

        if (
            current_price is not None
            and previous_close is not None
            and previous_close != 0
        ):
            change = current_price - previous_close
            change_rate = (
                change / previous_close
            ) * 100

        time_str = "정보 없음"

        if market_time:
            time_str = datetime.fromtimestamp(
                market_time
            ).strftime("%Y-%m-%d %H:%M:%S")

        return (
            f"종목명: {company_name}\n"
            f"종목코드: {symbol}\n"
            f"현재가: {current_price} {currency}\n"
            f"전일 종가: "
            f"{round(previous_close, 2) if previous_close is not None else '정보 없음'} "
            f"{currency}\n"
            f"가격 변동: "
            f"{round(change, 2) if change is not None else '정보 없음'}\n"
            f"등락률: "
            f"{round(change_rate, 2) if change_rate is not None else '정보 없음'}%\n"
            f"거래량: {volume}\n"
            f"기준 시각: {time_str}"
        )

    except Exception as e:

        return (
            f"오류: {symbol} 현재 주가 조회 중 "
            f"문제가 발생했습니다.\n{str(e)}"
        )


@tool(parse_docstring=True)
def get_historical_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "day",
) -> str:
    """특정 종목의 과거 OHLCV 주가 데이터를 조회합니다.

    Args:
        symbol: 주식 종목 코드. 예: AAPL, NVDA, 005930.KS
        start_date: 조회 시작 날짜. YYYY-MM-DD 형식
        end_date: 조회 종료 날짜. YYYY-MM-DD 형식
        timeframe: 조회 간격. day, week, month 중 하나

    Returns:
        날짜별 시가, 고가, 저가, 종가, 거래량 데이터
    """

    try:
        symbol = symbol.strip().upper()

        if timeframe not in {
            "day",
            "week",
            "month",
        }:
            return (
                "오류: timeframe은 "
                "day, week, month 중 하나여야 합니다."
            )

        start_dt = datetime.strptime(
            start_date,
            "%Y-%m-%d",
        )

        end_dt = datetime.strptime(
            end_date,
            "%Y-%m-%d",
        )

        if start_dt >= end_dt:
            return (
                "오류: end_date는 start_date보다 "
                "뒤의 날짜여야 합니다."
            )

        interval_map = {
            "day": "1d",
            "week": "1wk",
            "month": "1mo",
        }

        interval = interval_map[timeframe]

        period1 = int(
            start_dt.timestamp()
        )

        # Yahoo Finance의 period2는 보통 종료 시점 exclusive
        period2 = int(
            (
                end_dt
                + timedelta(days=1)
            ).timestamp()
        )

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(symbol)}"
            f"?period1={period1}"
            f"&period2={period2}"
            f"&interval={interval}"
            f"&includePrePost=false"
            f"&events=div%2Csplits"
        )

        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            },
        )

        with urlopen(
            req,
            timeout=10,
        ) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

        result = (
            data
            .get("chart", {})
            .get("result")
        )

        if not result:
            return (
                f"오류: {symbol}의 과거 주가 정보를 "
                f"가져오지 못했습니다."
            )

        chart_data = result[0]

        timestamps = chart_data.get(
            "timestamp",
            [],
        )

        indicators = chart_data.get(
            "indicators",
            {},
        )

        quote_list = indicators.get(
            "quote",
            [],
        )

        if not quote_list:
            return (
                f"오류: {symbol}의 OHLCV 데이터가 없습니다."
            )

        quote_data = quote_list[0]

        opens = quote_data.get("open", [])
        highs = quote_data.get("high", [])
        lows = quote_data.get("low", [])
        closes = quote_data.get("close", [])
        volumes = quote_data.get("volume", [])

        lines = [
            f"종목: {symbol}",
            f"기간: {start_date} ~ {end_date}",
            f"간격: {timeframe}",
            "",
        ]

        for index, timestamp in enumerate(
            timestamps
        ):

            date_string = datetime.fromtimestamp(
                timestamp
            ).strftime("%Y-%m-%d")

            open_price = (
                opens[index]
                if index < len(opens)
                else None
            )

            high_price = (
                highs[index]
                if index < len(highs)
                else None
            )

            low_price = (
                lows[index]
                if index < len(lows)
                else None
            )

            close_price = (
                closes[index]
                if index < len(closes)
                else None
            )

            volume = (
                volumes[index]
                if index < len(volumes)
                else None
            )

            lines.append(
                f"{date_string} | "
                f"O={open_price} | "
                f"H={high_price} | "
                f"L={low_price} | "
                f"C={close_price} | "
                f"V={volume}"
            )

        if len(lines) <= 4:
            return (
                f"오류: {symbol}의 OHLCV 데이터가 없습니다."
            )

        return "\n".join(lines)

    except ValueError:

        return (
            "오류: 날짜는 YYYY-MM-DD 형식으로 "
            "입력해야 합니다."
        )

    except Exception as e:

        return (
            f"오류: 과거 주가 조회 중 문제가 "
            f"발생했습니다.\n{str(e)}"
        )


@tool(parse_docstring=True)
def get_financial_metrics(
    ticker: str,
    period: str = "annual",
) -> Dict[str, Union[str, float, int, None]]:
    """특정 기업의 핵심 재무 지표를 조회합니다.

    Args:
        ticker: 주식 종목 코드. 예: AAPL, NVDA, 005930.KS
        period: annual 또는 quarterly

    Returns:
        PER, PBR, ROE, 매출액, 영업이익, EPS, 시가총액 등의 재무정보
    """

    try:
        ticker = ticker.strip().upper()

        if period not in {
            "annual",
            "quarterly",
        }:
            return {
                "error": (
                    "period는 annual 또는 "
                    "quarterly이어야 합니다."
                )
            }

        stock = yf.Ticker(ticker)

        info = stock.info or {}

        per = info.get(
            "trailingPE"
        )

        forward_per = info.get(
            "forwardPE"
        )

        pbr = info.get(
            "priceToBook"
        )

        roe = info.get(
            "returnOnEquity"
        )

        if roe is not None:
            roe = round(
                roe * 100,
                2,
            )

        market_cap = info.get(
            "marketCap"
        )

        eps = info.get(
            "trailingEps"
        )

        # yfinance는 dividendYield를 이미 퍼센트 단위로 반환한다.
        # (0.35 == 0.35%) 따라서 100을 곱하면 안 된다.
        dividend_yield = info.get(
            "dividendYield"
        )

        if dividend_yield is not None:
            dividend_yield = round(
                dividend_yield,
                2,
            )

        company_name = (
            info.get("longName")
            or info.get("shortName")
            or ticker
        )

        sector = info.get(
            "sector"
        )

        industry = info.get(
            "industry"
        )

        if period == "annual":
            financials = stock.financials

        else:
            financials = (
                stock.quarterly_financials
            )

        revenue = None
        operating_income = None
        report_date = None

        if financials is not None and not financials.empty:

            latest_column = (
                financials.columns[0]
            )

            try:
                report_date = (
                    latest_column.strftime(
                        "%Y-%m-%d"
                    )
                )

            except Exception:
                report_date = str(
                    latest_column
                )

            if "Total Revenue" in financials.index:

                revenue_value = financials.loc[
                    "Total Revenue",
                    latest_column,
                ]

                if pd.notna(revenue_value):
                    revenue = int(
                        revenue_value
                    )

            if "Operating Income" in financials.index:

                operating_value = financials.loc[
                    "Operating Income",
                    latest_column,
                ]

                if pd.notna(
                    operating_value
                ):
                    operating_income = int(
                        operating_value
                    )

        return {
            "ticker": ticker,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "period": period,
            "report_date": report_date,
            "market_cap": market_cap,
            "revenue": revenue,
            "operating_income": operating_income,
            "PER": (
                round(per, 2)
                if per is not None
                else None
            ),
            "forward_PER": (
                round(forward_per, 2)
                if forward_per is not None
                else None
            ),
            "PBR": (
                round(pbr, 2)
                if pbr is not None
                else None
            ),
            "ROE_percent": roe,
            "EPS": eps,
            "dividend_yield_percent": (
                dividend_yield
            ),
        }

    except Exception as e:

        return {
            "error": (
                "재무 데이터를 불러오는 중 "
                f"오류가 발생했습니다: {str(e)}"
            )
        }


@tool(parse_docstring=True)
def get_company_disclosures(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[Dict[str, str]]:
    """특정 기업의 최근 관련 뉴스 헤드라인을 조회합니다.

    Args:
        ticker: 주식 종목 코드
        start_date: 검색 시작일. YYYY-MM-DD 형식, 선택사항
        end_date: 검색 종료일. YYYY-MM-DD 형식, 선택사항
        keyword: 뉴스 제목 필터링 키워드, 선택사항

    Returns:
        날짜, 제목, 언론사, 링크가 포함된 뉴스 목록
    """

    try:
        ticker = ticker.strip().upper()

        stock = yf.Ticker(ticker)

        news_items = stock.news or []

        if not news_items:
            return []

        start_dt = (
            datetime.strptime(
                start_date,
                "%Y-%m-%d",
            )
            if start_date
            else None
        )

        end_dt = (
            datetime.strptime(
                end_date,
                "%Y-%m-%d",
            )
            if end_date
            else None
        )

        if end_dt:
            end_dt = (
                end_dt
                + timedelta(days=1)
            )

        filtered_news = []

        for item in news_items:

            # 최신 yfinance 구조 대응
            content = item.get(
                "content",
                item,
            )

            title = (
                content.get("title")
                or item.get("title")
                or ""
            )

            publisher = (
                item.get("publisher")
            )

            provider = content.get(
                "provider"
            )

            if (
                not publisher
                and isinstance(
                    provider,
                    dict,
                )
            ):
                publisher = provider.get(
                    "displayName"
                )

            if not publisher:
                publisher = "Unknown"

            link = (
                item.get("link")
                or ""
            )

            canonical_url = content.get(
                "canonicalUrl"
            )

            if (
                not link
                and isinstance(
                    canonical_url,
                    dict,
                )
            ):
                link = (
                    canonical_url.get(
                        "url",
                        "",
                    )
                )

            pub_time = (
                item.get(
                    "providerPublishTime"
                )
            )

            news_date = None

            if pub_time:

                news_date = datetime.fromtimestamp(
                    pub_time
                )

            else:

                pub_date_string = content.get(
                    "pubDate"
                )

                if pub_date_string:

                    try:
                        news_date = (
                            datetime.fromisoformat(
                                pub_date_string
                                .replace(
                                    "Z",
                                    "+00:00",
                                )
                            )
                        )

                        news_date = (
                            news_date.replace(
                                tzinfo=None
                            )
                        )

                    except Exception:
                        news_date = None

            if (
                start_dt
                and news_date
                and news_date < start_dt
            ):
                continue

            if (
                end_dt
                and news_date
                and news_date >= end_dt
            ):
                continue

            if (
                keyword
                and keyword.lower()
                not in title.lower()
            ):
                continue

            date_text = (
                news_date.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if news_date
                else "정보 없음"
            )

            filtered_news.append(
                {
                    "date": date_text,
                    "title": title,
                    "publisher": publisher,
                    "link": link,
                }
            )

            if len(filtered_news) >= 10:
                break

        return filtered_news

    except Exception:

        return []


# ============================================================
# 📁 파일 시스템 Tool
# ============================================================


@tool(parse_docstring=True)
def read_file(
    file_path: str,
) -> str:
    """파일 내용을 읽습니다.

    Args:
        file_path: 읽을 파일 경로

    Returns:
        파일 내용
    """

    try:

        with open(
            file_path,
            "r",
            encoding="utf-8",
        ) as file:

            content = file.read()

        line_count = len(
            content.splitlines()
        )

        return (
            f"파일: {file_path}\n"
            f"총 {line_count}줄\n\n"
            f"{content}"
        )

    except FileNotFoundError:

        return (
            f"오류: 파일을 찾을 수 없습니다: "
            f"{file_path}"
        )

    except PermissionError:

        return (
            f"오류: 파일 읽기 권한이 없습니다: "
            f"{file_path}"
        )

    except Exception as e:

        return f"오류: {str(e)}"


@tool(parse_docstring=True)
def write_file(
    file_path: str,
    content: str,
) -> str:
    """파일을 생성하거나 내용을 덮어씁니다.

    Args:
        file_path: 작성할 파일 경로
        content: 파일에 저장할 내용

    Returns:
        파일 작성 결과
    """

    try:

        directory = os.path.dirname(
            file_path
        )

        if directory:
            os.makedirs(
                directory,
                exist_ok=True,
            )

        with open(
            file_path,
            "w",
            encoding="utf-8",
        ) as file:

            file.write(content)

        line_count = len(
            content.splitlines()
        )

        return (
            f"성공: 파일이 작성되었습니다: "
            f"{file_path} "
            f"(총 {line_count}줄)"
        )

    except PermissionError:

        return (
            f"오류: 파일 쓰기 권한이 없습니다: "
            f"{file_path}"
        )

    except Exception as e:

        return f"오류: {str(e)}"


@tool(parse_docstring=True)
def delete_file(
    file_path: str,
) -> str:
    """파일을 삭제합니다.

    Args:
        file_path: 삭제할 파일 경로

    Returns:
        파일 삭제 결과
    """

    try:

        if not os.path.isfile(
            file_path
        ):

            return (
                f"오류: 파일을 찾을 수 없습니다: "
                f"{file_path}"
            )

        os.remove(
            file_path
        )

        return (
            f"성공: 파일이 삭제되었습니다: "
            f"{file_path}"
        )

    except PermissionError:

        return (
            f"오류: 파일 삭제 권한이 없습니다: "
            f"{file_path}"
        )

    except Exception as e:

        return f"오류: {str(e)}"


@tool(parse_docstring=True)
def create_directory(
    dir_path: str,
) -> str:
    """디렉터리를 생성합니다.

    Args:
        dir_path: 생성할 디렉터리 경로

    Returns:
        디렉터리 생성 결과
    """

    try:

        os.makedirs(
            dir_path,
            exist_ok=True,
        )

        return (
            f"성공: 디렉터리가 생성되었습니다: "
            f"{dir_path}"
        )

    except PermissionError:

        return (
            f"오류: 디렉터리 생성 권한이 없습니다: "
            f"{dir_path}"
        )

    except Exception as e:

        return f"오류: {str(e)}"


@tool(parse_docstring=True)
def list_directory(
    dir_path: str = ".",
) -> str:
    """디렉터리의 파일과 폴더 목록을 조회합니다.

    Args:
        dir_path: 조회할 디렉터리 경로

    Returns:
        파일 및 폴더 목록
    """

    try:

        if not os.path.exists(
            dir_path
        ):

            return (
                f"오류: 디렉터리를 찾을 수 없습니다: "
                f"{dir_path}"
            )

        if not os.path.isdir(
            dir_path
        ):

            return (
                f"오류: {dir_path}는 "
                f"디렉터리가 아닙니다."
            )

        items = sorted(
            os.listdir(
                dir_path
            )
        )

        if not items:

            return (
                f"디렉터리가 비어 있습니다: "
                f"{dir_path}"
            )

        folders = []
        files = []

        for item in items:

            item_path = os.path.join(
                dir_path,
                item,
            )

            if os.path.isdir(
                item_path
            ):

                folders.append(
                    f"[폴더] {item}/"
                )

            else:

                file_size = os.path.getsize(
                    item_path
                )

                files.append(
                    f"[파일] {item} "
                    f"({file_size} bytes)"
                )

        output = [
            f"디렉터리: {dir_path}",
            "",
        ]

        if folders:

            output.append("폴더:")
            output.extend(folders)
            output.append("")

        if files:

            output.append("파일:")
            output.extend(files)

        return "\n".join(
            output
        )

    except PermissionError:

        return (
            f"오류: 디렉터리 읽기 권한이 없습니다: "
            f"{dir_path}"
        )

    except Exception as e:

        return f"오류: {str(e)}"


@tool(parse_docstring=True)
def execute_python_code(
    code: str,
) -> str:
    """Python 코드를 실행합니다.

    Args:
        code: 실행할 Python 코드

    Returns:
        Python 코드 실행 결과
    """

    try:

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=os.getcwd(),
        )

        outputs = []

        if result.stdout:

            outputs.append(
                "출력:\n"
                + result.stdout.strip()
            )

        if result.stderr:

            outputs.append(
                "오류 출력:\n"
                + result.stderr.strip()
            )

        if result.returncode == 0:

            if outputs:

                return (
                    "실행 성공\n\n"
                    + "\n\n".join(
                        outputs
                    )
                )

            return (
                "실행 성공 "
                "(출력 없음)"
            )

        return (
            f"실행 실패 "
            f"(종료 코드: {result.returncode})\n\n"
            + "\n\n".join(
                outputs
            )
        )

    except subprocess.TimeoutExpired:

        return (
            "오류: Python 코드 실행 시간이 "
            "15초를 초과했습니다."
        )

    except Exception as e:

        return f"오류: {str(e)}"


# ============================================================
# Tool 그룹
# ============================================================


FILE_TOOLS = [
    read_file,
    write_file,
    delete_file,
    create_directory,
    list_directory,
    execute_python_code,
]


STOCK_TOOLS = [
    get_current_price,
    get_historical_ohlcv,
    get_financial_metrics,
    get_company_disclosures,
]


ALL_TOOLS = (
    FILE_TOOLS
    + STOCK_TOOLS
)