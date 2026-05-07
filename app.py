import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator
from datetime import datetime, timedelta
import urllib.parse
import random
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")

# ──────────────────────────────────────────────
# 용어 데이터
# ──────────────────────────────────────────────
ALL_TERMS = [
    ("이동평균선(MA)", "일정 기간 종가의 평균을 이은 선. 5일·20일·60일선으로 추세 파악"),
    ("눌림목", "상승 추세 중 일시적으로 가격이 내려오는 구간. 스윙 매수 기회"),
    ("정배열", "5일선 > 20일선 > 60일선 순서. 강한 상승 추세 신호"),
    ("역배열", "5일선 < 20일선 < 60일선 순서. 하락 추세 신호"),
    ("박스권", "일정 가격 범위 안에서 횡보하는 구간"),
    ("장대양봉", "시가 대비 종가가 크게 오른 캔들. 강한 매수세 신호"),
    ("장대음봉", "시가 대비 종가가 크게 내린 캔들. 강한 매도세 신호"),
    ("갭상승", "전일 종가보다 당일 시가가 높게 시작하는 것"),
    ("갭하락", "전일 종가보다 당일 시가가 낮게 시작하는 것"),
    ("RSI", "상대강도지수. 70 이상 과열(매도 검토), 30 이하 과매도(매수 검토)"),
    ("거래량", "그날 매매된 주식 수. 거래량 급증은 큰 수급 변화 신호"),
    ("거래대금", "거래량 × 가격. 실제 자금 흐름을 나타냄"),
    ("시가총액", "주가 × 발행주식수. 회사 전체 가치"),
    ("스윙매매", "수일~수주 단위로 추세를 타고 매매하는 방식"),
    ("손절", "손실을 확정하고 파는 것. 더 큰 손실 방지를 위해 필수"),
    ("익절", "수익을 확정하고 파는 것"),
    ("물타기", "하락 중 추가 매수해 평균 단가를 낮추는 것. 위험 수반"),
    ("불타기", "상승 중 추가 매수해 수익을 극대화하는 것"),
    ("저항선", "주가 상승을 막는 가격대. 돌파 시 강한 매수 신호"),
    ("지지선", "주가 하락을 막는 가격대. 이탈 시 추가 하락 신호"),
    ("골든크로스", "단기선이 장기선을 상향 돌파. 매수 신호"),
    ("데드크로스", "단기선이 장기선을 하향 돌파. 매도 신호"),
    ("상한가", "하루 주가 상승 한도(+30%). 강한 매수세 신호"),
    ("하한가", "하루 주가 하락 한도(-30%). 강한 매도세 신호"),
    ("시가", "당일 첫 번째 체결 가격"),
    ("종가", "당일 마지막 체결 가격. 차트 분석 기준"),
    ("캔들차트", "시가·고가·저가·종가 4가지를 하나의 막대로 표현한 차트"),
    ("볼린저밴드", "이동평균선과 표준편차로 만든 상하 밴드. 변동성 파악"),
    ("MACD", "단기·장기 이동평균 차이로 추세 전환 파악하는 지표"),
    ("수급", "사려는 힘(수요)과 팔려는 힘(공급)의 균형"),
    ("공매도", "주식을 빌려서 팔고 나중에 되사는 것. 하락에 베팅"),
    ("PER", "주가/주당순이익. 낮을수록 저평가 가능성"),
    ("PBR", "주가/주당순자산. 1 이하면 자산 대비 저평가"),
    ("EPS", "주당순이익. 회사가 주식 1주당 얼마나 벌었는지"),
    ("배당수익률", "주당 배당금/주가. 배당 투자 매력도 지표"),
    ("유상증자", "회사가 새 주식을 발행해 자금 조달. 기존 주주 지분 희석"),
    ("자사주매입", "회사가 자기 주식을 사들이는 것. 주가 부양 효과"),
    ("외국인순매수", "외국인이 산 주식 - 판 주식. 플러스면 매수 우위"),
    ("기관순매수", "기관이 산 주식 - 판 주식. 큰 자금 유입 신호"),
    ("신고가", "역대 또는 52주 최고가 경신. 강한 상승 모멘텀 신호"),
]

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("💰 시드 계산기")
    seed = st.number_input("총 시드 (원)", value=2000000, step=100000)
    c1, c2 = st.columns(2)
    c1.metric("1차 매수 30%", f"{int(seed*0.3):,}원")
    c1.metric("추가 매수 20%", f"{int(seed*0.2):,}원")
    c2.metric("최대 비중 50%", f"{int(seed*0.5):,}원")
    c2.metric("최소 현금 30%", f"{int(seed*0.3):,}원")

    st.divider()
    st.header("🔢 수량 계산기")
    calc_price = st.number_input("현재가 (원)", value=0, step=100, key="calc_price")
    if calc_price > 0 and seed > 0:
        qty_1st = int((seed * 0.3) // calc_price)
        qty_max = int((seed * 0.5) // calc_price)
        st.write(f"1차: **{qty_1st}주** ({int(qty_1st*calc_price):,}원)")
        st.write(f"최대: **{qty_max}주** ({int(qty_max*calc_price):,}원)")

    st.divider()
    st.header("🎯 매도 계산기")
    buy_price = st.number_input("매수가 (원)", value=0, step=100)
    buy_qty   = st.number_input("수량 (주)", value=0, step=1)
    if buy_price > 0:
        tp1 = int(buy_price * 1.05)
        tp2 = int(buy_price * 1.09)
        sl  = int(buy_price * 0.95)
        st.write(f"1차 익절 +5%: **{tp1:,}원**")
        st.write(f"2차 익절 +9%: **{tp2:,}원**")
        st.write(f"손절 -5%: **{sl:,}원**")
        if buy_qty > 0:
            st.write(f"익절 수익: **+{int((tp1-buy_price)*buy_qty):,}원**")
            st.write(f"손절 손실: **-{int((buy_price-sl)*buy_qty):,}원**")

    st.divider()
    st.header("📚 오늘의 용어")
    if 'today_terms' not in st.session_state:
        st.session_state.today_terms = random.sample(ALL_TERMS, 3)
    for term, desc in st.session_state.today_terms:
        st.markdown(f"**{term}**")
        st.caption(desc)
    if st.button("🔀 다른 용어", use_container_width=True):
        st.session_state.today_terms = random.sample(ALL_TERMS, 3)
        st.rerun()

# ──────────────────────────────────────────────
# 메인 헤더
# ──────────────────────────────────────────────
st.title("📈 스윙 종목 스크리너")
st.caption(f"기준일: {datetime.today().strftime('%Y-%m-%d')}  |  장 마감 후(15:30~) 실행 권장")

# ──────────────────────────────────────────────
# 매매 기록 (컴팩트)
# ──────────────────────────────────────────────
with st.expander("📝 매매 기록", expanded=False):
    if 'trade_log' not in st.session_state:
        st.session_state.trade_log = []
    col_a, col_b, col_c, col_d, col_e, col_f = st.columns([2,2,2,1,1,1])
    with col_a: t_name  = st.text_input("종목명", key="t_name", label_visibility="collapsed", placeholder="종목명")
    with col_b: t_price = st.number_input("매수가", value=0, step=100, key="t_price", label_visibility="collapsed")
    with col_c: t_qty   = st.number_input("수량", value=0, step=1, key="t_qty", label_visibility="collapsed")
    with col_d: t_grade = st.selectbox("등급", ["A","B","C"], key="t_grade", label_visibility="collapsed")
    with col_e: t_date  = st.date_input("날짜", value=datetime.today(), key="t_date", label_visibility="collapsed")
    with col_f:
        if st.button("➕ 추가", use_container_width=True):
            if t_name and t_price > 0 and t_qty > 0:
                st.session_state.trade_log.append({
                    '날짜': t_date.strftime('%Y-%m-%d'), '종목명': t_name,
                    '매수가': t_price, '수량': t_qty,
                    '투자금액': t_price * t_qty,
                    '1차익절': int(t_price*1.05), '2차익절': int(t_price*1.09),
                    '손절가': int(t_price*0.95), '등급': t_grade,
                })
                st.rerun()
    if st.session_state.trade_log:
        st.dataframe(pd.DataFrame(st.session_state.trade_log), use_container_width=True, height=180)
        if st.button("🗑 전체 삭제", type="secondary"):
            st.session_state.trade_log = []
            st.rerun()
    else:
        st.caption("아직 매매 기록이 없어요.")

st.divider()

# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_stock_list():
    kospi  = fdr.StockListing('KOSPI')[['Code','Name','Marcap','Close']]
    kosdaq = fdr.StockListing('KOSDAQ')[['Code','Name','Marcap','Close']]
    df = pd.concat([kospi, kosdaq], ignore_index=True)
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
def analyze_stock(code, name, marcap, close):
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
                'close': close_price, 'rsi': round(rsi,1),
                'reason': '20만원 이상 별도관심',
                'naver_url': f"https://finance.naver.com/item/main.naver?code={code}",
                'news_url': f"https://search.naver.com/search.naver?where=news&query={urllib.parse.quote(name)}+주식&sort=1",
                'buy_recommend': 0, 'tp1': 0, 'tp2': 0, 'sl': 0}

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
                            volume_today, volume_5avg, 'RSI 80 이상 과열')
    if surge_3d >= 25:
        return _make_result('D', code, name, close_price, ma5, ma20, rsi,
                            volume_today, volume_5avg, '3일 25% 이상 급등')
    if today_change >= 25:
        return _make_result('D', code, name, close_price, ma5, ma20, rsi,
                            volume_today, volume_5avg, '상한가 근처 급등')

    prev_body = (prev['Open'] - prev['Close']) / prev['Open'] * 100
    if prev_body >= 3 and today_change < 2:
        return _make_result('D', code, name, close_price, ma5, ma20, rsi,
                            volume_today, volume_5avg, '장대음봉 후 반등 없음')

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

    # 매수 추천가 계산
    if entry_a:
        # 눌림목: 20일선 근처 매수
        buy_recommend = int(ma20 * 1.005)
    elif entry_b_safe or entry_b_aggressive:
        # 박스권 돌파: 현재가 기준
        buy_recommend = int(close_price)
    else:
        buy_recommend = int(close_price)

    return _make_result(grade, code, name, close_price, ma5, ma20, rsi,
                        volume_today, volume_5avg, reason, marcap, pullback_pct,
                        buy_recommend)


