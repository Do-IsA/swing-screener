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


def get_kst_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo("Asia/Seoul"))
    return datetime.now()


now_kst = get_kst_now()

scan_basis_date = "-"

try:
    sample_df = fdr.DataReader(
        "005930",
        (get_kst_now() - timedelta(days=10)).strftime("%Y-%m-%d"),
    )

    if sample_df is not None and len(sample_df) >= 2:
        market_closed = now_kst.hour > 15 or (
            now_kst.hour == 15 and now_kst.minute >= 30
        )
        latest_pos = len(sample_df) - 1 if market_closed else len(sample_df) - 2
        scan_basis_date = str(sample_df.index[latest_pos].date())

except Exception:
    scan_basis_date = "-"
    
scan_basis_date = get_global_basis_date()

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
    if result.empty:
        return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"])

    result["Code"] = result["Code"].astype(str).str.zfill(6)
    result = result[result["Code"].str.match(r"^\d{6}$", na=False)]
    result = result.drop_duplicates(subset=["Code"])
    return result.reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_stock_list():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        ),
        "Referer": "https://finance.naver.com/",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    frames, logs = [], []
    markets = {"KOSPI": 0, "KOSDAQ": 1}
    max_page = 45

    for market_name, sosok in markets.items():
        market_frames = []
        seen_codes = set()
        empty_page_count = 0
        for page in range(1, max_page + 1):
            url = (
                f"https://finance.naver.com/sise/sise_market_sum.naver"
                f"?sosok={sosok}&page={page}"
            )
            try:
                res = requests.get(url, headers=headers, timeout=10)
                res.encoding = "euc-kr"
                if res.status_code != 200:
                    logs.append(f"{market_name} {page}페이지 HTTP {res.status_code}")
                    continue

                page_df = parse_naver_market_sum_html(res.text)
                if page_df.empty:
                    empty_page_count += 1
                    if page == 1:
                        logs.append(f"{market_name} 1페이지에서 종목 데이터를 찾지 못했습니다.")
                    if empty_page_count >= 2:
                        break
                    continue

                empty_page_count = 0
                page_codes = set(page_df["Code"].astype(str))
                new_codes = page_codes - seen_codes
                if not new_codes:
                    logs.append(f"{market_name} {page}페이지 신규 종목 없음 → 종료")
                    break

                seen_codes.update(page_codes)
                page_df = page_df[page_df["Code"].isin(new_codes)].drop_duplicates(
                    subset=["Code"]
                )
                if not page_df.empty:
                    market_frames.append(page_df)
            except Exception as e:
                logs.append(f"{market_name} {page}페이지 로딩 실패: {e}")
                continue

        if market_frames:
            market_df = pd.concat(market_frames, ignore_index=True).drop_duplicates(
                subset=["Code"]
            )
            frames.append(market_df)
            logs.append(f"{market_name}: {len(market_df)}개 로딩")
        else:
            logs.append(f"{market_name}: 로딩된 종목 없음")

    if not frames:
        return pd.DataFrame(columns=["Code", "Name", "Marcap", "Close"]), logs

    result_df = pd.concat(frames, ignore_index=True)
    result_df["Code"] = result_df["Code"].astype(str).str.zfill(6)
    result_df = result_df[result_df["Code"].str.match(r"^\d{6}$", na=False)]
    result_df = result_df.drop_duplicates(subset=["Code"]).reset_index(drop=True)
    logs.append(f"원자료 종목 수: {len(result_df):,}개")
    return result_df, logs


def apply_base_filters(stocks):
    logs = []
    before = len(stocks)
    stocks = stocks.copy()
    stocks["Code"] = stocks["Code"].astype(str).str.zfill(6)
    stocks["Name"] = stocks["Name"].astype(str)
    stocks["Marcap"] = pd.to_numeric(stocks["Marcap"], errors="coerce")
    stocks["Close"] = pd.to_numeric(stocks["Close"], errors="coerce")
    stocks = stocks.dropna(subset=["Code", "Name", "Marcap", "Close"])
    logs.append(f"원자료 정리 후: {len(stocks):,}개 / 최초 {before:,}개")

    pattern = "|".join([re.escape(x) for x in EXCLUDE_KEYWORDS])
    stocks = stocks[
        ~stocks["Name"].str.contains(pattern, case=False, regex=True, na=False)
    ]
    stocks = stocks[
        ~stocks["Name"].str.contains(r"우$|우B$|우C$|우선주", regex=True, na=False)
    ]
    logs.append(f"ETF/ETN/스팩/리츠/우선주 제외 후: {len(stocks):,}개")

    stocks = stocks[stocks["Marcap"] >= MARCAP_MIN]
    logs.append(f"시총 {MARCAP_MIN:,}원 이상 필터 후: {len(stocks):,}개")
    logs.append("가격 필터는 analyze_stock()의 기준봉 종가로 적용")
    return stocks.reset_index(drop=True), logs


