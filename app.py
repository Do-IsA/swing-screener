import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator
from datetime import datetime, timedelta
from urllib.parse import quote
import warnings

warnings.filterwarnings("ignore")

st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")
st.title("📈 스윙 종목 스크리너")
st.caption(f"기준일: {datetime.today().strftime('%Y-%m-%d')}")

# =========================
# 설정값
# =========================

PRICE_MIN = 30_000
HIGH_PRICE_THRESHOLD = 200_000

MARCAP_MIN = 300_000_000_000          # 3,000억
TRADE_AMOUNT_20AVG_MIN = 10_000_000_000   # 100억
TRADE_AMOUNT_TODAY_MIN = 5_000_000_000    # 50억

# =========================
# 사이드바
# =========================

st.sidebar.header("💰 시드 계산기")
seed = st.sidebar.number_input("총 시드 (원)", value=2_000_000, step=100_000)

st.sidebar.write(f"1차 매수 (30%): **{int(seed * 0.3):,}원**")
st.sidebar.write(f"추가 매수 (20%): **{int(seed * 0.2):,}원**")
st.sidebar.write(f"최대 비중 (50%): **{int(seed * 0.5):,}원**")
st.sidebar.write(f"최소 현금 (30%): **{int(seed * 0.3):,}원**")

view_mode = st.sidebar.radio(
    "보기 방식",
    ["카드뷰", "표뷰"],
    index=0
)

st.sidebar.divider()
use_sector = st.sidebar.checkbox("섹터 정보 표시", value=True)

# =========================
# 데이터 로드
# =========================

@st.cache_data(ttl=3600)
def load_stock_list():
    kospi = fdr.StockListing("KOSPI")[["Code", "Name", "Marcap", "Close"]]
    kosdaq = fdr.StockListing("KOSDAQ")[["Code", "Name", "Marcap", "Close"]]
    return pd.concat([kospi, kosdaq], ignore_index=True)


@st.cache_data(ttl=3600)
def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except Exception:
        return None


@st.cache_data(ttl=86400)
def load_sector_map():
    """
    pykrx가 설치되어 있으면 섹터/지수 구성 정보를 불러옴.
    실패하면 빈 dict 반환.
    """
    try:
        from pykrx import stock

        sector_map = {}
        date = datetime.today().strftime("%Y%m%d")

        for market in ["KOSPI", "KOSDAQ"]:
            try:
                index_codes = stock.get_index_ticker_list(date, market=market)
            except Exception:
                continue

            for index_code in index_codes:
                try:
                    index_name = stock.get_index_ticker_name(index_code)
                    tickers = stock.get_index_portfolio_deposit_file(index_code, date)

                    for ticker in tickers:
                        if ticker not in sector_map:
                            sector_map[ticker] = index_name

                except Exception:
                    continue

        return sector_map

    except Exception:
        return {}


# =========================
# 계산 함수
# =========================

def make_urls(code, name):
    chart_url = f"https://finance.naver.com/item/main.naver?code={code}"
    news_url = f"https://search.naver.com/search.naver?where=news&query={quote(name)}"
    return chart_url, news_url


def calc_buy_zone(trade_type, close_price, ma20, high_10d):
    if trade_type == "눌림형":
        buy_low = ma20 * 0.98
        buy_high = ma20 * 1.02
        strategy = "20일선 근처 눌림 매수"

    elif trade_type == "돌파형 안정형":
        buy_low = high_10d * 0.995
        buy_high = high_10d * 1.015
        strategy = "전고점 돌파 후 눌림/재돌파 매수"

    elif trade_type == "돌파형 공격형":
        buy_low = high_10d * 0.99
        buy_high = high_10d * 1.02
        strategy = "강한 돌파 후보, 다음날 눌림 확인"

    else:
        buy_low = close_price * 0.98
        buy_high = close_price * 1.01
        strategy = "관찰"

    return round(buy_low), round(buy_high), strategy


def calc_stop_loss(trade_type, buy_low, ma20, recent_low):
    if trade_type == "눌림형":
        stop = min(ma20 * 0.97, recent_low * 0.99)

    elif trade_type in ["돌파형 안정형", "돌파형 공격형"]:
        stop = min(buy_low * 0.97, recent_low * 0.99)

    else:
        stop = recent_low * 0.98

    return round(stop)