def _make_result(grade, code, name, close, ma5, ma20, rsi,
                 vol, vol5avg, reason, marcap=0, pullback=0, buy_recommend=0):
    br = buy_recommend if buy_recommend > 0 else int(close)
    return {
        'grade':         grade,
        'code':          code,
        'name':          name,
        'close':         close,
        'ma5':           round(ma5,  0) if ma5  else 0,
        'ma20':          round(ma20, 0) if ma20 else 0,
        'rsi':           round(rsi,  1) if rsi  else 0,
        'vol_ratio':     round(vol / vol5avg * 100, 1) if vol5avg > 0 else 0,
        'pullback':      round(pullback, 1),
        'reason':        reason,
        'marcap':        marcap,
        'buy_recommend': br,
        'tp1':           int(br * 1.05),
        'tp2':           int(br * 1.09),
        'sl':            int(br * 0.95),
        'naver_url':     f"https://finance.naver.com/item/main.naver?code={code}",
        'news_url':      f"https://search.naver.com/search.naver?where=news&query={urllib.parse.quote(name)}+주식&sort=1",
    }

# ──────────────────────────────────────────────
# 결과 렌더링
# ──────────────────────────────────────────────
def render_table(df_result, grade):
    d = df_result[df_result['grade'] == grade].copy()
    if d.empty:
        st.info("해당 종목 없음")
        return

    cols      = ['name','code','close','ma20','rsi','vol_ratio','pullback','buy_recommend','tp1','tp2','sl','reason']
    col_names = ['종목명','코드','현재가','20일선','RSI','거래량비율(%)','고점대비(%)','매수추천가','1차익절','2차익절','손절가','사유']
    st.dataframe(d[cols].rename(columns=dict(zip(cols, col_names))), use_container_width=True)

    # 종목별 뉴스 링크 (컴팩트)
    st.markdown("##### 🔗 종목별 바로가기")
    for _, row in d.iterrows():
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.write(f"**{row['name']}** ({row['code']})")
        with col2:
            st.markdown(f"[📊 차트]({row['naver_url']})")
        with col3:
            st.markdown(f"[📰 뉴스]({row['news_url']})")

# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────
col_btn1, col_btn2 = st.columns([1, 5])
with col_btn1:
    scan_clicked = st.button("🔍 종목 스캔 시작", type="primary", use_container_width=True)
with col_btn2:
    if 'scan_time' in st.session_state:
        st.caption(f"마지막 스캔: {st.session_state.scan_time}")

if scan_clicked:
    with st.spinner("종목 리스트 불러오는 중..."):
        stocks = load_stock_list()

    stocks = stocks[stocks['Marcap'] >= 300_000_000_000]
    stocks = stocks[stocks['Close'] >= 30000]

    results    = []
    watch_high = []
    progress   = st.progress(0)
    status     = st.empty()
    total      = len(stocks)

    for i, row in enumerate(stocks.itertuples()):
        status.text(f"분석 중... {i+1}/{total} - {row.Name}")
        progress.progress((i+1) / total)
        result = analyze_stock(row.Code, row.Name, row.Marcap, row.Close)
        if result:
            if result['grade'] == 'watch_high':
                watch_high.append(result)
            else:
                results.append(result)

    status.text("✅ 분석 완료!")
    st.session_state.scan_results    = results
    st.session_state.scan_watch_high = watch_high
    st.session_state.scan_time       = datetime.now().strftime('%Y-%m-%d %H:%M')

if 'scan_results' not in st.session_state:
    st.info("스캔 버튼을 눌러 종목 분석을 시작하세요.")
    st.stop()

results    = st.session_state.scan_results
watch_high = st.session_state.scan_watch_high
df_result  = pd.DataFrame(results)

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
            st.dataframe(wh[['name','code','close','rsi','reason']], use_container_width=True)
            for _, row in wh.iterrows():
                col1, col2, col3 = st.columns([2,1,1])
                with col1: st.write(f"**{row['name']}** ({row['code']})")
                with col2: st.markdown(f"[📊 차트]({row['naver_url']})")
                with col3: st.markdown(f"[📰 뉴스]({row['news_url']})")
        else:
            st.info("해당 종목 없음")
else:
    st.warning("조건에 맞는 종목이 없어요.")
