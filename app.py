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

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
st.sidebar.header("💰 시드 계산기")
seed = st.sidebar.number_input("총 시드 (원)", value=2000000, step=100000)
st.sidebar.write(f"1차 매수 (30%): **{int(seed*0.3):,}원**")
st.sidebar.write(f"추가 매수 (20%): **{int(seed*0.2):,}원**")
st.sidebar.write(f"최대 비중 (50%): **{int(seed*0.5):,}원**")
st.sidebar.write(f"최소 현금 (30%): **{int(seed*0.3):,}원**")

st.sidebar.divider()
st.sidebar.header("🎯 매도 가격 계산기")
buy_price = st.sidebar.number_input("매수가 (원)", value=0, step=100)
buy_qty   = st.sidebar.number_input("매수 수량 (주)", value=0, step=1)
if buy_price > 0:
    tp1 = int(buy_price * 1.05)
    tp2 = int(buy_price * 1.09)
    sl  = int(buy_price * 0.95)
    st.sidebar.write(f"1차 익절 (+5%): **{tp1:,}원**")
    st.sidebar.write(f"2차 익절 (+9%): **{tp2:,}원**")
    st.sidebar.write(f"손절 (-5%): **{sl:,}원**")
    if buy_qty > 0:
        st.sidebar.write(f"1차 익절 수익: **+{int((tp1-buy_price)*buy_qty):,}원**")
        st.sidebar.write(f"손절 손실: **-{int((buy_price-sl)*buy_qty):,}원**")

