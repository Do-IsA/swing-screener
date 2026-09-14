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

st.set_page_config(page_title="스윙 종목 스크리너", layout="wide")
st.title("📈 스윙 종목 스크리너")


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
    "KODEX", "TIGER", "ACE", "SOL", "RISE", "PLUS", "HANARO",
    "KBSTAR", "ARIRANG", "KOSEF", "TIMEFOLIO", "TIME", "TREX", "마이티",
]


# =========================
# 유틸 함수 (실행 코드보다 먼저 정의)
# =========================
def get_kst_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


@st.cache_data(ttl=3600, show_spinner=False)
def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except Exception:
        return None


def get_latest_pos(df):
    now = get_kst_now()
    is_weekday = now.weekday() < 5
    is_market_hours = is_weekday and (
        (now.hour > 9 or (now.hour == 9 and now.minute >= 0))
        and (now.hour < 15 or (now.hour == 15 and now.minute < 30))
    )
    return len(df) - 2 if is_market_hours else len(df) - 1


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
# 페이지 상단 — 기준시간 표시
# =========================
now_kst = get_kst_now()
scan_basis_date = get_global_basis_date()
basis_date = scan_basis_date  # analyze_stock() 에서 전역으로 참조

st.caption(
    f"기준시간: {now_kst.strftime('%Y-%m-%d %H:%M')} KST "
    f"/ 실제 분석봉: {scan_basis_date}"
)

