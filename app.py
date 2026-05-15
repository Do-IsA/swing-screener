
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
from io import StringIO

warnings.filterwarnings("ignore")

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")
st.title("📈 스윙 종목 스크리너")


def get_kst_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


now_kst = get_kst_now()
st.caption(f"기준일: {now_kst.strftime('%Y-%m-%d')} / KST {now_kst.strftime('%H:%M')}")

PRICE_MIN = 30000
HIGH_PRICE_THRESHOLD = 200000
MARCAP_MIN = 300_000_000_000
TRADE_AMOUNT_20AVG_MIN = 10_000_000_000
TRADE_AMOUNT_TODAY_MIN = 5_000_000_000


st.sidebar.header("💰 시드 계산기")
seed = st.sidebar.number_input("총 시드 (원)", value=2_000_000, step=100_000)
st.sidebar.write(f"1차 매수 (30%): **{int(seed * 0.3):,}원**")
st.sidebar.write(f"추가 매수 (20%): **{int(seed * 0.2):,}원**")
st.sidebar.write(f"최대 비중 (50%): **{int(seed * 0.5):,}원**")
st.sidebar.write(f"최소 현금 (30%): **{int(seed * 0.3):,}원**")
st.sidebar.divider()

view_mode = st.sidebar.radio("보기 방식", ["카드뷰", "표뷰"], index=0)
st.sidebar.divider()

favorite_input = st.sidebar.text_area(
    "⭐ 관심종목 코드",
    value="",
    placeholder="예: 005930,000660,319660"
)
favorite_codes = {c.strip() for c in favorite_input.replace("\n", ",").split(",") if c.strip()}


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

    if not code_map:
        return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"])

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

    return result.reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_stock_list():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Referer": "https://finance.naver.com/",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    frames = []
    logs = []
    markets = {"KOSPI": 0, "KOSDAQ": 1}

    for market_name, sosok in markets.items():
        market_frames = []

        for page in range(1, 80):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"

            try:
                res = requests.get(url, headers=headers, timeout=10)
                res.encoding = "euc-kr"

                if res.status_code != 200:
                    logs.append(f"{market_name} {page}페이지 HTTP {res.status_code}")
                    continue

                result = parse_naver_market_sum_html(res.text)

                if result.empty:
                    if page == 1:
                        logs.append(f"{market_name} 1페이지에서 종목 데이터를 찾지 못했습니다.")
                    break

                market_frames.append(result)

            except Exception as e:
                logs.append(f"{market_name} {page}페이지 로딩 실패: {e}")
                continue

        if market_frames:
            market_df = pd.concat(market_frames, ignore_index=True)
            frames.append(market_df)
            logs.append(f"{market_name}: {len(market_df)}개 로딩")
        else:
            logs.append(f"{market_name}: 로딩된 종목 없음")

    if not frames:
        return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"]), logs

    result_df = pd.concat(frames, ignore_index=True)
    result_df = result_df.drop_duplicates(subset=["Code"]).reset_index(drop=True)
    logs.append(f"전체 종목 수: {len(result_df)}개")

    return result_df, logs


@st.cache_data(ttl=3600, show_spinner=False)
def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except Exception:
        return None


def make_urls(code, name):
    chart_url = f"https://finance.naver.com/item/main.naver?code={code}"
    news_url = f"https://search.naver.com/search.naver?where=news&query={quote(name)}"
    return chart_url, news_url


def fmt_price(value):
    try:
        if pd.isna(value):
            return "-"
        return f"{int(value):,}원"
    except Exception:
        return "-"


def fmt_number(value):
    try:
        if pd.isna(value):
            return "-"
        return f"{int(value):,}"
    except Exception:
        return "-"


def calc_buy_zone(trade_type, close_price, ma20, high_10d):
    if trade_type == "눌림형":
        return round(ma20 * 0.98), round(ma20 * 1.02), "20일선 근처 눌림 매수"
    if trade_type == "돌파형 안정형":
        return round(high_10d * 0.995), round(high_10d * 1.015), "전고점 돌파 후 눌림/재돌파 매수"
    if trade_type == "돌파형 공격형":
        return round(high_10d * 0.99), round(high_10d * 1.02), "강한 돌파 후보, 다음날 눌림 확인"
    return round(close_price * 0.98), round(close_price * 1.01), "관찰"


def calc_stop_loss(trade_type, buy_low, ma20, recent_low):
    if trade_type == "눌림형":
        stop = min(ma20 * 0.97, recent_low * 0.99)
    elif trade_type in ["돌파형 안정형", "돌파형 공격형"]:
        stop = min(buy_low * 0.97, recent_low * 0.99)
    else:
        stop = recent_low * 0.98
    return round(stop)