@st.cache_data(ttl=3600, show_spinner=False)
def load_ohlcv(code, start):
    try:
        return fdr.DataReader(code, start)
    except Exception:
        return None
        
def get_latest_pos(df):
    now = get_kst_now()

    market_closed = (
        now.hour > 15
        or (now.hour == 15 and now.minute >= 30)
    )

    return len(df) - 1 if market_closed else len(df) - 2
    
def get_basis_date_for_code(code):
    start = (get_kst_now() - timedelta(days=160)).strftime("%Y-%m-%d")

    df = load_ohlcv(code, start)

    if df is None or len(df) < 2:
        return "-"

    try:
        latest_pos = get_latest_pos(df)
        return str(df.index[latest_pos].date())
    except Exception:
        return "-"



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
    return round(stop)


def make_result(
    grade, code, name, close_price, ma5, ma20, rsi,
    volume_today, volume_5avg, reason, marcap, pullback,
    trade_type, buy_low, buy_high, stop_loss, strategy,
    basis_date,
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
    
    # 장중/장후 기준봉 위치 확정
    now = get_kst_now()
    market_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 30)
    try:
        latest_pos = len(df) - 1 if market_closed else len(df) - 2
        prev_pos = latest_pos - 1
        if latest_pos < 60 or prev_pos < 0:
            return None

        basis_date = str(df.index[latest_pos].date())
    except Exception:
        return None

    # ── 조기 탈출: 가격 필터 (지표 계산 전) ──────────────────────
    close_price = df["Close"].iloc[latest_pos]
    if close_price < PRICE_MIN:
        return None

    # ── 지표 계산 ─────────────────────────────────────────────────
    df["ma5"] = SMAIndicator(df["Close"], window=5).sma_indicator()
    df["ma20"] = SMAIndicator(df["Close"], window=20).sma_indicator()
    df["ma60"] = SMAIndicator(df["Close"], window=60).sma_indicator()
    df["rsi"] = RSIIndicator(df["Close"], window=14).rsi()

    # 지표 계산 후 latest/prev 재할당 (KeyError 방지 핵심)
    latest = df.iloc[latest_pos]
    prev = df.iloc[prev_pos]

    ma5 = latest["ma5"]
    ma20 = latest["ma20"]
    ma60 = latest["ma60"]
    rsi = latest["rsi"]

    if pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60) or pd.isna(rsi):
        return None

    # ── 거래량 / 거래대금 계산 ────────────────────────────────────
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

    # ── 거래대금 필터 ─────────────────────────────────────────────
    if trade_amount_20avg < TRADE_AMOUNT_20AVG_MIN:
        return None
    if trade_amount_today < TRADE_AMOUNT_TODAY_MIN:
        return None
    # OR 조건: 둘 중 하나라도 해당하면 거래 죽은 종목
    if (
        trade_amount_3avg < trade_amount_20avg * 0.5
        and trade_amount_3avg < TRADE_AMOUNT_20AVG_MIN
    ):
        return None

    # ── 과열 / 급등 필터 ──────────────────────────────────────────
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

    # ── 추세 / 눌림 조건 계산 ─────────────────────────────────────
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

    # pullback_ok: 핵심 2개 필수 / sideways·vol_decrease는 entry_a에서 확인
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
        and not entry_b_safe  # 명시적 분리
    )

    # ── 등급 결정 ─────────────────────────────────────────────────
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

    # ── 20만원 이상 watch_high 분류 ───────────────────────────────
    if close_price >= HIGH_PRICE_THRESHOLD:
        return make_result(
            "watch_high", code, name, close_price, ma5, ma20, rsi,
            volume_today, volume_5avg,
            f"20만원 이상 별도관심 / 원래 등급: {grade} / {reason}",
            marcap, pullback_pct, trade_type,
            buy_low, buy_high, stop_loss, strategy,
            basis_date,
            original_grade=grade,
        )

    return make_result(
        grade, code, name, close_price, ma5, ma20, rsi,
        volume_today, volume_5avg, reason,
        marcap, pullback_pct, trade_type,
        buy_low, buy_high, stop_loss, strategy,
        basis_date,
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
        lines.append(
            f"[{row['grade']}] {row['name']} ({row['code']})\n"
            f"현재가: {row['close']:,}원\n"
            f"매수구간: {row['buy_zone']}\n"
            f"손절가: {row['stop_loss']}\n"
            f"사유: {row['reason']}\n"
        )

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

    basis_date_preview = get_basis_date_for_code(stocks.iloc[0]["Code"])
    st.success(
        f"📅 분석 기준봉 : {basis_date_preview}"
    )

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
    
        copy_button(
            make_copy_text(d),
            "copy_a"
        )

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