st.markdown(
    """
    <style>
    div[data-testid="stVerticalBlockBorderWrapper"] {padding:0.55rem 0.65rem!important;border-radius:0.7rem!important;}
    div[data-testid="stExpander"] details {font-size:0.82rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


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

st.sidebar.divider()
favorite_input = st.sidebar.text_area(
    "⭐ 관심종목 코드", value="", placeholder="예: 005930,000660,319660"
)
favorite_codes = {
    code.strip().zfill(6)
    for code in favorite_input.replace("\n", ",").split(",")
    if code.strip()
}

st.sidebar.divider()

if st.sidebar.button("🔄 데이터 캐시 초기화"):
    st.cache_data.clear()
    st.rerun()


# =========================
# 종목 리스트
# =========================
@st.cache_data(ttl=3600, show_spinner=False)
def load_stock_list():
    logs = []
    df = None
    
    # 1차 시도: KRX 전체 상장종목
    try:
        df = fdr.StockListing("KRX")
    except Exception as e:
        logs.append(f"KRX 호출 실패: {e}")

    # 2차 시도: 1차가 비어있으면 KOSPI + KOSDAQ 개별 호출
    if df is None or df.empty:
        try:
            df_kospi = fdr.StockListing("KOSPI")
            df_kosdaq = fdr.StockListing("KOSDAQ")
            df = pd.concat([df_kospi, df_kosdaq], ignore_index=True)
        except Exception as e:
            logs.append(f"KOSPI/KOSDAQ 개별 호출 실패: {e}")

    if df is None or df.empty:
        return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"]), logs

    df = df.copy()

    # FinanceDataReader 버전에 따른 컬럼명 대응 (Code/Symbol 매핑)
    col_rename = {}
    if "Symbol" in df.columns and "Code" not in df.columns:
        col_rename["Symbol"] = "Code"
    if "Stocks" in df.columns and "Marcap" not in df.columns:
        # 시총 컬럼이 없을 경우 주식수 * 종가 계산 대비
        pass
    df = df.rename(columns=col_rename)

    # 필수 컬럼 존재 여부 확인
    for req_col in ["Code", "Name", "Close"]:
        if req_col not in df.columns:
            logs.append(f"필수 컬럼 누락: {req_col} (현재 컬럼 목록: {list(df.columns)})")
            return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"]), logs

    # Marcap 컬럼이 없으면 0으로 채움
    if "Marcap" not in df.columns:
        df["Marcap"] = 0

    df["Code"] = df["Code"].astype(str).str.zfill(6)
    df["Marcap"] = pd.to_numeric(df["Marcap"], errors="coerce").fillna(0)
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce").fillna(0)

    df = df.dropna(subset=["Code", "Name"])
    logs.append(f"원자료 종목 수: {len(df):,}개")
    return df[["Code", "Name", "Marcap", "Close"]].reset_index(drop=True), logs

def apply_base_filters(stocks):
    logs = []
    before = len(stocks)
    stocks = stocks.copy()
    stocks["Code"] = stocks["Code"].astype(str).str.zfill(6)
    stocks["Name"] = stocks["Name"].astype(str)
    stocks["Marcap"] = pd.to_numeric(stocks["Marcap"], errors="coerce").fillna(0)
    stocks["Close"] = pd.to_numeric(stocks["Close"], errors="coerce").fillna(0)
    stocks = stocks.dropna(subset=["Code", "Name", "Marcap", "Close"])
    logs.append(f"원자료 정리 후: {len(stocks):,}개 / 최초 {before:,}개")

    # FinanceDataReader의 Marcap 단위 자동 보정 (억원/백만원 단위 대응)
    max_marcap = stocks["Marcap"].max()
    if max_marcap < 1_000_000_000:  # 최대 시총(삼성전자 등)이 10억 미만으로 잡혀있다면 '억원' 단위임
        stocks["Marcap"] = stocks["Marcap"] * 100_000_000
    elif max_marcap < 100_000_000_000:  # 백만원 단위 대응
        stocks["Marcap"] = stocks["Marcap"] * 1_000_000

    # 제외 키워드 필터링
    pattern = "|".join([re.escape(x) for x in EXCLUDE_KEYWORDS])
    stocks = stocks[
        ~stocks["Name"].str.contains(pattern, case=False, regex=True, na=False)
    ]
    stocks = stocks[
        ~stocks["Name"].str.contains(r"우$|우B$|우C$|우선주", regex=True, na=False)
    ]
    logs.append(f"ETF/ETN/스팩/리츠/우선주 제외 후: {len(stocks):,}개")

    # 시가총액 필터 적용
    stocks = stocks[stocks["Marcap"] >= MARCAP_MIN]
    logs.append(f"시총 {MARCAP_MIN:,}원 이상 필터 후: {len(stocks):,}개")
    return stocks.reset_index(drop=True), logs


def make_urls(code, name):
    return (
        f"https://finance.naver.com/item/main.naver?code={code}",
        f"https://search.naver.com/search.naver?where=news&query={quote(name)}",
    )

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
    stop = min(stop, buy_low * 0.99)  # 손절가는 항상 매수하단보다 낮게
    return round(stop)


def make_result(
    grade, code, name, close_price, ma5, ma20, rsi,
    volume_today, volume_5avg, reason, marcap, pullback,
    trade_type, buy_low, buy_high, stop_loss, strategy,
    original_grade=None,
):
    chart_url, news_url = make_urls(code, name)
    return {
        "grade": grade,
        "original_grade": original_grade or grade,
        "name": name,
        "code": str(code).zfill(6),
        "basis_date": basis_date,
        "close": int(close_price),
        "ma5": round(ma5, 0) if pd.notna(ma5) else 0,
        "ma20": round(ma20, 0) if pd.notna(ma20) else 0,
        "rsi": round(rsi, 1) if pd.notna(rsi) else 0,
        "vol_ratio": round(volume_today / volume_5avg * 100, 1) if volume_5avg > 0 else 0,
        "pullback": round(pullback, 1),
        "trade_type": trade_type,
        "buy_low_raw": buy_low,
        "buy_high_raw": buy_high,
        "stop_loss_raw": stop_loss,
        "buy_zone": f"{buy_low:,} ~ {buy_high:,}" if buy_low else "-",
        "stop_loss": f"{stop_loss:,}" if stop_loss else "-",
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

    try:
        latest_pos = get_latest_pos(df)
        prev_pos = latest_pos - 1
        if latest_pos < 60 or prev_pos < 0:
            return None
    except Exception:
        return None

    close_price = df["Close"].iloc[latest_pos]
    if close_price < PRICE_MIN:
        return None

    df["ma5"] = SMAIndicator(df["Close"], window=5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], window=20).sma_indicator()
    df["ma60"] = SMAIndicator(df["Close"], window=60).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], window=14).rsi()

    latest = df.iloc[latest_pos]
    prev = df.iloc[prev_pos]

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

    if trade_amount_20avg < TRADE_AMOUNT_20AVG_MIN:
        return None
    if trade_amount_today < TRADE_AMOUNT_TODAY_MIN:
        return None
    if (
        trade_amount_3avg < trade_amount_20avg * 0.5
        and trade_amount_3avg < TRADE_AMOUNT_20AVG_MIN
    ):
        return None

    try:
        surge_3d = (
            (close_price - df["Close"].iloc[latest_pos - 3])
            / df["Close"].iloc[latest_pos - 3]
        ) * 100
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

    pullback_ok = -15 <= pullback_pct <= -3 and near_ma20

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
            "watch_high", code, name, close_price, ma5, ma20, rsi,
            volume_today, volume_5avg,
            f"20만원 이상 별도관심 / 원래 등급: {grade} / {reason}",
            marcap, pullback_pct, trade_type,
            buy_low, buy_high, stop_loss, strategy,
            original_grade=grade,
        )

    return make_result(
        grade, code, name, close_price, ma5, ma20, rsi,
        volume_today, volume_5avg, reason,
        marcap, pullback_pct, trade_type,
        buy_low, buy_high, stop_loss, strategy,
    )


# =========================
# 카드 / 표 렌더링
# =========================
col_names = {
    "name": "종목명", "code": "코드", "original_grade": "원래등급",
    "close": "현재가", "ma5": "5일선", "ma20": "20일선", "rsi": "RSI",
    "vol_ratio": "거래량비율(%)", "pullback": "고점대비(%)", "trade_type": "유형",
    "buy_zone": "매수구간", "stop_loss": "손절가", "strategy": "전략",
    "reason": "사유", "chart": "차트", "news": "뉴스", "marcap": "시가총액",
}

base_cols = [
    "name", "code", "close", "ma5", "ma20", "rsi", "vol_ratio", "pullback",
    "trade_type", "buy_zone", "stop_loss", "strategy", "reason", "chart", "news", "marcap",
]
watch_cols = [
    "name", "code", "original_grade", "close", "ma5", "ma20", "rsi", "vol_ratio", "pullback",
    "trade_type", "buy_zone", "stop_loss", "strategy", "reason", "chart", "news", "marcap",
]


def show_table(df, cols):
    if df is None or df.empty:
        st.write("해당 종목 없음")
        return

    display_df = df[cols].rename(columns=col_names)

    st.dataframe(
        display_df,
        use_container_width=True,
        column_config={
            "차트": st.column_config.LinkColumn("차트", display_text="차트 보기"),
            "뉴스": st.column_config.LinkColumn("뉴스", display_text="뉴스 보기"),
        },
    )


def get_favorite_df(df_result, df_watch):
    frames = []
    if df_result is not None and not df_result.empty:
        frames.append(df_result.copy())
    if df_watch is not None and not df_watch.empty:
        frames.append(df_watch.copy())
    if not frames:
        return pd.DataFrame()
    all_df = pd.concat(frames, ignore_index=True)
    all_df["code"] = all_df["code"].astype(str).str.zfill(6)
    return all_df[all_df["code"].isin(favorite_codes)]


def make_copy_text(df):
    if df is None or df.empty:
        return "해당 종목 없음"

    lines = []
    for _, row in df.iterrows():
        grade = row.get("original_grade", row["grade"])
        lines.append("\t".join([
            str(row.get("basis_date", "")),
            row["name"],
            row["code"],
            grade,
            row["trade_type"],
            str(row["close"]),
            str(int(row["ma20"])),
            str(row["rsi"]),
            str(row["vol_ratio"]),
            str(row["pullback"]),
            row["buy_zone"],
            row["stop_loss"],
            "",   # 익일종가(확인용) — 직접 입력
            "",   # 진입가 — 직접 입력
        ]))
    return "\n".join(lines)


import streamlit.components.v1 as components


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


# =========================
# 메인 실행
# =========================
col_scan1, col_scan2 = st.columns(2)

with col_scan1:
    scan_full = st.button(
        "🚀 전체 종목 스캔",
        use_container_width=True,
        type="primary"
    )

with col_scan2:
    scan_favorites = st.button(
        "⭐ 관심종목 스캔",
        use_container_width=True
    )

if scan_full or scan_favorites:
    with st.spinner("종목 리스트 불러오는 중..."):
        stocks, load_logs = load_stock_list()

    if stocks.empty:
        st.error("종목 리스트를 불러오지 못했습니다.")
        st.write("발생한 에러 로그:", load_logs)  # <--- 이 줄 추가
        st.stop()

    stocks, filter_logs = apply_base_filters(stocks)

    if scan_favorites:
        if not favorite_codes:
            st.warning("관심종목 코드가 없습니다. 사이드바에 종목코드를 먼저 입력해 주세요.")
            st.stop()
        stocks = stocks[stocks["Code"].isin(favorite_codes)]
        if stocks.empty:
            st.warning("입력한 관심종목 코드가 기본 필터를 통과하지 못했거나 종목 리스트에 없습니다.")
            st.stop()

    if stocks.empty:
        st.warning("기본 필터 통과 종목이 없습니다.")
        st.stop()

    st.success(f"실제 분석 대상: {len(stocks):,}개")

    results, watch_high = [], []
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

    df_result = pd.DataFrame(results) if results else pd.DataFrame()
    df_watch = pd.DataFrame(watch_high) if watch_high else pd.DataFrame()

    a_count = len(df_result[df_result["grade"] == "A"]) if not df_result.empty else 0
    b_count = len(df_result[df_result["grade"] == "B"]) if not df_result.empty else 0
    c_count = len(df_result[df_result["grade"] == "C"]) if not df_result.empty else 0
    watch_count = len(df_watch)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        f"🟢 A등급 ({a_count})",
        f"🔵 B등급 ({b_count})",
        f"🟡 C등급 ({c_count})",
        f"👀 20만원↑ ({watch_count})",
        f"⭐ 관심종목 ({len(favorite_codes)})",
    ])

    with tab1:
        d = df_result[df_result["grade"] == "A"] if not df_result.empty else pd.DataFrame()
        copy_button(make_copy_text(d), "copy_a")
        show_table(d, base_cols)

    with tab2:
        d = df_result[df_result["grade"] == "B"] if not df_result.empty else pd.DataFrame()
        copy_button(make_copy_text(d), "copy_b")
        show_table(d, base_cols)

    with tab3:
        d = df_result[df_result["grade"] == "C"] if not df_result.empty else pd.DataFrame()
        copy_button(make_copy_text(d), "copy_c")
        show_table(d, base_cols)

    with tab4:
        copy_button(make_copy_text(df_watch), "copy_watch")
        show_table(df_watch, watch_cols)

    with tab5:
        if not favorite_codes:
            st.write("사이드바에 관심종목 코드를 입력해 주세요.")
        else:
            fav_df = get_favorite_df(df_result, df_watch)
            if fav_df.empty:
                st.write("오늘 스크리닝 결과에 포함된 관심종목이 없습니다.")
            else:
                show_table(
                    fav_df,
                    watch_cols if "original_grade" in fav_df.columns else base_cols,
                )
                copy_button(make_copy_text(fav_df), "copy_fav")