def make_result(grade, code, name, close_price, ma5, ma20, rsi, volume_today,
                volume_5avg, reason, marcap, pullback, trade_type,
                buy_low, buy_high, stop_loss, strategy, original_grade=None):
    chart_url, news_url = make_urls(code, name)
    return {
        "grade": grade,
        "original_grade": original_grade or grade,
        "name": name,
        "code": code,
        "close": int(close_price),
        "ma5": round(ma5, 0) if pd.notna(ma5) else 0,
        "ma20": round(ma20, 0) if pd.notna(ma20) else 0,
        "rsi": round(rsi, 1) if pd.notna(rsi) else 0,
        "vol_ratio": round(volume_today / volume_5avg * 100, 1) if volume_5avg > 0 else 0,
        "pullback": round(pullback, 1),
        "trade_type": trade_type,
        "buy_zone": f"{buy_low:,} ~ {buy_high:,}",
        "stop_loss": f"{stop_loss:,}",
        "strategy": strategy,
        "reason": reason,
        "chart": chart_url,
        "news": news_url,
        "marcap": marcap,
    }


def analyze_stock(code, name, marcap):
    start = (get_kst_now() - timedelta(days=160)).strftime("%Y-%m-%d")
    df = load_ohlcv(code, start)

    if df is None or len(df) < 80:
        return None

    df["ma5"] = SMAIndicator(df["Close"], window=5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], window=20).sma_indicator()
    df["ma60"] = SMAIndicator(df["Close"], window=60).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], window=14).rsi()

    now = get_kst_now()
    use_today_candle = now.hour > 14 or (now.hour == 14 and now.minute >= 0)

    try:
        latest_pos = len(df) - 1 if use_today_candle else len(df) - 2
        prev_pos = latest_pos - 1
        if latest_pos < 60 or prev_pos < 0:
            return None
        latest = df.iloc[latest_pos]
        prev = df.iloc[prev_pos]
    except Exception:
        return None

    close_price = latest["Close"]
    ma5 = latest["ma5"]
    ma20 = latest["ma20"]
    ma60 = latest["ma60"]
    rsi = latest["rsi"]

    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60) or pd.isna(rsi):
        return None

    try:
        ma60_5ago = df.iloc[latest_pos - 5]["ma60"]
        volume_today = latest["Volume"]
        volume_5avg = df["Volume"].iloc[latest_pos - 5:latest_pos].mean()
        volume_20avg = df["Volume"].iloc[latest_pos - 20:latest_pos].mean()
        trade_amount_today = close_price * volume_today
        trade_amount_20avg = (df["Close"] * df["Volume"]).iloc[latest_pos - 20:latest_pos].mean()
        trade_amount_3avg = (df["Close"] * df["Volume"]).iloc[latest_pos - 3:latest_pos].mean()
    except Exception:
        return None

    if close_price < PRICE_MIN:
        return None
    if marcap < MARCAP_MIN:
        return None
    if trade_amount_20avg < TRADE_AMOUNT_20AVG_MIN:
        return None
    if trade_amount_today < TRADE_AMOUNT_TODAY_MIN:
        return None
    if trade_amount_3avg < trade_amount_20avg * 0.5 and trade_amount_3avg < TRADE_AMOUNT_20AVG_MIN:
        return None

    try:
        surge_3d = ((close_price - df["Close"].iloc[latest_pos - 3]) / df["Close"].iloc[latest_pos - 3]) * 100
        today_change = ((close_price - prev["Close"]) / prev["Close"]) * 100
        prev_body = ((prev["Open"] - prev["Close"]) / prev["Open"]) * 100
    except Exception:
        return None

    if rsi >= 80 or surge_3d >= 25 or today_change >= 25:
        return None
    if prev_body >= 3 and today_change < 2:
        return None

    trend_ok = close_price > ma20 and ma20 > ma60 and ma60 > ma60_5ago

    try:
        high_20d = df["High"].iloc[latest_pos - 20:latest_pos].max()
        pullback_pct = ((close_price - high_20d) / high_20d) * 100
        near_ma20 = abs(close_price - ma20) / ma20 * 100 < 3
        recent_high = df["High"].iloc[latest_pos - 5:latest_pos].max()
        recent_low = df["Low"].iloc[latest_pos - 5:latest_pos].min()
        sideways = (recent_high - recent_low) / recent_low * 100 < 8
        vol_decrease = volume_today < volume_20avg
        high_10d = df["High"].iloc[latest_pos - 10:latest_pos].max()
        vol_ratio = volume_today / volume_5avg * 100 if volume_5avg > 0 else 0
    except Exception:
        return None

    pullback_ok = -20 <= pullback_pct <= -5 and near_ma20 and sideways and vol_decrease

    entry_a = (
        trend_ok and pullback_ok and close_price > prev["Close"] and
        close_price > ma5 and volume_today > prev["Volume"] and
        45 <= rsi <= 65 and close_price > ma20
    )
    entry_b_safe = (
        trend_ok and close_price > high_10d and vol_ratio >= 150 and
        rsi < 70 and close_price <= ma20 * 1.12
    )
    entry_b_aggressive = (
        trend_ok and close_price > high_10d and vol_ratio >= 150 and
        rsi < 72 and close_price <= ma20 * 1.18
    )

    if entry_a:
        grade, trade_type, reason = "A", "눌림형", "눌림 후 재상승"
    elif entry_b_safe:
        grade, trade_type, reason = "A", "돌파형 안정형", "박스권 돌파 안정형"
    elif entry_b_aggressive and not entry_b_safe:
        grade, trade_type, reason = "B", "돌파형 공격형", "박스권 돌파 공격형 / 다음날 눌림 확인"
    elif trend_ok and pullback_ok:
        grade, trade_type, reason = "B", "눌림형", "눌림 형성 중 / 거래량 확인 필요"
    elif trend_ok:
        grade, trade_type, reason = "C", "관심", "추세 양호, 차트 형성 중"
    else:
        return None

    buy_low, buy_high, strategy = calc_buy_zone(trade_type, close_price, ma20, high_10d)
    stop_loss = calc_stop_loss(trade_type, buy_low, ma20, recent_low)

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
    )


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
            },
        )
        return

    for _, row in df.iterrows():
        star = "⭐ " if row.get("code") in favorite_codes else ""

        with st.container(border=True):
            st.markdown(f"### {star}{row.get('name', '-')} ({row.get('code', '-')})")

            if row.get("grade") == "watch_high":
                st.caption(f"원래등급: {row.get('original_grade', '-')}")

            st.markdown(f"**유형:** {row.get('trade_type', '-')}")
            st.markdown(f"**현재가:** {fmt_price(row.get('close'))}")
            st.markdown(f"**매수구간:** {row.get('buy_zone', '-')}")
            st.markdown(f"**손절가:** {row.get('stop_loss', '-')}")
            st.markdown(f"**사유:** {row.get('reason', '-')}")

            st.markdown(
                f"[📈 차트 보기]({row.get('chart', '')})"
                f"  |  "
                f"[📰 뉴스 보기]({row.get('news', '')})"
            )

            with st.expander("📊 상세 정보 보기"):
                st.write(f"**전략:** {row.get('strategy', '-')}")
                st.write(f"**20일선:** {fmt_price(row.get('ma20'))}")
                st.write(f"**5일선:** {fmt_price(row.get('ma5'))}")
                st.write(f"**RSI:** {row.get('rsi', '-')}")
                st.write(f"**거래량비율:** {row.get('vol_ratio', '-')}%")
                st.write(f"**고점대비:** {row.get('pullback', '-')}%")
                st.write(f"**시가총액:** {fmt_number(row.get('marcap'))}원")


