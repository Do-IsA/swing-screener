import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import warnings

from bs4 import BeautifulSoup
from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator

from datetime import datetime, timedelta
from urllib.parse import quote

warnings.filterwarnings("ignore")

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


# =========================
# 기본 설정
# =========================

st.set_page_config(
    page_title="스윙 종목 스크리너",
    layout="wide"
)

st.title("📈 스윙 종목 스크리너")


def get_kst_now():
    if ZoneInfo:
        return datetime.now(
            ZoneInfo("Asia/Seoul")
        )

    return datetime.now()


now_kst = get_kst_now()

st.caption(
    f"기준일: {now_kst.strftime('%Y-%m-%d')} "
    f"/ KST {now_kst.strftime('%H:%M')}"
)

PRICE_MIN = 30000
MARCAP_MIN = 300_000_000_000


# =========================
# 사이드바
# =========================

view_mode = st.sidebar.radio(
    "보기 방식",
    ["카드뷰", "표뷰"],
    index=0
)

favorite_input = st.sidebar.text_area(
    "⭐ 관심종목 코드",
    value="",
    placeholder="예: 005930,000660,319660"
)

favorite_codes = {
    code.strip()
    for code in favorite_input.replace("\n", ",").split(",")
    if code.strip()
}


# =========================
# 종목 리스트
# =========================

@st.cache_data(ttl=3600)
def load_stock_list():

    headers = {
        "User-Agent": (
            "Mozilla/5.0"
        )
    }

    frames = []

    markets = {
        "KOSPI": 0,
        "KOSDAQ": 1
    }

    for market_name, sosok in markets.items():

        market_frames = []

        for page in range(1, 50):

            url = (
                "https://finance.naver.com/sise/"
                f"sise_market_sum.naver?"
                f"sosok={sosok}&page={page}"
            )

            try:
                res = requests.get(
                    url,
                    headers=headers,
                    timeout=10
                )

                res.encoding = "euc-kr"

                tables = pd.read_html(res.text)

                target_df = None

                for table in tables:

                    cols = [str(c) for c in table.columns]

                    if (
                        "종목명" in cols
                        and "현재가" in cols
                        and "시가총액" in cols
                    ):
                        target_df = table.copy()
                        break

                if target_df is None:
                    continue

                target_df = target_df.dropna(
                    subset=["종목명"]
                )

                if target_df.empty:
                    continue

                soup = BeautifulSoup(
                    res.text,
                    "html.parser"
                )

                code_map = {}

                for link in soup.select("a.tltle"):

                    href = link.get("href", "")
                    name = link.text.strip()

                    if "code=" in href:
                        code = href.split("code=")[-1][:6]
                        code_map[name] = code

                target_df["Code"] = (
                    target_df["종목명"]
                    .map(code_map)
                )

                target_df["Name"] = (
                    target_df["종목명"]
                )

                target_df["Close"] = pd.to_numeric(
                    target_df["현재가"],
                    errors="coerce"
                )

                target_df["Marcap"] = (
                    pd.to_numeric(
                        target_df["시가총액"],
                        errors="coerce"
                    ) * 100000000
                )

                result = target_df[
                    ["Code", "Name", "Marcap", "Close"]
                ].copy()

                result = result.dropna(
                    subset=[
                        "Code",
                        "Name",
                        "Marcap",
                        "Close"
                    ]
                )

                result["Code"] = (
                    result["Code"]
                    .astype(str)
                    .str.zfill(6)
                )

                market_frames.append(result)

            except Exception:
                continue

        if market_frames:

            frames.append(
                pd.concat(
                    market_frames,
                    ignore_index=True
                )
            )

    if not frames:

        return pd.DataFrame(
            columns=[
                "Code",
                "Name",
                "Marcap",
                "Close"
            ]
        )

    result_df = pd.concat(
        frames,
        ignore_index=True
    )

    result_df = result_df.drop_duplicates(
        subset=["Code"]
    )

    return result_df.reset_index(drop=True)


# =========================
# 차트 데이터
# =========================

@st.cache_data(ttl=3600)
def load_ohlcv(code, start):

    try:
        return fdr.DataReader(code, start)

    except Exception:
        return None