def make_result(
    grade,
    code,
    name,
    close_price,
    ma5,
    ma20,
    rsi,
    volume_today,
    volume_5avg,
    reason,
    marcap,
    pullback,
    trade_type,
    buy_low,
    buy_high,
    stop_loss,
    strategy,
    sector="-",
    original_grade=None
):
    chart_url, news_url = make_urls(code, name)

    return {
        "grade": grade,
        "original_grade": original_grade or grade,
        "name": name,
        "code": code,
        "sector": sector,
        "close": int(close_price),
        "ma5": round(ma5, 0) if ma5 else 0,
        "ma20": round(ma20, 0) if ma20 else 0,
        "rsi": round(rsi, 1) if rsi else 0,
        "vol_ratio": round(volume_today / volume_5avg * 100, 1) if volume_5avg > 0 else 0,
        "pullback": round(pullback, 1),
        "trade_type": trade_type,
        "buy_zone": f"{buy_low:,} ~ {buy_high:,}" if buy_low else "-",
        "stop_loss": f"{stop_loss:,}" if stop_loss else "-",
        "strategy": strategy,
        "reason": reason,
        "chart": chart_url,
        "news": news_url,
        "marcap": marcap,
    }


# =========================
# 종목 분석
# =========================

def analyze_stock(code, name, marcap, sector="-"):
    start = (datetime.today() - timedelta(days=140)).strftime("%Y-%m-%d")
    df = load_ohlcv(code, start)

    if df is None or len(df) < 70:
        return None

    df["ma5"] = SMAIndicator(df["Close"], window=5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], window=20).sma_indicator()
    df["ma60"] = SMAIndicator(df["Close"], window=60).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], window=14).rsi()

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    close_price = latest["Close"]
    ma5 = latest["ma5"]
    ma20 = latest["ma20"]
    ma60 = latest["ma60"]
    ma60_5ago = df.iloc[-6]["ma60"]
    rsi = latest["rsi"]

    volume_today = latest["Volume"]
    volume_5avg = df["Volume"].iloc[-6:-1].mean()
    volume_20avg = df["Volume"].iloc[-21:-1].mean()

    trade_amount_today = close_price * volume_today
    trade_amount_20avg = (df["Close"] * df["Volume"]).iloc[-21:-1].mean()
    trade_amount_3avg = (df["Close"] * df["Volume"]).iloc[-4:-1].mean()

    # 기본 필터
    if close_price < PRICE_MIN:
        return None

    if marcap < MARCAP_MIN:
        return None

    if trade_amount_20avg < TRADE_AMOUNT_20AVG_MIN:
        return None

    if trade_amount_today < TRADE_AMOUNT_TODAY_MIN:
        return None

    # 최근 거래대금이 너무 죽은 종목 제외
    if trade_amount_3avg < trade_amount_20avg * 0.5 and trade_amount_3avg < TRADE_AMOUNT_20AVG_MIN:
        return None

    # 과열/위험 제외
    surge_3d = (close_price - df["Close"].iloc[-4]) / df["Close"].iloc[-4] * 100
    today_change = (close_price - prev["Close"]) / prev["Close"] * 100

    if rsi >= 80:
        return None

    if surge_3d >= 25:
        return None

    if today_change >= 25:
        return None

    # 장대음봉 후 반등 없음 제외
    prev_body = (prev["Open"] - prev["Close"]) / prev["Open"] * 100
    if prev_body >= 3 and today_change < 2:
        return None

    # 추세 조건
    trend_ok = (
        close_price > ma20 and
        ma20 > ma60 and
        ma60 > ma60_5ago
    )

    # 눌림 조건
    high_20d = df["High"].iloc[-21:-1].max()
    pullback_pct = (close_price - high_20d) / high_20d * 100

    near_ma20 = abs(close_price - ma20) / ma20 * 100 < 3

    recent_high = df["High"].iloc[-6:-1].max()
    recent_low = df["Low"].iloc[-6:-1].min()

    sideways = (recent_high - recent_low) / recent_low * 100 < 8
    vol_decrease = volume_today < volume_20avg

    pullback_ok = (
        -20 <= pullback_pct <= -5 and
        near_ma20 and
        sideways and
        vol_decrease
    )

    # entry A: 눌림 후 재상승
    entry_a = (
        trend_ok and
        pullback_ok and
        close_price > prev["Close"] and
        close_price > ma5 and
        volume_today > prev["Volume"] and
        45 <= rsi <= 65 and
        close_price > ma20
    )

    # entry B: 박스권 돌파
    high_10d = df["High"].iloc[-11:-1].max()
    vol_ratio = volume_today / volume_5avg * 100 if volume_5avg > 0 else 0

    entry_b_safe = (
        trend_ok and
        close_price > high_10d and
        vol_ratio >= 150 and
        rsi < 70 and
        close_price <= ma20 * 1.12
    )

    entry_b_aggressive = (
        trend_ok and
        close_price > high_10d and
        vol_ratio >= 150 and
        rsi < 72 and
        close_price <= ma20 * 1.18
    )

    # 등급 결정
    if entry_a:
        grade = "A"
        trade_type = "눌림형"
        reason = "눌림 후 재상승"

    elif entry_b_safe:
        grade = "A"
        trade_type = "돌파형 안정형"
        reason = "박스권 돌파 안정형"

    elif entry_b_aggressive and not entry_b_safe:
        grade = "B"
        trade_type = "돌파형 공격형"
        reason = "박스권 돌파 공격형 / 다음날 눌림 확인"

    elif trend_ok and pullback_ok:
        grade = "B"
        trade_type = "눌림형"
        reason = "눌림 형성 중 / 거래량 확인 필요"

    elif trend_ok:
        grade = "C"
        trade_type = "관심"
        reason = "추세 양호, 차트 형성 중"

    else:
        return None

    buy_low, buy_high, strategy = calc_buy_zone(
        trade_type,
        close_price,
        ma20,
        high_10d
    )

    stop_loss = calc_stop_loss(
        trade_type,
        buy_low,
        ma20,
        recent_low
    )

    # 별도관심 기준:
    # 조건을 모두 통과한 종목 중, 현재가가 20만원 이상인 종목만 별도 탭으로 이동
    if close_price >= HIGH_PRICE_THRESHOLD:
        return make_result(
            grade="watch_high",
            original_grade=grade,
            code=code,
            name=name,
            close_price=close_price,
            ma5=ma5,
            ma20=ma20,
            rsi=rsi,
            volume_today=volume_today,
            volume_5avg=volume_5avg,
            reason=f"20만원 이상 별도관심 / 원래 등급: {grade} / {reason}",
            marcap=marcap,
            pullback=pullback_pct,
            trade_type=trade_type,
            buy_low=buy_low,
            buy_high=buy_high,
            stop_loss=stop_loss,
            strategy=strategy,
            sector=sector,
        )

    return make_result(
        grade=grade,
        code=code,
        name=name,
        close_price=close_price,
        ma5=ma5,
        ma20=ma20,
        rsi=rsi,
        volume_today=volume_today,
        volume_5avg=volume_5avg,
        reason=reason,
        marcap=marcap,
        pullback=pullback_pct,
        trade_type=trade_type,
        buy_low=buy_low,
        buy_high=buy_high,
        stop_loss=stop_loss,
        strategy=strategy,
        sector=sector,
    )


