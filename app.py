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
# 시간 함수 먼저 선언 (중요)
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
    market_closed = (now.hour > 15 or (now.hour == 15 and now.minute >= 30))
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
# Streamlit 기본
# =========================
st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")
st.title("📈 스윙 종목 스크리너")

now_kst = get_kst_now()
scan_basis_date = get_global_basis_date()

st.caption(
    f"기준시간: {now_kst.strftime('%Y-%m-%d %H:%M')} KST "
    f"/ 실제 분석봉: {scan_basis_date}"
)

# =========================
# 핵심 필터
# =========================
PRICE_MIN = 30000
HIGH_PRICE_THRESHOLD = 200000
MARCAP_MIN = 300_000_000_000
TRADE_AMOUNT_20AVG_MIN = 10_000_000_000
TRADE_AMOUNT_TODAY_MIN = 5_000_000_000

EXCLUDE_KEYWORDS = [
    "스팩", "SPAC", "리츠", "ETN", "ETF", "액티브",
    "인버스", "레버리지", "선물",
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "HANARO",
    "KBSTAR", "ARIRANG", "KOSEF", "TIMEFOLIO", "TIME", "TREX", "마이티",
]

# =========================
# 사이드바
# =========================
st.sidebar.header("💰 시드 계산기")

seed = st.sidebar.number_input("총 시드 (원)", value=2_000_000, step=100_000)
st.sidebar.write(f"1차 매수 (30%): **{int(seed*0.3):,}원**")
st.sidebar.write(f"추가 매수 (20%): **{int(seed*0.2):,}원**")
st.sidebar.write(f"최대 비중 (50%): **{int(seed*0.5):,}원**")
st.sidebar.write(f"최소 현금 (30%): **{int(seed*0.3):,}원**")

favorite_input = st.sidebar.text_area(
    "⭐ 관심종목 코드", value="", placeholder="예: 005930,000660"
)

favorite_codes = {
    c.strip().zfill(6)
    for c in favorite_input.replace("\n", ",").split(",")
    if c.strip()
}

if st.sidebar.button("🔄 캐시 초기화"):
    st.cache_data.clear()
    st.rerun()

# =========================
# 유틸
# =========================
def clean_number(v):
    return pd.to_numeric(str(v).replace(",", ""), errors="coerce")


def make_urls(code, name):
    return (
        f"https://finance.naver.com/item/main.naver?code={code}",
        f"https://search.naver.com/search.naver?where=news&query={quote(name)}",
    )

# =========================
# (이 부분은 네 기존 그대로 유지)
# parse / load_stock_list / apply_base_filters
# =========================

def analyze_stock(code, name, marcap):
    start = (get_kst_now() - timedelta(days=160)).strftime("%Y-%m-%d")
    df = load_ohlcv(code, start)

    if df is None or len(df) < 80:
        return None

    idx = get_latest_pos(df)
    prev = idx - 1

    close = df["Close"].iloc[idx]

    if close < PRICE_MIN:
        return None

    df["ma5"] = SMAIndicator(df["Close"], 5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], 20).sma_indicator()
    df["ma60"] = SMAIndicator(df["Close"], 60).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], 14).rsi()

    latest = df.iloc[idx]

    ma20 = latest["ma20"]
    ma60 = latest["ma60"]
    rsi = latest["rsi"]

    if pd.isna(ma20) or pd.isna(ma60) or pd.isna(rsi):
        return None

    trend_ok = close > ma20 and ma20 > ma60
    high_10 = df["High"].iloc[idx-10:idx].max()

    entry_a = trend_ok and close < ma20 * 1.03
    entry_b = trend_ok and close > high_10

    if entry_a:
        grade = "A"
        reason = "눌림"
    elif entry_b:
        grade = "B"
        reason = "돌파"
    else:
        grade = "C"
        reason = "관심"

    chart, news = make_urls(code, name)

    return {
        "grade": grade,
        "name": name,
        "code": code,
        "close": int(close),
        "ma20": round(ma20),
        "rsi": round(rsi, 1),
        "reason": reason,
        "chart": chart,
        "news": news
    }


# =========================
# 실행
# =========================
if st.button("🚀 스캔"):
    stocks = apply_base_filters(load_stock_list())

    results = []

    for row in stocks.itertuples():
        res = analyze_stock(row.Code, row.종목명, row.Marcap)
        if res:
            results.append(res)

    st.dataframe(pd.DataFrame(results))
