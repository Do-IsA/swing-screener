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
return datetime.now(ZoneInfo("Asia/Seoul"))
return datetime.now()

now_kst = get_kst_now()

st.caption(
f"기준일: {now_kst.strftime('%Y-%m-%d')} "
f"/ KST {now_kst.strftime('%H:%M')}"
)

PRICE_MIN = 30000
HIGH_PRICE_THRESHOLD = 200000

MARCAP_MIN = 300_000_000_000
TRADE_AMOUNT_20AVG_MIN = 10_000_000_000
TRADE_AMOUNT_TODAY_MIN = 5_000_000_000

# =========================

# 사이드바

# =========================

st.sidebar.header("💰 시드 계산기")

seed = st.sidebar.number_input(
"총 시드 (원)",
value=2000000,
step=100000
)

st.sidebar.write(
f"1차 매수 (30%): {int(seed * 0.3):,}원"
)

st.sidebar.write(
f"추가 매수 (20%): {int(seed * 0.2):,}원"
)

st.sidebar.write(
f"최대 비중 (50%): {int(seed * 0.5):,}원"
)

st.sidebar.write(
f"최소 현금 (30%): {int(seed * 0.3):,}원"
)

st.sidebar.divider()

view_mode = st.sidebar.radio(
"보기 방식",
["카드뷰", "표뷰"],
index=0
)

st.sidebar.divider()

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

# 종목 리스트 로딩

# =========================

@st.cache_data(ttl=3600)
def load_stock_list():

```
headers = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

frames = []

markets = {
    "KOSPI": 0,
    "KOSDAQ": 1
}

for market_name, sosok in markets.items():

    market_frames = []

    for page in range(1, 80):

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

        except Exception as e:
            st.warning(
                f"{market_name} {page}페이지 실패: {e}"
            )
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
```

# =========================

# OHLCV

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

```
chart_url = (
    "https://finance.naver.com/item/main.naver"
    f"?code={code}"
)

news_url = (
    "https://search.naver.com/search.naver"
    f"?where=news&query={quote(name)}"
)

return chart_url, news_url
```

def fmt_price(value):

```
try:
    if pd.isna(value):
        return "-"
    return f"{int(value):,}원"
except Exception:
    return "-"
```

def fmt_number(value):

```
try:
    if pd.isna(value):
        return "-"
    return f"{int(value):,}"
except Exception:
    return "-"
```

# =========================

# 분석

# =========================

def analyze_stock(code, name, marcap):