# =========================
# 실행
# =========================

if st.button("🔍 종목 스캔 시작", type="primary"):
    with st.spinner("종목 리스트 불러오는 중..."):
        stocks = load_stock_list()

    sector_map = {}
    if use_sector:
        with st.spinner("섹터 정보 불러오는 중..."):
            sector_map = load_sector_map()

    # 1차 필터
    stocks = stocks[stocks["Marcap"] >= MARCAP_MIN]
    stocks = stocks[stocks["Close"] >= PRICE_MIN]

    results = []
    watch_high = []

    progress = st.progress(0)
    status = st.empty()
    total = len(stocks)

    for i, row in enumerate(stocks.itertuples()):
        status.text(f"분석 중... {i + 1}/{total} - {row.Name}")
        progress.progress((i + 1) / total)

        sector = sector_map.get(row.Code, "-") if sector_map else "-"

        result = analyze_stock(
            code=row.Code,
            name=row.Name,
            marcap=row.Marcap,
            sector=sector
        )

        if result:
            if result["grade"] == "watch_high":
                watch_high.append(result)
            else:
                results.append(result)

    status.text("분석 완료!")

    df_result = pd.DataFrame(results)
    df_watch = pd.DataFrame(watch_high)

    base_cols = [
        "name", "code", "sector", "close", "ma20", "rsi",
        "vol_ratio", "pullback", "trade_type",
        "buy_zone", "stop_loss", "strategy", "reason",
        "chart", "news"
    ]

    watch_cols = [
        "name", "code", "sector", "original_grade", "close", "ma20", "rsi",
        "vol_ratio", "pullback", "trade_type",
        "buy_zone", "stop_loss", "strategy", "reason",
        "chart", "news"
    ]

    col_names = {
        "name": "종목명",
        "code": "코드",
        "sector": "섹터",
        "original_grade": "원래등급",
        "close": "현재가",
        "ma20": "20일선",
        "rsi": "RSI",
        "vol_ratio": "거래량비율(%)",
        "pullback": "고점대비(%)",
        "trade_type": "유형",
        "buy_zone": "매수구간",
        "stop_loss": "손절가",
        "strategy": "전략",
        "reason": "사유",
        "chart": "차트",
        "news": "뉴스",
    }

    tab1, tab2, tab3, tab4 = st.tabs([
        "🟢 A등급 진입검토",
        "🔵 B등급 대기/눌림확인",
        "🟡 C등급 관심",
        "👀 20만원↑ 별도관심"
    ])

    def show_table(df, cols):
    if df.empty:
        st.write("해당 종목 없음")
        return

    display_df = df[cols].rename(columns=col_names)

    if view_mode == "표뷰":
        st.dataframe(
            display_df,
            use_container_width=True,
            column_config={
                "차트": st.column_config.LinkColumn("차트", display_text="차트 보기"),
                "뉴스": st.column_config.LinkColumn("뉴스", display_text="뉴스 보기"),
            }
        )
        return

    # 모바일 친화 카드뷰
    for _, row in df.iterrows():
        with st.container(border=True):
            st.markdown(f"### {row['name']} ({row['code']})")

            if "original_grade" in row and pd.notna(row.get("original_grade")):
                st.caption(f"원래등급: {row['original_grade']}")

            st.write(f"**섹터**: {row.get('sector', '-')}")
            st.write(f"**현재가**: {int(row['close']):,}원")
            st.write(f"**유형**: {row.get('trade_type', '-')}")
            st.write(f"**사유**: {row.get('reason', '-')}")

            st.divider()

            st.write(f"**매수구간**: {row.get('buy_zone', '-')}")
            st.write(f"**손절가**: {row.get('stop_loss', '-')}")
            st.write(f"**전략**: {row.get('strategy', '-')}")

            st.divider()

            col1, col2 = st.columns(2)
            with col1:
                st.metric("RSI", row.get("rsi", "-"))
                st.metric("고점대비", f"{row.get('pullback', '-')}%")
            with col2:
                st.metric("거래량비율", f"{row.get('vol_ratio', '-')}%")
                st.metric("20일선", f"{int(row.get('ma20', 0)):,}원")

            st.markdown(
                f"[차트 보기]({row['chart']})  |  [뉴스 보기]({row['news']})"
            )

    with tab1:
        if not df_result.empty:
            show_table(df_result[df_result["grade"] == "A"], base_cols)
        else:
            st.write("해당 종목 없음")

    with tab2:
        if not df_result.empty:
            show_table(df_result[df_result["grade"] == "B"], base_cols)
        else:
            st.write("해당 종목 없음")

    with tab3:
        if not df_result.empty:
            show_table(df_result[df_result["grade"] == "C"], base_cols)
        else:
            st.write("해당 종목 없음")

    with tab4:
        show_table(df_watch, watch_cols)
