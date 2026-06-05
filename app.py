import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
import warnings
import re

from bs4 import BeautifulSoup
from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator
from datetime import datetime, timedelta
from urllib.parse import quote
from io import StringIO

warnings.filterwarnings("ignore")

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


# =========================
# 시간 관련 (먼저 정의해야 함)
# =========================
def get_kst_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except Exception:
        return None


def get_latest_pos(df):
    now = get_kst_now()

    market_closed = (
        now.hour > 15
        or (now.hour == 15 and now.minute >= 30)
    )

    return len(df) - 1 if market_closed else len(df) - 2


def get_global_basis_date():
    try:
        start = (get_kst_now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = load_ohlcv("005930", start)

        if df is None or len(df) < 2:
            return "-"

        latest_pos = get_latest_pos(df)
        return str(df.index[latest_pos].date())

    except Exception:
        return "-"


# =========================
# Streamlit 기본 설정
# =========================
st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")
st.title("📈 스윙 종목 스크리너")

now_kst = get_kst_now()
scan_basis_date = get_global_basis_date()

st.caption(
    f"기준시간: {now_kst.strftime('%Y-%m-%d %H:%M')} KST "
    f"/ 실제 분석봉: {scan_basis_date}"
)

st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlockBorderWrapper"] {
        padding:0.55rem 0.65rem!important;
        border-radius:0.7rem!important;
    }
    div[data-testid="stExpander"] details {font-size:0.82rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================
# 핵심 필터 기준
# =========================
PRICE_MIN = 30_000
HIGH_PRICE_THRESHOLD = 200_000
MARCAP_MIN = 300_000_000_000
TRADE_AMOUNT_20AVG_MIN = 10_000_000_000
TRADE_AMOUNT_TODAY_MIN = 5_000_000_000

EXCLUDE_KEYWORDS = [
    "스팩", "SPAC", "리츠", "ETN", "ETF", "액티브",
    "인버스", "레버리지", "선물",
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS",
    "HANARO", "KBSTAR", "ARIRANG", "KOSEF",
    "TIMEFOLIO", "TIME", "TREX", "마이티",
]

# =========================
# 사이드바
# =========================
st.sidebar.header("💰 시드 계산기")
seed = st.sidebar.number_input("총 시드 (원)", value=2_000_000, step=100_000)

st.sidebar.write(f"1차 매수 (30%): **{int(seed * 0.3):,}원**")
st.sidebar.write(f"추가 매수 (20%): **{int(seed * 0.2):,}원**")
st.sidebar.write(f"최대 비중 (50%): **{int(seed * 0.5):,}원**")
st.sidebar.write(f"최소 현금 (30%): **{int(seed * 0.3):,}원**")

st.sidebar.divider()

favorite_input = st.sidebar.text_area(
    "⭐ 관심종목 코드", value="", placeholder="예: 005930,000660"
)

favorite_codes = {
    code.strip().zfill(6)
    for code in favorite_input.replace("\n", ",").split(",")
    if code.strip()
}

if st.sidebar.button("🔄 데이터 캐시 초기화"):
    st.cache_data.clear()
    st.rerun()


# =========================
# 데이터 로더
# =========================
def clean_number(value):
    try:
        text = str(value).strip().replace(",", "").replace("+", "").replace("-", "")
        return pd.to_numeric(text, errors="coerce")
    except Exception:
        return pd.NA


def parse_naver_market_sum_html(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    code_map = {}

    for link in soup.select("a.tltle"):
        href = link.get("href", "")
        name = link.text.strip()
        if "code=" in href:
            code_map[name] = href.split("code=")[-1][:6]

    tables = pd.read_html(StringIO(html_text))
    target_df = None

    for table in tables:
        cols = [str(c) for c in table.columns]
        if "종목명" in cols and "현재가" in cols and "시가총액" in cols:
            target_df = table.copy()
            break

    if target_df is None:
        return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"])

    target_df = target_df.dropna(subset=["종목명"])

    target_df["Code"] = target_df["종목명"].map(code_map)
    target_df["Name"] = target_df["종목명"]
    target_df["Close"] = target_df["현재가"].apply(clean_number)
    target_df["Marcap"] = target_df["시가총액"].apply(clean_number) * 100_000_000

    result = target_df[["Code", "Name", "Marcap", "Close"]].dropna()
    result["Code"] = result["Code"].astype(str).str.zfill(6)

    return result.drop_duplicates("Code").reset_index(drop=True)


@st.cache_data(ttl=3600)
def load_stock_list():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.naver.com/"
    }

    markets = {"KOSPI": 0, "KOSDAQ": 1}
    frames = []

    for _, sosok in markets.items():
        for page in range(1, 40):
            url = (
                "https://finance.naver.com/sise/sise_market_sum.naver"
                f"?sosok={sosok}&page={page}"
            )

            res = requests.get(url, headers=headers)
            res.encoding = "euc-kr"

            df = parse_naver_market_sum_html(res.text)
            if df.empty:
                break

            frames.append(df)

    return pd.concat(frames).drop_duplicates("Code"), []


def apply_base_filters(stocks):
    stocks = stocks.copy()
    stocks["Marcap"] = pd.to_numeric(stocks["Marcap"], errors="coerce")
    stocks["Close"] = pd.to_numeric(stocks["Close"], errors="coerce")

    stocks = stocks.dropna()

    pattern = "|".join(map(re.escape, EXCLUDE_KEYWORDS))
    stocks = stocks[~stocks["Name"].str.contains(pattern, case=False, na=False)]

    stocks = stocks[stocks["Marcap"] >= MARCAP_MIN]

    return stocks.reset_index(drop=True), []


# =========================
# 분석 로직
# =========================
def make_urls(code, name):
    return (
        f"https://finance.naver.com/item/main.naver?code={code}",
        f"https://search.naver.com/search.naver?where=news&query={quote(name)}",
    )


def calc_buy_zone(trade_type, close_price, ma20, high_10d):
    if trade_type == "눌림형":
        return round(ma20 * 0.98), round(ma20 * 1.02), "눌림"
    if trade_type == "돌파형 안정형":
        return round(high_10d * 0.995), round(high_10d * 1.015), "돌파"
    return round(close_price * 0.98), round(close_price * 1.01), "기타"


def calc_stop_loss(trade_type, buy_low, ma20, recent_low):
    return round(min(ma20 * 0.97, recent_low * 0.99))


def make_result(grade, code, name, close_price, ma5, ma20, rsi,
                vol, vol5, reason, marcap, pullback,
                trade_type, buy_low, buy_high, stop_loss, strategy,
                original_grade=None):

    chart, news = make_urls(code, name)

    return {
        "grade": grade,
        "original_grade": original_grade or grade,
        "name": name,
        "code": code,
        "basis_date": scan_basis_date,
        "close": int(close_price),
        "ma5": round(ma5),
        "ma20": round(ma20),
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol / vol5 * 100, 1) if vol5 else 0,
        "pullback": round(pullback, 1),
        "trade_type": trade_type,
        "buy_zone": f"{buy_low}~{buy_high}",
        "stop_loss": str(stop_loss),
        "strategy": strategy,
        "reason": reason,
        "chart": chart,
        "news": news,
        "marcap": marcap,
    }