```
start = (
    get_kst_now() - timedelta(days=160)
).strftime("%Y-%m-%d")

df = load_ohlcv(code, start)

if df is None or len(df) < 80:
    return None

df["ma5"] = SMAIndicator(
    df["Close"],
    window=5
).sma_indicator()

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

now = get_kst_now()

use_today_candle = (
    now.hour > 14
    or (now.hour == 14 and now.minute >= 0)
)

latest_pos = (
    len(df) - 1
    if use_today_candle
    else len(df) - 2
)

prev_pos = latest_pos - 1

if latest_pos < 60:
    return None

latest = df.iloc[latest_pos]
prev = df.iloc[prev_pos]

close_price = latest["Close"]
ma5 = latest["ma5"]
ma20 = latest["ma20"]
ma60 = latest["ma60"]
rsi = latest["rsi"]

if (
    pd.isna(ma5)
    or pd.isna(ma20)
    or pd.isna(ma60)
    or pd.isna(rsi)
):
    return None

ma60_5ago = df.iloc[
    latest_pos - 5
]["ma60"]

volume_today = latest["Volume"]

volume_5avg = (
    df["Volume"]
    .iloc[latest_pos - 5:latest_pos]
    .mean()
)

volume_20avg = (
    df["Volume"]
    .iloc[latest_pos - 20:latest_pos]
    .mean()
)

trade_amount_today = (
    close_price * volume_today
)

trade_amount_20avg = (
    (df["Close"] * df["Volume"])
    .iloc[latest_pos - 20:latest_pos]
    .mean()
)

trade_amount_3avg = (
    (df["Close"] * df["Volume"])
    .iloc[latest_pos - 3:latest_pos]
    .mean()
)

if close_price < PRICE_MIN:
    return None

if marcap < MARCAP_MIN:
    return None

if trade_amount_20avg < TRADE_AMOUNT_20AVG_MIN:
    return None

if trade_amount_today < TRADE_AMOUNT_TODAY_MIN:
    return None

if (
    trade_amount_3avg < trade_amount_20avg * 0.5
    and trade_amount_3avg < TRADE_AMOUNT_20AVG_MIN
):
    return None

trend_ok = (
    close_price > ma20
    and ma20 > ma60
    and ma60 > ma60_5ago
)

high_20d = (
    df["High"]
    .iloc[latest_pos - 20:latest_pos]
    .max()
)

pullback_pct = (
    (close_price - high_20d)
    / high_20d
    * 100
)

recent_high = (
    df["High"]
    .iloc[latest_pos - 5:latest_pos]
    .max()
)

recent_low = (
    df["Low"]
    .iloc[latest_pos - 5:latest_pos]
    .min()
)

high_10d = (
    df["High"]
    .iloc[latest_pos - 10:latest_pos]
    .max()
)

vol_ratio = (
    volume_today / volume_5avg * 100
    if volume_5avg > 0
    else 0
)

pullback_ok = (
    -20 <= pullback_pct <= -5
    and abs(close_price - ma20) / ma20 * 100 < 3
)

entry_a = (
    trend_ok
    and pullback_ok
    and close_price > prev["Close"]
    and close_price > ma5
    and 45 <= rsi <= 65
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
)

if entry_a:
    grade = "A"
    trade_type = "눌림형"
    reason = "눌림 후 재상승"

elif entry_b_safe:
    grade = "A"
    trade_type = "돌파형 안정형"
    reason = "박스권 돌파 안정형"

elif entry_b_aggressive:
    grade = "B"
    trade_type = "돌파형 공격형"
    reason = "박스권 돌파 공격형"

elif trend_ok:
    grade = "C"
    trade_type = "관심"
    reason = "추세 양호"

else:
    return None

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
    "trade_type": trade_type,
    "reason": reason,
    "chart": chart_url,
    "news": news_url,
    "marcap": marcap,
    "buy_zone": (
        f"{int(ma20 * 0.98):,}"
        f" ~ "
        f"{int(ma20 * 1.02):,}"
    ),
    "stop_loss": f"{int(recent_low):,}",
}
```

# =========================

# 출력

# =========================

def show_cards(df):

```
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
            f"**유형:** {row['trade_type']}"
        )

        st.markdown(
            f"**현재가:** "
            f"{fmt_price(row['close'])}"
        )

        st.markdown(
            f"**매수구간:** "
            f"{row['buy_zone']}"
        )

        st.markdown(
            f"**손절가:** "
            f"{row['stop_loss']}"
        )

        st.markdown(
            f"**사유:** "
            f"{row['reason']}"
        )

        st.markdown(
            f"[📈 차트 보기]"
            f"({row['chart']})"
            f" | "
            f"[📰 뉴스 보기]"
            f"({row['news']})"
        )

        with st.expander("📊 상세정보"):

            st.write(
                f"20일선: "
                f"{fmt_price(row['ma20'])}"
            )

            st.write(
                f"RSI: "
                f"{row['rsi']}"
            )

            st.write(
                f"시가총액: "
                f"{fmt_number(row['marcap'])}"
            )
```

# =========================

# 실행

# =========================

if st.button(
"🔍 종목 스캔 시작",
type="primary"
):

```
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

stocks = stocks[
    stocks["Close"] >= PRICE_MIN
]

results = []

progress = st.progress(0)
status = st.empty()

total = len(stocks)

for i, row in enumerate(stocks.itertuples()):

    status.text(
        f"분석 중... "
        f"{i + 1}/{total} "
        f"- {row.Name}"
    )

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

status.text("분석 완료!")

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
```
