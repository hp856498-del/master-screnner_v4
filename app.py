import streamlit as st
import pandas as pd
import requests
import ta
import pytz
import concurrent.futures
from datetime import datetime

st.set_page_config(page_title="Master Screener v2", layout="wide")

# ================= SESSION =================
for key in ["rsi_results", "pattern_results", "matches"]:
    if key not in st.session_state:
        st.session_state[key] = []

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc

# ================= COMMON =================
def get_top_symbols(limit):
    exchange = requests.get("https://api.binance.com/api/v3/exchangeInfo").json()
    valid = {s["symbol"] for s in exchange["symbols"]
             if s["status"] == "TRADING" and s["quoteAsset"] == "USDT"}

    ticker = requests.get("https://api.binance.com/api/v3/ticker/24hr").json()
    filtered = [x for x in ticker if x["symbol"] in valid]

    sorted_pairs = sorted(filtered, key=lambda x: float(x["quoteVolume"]), reverse=True)
    return [x["symbol"] for x in sorted_pairs[:limit]]

# ================= LAYOUT =================
col1, col2, col3 = st.columns(3)

# =========================================================
# ================= RSI (LEFT) =================
# =========================================================
with col1:
    st.header("🔥 RSI Divergence")

    rsi_date = st.date_input("Date", key="rsi_date")
    rsi_tf = st.selectbox("TF", ["15m","30m","1h","2h","4h","1d"], key="rsi_tf")
    rsi_limit = st.selectbox("Coins", [50,100,200,400], key="rsi_limit")

    def get_rsi_data(sym):
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={rsi_tf}&limit=200"
        data = requests.get(url).json()

        if isinstance(data, dict):
            return None

        df = pd.DataFrame(data, columns=["time","o","h","l","c","v","ct","q","n","tb","tq","ig"])
        df["c"]=df["c"].astype(float)
        df["h"]=df["h"].astype(float)
        df["l"]=df["l"].astype(float)

        df["time"]=pd.to_datetime(df["time"], unit='ms')
        df["time"]=df["time"].dt.tz_localize('UTC').dt.tz_convert(IST)

        return df

    def find_pivots(df):
        ph, pl = [], []
        for i in range(3, len(df)-2):
            if df["h"][i] == max(df["h"][i-3:i+3]):
                ph.append(i)
            if df["l"][i] == min(df["l"][i-3:i+3]):
                pl.append(i)
        return ph, pl

    def check_div(df):
        df["rsi"] = ta.momentum.RSIIndicator(df["c"], window=14).rsi()
        ph, pl = find_pivots(df)

        times=[]
        for i in range(1,len(pl)):
            if df["l"][pl[i]]<df["l"][pl[i-1]] and df["rsi"][pl[i]]>df["rsi"][pl[i-1]]:
                times.append(df["time"][pl[i]])

        for i in range(1,len(ph)):
            if df["h"][ph[i]]>df["h"][ph[i-1]] and df["rsi"][ph[i]]<df["rsi"][ph[i-1]]:
                times.append(df["time"][ph[i]])

        return times

    def scan_rsi(sym):
        try:
            df = get_rsi_data(sym)
            if df is None: return None
            for t in check_div(df):
                if t.date()==rsi_date:
                    return sym
        except:
            return None

    if st.button("Run RSI"):
        coins = get_top_symbols(rsi_limit)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            res = list(ex.map(scan_rsi, coins))

        st.session_state.rsi_results = list(set([r for r in res if r]))

    if st.session_state.rsi_results:
        df = pd.DataFrame(st.session_state.rsi_results, columns=["RSI Coins"])
        st.dataframe(df)
        st.download_button("Download RSI", df.to_csv(index=False), "rsi.csv")

# =========================================================
# ================= PATTERN (RIGHT) =================
# =========================================================
with col3:
    st.header("📊 Candle Patterns")

    patterns = st.multiselect(
        "Select Patterns",
        ["Inside Bar","Bullish Engulfing","Bearish Engulfing","Bullish Harami","Bearish Harami"],
        default=["Bullish Engulfing"]
    )

    tf = st.selectbox("TF", ["15m","30m","1h","4h","1d"], key="ptf")
    limit = st.selectbox("Coins", [50,100,200,400], key="plimit")

    date = st.date_input("Date", key="pdate")
    time_input = st.time_input("Time", key="ptime")

    def get_ts():
        dt = IST.localize(datetime.combine(date, time_input))
        return int(dt.astimezone(UTC).timestamp()*1000)

    def get_data(sym):
        url="https://api.binance.com/api/v3/klines"
        df=pd.DataFrame(requests.get(url,params={"symbol":sym,"interval":tf,"limit":100}).json())
        df.columns=["time","o","h","l","c","v","ct","q","n","tb","tq","ig"]

        df["ct"]=pd.to_datetime(df["ct"],unit="ms")
        df["o"]=df["o"].astype(float)
        df["c"]=df["c"].astype(float)
        df["h"]=df["h"].astype(float)
        df["l"]=df["l"].astype(float)
        return df

    def check_pattern(c1,c2):
        found=[]

        if "Inside Bar" in patterns and c2["h"]<c1["h"] and c2["l"]>c1["l"]:
            found.append("Inside Bar")

        if "Bullish Engulfing" in patterns and c1["c"]<c1["o"] and c2["c"]>c2["o"] and c2["c"]>c1["o"]:
            found.append("Bullish Engulfing")

        if "Bearish Engulfing" in patterns and c1["c"]>c1["o"] and c2["c"]<c2["o"] and c2["c"]<c1["o"]:
            found.append("Bearish Engulfing")

        if "Bullish Harami" in patterns and c1["c"]<c1["o"] and c2["c"]>c2["o"] and c2["c"]<c1["o"] and c2["o"]>c1["c"]:
            found.append("Bullish Harami")

        if "Bearish Harami" in patterns and c1["c"]>c1["o"] and c2["c"]<c2["o"] and c2["o"]<c1["c"] and c2["c"]>c1["o"]:
            found.append("Bearish Harami")

        return found

    def scan_pattern(sym):
        try:
            df=get_data(sym)
            df=df[df["ct"]<pd.to_datetime(get_ts(),unit="ms")]

            if len(df)<2: return None
            c1,c2=df.iloc[-2],df.iloc[-1]

            res=check_pattern(c1,c2)
            if res:
                return sym
        except:
            return None

    if st.button("Run Pattern"):
        syms=get_top_symbols(limit)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
            res=list(ex.map(scan_pattern, syms))

        st.session_state.pattern_results=list(set([r for r in res if r]))

    if st.session_state.pattern_results:
        df=pd.DataFrame(st.session_state.pattern_results, columns=["Pattern Coins"])
        st.dataframe(df)
        st.download_button("Download Pattern", df.to_csv(index=False), "pattern.csv")

# =========================================================
# ================= MATCH =================
# =========================================================
with col2:
    st.header("🎯 Matching")

    if st.button("Find Matches"):
        st.session_state.matches=list(
            set(st.session_state.rsi_results) &
            set(st.session_state.pattern_results)
        )

    if st.session_state.matches:
        df=pd.DataFrame(st.session_state.matches, columns=["Matches"])
        st.dataframe(df)
        st.download_button("Download Matches", df.to_csv(index=False), "match.csv")
    else:
        st.info("Run both scanners")