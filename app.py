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
# 기본 설정
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


# ❗ FIX: 원래 코드에서 호출 순서 문제 해결 (그대로 유지 기능)
def get_global_basis_date():
    try:
        start = (get_kst_now() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = load_ohlcv("005930", start)

        if df is None or len(df) < 2:
            return "-"

        pos = get_latest_pos(df)
        return str(df.index[pos].date())

    except Exception:
        return "-"


# =========================
# 필터 기준
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

favorite_input = st.sidebar.text_area(
    "⭐ 관심종목 코드",
    value="",
    placeholder="예: 005930,000660,319660"
)

favorite_codes = {
    code.strip().zfill(6)
    for code in favorite_input.replace("\n", ",").split(",")
    if code.strip()
}


# =========================
# 유틸
# =========================
def clean_number(value):
    try:
        text = str(value).strip().replace(",", "").replace("+", "").replace("-", "")
        return pd.to_numeric(text, errors="coerce")
    except Exception:
        return pd.NA


def make_urls(code, name):
    return (
        f"https://finance.naver.com/item/main.naver?code={code}",
        f"https://search.naver.com/search.naver?where=news&query={quote(name)}",
    )


# =========================
# 종목 리스트
# =========================
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
    if target_df.empty:
        return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"])

    target_df["Code"] = target_df["종목명"].map(code_map)
    target_df["Name"] = target_df["종목명"]
    target_df["Close"] = target_df["현재가"].apply(clean_number)
    target_df["Marcap"] = target_df["시가총액"].apply(clean_number) * 100_000_000

    result = target_df[["Code", "Name", "Marcap", "Close"]].copy()
    result = result.dropna(subset=["Code", "Name", "Marcap", "Close"])
    result["Code"] = result["Code"].astype(str).str.zfill(6)
    result = result[result["Code"].str.match(r"^\d{6}$", na=False)]
    result = result.drop_duplicates(subset=["Code"])

    return result.reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_stock_list():
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.naver.com/",
    }

    frames = []
    markets = {"KOSPI": 0, "KOSDAQ": 1}

    for market_name, sosok in markets.items():
        for page in range(1, 45):
            url = (
                "https://finance.naver.com/sise/sise_market_sum.naver"
                f"?sosok={sosok}&page={page}"
            )

            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = "euc-kr"

            df = parse_naver_market_sum_html(res.text)

            if df.empty:
                break

            frames.append(df)

    if not frames:
        return pd.DataFrame(), []

    return pd.concat(frames).drop_duplicates("Code"), []


def apply_base_filters(stocks):
    stocks = stocks.copy()

    stocks["Marcap"] = pd.to_numeric(stocks["Marcap"], errors="coerce")
    stocks["Close"] = pd.to_numeric(stocks["Close"], errors="coerce")

    stocks = stocks.dropna(subset=["Code", "Name", "Marcap", "Close"])

    pattern = "|".join([re.escape(x) for x in EXCLUDE_KEYWORDS])

    stocks = stocks[
        ~stocks["Name"].str.contains(pattern, case=False, na=False)
    ]

    stocks = stocks[
        ~stocks["Name"].str.contains(r"우$|우B$|우C$|우선주", regex=True, na=False)
    ]

    stocks = stocks[stocks["Marcap"] >= MARCAP_MIN]

    return stocks.reset_index(drop=True), []


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
# 분석 로직 (원본 유지 핵심)
# =========================
def analyze_stock(code, name, marcap):
    start = (get_kst_now() - timedelta(days=160)).strftime("%Y-%m-%d")
    df = load_ohlcv(code, start)

    if df is None or len(df) < 80:
        return None

    latest_pos = get_latest_pos(df)
    prev_pos = latest_pos - 1

    if latest_pos < 60 or prev_pos < 0:
        return None

    close_price = df["Close"].iloc[latest_pos]

    if close_price < PRICE_MIN:
        return None

    df["ma5"] = SMAIndicator(df["Close"], 5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], 20).sma_indicator()
    df["ma60"] = SMAIndicator(df["Close"], 60).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], 14).rsi()

    latest = df.iloc[latest_pos]
    prev = df.iloc[prev_pos]

    ma5 = latest["ma5"]
    ma20 = latest["ma20"]
    ma60 = latest["ma60"]
    rsi = latest["rsi"]

    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60) or pd.isna(rsi):
        return None

    volume_today = latest["Volume"]
    volume_5avg = df["Volume"].iloc[latest_pos-5:latest_pos].mean()
    volume_20avg = df["Volume"].iloc[latest_pos-20:latest_pos].mean()

    trade_amount_today = close_price * volume_today
    trade_amount_20avg = (df["Close"] * df["Volume"]).iloc[latest_pos-20:latest_pos].mean()
    trade_amount_3avg = (df["Close"] * df["Volume"]).iloc[latest_pos-3:latest_pos].mean()

    if trade_amount_20avg < TRADE_AMOUNT_20AVG_MIN:
        return None
    if trade_amount_today < TRADE_AMOUNT_TODAY_MIN:
        return None
    if (
        trade_amount_3avg < trade_amount_20avg * 0.5
        and trade_amount_3avg < TRADE_AMOUNT_20AVG_MIN
    ):
        return None

    surge_3d = (
        (close_price - df["Close"].iloc[latest_pos - 3])
        / df["Close"].iloc[latest_pos - 3]
    ) * 100

    today_change = ((close_price - prev["Close"]) / prev["Close"]) * 100

    prev_body = ((prev["Open"] - prev["Close"]) / prev["Open"]) * 100

    if rsi >= 80 or surge_3d >= 25 or today_change >= 25:
        return None
    if prev_body >= 3 and today_change < 2:
        return None

    ma60_5ago = df.iloc[latest_pos - 5]["ma60"]

    trend_ok = close_price > ma20 > ma60 > ma60_5ago

    high_20d = df["High"].iloc[latest_pos-20:latest_pos].max()
    high_10d = df["High"].iloc[latest_pos-10:latest_pos].max()

    pullback_pct = ((close_price - high_20d) / high_20d) * 100
    near_ma20 = abs(close_price - ma20) / ma20 * 100 < 3

    recent_high = df["High"].iloc[latest_pos-5:latest_pos].max()
    recent_low = df["Low"].iloc[latest_pos-5:latest_pos].min()

    sideways = (recent_high - recent_low) / recent_low * 100 < 8
    vol_decrease = volume_today < volume_20avg

    vol_ratio = volume_today / volume_5avg * 100 if volume_5avg > 0 else 0

    pullback_ok = (-15 <= pullback_pct <= -3 and near_ma20)

    entry_a = (
        trend_ok
        and pullback_ok
        and sideways
        and vol_decrease
        and close_price > prev["Close"]
        and close_price > ma5
        and volume_today >= volume_20avg * 0.8
        and 40 <= rsi <= 68
        and close_price > ma20
    )

    entry_b_safe = (
        trend_ok
        and close_price > high_10d
        and vol_ratio >= 150
        and rsi < 70
        and close_price <= ma20 * 1.12
    )

    entry_b_aggressive = (
        trend_ok
        and close_price > high_10d
        and vol_ratio >= 150
        and rsi < 72
        and close_price <= ma20 * 1.18
        and not entry_b_safe
    )

    if entry_a:
        grade, trade_type, reason = "A", "눌림형", "눌림 후 재상승"
    elif entry_b_safe:
        grade, trade_type, reason = "A", "돌파형 안정형", "박스권 돌파 안정형"
    elif entry_b_aggressive:
        grade, trade_type, reason = "B", "돌파형 공격형", "박스권 돌파 공격형"
    elif trend_ok and pullback_ok:
        grade, trade_type, reason = "B", "눌림형", "눌림 형성"
    elif trend_ok:
        grade, trade_type, reason = "C", "관심", "추세"
    else:
        return None

    chart, news = make_urls(code, name)

    return {
        "grade": grade,
        "original_grade": grade,
        "name": name,
        "code": str(code).zfill(6),
        "basis_date": scan_basis_date,
        "close": int(close_price),
        "ma5": round(ma5, 0),
        "ma20": round(ma20, 0),
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 1),
        "pullback": round(pullback_pct, 1),
        "trade_type": trade_type,
        "buy_zone": "-",
        "stop_loss": "-",
        "strategy": "",
        "reason": reason,
        "chart": chart,
        "news": news,
        "marcap": marcap,
    }