if st.button("🔍 종목 스캔 시작", type="primary"):
    with st.spinner("종목 리스트 불러오는 중..."):
        stocks, load_logs = load_stock_list()

    st.subheader("종목 리스트 로딩 로그")

    if load_logs:
        for log in load_logs:
            st.write(log)
    else:
        st.write("로딩 로그가 비어 있습니다.")

    if stocks.empty:
        st.error("종목 리스트를 불러오지 못했습니다.")
        st.stop()

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

        result = analyze_stock(code=row.Code, name=row.Name, marcap=row.Marcap)

        if result:
            if result["grade"] == "watch_high":
                watch_high.append(result)
            else:
                results.append(result)

    status.text("분석 완료!")

    df_result = pd.DataFrame(results)
    df_watch = pd.DataFrame(watch_high)

    base_cols = [
        "name", "code", "close", "ma5", "ma20", "rsi",
        "vol_ratio", "pullback", "trade_type", "buy_zone",
        "stop_loss", "strategy", "reason", "chart", "news", "marcap"
    ]
    watch_cols = [
        "name", "code", "original_grade", "close", "ma5", "ma20",
        "rsi", "vol_ratio", "pullback", "trade_type", "buy_zone",
        "stop_loss", "strategy", "reason", "chart", "news", "marcap"
    ]
    col_names = {
        "name": "종목명",
        "code": "코드",
        "original_grade": "원래등급",
        "close": "현재가",
        "ma5": "5일선",
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
        "marcap": "시가총액",
    }

    tab1, tab2, tab3, tab4 = st.tabs([
        "🟢 A등급 진입검토",
        "🔵 B등급 대기/눌림확인",
        "🟡 C등급 관심",
        "👀 20만원↑ 별도관심",
    ])

    with tab1:
        show_table(df_result[df_result["grade"] == "A"], base_cols) if not df_result.empty else st.write("해당 종목 없음")
    with tab2:
        show_table(df_result[df_result["grade"] == "B"], base_cols) if not df_result.empty else st.write("해당 종목 없음")
    with tab3:
        show_table(df_result[df_result["grade"] == "C"], base_cols) if not df_result.empty else st.write("해당 종목 없음")
    with tab4:
        show_table(df_watch, watch_cols) if not df_watch.empty else st.write("해당 종목 없음")
