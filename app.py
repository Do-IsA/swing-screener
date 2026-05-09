import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")
st.title("📈 스윙 종목 스크리너")
st.caption(f"기준일: {datetime.today().strftime('%Y-%m-%d')}")

# 사이드바 - 시드 계산기
st.sidebar.header("💰 시드 계산기")
seed = st.sidebar.number_input("총 시드 (원)", value=2000000, step=100000)
st.sidebar.write(f"1차 매수 (30%): **{int(seed*0.3):,}원**")
st.sidebar.write(f"추가 매수 (20%): **{int(seed*0.2):,}원**")
st.sidebar.write(f"최대 비중 (50%): **{int(seed*0.5):,}원**")
st.sidebar.write(f"최소 현금 (30%): **{int(seed*0.3):,}원**")


@st.cache_data(ttl=3600)
def load_stock_list():
    kospi = fdr.StockListing('KOSPI')[['Code', 'Name', 'Marcap', 'Close']]
    kosdaq = fdr.StockListing('KOSDAQ')[['Code', 'Name', 'Marcap', 'Close']]
    return pd.concat([kospi, kosdaq], ignore_index=True)


@st.cache_data(ttl=3600)
def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except:
        return None


def calc_buy_zone(trade_type, close_price, ma20, high_10d):
    """
    자동 매수 구간 계산
    - 눌림형: 20일선 근처
    - 돌파형: 10일 고점 돌파선 근처
    """
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
    """
    자동 손절가 계산
    """
    if trade_type == "눌림형":
        stop = min(ma20 * 0.97, recent_low * 0.99)

    elif trade_type in ["돌파형 안정형", "돌파형 공격형"]:
        stop = min(buy_low * 0.97, recent_low * 0.99)

    else:
        stop = recent_low * 0.98

    return round(stop)


def _make_result(
    grade, code, name, close, ma5, ma20, rsi,
    vol, vol5avg, reason, marcap=0, pullback=0,
    trade_type="기타", buy_low=0, buy_high=0,
    stop_loss=0, strategy=""
):
    return {
        'grade': grade,
        'code': code,
        'name': name,
        'close': int(close),
        'ma5': round(ma5, 0) if ma5 else 0,
        'ma20': round(ma20, 0) if ma20 else 0,
        'rsi': round(rsi, 1) if rsi else 0,
        'vol_ratio': round(vol / vol5avg * 100, 1) if vol5avg > 0 else 0,
        'pullback': round(pullback, 1),
        'trade_type': trade_type,
        'buy_zone': f"{buy_low:,} ~ {buy_high:,}" if buy_low else "-",
        'stop_loss': f"{stop_loss:,}" if stop_loss else "-",
        'strategy': strategy,
        'reason': reason,
        'marcap': marcap
    }