# =========================
# 유틸
# =========================

def make_urls(code, name):

    chart_url = (
        "https://finance.naver.com/item/main.naver"
        f"?code={code}"
    )

    news_url = (
        "https://search.naver.com/search.naver"
        f"?where=news&query={quote(name)}"
    )

    return chart_url, news_url


def fmt_price(value):

    try:
        return f"{int(value):,}원"

    except Exception:
        return "-"


# =========================
# 분석
# =========================

def analyze_stock(code, name, marcap):

    start = (
        get_kst_now() - timedelta(days=160)
    ).strftime("%Y-%m-%d")

    df = load_ohlcv(code, start)

    if df is None or len(df) < 80:
        return None

    df["ma20"] = SMAIndicator(
        df["Close"],
        window=20
    ).sma_indicator()

    df["ma60"] = SMAIndicator(
        df["Close"],
        window=60
    ).sma_indicator()

    df["rsi"] = RSIIndicator(
        df["Close"],
        window=14
    ).rsi()

    latest = df.iloc[-1]

    close_price = latest["Close"]
    ma20 = latest["ma20"]
    ma60 = latest["ma60"]
    rsi = latest["rsi"]

    if (
        pd.isna(ma20)
        or pd.isna(ma60)
        or pd.isna(rsi)
    ):
        return None

    if close_price < PRICE_MIN:
        return None

    if marcap < MARCAP_MIN:
        return None

    trend_ok = (
        close_price > ma20
        and ma20 > ma60
    )

    if not trend_ok:
        return None

    if rsi < 70:
        grade = "A"
    elif rsi < 75:
        grade = "B"
    else:
        grade = "C"

    chart_url, news_url = make_urls(
        code,
        name
    )

    return {
        "grade": grade,
        "name": name,
        "code": code,
        "close": int(close_price),
        "ma20": int(ma20),
        "rsi": round(rsi, 1),
        "chart": chart_url,
        "news": news_url,
        "marcap": marcap,
    }


# =========================
# 출력
# =========================

def show_cards(df):

    if df.empty:
        st.write("해당 종목 없음")
        return

    for _, row in df.iterrows():

        star = (
            "⭐ "
            if row["code"] in favorite_codes
            else ""
        )

        with st.container(border=True):

            st.markdown(
                f"### {star}"
                f"{row['name']} "
                f"({row['code']})"
            )

            st.markdown(
                f"현재가: "
                f"{fmt_price(row['close'])}"
            )

            st.markdown(
                f"RSI: {row['rsi']}"
            )

            st.markdown(
                f"20일선: "
                f"{fmt_price(row['ma20'])}"
            )

            st.markdown(
                f"[📈 차트 보기]"
                f"({row['chart']})"
                f" | "
                f"[📰 뉴스 보기]"
                f"({row['news']})"
            )


# =========================
# 실행
# =========================

if st.button(
    "🔍 종목 스캔 시작",
    type="primary"
):

    with st.spinner(
        "종목 리스트 불러오는 중..."
    ):

        stocks = load_stock_list()

    if stocks.empty:

        st.error(
            "종목 리스트를 불러오지 못했습니다."
        )

        st.stop()

    stocks = stocks[
        stocks["Marcap"] >= MARCAP_MIN
    ]

    results = []

    progress = st.progress(0)

    total = len(stocks)

    for i, row in enumerate(stocks.itertuples()):

        progress.progress(
            (i + 1) / total
        )

        result = analyze_stock(
            code=row.Code,
            name=row.Name,
            marcap=row.Marcap
        )

        if result:
            results.append(result)

    df_result = pd.DataFrame(results)

    tab1, tab2, tab3 = st.tabs([
        "🟢 A등급",
        "🔵 B등급",
        "🟡 C등급"
    ])

    with tab1:
        show_cards(
            df_result[
                df_result["grade"] == "A"
            ]
        )

    with tab2:
        show_cards(
            df_result[
                df_result["grade"] == "B"
            ]
        )

    with tab3:
        show_cards(
            df_result[
                df_result["grade"] == "C"
            ]
        )
