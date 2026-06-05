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
# Streamlit 기본
# =========================
st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")
st.title("📈 스윙 종목 스크리너")


# =========================
# 시간
# =========================
def get_kst_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


now_kst = get_kst_now()


def get_latest_pos(df):
    market_closed = (
        now_kst.hour > 15 or (now_kst.hour == 15 and now_kst.minute >= 30)
    )
    return len(df) - 1 if market_closed else len(df) - 2


def get_global_basis_date():
    try:
        start = (get_kst_now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = fdr.DataReader("005930", start)

        if df is None or len(df) < 2:
            return "-"

        pos = get_latest_pos(df)
        return str(df.index[pos].date())

    except Exception:
        return "-"


scan_basis_date = get_global_basis_date()

st.caption(
    f"기준시간: {now_kst.strftime('%Y-%m-%d %H:%M')} KST / 실제 분석봉: {scan_basis_date}"
)


# =========================
# CONFIG
# =========================
PRICE_MIN = 30_000
HIGH_PRICE_THRESHOLD = 200_000

MARCAP_MIN = 300_000_000_000

TRADE_AMOUNT_20AVG_MIN = 10_000_000_000
TRADE_AMOUNT_TODAY_MIN = 5_000_000_000

EXCLUDE_KEYWORDS = [
    "스팩", "SPAC", "리츠", "ETN", "ETF", "액티브",
    "인버스", "레버리지", "선물",
    "KODEX", "TIGER", "ACE", "SOL", "RISE",
    "PLUS", "HANARO", "KBSTAR", "ARIRANG", "KOSEF"
]


# =========================
# 사이드바
# =========================
st.sidebar.header("💰 시드 계산기")

seed = st.sidebar.number_input("총 시드 (원)", value=2_000_000, step=100_000)

st.sidebar.write(f"1차 매수 (30%): {int(seed * 0.3):,}원")
st.sidebar.write(f"추가 매수 (20%): {int(seed * 0.2):,}원")
st.sidebar.write(f"최대 비중 (50%): {int(seed * 0.5):,}원")

favorite_input = st.sidebar.text_area(
    "⭐ 관심종목 코드", value="", placeholder="예: 005930,000660"
)

favorite_codes = {
    code.strip().zfill(6)
    for code in favorite_input.replace("\n", ",").split(",")
    if code.strip()
}


# =========================
# 종목 리스트
# =========================
def clean_number(v):
    try:
        return pd.to_numeric(str(v).replace(",", ""), errors="coerce")
    except:
        return pd.NA


def parse_table(html):
    soup = BeautifulSoup(html, "html.parser")

    code_map = {}
    for a in soup.select("a.tltle"):
        href = a.get("href", "")
        if "code=" in href:
            code_map[a.text.strip()] = href.split("code=")[-1][:6]

    tables = pd.read_html(StringIO(html))
    df = None

    for t in tables:
        cols = list(t.columns)
        if "종목명" in cols and "현재가" in cols:
            df = t
            break

    if df is None:
        return pd.DataFrame()

    df["Code"] = df["종목명"].map(code_map)
    df["Name"] = df["종목명"]
    df["Close"] = df["현재가"].apply(clean_number)
    df["Marcap"] = df["시가총액"].apply(clean_number) * 100_000_000

    df = df[["Code", "Name", "Close", "Marcap"]].dropna()
    df["Code"] = df["Code"].astype(str).str.zfill(6)

    return df


@st.cache_data(ttl=3600)
def load_stock_list():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.naver.com/"
    }

    frames = []

    for market, sosok in {"KOSPI": 0, "KOSDAQ": 1}.items():
        for page in range(1, 30):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            res = requests.get(url, headers=headers)
            res.encoding = "euc-kr"

            df = parse_table(res.text)

            if df.empty:
                break

            frames.append(df)

    if not frames:
        return pd.DataFrame(), []

    return pd.concat(frames).drop_duplicates("Code"), []


def apply_base_filters(df):
    df = df.copy()

    df = df[df["Marcap"] >= MARCAP_MIN]

    pattern = "|".join(EXCLUDE_KEYWORDS)
    df = df[~df["Name"].str.contains(pattern, na=False)]

    return df.reset_index(drop=True)


# =========================
# OHLCV
# =========================
@st.cache_data(ttl=3600)
def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except:
        return None


# =========================
# 분석
# =========================
def analyze_stock(code, name):
    start = (get_kst_now() - timedelta(days=160)).strftime("%Y-%m-%d")
    df = load_ohlcv(code, start)

    if df is None or len(df) < 80:
        return None

    pos = get_latest_pos(df)

    if pos < 60:
        return None

    close = df["Close"].iloc[pos]

    if close < PRICE_MIN:
        return None

    df["ma5"] = SMAIndicator(df["Close"], 5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], 20).sma_indicator()
    df["ma60"] = SMAIndicator(df["Close"], 60).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], 14).rsi()

    latest = df.iloc[pos]
    prev = df.iloc[pos - 1]

    ma20 = latest["ma20"]
    ma60 = latest["ma60"]
    rsi = latest["rsi"]

    if pd.isna(ma20) or pd.isna(ma60) or pd.isna(rsi):
        return None

    trend_ok = close > ma20 > ma60

    high_20 = df["High"].iloc[pos-20:pos].max()
    pullback = (close - high_20) / high_20 * 100

    volume_today = latest["Volume"]
    volume_avg = df["Volume"].iloc[pos-20:pos].mean()

    pullback_ok = (-15 <= pullback <= -3)

    entry_a = trend_ok and pullback_ok and rsi < 70
    entry_b = trend_ok and close > high_20 and rsi < 75

    if entry_a:
        grade, t, r = "A", "눌림형", "눌림 후 재상승"
    elif entry_b:
        grade, t, r = "B", "돌파형", "돌파"
    else:
        grade, t, r = "C", "관심", "추세"

    return {
        "code": code,
        "name": name,
        "grade": grade,
        "type": t,
        "reason": r,
        "close": int(close),
        "ma20": round(ma20),
        "rsi": round(rsi, 1),
        "pullback": round(pullback, 1),
    }


# =========================
# 실행
# =========================
scan_full = st.button("🚀 전체 스캔")

if scan_full:
    stocks, _ = load_stock_list()
    stocks = apply_base_filters(stocks)

    results = []

    progress = st.progress(0)

    for i, row in enumerate(stocks.itertuples()):
        progress.progress(i / len(stocks))

        r = analyze_stock(row.Code, row.Name)
        if r:
            results.append(r)

    df = pd.DataFrame(results)

    st.success(f"완료: {len(df)}개")

    st.dataframe(df)