def analyze_stock(code, name, marcap):
    df = load_ohlcv(code, (get_kst_now() - timedelta(days=160)).strftime("%Y-%m-%d"))
    if df is None or len(df) < 80:
        return None

    latest_pos = get_latest_pos(df)
    if latest_pos < 60:
        return None

    df["ma5"] = SMAIndicator(df["Close"], 5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], 20).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], 14).rsi()

    close = df["Close"].iloc[latest_pos]
    if close < PRICE_MIN:
        return None

    latest = df.iloc[latest_pos]

    if pd.isna(latest["ma20"]):
        return None

    ma20 = latest["ma20"]
    ma5 = latest["ma5"]
    rsi = latest["rsi"]

    high_10d = df["High"].iloc[latest_pos-10:latest_pos].max()
    recent_low = df["Low"].iloc[latest_pos-5:latest_pos].min()

    pullback = (close - high_10d) / high_10d * 100

    if rsi > 80:
        return None

    entry_a = close > ma20 and 40 < rsi < 68 and pullback < -3

    if entry_a:
        grade = "A"
        trade_type = "눌림형"
    else:
        grade = "C"
        trade_type = "관심"

    buy_low, buy_high, strategy = calc_buy_zone(trade_type, close, ma20, high_10d)
    stop_loss = calc_stop_loss(trade_type, buy_low, ma20, recent_low)

    return make_result(
        grade, code, name, close, ma5, ma20, rsi,
        latest["Volume"], df["Volume"].iloc[latest_pos-5:latest_pos].mean(),
        "자동", marcap, pullback,
        trade_type, buy_low, buy_high, stop_loss, strategy
    )


# =========================
# UI
# =========================
col1, col2 = st.columns(2)

scan_full = col1.button("전체 스캔")
scan_fav = col2.button("관심 스캔")

if scan_full or scan_fav:
    stocks, _ = load_stock_list()
    stocks, _ = apply_base_filters(stocks)

    if scan_fav:
        stocks = stocks[stocks["Code"].isin(favorite_codes)]

    results = []

    for i, row in enumerate(stocks.itertuples()):
        r = analyze_stock(row.Code, row.Name, row.Marcap)
        if r:
            results.append(r)

    df = pd.DataFrame(results)

    st.dataframe(df)