def analyze_stock(code, name, marcap, close):
    start = (datetime.today() - timedelta(days=140)).strftime('%Y-%m-%d')
    df = load_ohlcv(code, start)

    if df is None or len(df) < 70:
        return None

    # 이동평균선
    df['ma5'] = SMAIndicator(df['Close'], window=5).sma_indicator()
    df['ma20'] = SMAIndicator(df['Close'], window=20).sma_indicator()
    df['ma60'] = SMAIndicator(df['Close'], window=60).sma_indicator()

    # RSI
    df['rsi'] = RSIIndicator(df['Close'], window=14).rsi()

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    close_price = latest['Close']
    ma5 = latest['ma5']
    ma20 = latest['ma20']
    ma60 = latest['ma60']
    ma60_5ago = df.iloc[-6]['ma60']
    rsi = latest['rsi']

    volume_today = latest['Volume']
    volume_5avg = df['Volume'].iloc[-6:-1].mean()
    volume_20avg = df['Volume'].iloc[-21:-1].mean()

    trade_amount_today = close_price * volume_today
    trade_amount_20avg = (df['Close'] * df['Volume']).iloc[-21:-1].mean()
    trade_amount_3avg = (df['Close'] * df['Volume']).iloc[-4:-1].mean()

    # 20만원 이상은 별도 관심
    if close_price > 200000:
        return {
            'grade': 'watch_high',
            'name': name,
            'code': code,
            'close': int(close_price),
            'rsi': round(rsi, 1) if rsi else 0,
            'reason': '20만원 이상 별도관심'
        }

    # 기본 제외 조건
    if not (30000 <= close_price <= 150000):
        return None

    if marcap < 300_000_000_000:  # 3000억
        return None

    if trade_amount_20avg < 10_000_000_000:  # 100억
        return None

    if trade_amount_today < 5_000_000_000:  # 50억
        return None

    # 최근 거래대금이 너무 죽은 종목 제외
    if trade_amount_3avg < trade_amount_20avg * 0.5 and trade_amount_3avg < 10_000_000_000:
        return None

    # 과열 제외 조건
    surge_3d = (close_price - df['Close'].iloc[-4]) / df['Close'].iloc[-4] * 100
    today_change = (close_price - prev['Close']) / prev['Close'] * 100

    if rsi >= 80:
        return None

    if surge_3d >= 25:
        return None

    # 상한가 근처 제외
    if today_change >= 25:
        return None

    # 장대음봉 후 반등 없음 제외
    prev_body = (prev['Open'] - prev['Close']) / prev['Open'] * 100
    if prev_body >= 3 and today_change < 2:
        return None

    # 추세 조건
    trend_ok = (
        close_price > ma20 and
        ma20 > ma60 and
        ma60 > ma60_5ago
    )

    # 눌림목 조건
    high_20d = df['High'].iloc[-21:-1].max()
    pullback_pct = (close_price - high_20d) / high_20d * 100
    near_ma20 = abs(close_price - ma20) / ma20 * 100 < 3

    recent_high = df['High'].iloc[-6:-1].max()
    recent_low = df['Low'].iloc[-6:-1].min()
    sideways = (recent_high - recent_low) / recent_low * 100 < 8
    vol_decrease = volume_today < volume_20avg

    pullback_ok = (
        -20 <= pullback_pct <= -5 and
        near_ma20 and
        sideways and
        vol_decrease
    )

    # 진입가능 A: 눌림 후 재상승
    entry_a = (
        trend_ok and
        pullback_ok and
        close_price > prev['Close'] and
        close_price > ma5 and
        volume_today > prev['Volume'] and
        45 <= rsi <= 65 and
        close_price > ma20
    )

    # 박스권 돌파 조건
    high_10d = df['High'].iloc[-11:-1].max()
    vol_ratio = volume_today / volume_5avg * 100 if volume_5avg > 0 else 0

    # 돌파형 안정형: 초보용 A등급
    entry_b_safe = (
        trend_ok and
        close_price > high_10d and
        vol_ratio >= 150 and
        rsi < 70 and
        close_price <= ma20 * 1.12
    )

    # 돌파형 공격형: 좋지만 눌림 확인 필요한 B등급
    entry_b_aggressive = (
        trend_ok and
        close_price > high_10d and
        vol_ratio >= 150 and
        rsi < 72 and
        close_price <= ma20 * 1.18
    )

    # 등급/유형 결정
    if entry_a:
        grade = 'A'
        trade_type = '눌림형'
        reason = '눌림 후 재상승'

    elif entry_b_safe:
        grade = 'A'
        trade_type = '돌파형 안정형'
        reason = '박스권 돌파 안정형'

    elif entry_b_aggressive:
        grade = 'B'
        trade_type = '돌파형 공격형'
        reason = '박스권 돌파 공격형 / 다음날 눌림 확인'

    elif trend_ok and pullback_ok:
        grade = 'B'
        trade_type = '눌림형'
        reason = '눌림 형성 중 / 거래량 확인 필요'

    elif trend_ok:
        grade = 'C'
        trade_type = '관심'
        reason = '추세 양호, 차트 형성 중'

    else:
        return None

    buy_low, buy_high, strategy = calc_buy_zone(
        trade_type, close_price, ma20, high_10d
    )

    stop_loss = calc_stop_loss(
        trade_type, buy_low, ma20, recent_low
    )

    return _make_result(
        grade, code, name, close_price, ma5, ma20, rsi,
        volume_today, volume_5avg, reason,
        marcap, pullback_pct,
        trade_type, buy_low, buy_high,
        stop_loss, strategy
    )


# 메인 실행
if st.button("🔍 종목 스캔 시작", type="primary"):
    with st.spinner("종목 리스트 불러오는 중..."):
        stocks = load_stock_list()

    # 1차 필터
    stocks = stocks[stocks['Marcap'] >= 300_000_000_000]
    stocks = stocks[stocks['Close'] >= 30000]

    results = []
    watch_high = []

    progress = st.progress(0)
    status = st.empty()
    total = len(stocks)

    for i, row in enumerate(stocks.itertuples()):
        status.text(f"분석 중... {i+1}/{total} - {row.Name}")
        progress.progress((i+1) / total)

        result = analyze_stock(row.Code, row.Name, row.Marcap, row.Close)

        if result:
            if result['grade'] == 'watch_high':
                watch_high.append(result)
            else:
                results.append(result)

    status.text("분석 완료!")

    df_result = pd.DataFrame(results)

    if not df_result.empty:
        tab1, tab2, tab3, tab4 = st.tabs([
            "🟢 A등급 진입검토",
            "🔵 B등급 대기/눌림확인",
            "🟡 C등급 관심",
            "👀 20만원↑ 별도관심"
        ])

        cols = [
            'name', 'code', 'close', 'ma20', 'rsi',
            'vol_ratio', 'pullback', 'trade_type',
            'buy_zone', 'stop_loss', 'strategy', 'reason'
        ]

        col_names = [
            '종목명', '코드', '현재가', '20일선', 'RSI',
            '거래량비율(%)', '고점대비(%)', '유형',
            '매수구간', '손절가', '전략', '사유'
        ]

        with tab1:
            d = df_result[df_result['grade'] == 'A'][cols]
            st.dataframe(
                d.rename(columns=dict(zip(cols, col_names))),
                use_container_width=True
            )

        with tab2:
            d = df_result[df_result['grade'] == 'B'][cols]
            st.dataframe(
                d.rename(columns=dict(zip(cols, col_names))),
                use_container_width=True
            )

        with tab3:
            d = df_result[df_result['grade'] == 'C'][cols]
            st.dataframe(
                d.rename(columns=dict(zip(cols, col_names))),
                use_container_width=True
            )

        with tab4:
            if watch_high:
                st.dataframe(pd.DataFrame(watch_high), use_container_width=True)
            else:
                st.write("해당 종목 없음")

    else:
        st.warning("조건에 맞는 종목이 없습니다.")