st.sidebar.divider()
st.sidebar.header("🔢 수량 계산기")
calc_price = st.sidebar.number_input("종목 현재가 (원)", value=0, step=100, key="calc_price")
if calc_price > 0 and seed > 0:
    qty_1st = int((seed * 0.3) // calc_price)
    qty_max = int((seed * 0.5) // calc_price)
    st.sidebar.write(f"1차 매수 수량: **{qty_1st:,}주** ({int(qty_1st*calc_price):,}원)")
    st.sidebar.write(f"최대 매수 수량: **{qty_max:,}주** ({int(qty_max*calc_price):,}원)")

# ──────────────────────────────────────────────
# 용어 사전
# ──────────────────────────────────────────────
with st.expander("📚 주식 용어 공부 (클릭해서 펼치기)"):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
**📈 차트 용어**
- **이동평균선(MA)**: 일정 기간 종가의 평균선. 5일선·20일선·60일선으로 추세 파악
- **눌림목**: 상승 추세 중 일시적으로 가격이 내려오는 구간. 매수 기회
- **정배열**: 5일선 > 20일선 > 60일선 순서. 강한 상승 추세 신호
- **박스권**: 일정 범위 안에서 횡보하는 구간
- **장대양봉/음봉**: 시가 대비 종가가 크게 오른(양) / 내린(음) 캔들
- **갭상승/하락**: 전일 종가보다 당일 시가가 크게 올라/내려 시작하는 것
        """)
    with col2:
        st.markdown("""
**📊 지표 용어**
- **RSI**: 과매수/과매도 측정 지표. 70 이상 과열, 30 이하 과매도
- **거래량**: 그날 매매된 주식 수. 거래량 증가 = 관심 증가
- **거래대금**: 거래량 × 가격. 실제 돈의 흐름
- **시가총액**: 주가 × 발행주식수. 회사 규모

**💡 매매 용어**
- **스윙매매**: 수일~수주 단위로 매매하는 방식
- **손절**: 손실을 확정하고 파는 것. 더 큰 손실 방지
- **익절**: 수익을 확정하고 파는 것
- **1차 매수**: 전체 매수 물량의 일부만 먼저 사는 것
        """)

# ──────────────────────────────────────────────
# 매매 기록
# ──────────────────────────────────────────────
with st.expander("📝 매매 기록 (클릭해서 펼치기)"):
    if 'trade_log' not in st.session_state:
        st.session_state.trade_log = []

    with st.form("trade_form"):
        tc1, tc2, tc3, tc4, tc5 = st.columns(5)
        with tc1:
            t_date = st.date_input("날짜", value=datetime.today())
        with tc2:
            t_name = st.text_input("종목명")
        with tc3:
            t_price = st.number_input("매수가", value=0, step=100)
        with tc4:
            t_qty = st.number_input("수량", value=0, step=1)
        with tc5:
            t_grade = st.selectbox("등급", ["A", "B", "C"])
        submitted = st.form_submit_button("기록 추가")
        if submitted and t_name and t_price > 0 and t_qty > 0:
            st.session_state.trade_log.append({
                '날짜': t_date.strftime('%Y-%m-%d'),
                '종목명': t_name,
                '매수가': t_price,
                '수량': t_qty,
                '투자금액': t_price * t_qty,
                '1차익절가': int(t_price * 1.05),
                '2차익절가': int(t_price * 1.09),
                '손절가': int(t_price * 0.95),
                '등급': t_grade,
            })
            st.success(f"{t_name} 기록 추가됨!")

    if st.session_state.trade_log:
        df_log = pd.DataFrame(st.session_state.trade_log)
        st.dataframe(df_log, use_container_width=True)
        if st.button("기록 전체 삭제"):
            st.session_state.trade_log = []
            st.rerun()
    else:
        st.info("아직 매매 기록이 없어요.")

st.divider()

# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_stock_list():
    kospi  = fdr.StockListing('KOSPI')
    kosdaq = fdr.StockListing('KOSDAQ')
    # 업종 컬럼 추출 (있으면 사용, 없으면 빈값)
    def extract(df):
        cols = ['Code', 'Name', 'Marcap', 'Close']
        if 'Sector' in df.columns:
            cols.append('Sector')
        elif 'Dept' in df.columns:
            cols.append('Dept')
        result = df[cols].copy()
        if 'Sector' not in result.columns and 'Dept' not in result.columns:
            result['Sector'] = ''
        if 'Dept' in result.columns and 'Sector' not in result.columns:
            result = result.rename(columns={'Dept': 'Sector'})
        return result
    df = pd.concat([extract(kospi), extract(kosdaq)], ignore_index=True)
    df['Sector'] = df['Sector'].fillna('')
    return df

@st.cache_data(ttl=3600)
def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except:
        return None

# ──────────────────────────────────────────────
# 분석 함수
# ──────────────────────────────────────────────
def analyze_stock(code, name, marcap, close, sector=''):
    start = (datetime.today() - timedelta(days=120)).strftime('%Y-%m-%d')
    df = load_ohlcv(code, start)

    if df is None or len(df) < 60:
        return None

    df['ma5']  = SMAIndicator(df['Close'], window=5).sma_indicator()
    df['ma20'] = SMAIndicator(df['Close'], window=20).sma_indicator()
    df['ma60'] = SMAIndicator(df['Close'], window=60).sma_indicator()
    df['rsi']  = RSIIndicator(df['Close'], window=14).rsi()

    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    close_price = latest['Close']
    ma5         = latest['ma5']
    ma20        = latest['ma20']
    ma60        = latest['ma60']
    ma60_5ago   = df.iloc[-6]['ma60'] if len(df) >= 6 else ma60
    rsi         = latest['rsi']

    volume_today = latest['Volume']
    volume_5avg  = df['Volume'].iloc[-6:-1].mean()
    volume_20avg = df['Volume'].iloc[-21:-1].mean()

    trade_amount_today = close_price * volume_today
    trade_amount_20avg = (df['Close'] * df['Volume']).iloc[-21:-1].mean()
    trade_amount_3avg  = (df['Close'] * df['Volume']).iloc[-4:-1].mean()

    if close_price > 200000:
        return {'grade': 'watch_high', 'name': name, 'code': code,
                'close': close_price, 'rsi': round(rsi, 1),
                'sector': sector, 'reason': '20만원 이상 별도관심',
                'naver_url': f"https://finance.naver.com/item/main.naver?code={code}"}

    if not (30000 <= close_price <= 150000): return None
    if marcap < 300_000_000_000:             return None
    if trade_amount_20avg < 10_000_000_000:  return None
    if trade_amount_today < 5_000_000_000:   return None
    if trade_amount_3avg < trade_amount_20avg * 0.5 and trade_amount_3avg < 10_000_000_000:
        return None

    surge_3d     = (close_price - df['Close'].iloc[-4]) / df['Close'].iloc[-4] * 100
    today_change = (close_price - prev['Close']) / prev['Close'] * 100

    if rsi >= 80:
        return _make_result('D', code, name, close_price, ma5, ma20, rsi,
                            volume_today, volume_5avg, 'RSI 80 이상 과열', sector=sector)
    if surge_3d >= 25:
        return _make_result('D', code, name, close_price, ma5, ma20, rsi,
                            volume_today, volume_5avg, '3일 25% 이상 급등', sector=sector)
    if today_change >= 25:
        return _make_result('D', code, name, close_price, ma5, ma20, rsi,
                            volume_today, volume_5avg, '상한가 근처 급등', sector=sector)

    prev_body = (prev['Open'] - prev['Close']) / prev['Open'] * 100
    if prev_body >= 3 and today_change < 2:
        return _make_result('D', code, name, close_price, ma5, ma20, rsi,
                            volume_today, volume_5avg, '장대음봉 후 반등 없음', sector=sector)

    trend_ok = (close_price > ma20) and (ma20 > ma60) and (ma60 > ma60_5ago)

    high_20d     = df['High'].iloc[-21:-1].max()
    pullback_pct = (close_price - high_20d) / high_20d * 100
    near_ma20    = abs(close_price - ma20) / ma20 * 100 < 3
    recent_high  = df['High'].iloc[-6:-1].max()
    recent_low   = df['Low'].iloc[-6:-1].min()
    sideways     = (recent_high - recent_low) / recent_low * 100 < 8
    vol_decrease = volume_today < volume_20avg
    pullback_ok  = (-20 <= pullback_pct <= -5) and near_ma20 and sideways and vol_decrease

    entry_a = (
        trend_ok and pullback_ok and
        close_price > prev['Close'] and
        close_price > ma5 and
        volume_today > prev['Volume'] and
        45 <= rsi <= 65 and
        close_price > ma20
    )

    high_10d  = df['High'].iloc[-11:-1].max()
    vol_ratio = volume_today / volume_5avg * 100 if volume_5avg > 0 else 0

    entry_b_safe = (
        close_price > high_10d and
        vol_ratio >= 150 and
        rsi < 70 and
        close_price <= ma20 * 1.12
    )

    entry_b_aggressive = (
        close_price > high_10d and
        vol_ratio >= 150 and
        rsi < 72 and
        close_price <= ma20 * 1.18
    )

    if entry_a or entry_b_safe:
        grade  = 'A'
        reason = '눌림 후 재상승' if entry_a else '박스권 돌파 안정형'
    elif entry_b_aggressive:
        grade  = 'B'
        reason = '박스권 돌파 공격형 / 눌림 확인 필요'
    elif trend_ok and pullback_ok:
        grade  = 'B'
        reason = '거래량 확인 필요'
    elif trend_ok:
        grade  = 'C'
        reason = '추세 양호, 차트 형성 중'
    else:
        return None

    return _make_result(grade, code, name, close_price, ma5, ma20, rsi,
                        volume_today, volume_5avg, reason, marcap, pullback_pct, sector)


def _make_result(grade, code, name, close, ma5, ma20, rsi,
                 vol, vol5avg, reason, marcap=0, pullback=0, sector=''):
    return {
        'grade':      grade,
        'code':       code,
        'name':       name,
        'sector':     sector,
        'close':      close,
        'ma5':        round(ma5,  0) if ma5  else 0,
        'ma20':       round(ma20, 0) if ma20 else 0,
        'rsi':        round(rsi,  1) if rsi  else 0,
        'vol_ratio':  round(vol / vol5avg * 100, 1) if vol5avg > 0 else 0,
        'pullback':   round(pullback, 1),
        'reason':     reason,
        'marcap':     marcap,
        'naver_url':  f"https://finance.naver.com/item/main.naver?code={code}",
        'news_url':   f"https://finance.naver.com/item/news_news.naver?code={code}",
    }

# ──────────────────────────────────────────────
# 결과 렌더링 헬퍼
# ──────────────────────────────────────────────
def render_table(df_result, grade):
    d = df_result[df_result['grade'] == grade].copy()
    if d.empty:
        st.info("해당 종목 없음")
        return

    cols      = ['name', 'sector', 'code', 'close', 'ma20', 'rsi', 'vol_ratio', 'pullback', 'reason']
    col_names = ['종목명', '업종', '코드', '현재가', '20일선', 'RSI', '거래량비율(%)', '고점대비(%)', '사유']
    display   = d[cols].rename(columns=dict(zip(cols, col_names)))
    st.dataframe(display, use_container_width=True)

    st.markdown("**🔗 네이버 증권 바로가기**")
    link_cols = st.columns(min(len(d), 6))
    for i, (_, row) in enumerate(d.iterrows()):
        with link_cols[i % 6]:
            st.markdown(f"[{row['name']} 차트]({row['naver_url']})")
            st.markdown(f"[{row['name']} 뉴스]({row['news_url']})")

# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────
if st.button("🔍 종목 스캔 시작", type="primary"):
    with st.spinner("종목 리스트 불러오는 중..."):
        stocks = load_stock_list()

    stocks = stocks[stocks['Marcap'] >= 300_000_000_000]
    stocks = stocks[stocks['Close'] >= 30000]

    results    = []
    watch_high = []

    progress = st.progress(0)
    status   = st.empty()
    total    = len(stocks)

    for i, row in enumerate(stocks.itertuples()):
        status.text(f"분석 중... {i+1}/{total} - {row.Name}")
        progress.progress((i+1) / total)
        sector = getattr(row, 'Sector', '')
        result = analyze_stock(row.Code, row.Name, row.Marcap, row.Close, sector)
        if result:
            if result['grade'] == 'watch_high':
                watch_high.append(result)
            else:
                results.append(result)

    status.text("✅ 분석 완료!")
    df_result = pd.DataFrame(results)

    if not df_result.empty:
        a_cnt = len(df_result[df_result['grade'] == 'A'])
        b_cnt = len(df_result[df_result['grade'] == 'B'])
        c_cnt = len(df_result[df_result['grade'] == 'C'])
        d_cnt = len(df_result[df_result['grade'] == 'D'])
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("🟢 A등급", f"{a_cnt}개")
        mc2.metric("🔵 B등급", f"{b_cnt}개")
        mc3.metric("🟡 C등급", f"{c_cnt}개")
        mc4.metric("🔴 D등급", f"{d_cnt}개")

        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["🟢 A등급 진입가능", "🔵 B등급 진입대기",
             "🟡 C등급 관심", "🔴 D등급 제외", "👀 20만원↑ 별도관심"])

        with tab1: render_table(df_result, 'A')
        with tab2: render_table(df_result, 'B')
        with tab3: render_table(df_result, 'C')
        with tab4: render_table(df_result, 'D')
        with tab5:
            if watch_high:
                wh = pd.DataFrame(watch_high)
                st.dataframe(wh[['name','sector','code','close','rsi','reason']], use_container_width=True)
                st.markdown("**🔗 네이버 증권 바로가기**")
                wh_cols = st.columns(min(len(wh), 6))
                for i, (_, row) in enumerate(wh.iterrows()):
                    with wh_cols[i % 6]:
                        st.markdown(f"[{row['name']} 차트]({row['naver_url']})")
            else:
                st.info("해당 종목 없음")
    else:
        st.warning("조건에 맞는 종목이 없어요.")