# =========================
# UI (그대로 유지)
# =========================
import streamlit.components.v1 as components


def make_copy_text(df):
    if df is None or df.empty:
        return "해당 종목 없음"

    lines = []
    for _, row in df.iterrows():
        lines.append(
            f"[{row['grade']}] {row['name']} ({row['code']})\n"
            f"현재가: {row['close']:,}원\n"
            f"매수구간: {row['buy_zone']}\n"
            f"손절가: {row['stop_loss']}\n"
            f"사유: {row['reason']}\n"
        )

    return "\n".join(lines)


def copy_button(text, key):
    safe_text = text.replace("`", "'")
    components.html(
        f"""
        <button onclick="
        navigator.clipboard.writeText(`{safe_text}`);
        this.innerText='복사완료!';
        ">
        📋 결과 복사
        </button>
        """,
        height=40,
    )


def show_table(df, cols):
    if df is None or df.empty:
        st.write("해당 종목 없음")
        return
    st.dataframe(df[cols], use_container_width=True)


# =========================
# 실행
# =========================
col1, col2 = st.columns(2)

with col1:
    scan_full = st.button("🚀 전체 종목 스캔", type="primary")

with col2:
    scan_favorites = st.button("⭐ 관심종목 스캔")


if scan_full or scan_favorites:

    stocks, _ = load_stock_list()
    stocks, _ = apply_base_filters(stocks)

    if scan_favorites:
        stocks = stocks[stocks["Code"].isin(favorite_codes)]

    results, watch_high = [], []

    progress = st.progress(0)

    for i, row in enumerate(stocks.itertuples()):
        progress.progress((i + 1) / len(stocks))

        r = analyze_stock(row.Code, row.Name, row.Marcap)

        if r:
            if r["grade"] == "watch_high":
                watch_high.append(r)
            else:
                results.append(r)

    df_result = pd.DataFrame(results)
    df_watch = pd.DataFrame(watch_high)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "A등급", "B등급", "C등급", "20만원↑", "관심종목"
    ])

    with tab1:
        d = df_result[df_result["grade"] == "A"]
        copy_button(make_copy_text(d), "a")
        show_table(d, df_result.columns)

    with tab2:
        d = df_result[df_result["grade"] == "B"]
        copy_button(make_copy_text(d), "b")
        show_table(d, df_result.columns)

    with tab3:
        d = df_result[df_result["grade"] == "C"]
        copy_button(make_copy_text(d), "c")
        show_table(d, df_result.columns)

    with tab4:
        copy_button(make_copy_text(df_watch), "w")
        show_table(df_watch, df_watch.columns)

    with tab5:
        fav = df_result[df_result["code"].isin(favorite_codes)]
        show_table(fav, df_result.columns)
