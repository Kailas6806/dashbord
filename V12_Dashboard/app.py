import streamlit as st
import pandas as pd
import datetime
import os
import requests
import plotly.express as px
from streamlit_autorefresh import st_autorefresh
from jugaad_data.nse import NSELive

# ─── TELEGRAM ALERT ───
def send_telegram(msg: str):
    """Send alert to Telegram. Set TELEGRAM_TOKEN & TELEGRAM_CHAT_ID in st.secrets."""
    try:
        token   = st.secrets.get("TELEGRAM_TOKEN", "")
        chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return  # silently skip if not configured
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg,
                                  "parse_mode": "Markdown"}, timeout=5)
    except Exception:
        pass  # never crash dashboard due to notification failure

st.set_page_config(page_title="V12 PRO MAX Dashboard", page_icon="🧠")
st.markdown("""
<style>
/* ─── BASE ─── */
* { box-sizing: border-box; }
.card{
    padding:14px;border-radius:14px;background:#111827;
    color:white;box-shadow:0 4px 14px rgba(0,0,0,.3);margin-bottom:8px;
}
.kpi{font-size:22px;font-weight:700;word-break:break-word;}
.label{color:#9CA3AF;font-size:11px;text-transform:uppercase;letter-spacing:.05em;}
.signal-green{background:linear-gradient(135deg,#064E3B,#065F46);}
.signal-red  {background:linear-gradient(135deg,#7F1D1D,#991B1B);}
.signal-yellow{background:linear-gradient(135deg,#78350F,#92400E);}
.trap-alert{background:#DC2626;color:white;font-weight:bold;padding:12px;
            border-radius:8px;text-align:center;margin-bottom:15px;font-size:14px;}
.pnl-green{color:#34D399;font-weight:700;}
.pnl-red  {color:#F87171;font-weight:700;}

/* ─── RESPONSIVE GRID ─── */
.kpi-grid{
    display:grid;
    grid-template-columns:repeat(auto-fill,minmax(130px,1fr));
    gap:8px;margin-bottom:8px;
}
.filter-grid{
    display:grid;
    grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
    gap:8px;margin-bottom:8px;
}
.tracker-grid{
    display:grid;
    grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
    gap:8px;margin-bottom:8px;
}
.pos-grid{
    display:flex;flex-wrap:wrap;gap:20px;
}
.pos-item{min-width:100px;flex:1 1 120px;}

/* ─── MOBILE ─── */
@media(max-width:640px){
    h1{font-size:20px !important;}
    h2{font-size:18px !important;}
    .kpi{font-size:18px;}
    .label{font-size:10px;}
    .kpi-grid{grid-template-columns:repeat(2,1fr);}
    .filter-grid{grid-template-columns:repeat(2,1fr);}
    .tracker-grid{grid-template-columns:repeat(2,1fr);}
    .pos-item{min-width:80px;}
    .card{padding:10px;}
    [data-testid="stDataFrame"]{font-size:12px;}
}
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=10000, key="refresh")

# CONFIG
NIFTY_LOT = 65
CAPITAL   = 20_000
MAX_LOSS  = 500
DAILY_TGT = 1_000

st.title("🧠 V12 PRO MAX — TRADER DASHBOARD")

# FILES
today        = datetime.datetime.now().strftime('%Y-%m-%d')
log_file     = f"trade_log_{today}.csv"

LOG_COLS = ["Entry Time","Exit Time","Signal","Spot","Strike",
            "Entry Price","Live Price","Exit Price",
            "Stop Loss","Target","Qty","Max Loss ₹","Target P&L ₹",
            "Actual P&L ₹","Status","Result"]

def load_log():
    if os.path.exists(log_file):
        df = pd.read_csv(log_file)
        for c in LOG_COLS:
            if c not in df.columns:
                df[c] = None
        return df[LOG_COLS].to_dict("records")
    return []

def save_log():
    if st.session_state.trade_log:
        pd.DataFrame(st.session_state.trade_log)[LOG_COLS].to_csv(log_file, index=False)

# SESSION STATE
if "prev_df"     not in st.session_state: st.session_state.prev_df     = None
if "trade_log"   not in st.session_state: st.session_state.trade_log   = load_log()
if "last_signal" not in st.session_state: st.session_state.last_signal = "WAIT"
if "last_played" not in st.session_state: st.session_state.last_played = "WAIT"
if "signal_buffer" not in st.session_state: st.session_state.signal_buffer = []

# FETCH
@st.cache_data(ttl=8)
def get_data():
    try:
        n = NSELive()
        d = n.index_option_chain("NIFTY")
        if "records" in d: return d
    except: pass
    return None

data = get_data()
if data is None:
    st.error("❌ NSE data unavailable. Retrying..."); st.stop()

records = data["records"]["data"]
spot    = data["records"]["underlyingValue"]
atm     = round(spot / 50) * 50

rows = []
for item in records:
    s = item["strikePrice"]
    if abs(s - atm) <= 300:
        ce = item.get("CE", {}); pe = item.get("PE", {})
        rows.append({"Strike":s,"CE LTP":ce.get("lastPrice",0),"CE OI":ce.get("openInterest",0),
                     "PE LTP":pe.get("lastPrice",0),"PE OI":pe.get("openInterest",0)})

df = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
if df.empty: st.error("No data. Market may be closed."); st.stop()

df["dist"]   = (df["Strike"] - spot).abs()
atm_actual   = int(df.loc[df["dist"].idxmin(), "Strike"])
atm_row      = df[df["Strike"] == atm_actual].iloc[0]

# OI CHANGE
if st.session_state.prev_df is not None:
    merged = pd.merge(df, st.session_state.prev_df, on="Strike", how="left", suffixes=("","_p"))
    df["CE OI Δ"] = (merged["CE OI"] - merged["CE OI_p"]).fillna(0)
    df["PE OI Δ"] = (merged["PE OI"] - merged["PE OI_p"]).fillna(0)
else:
    df["CE OI Δ"] = 0; df["PE OI Δ"] = 0
st.session_state.prev_df = df[["Strike","CE OI","PE OI"]].copy()

# PCR / BIAS
tot_ce = df["CE OI"].sum(); tot_pe = df["PE OI"].sum()
pcr    = round(tot_pe/tot_ce, 2) if tot_ce else 0
bias   = "Bullish" if pcr>1.2 else ("Bearish" if pcr<0.8 else "Neutral")

resistance = int(df.loc[df["CE OI"].idxmax(),"Strike"])
support    = int(df.loc[df["PE OI"].idxmax(),"Strike"])
ce_build   = int(df.loc[df["CE OI Δ"].idxmax(),"Strike"])
pe_build   = int(df.loc[df["PE OI Δ"].idxmax(),"Strike"])

# ══════════════════════════════════════════
# 🔰 FILTER 1 — TIME WINDOW (9:30 AM – 2:30 PM)
# ══════════════════════════════════════════
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
now_ist    = datetime.datetime.now(IST)
now_time   = now_ist.time()
mkt_open   = datetime.time(9, 30)
mkt_close  = datetime.time(14, 30)
in_window  = mkt_open <= now_time <= mkt_close

# ══════════════════════════════════════════
# 🔰 FILTER 2 — MIN OI CHANGE THRESHOLD (ignore noise < 500 contracts)
# ══════════════════════════════════════════
MIN_OI_CHANGE = 500
total_ce_delta = df["CE OI Δ"].sum()
total_pe_delta = df["PE OI Δ"].sum()
oi_active = abs(total_ce_delta) >= MIN_OI_CHANGE or abs(total_pe_delta) >= MIN_OI_CHANGE

# ══════════════════════════════════════════
# 🔰 FILTER 3 — PCR MOMENTUM (PCR must be trending, not flat)
# ══════════════════════════════════════════
if "pcr_history" not in st.session_state:
    st.session_state.pcr_history = []
st.session_state.pcr_history.append(pcr)
st.session_state.pcr_history = st.session_state.pcr_history[-5:]  # keep last 5

pcr_momentum = "FLAT"
if len(st.session_state.pcr_history) >= 3:
    recent = st.session_state.pcr_history
    if recent[-1] > recent[-3] + 0.05:
        pcr_momentum = "RISING"   # bullish
    elif recent[-1] < recent[-3] - 0.05:
        pcr_momentum = "FALLING"  # bearish

# ══════════════════════════════════════════
# 🔰 FILTER 4 — VWAP PROXY (rolling spot avg as VWAP approximation)
# ══════════════════════════════════════════
if "spot_history" not in st.session_state:
    st.session_state.spot_history = []
st.session_state.spot_history.append(spot)
st.session_state.spot_history = st.session_state.spot_history[-20:]  # ~3 min of data

vwap_proxy   = round(sum(st.session_state.spot_history) / len(st.session_state.spot_history), 2)
spot_vs_vwap = "ABOVE" if spot > vwap_proxy else "BELOW"

# ══════════════════════════════════════════
# 🚦 SIGNAL LOGIC (with all filters)
# ══════════════════════════════════════════
signal = "WAIT"; confidence = "LOW"; filter_reason = ""

if not in_window:
    signal = "WAIT"; filter_reason = "⏰ Outside trading hours (9:30–2:30)"
elif not oi_active:
    signal = "WAIT"; filter_reason = "📉 OI change too small (noise)"
elif pe_build > ce_build and spot > support and spot_vs_vwap == "ABOVE" and pcr_momentum in ("RISING","FLAT"):
    signal = "BUY CE"; confidence = "HIGH"
elif ce_build > pe_build and spot < resistance and spot_vs_vwap == "BELOW" and pcr_momentum in ("FALLING","FLAT"):
    signal = "BUY PE"; confidence = "HIGH"
elif bias == "Neutral":
    signal = "⚠️ SIDEWAYS"; confidence = "AVOID"

# TRAP
trap = "NONE"
if spot > resistance and total_ce_delta > total_pe_delta: trap = "🚨 BULL TRAP"
elif spot < support and total_pe_delta > total_ce_delta:  trap = "🚨 BEAR TRAP"

# ── SIGNAL CONFIRMATION BUFFER (needs 2/3 refreshes to confirm) ──
st.session_state.signal_buffer.append(signal)
st.session_state.signal_buffer = st.session_state.signal_buffer[-3:]

buf = st.session_state.signal_buffer
if buf.count("BUY CE") >= 2:
    final_signal = "BUY CE";   final_confidence = "HIGH"
elif buf.count("BUY PE") >= 2:
    final_signal = "BUY PE";   final_confidence = "HIGH"
else:
    final_signal = "WAIT";     final_confidence = "LOW"

# ── BLOCK NEW SIGNAL IF OPEN TRADE EXISTS (one trade at a time) ──
open_trade_exists = any(t.get("Status") == "OPEN" for t in st.session_state.trade_log)
if open_trade_exists and final_signal in ("BUY CE", "BUY PE"):
    final_signal     = "WAIT"
    final_confidence = "LOW"

# PRICES
ce_price = round(float(atm_row["CE LTP"]), 2)
pe_price = round(float(atm_row["PE LTP"]), 2)

def calc_trade(ep):
    sl_u  = round(ep * 0.25, 2)
    tgt_u = round(ep * 1.0,  2)
    sl_p  = round(ep - sl_u, 2)
    tgt_p = round(ep + tgt_u, 2)
    qty   = max(NIFTY_LOT, (int(MAX_LOSS / sl_u) // NIFTY_LOT) * NIFTY_LOT) if sl_u > 0 else NIFTY_LOT
    if ep * qty > CAPITAL:
        qty = max(NIFTY_LOT, (int(CAPITAL / ep) // NIFTY_LOT) * NIFTY_LOT)
    return qty, sl_p, tgt_p, round(sl_u*qty,2), round(tgt_u*qty,2)

# ── CHECK OPEN TRADES FOR SL / TARGET HIT ──
def get_live_price(sig):
    """Get current option price for an open trade by signal type."""
    return ce_price if sig == "BUY CE" else pe_price

changed = False
for trade in st.session_state.trade_log:
    if trade.get("Status") == "OPEN":
        lp  = get_live_price(trade.get("Signal",""))
        sl  = float(trade.get("Stop Loss") or 0)
        tgt = float(trade.get("Target") or 0)
        ep  = float(trade.get("Entry Price") or 0)
        qty = int(trade.get("Qty") or 0)
        trade["Live Price"] = lp
        now_str = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
        if lp <= sl:
            trade["Status"]       = "CLOSED"
            trade["Result"]       = "🔴 LOSS"
            trade["Exit Price"]   = lp
            trade["Exit Time"]    = now_str
            trade["Actual P&L ₹"] = round((lp - ep) * qty, 2)
            changed = True
            send_telegram(
                f"🔴 *SL HIT — {trade.get('Signal')}*\n"
                f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                f"💸 P&L: `₹{trade['Actual P&L ₹']:,.0f}` | Time: `{now_str}`"
            )
        elif lp >= tgt:
            trade["Status"]       = "CLOSED"
            trade["Result"]       = "🟢 WIN"
            trade["Exit Price"]   = lp
            trade["Exit Time"]    = now_str
            trade["Actual P&L ₹"] = round((lp - ep) * qty, 2)
            changed = True
            send_telegram(
                f"🟢 *TARGET HIT — {trade.get('Signal')}*\n"
                f"📍 Strike: `{trade.get('Strike')}` | Exit: `{lp}`\n"
                f"💸 P&L: `₹{trade['Actual P&L ₹']:,.0f}` | Time: `{now_str}`"
            )
if changed:
    save_log()

# KPI CARDS — CSS Grid (auto-wraps on mobile)
st.markdown(f"""
<div class="kpi-grid">
  <div class="card"><div class="label">SPOT</div><div class="kpi">{round(spot,2)}</div></div>
  <div class="card"><div class="label">ATM Strike</div><div class="kpi">{atm_actual}</div></div>
  <div class="card"><div class="label">PCR</div><div class="kpi">{pcr}</div></div>
  <div class="card"><div class="label">BIAS</div><div class="kpi">{bias}</div></div>
  <div class="card"><div class="label">SUPPORT</div><div class="kpi">{support}</div></div>
  <div class="card"><div class="label">RESISTANCE</div><div class="kpi">{resistance}</div></div>
</div>
""", unsafe_allow_html=True)

# FILTER STATUS — CSS Grid
tw_color = "#34D399" if in_window   else "#F87171"
oi_color = "#34D399" if oi_active   else "#F87171"
vw_color = "#34D399" if spot_vs_vwap=="ABOVE" else "#F87171"
pm_color = "#34D399" if pcr_momentum!="FLAT"  else "#F59E0B"
st.markdown(f"""
<div class="filter-grid">
  <div class="card" style="padding:10px;">
    <div class="label">⏰ Time Filter</div>
    <div style="color:{tw_color};font-weight:700;">{"✅ IN WINDOW" if in_window else "❌ CLOSED"}</div>
  </div>
  <div class="card" style="padding:10px;">
    <div class="label">📊 OI Activity</div>
    <div style="color:{oi_color};font-weight:700;">{"✅ ACTIVE" if oi_active else "❌ LOW OI"}</div>
  </div>
  <div class="card" style="padding:10px;">
    <div class="label">📈 Spot vs VWAP ({vwap_proxy})</div>
    <div style="color:{vw_color};font-weight:700;">{spot_vs_vwap}</div>
  </div>
  <div class="card" style="padding:10px;">
    <div class="label">🔄 PCR Momentum</div>
    <div style="color:{pm_color};font-weight:700;">{pcr_momentum}</div>
  </div>
</div>
""", unsafe_allow_html=True)

st.write("")

# TRAP / SIGNAL BANNER
if trap != "NONE":
    st.markdown(f'<div class="trap-alert">{trap} DETECTED!</div>', unsafe_allow_html=True)

cc = "signal-green" if "CE" in final_signal else ("signal-red" if "PE" in final_signal else "signal-yellow")
reason_html = f'<p style="font-size:12px;color:#F87171;">{filter_reason}</p>' if filter_reason else ""
st.markdown(
    f'<div class="card {cc}"><h2>{final_signal}</h2><p>Confidence: {final_confidence}</p>'
    f'<p style="font-size:11px;color:#9CA3AF;">Raw: {signal} | Buffer: {", ".join(st.session_state.signal_buffer[-3:])}'
    f'{"|" + filter_reason if filter_reason else ""}</p></div>',
    unsafe_allow_html=True
)

# ── LOG / DISPLAY TRADE ──
if final_signal in ("BUY CE","BUY PE") and final_confidence == "HIGH":
    ep      = ce_price if final_signal == "BUY CE" else pe_price
    lbl     = "CE LTP" if final_signal == "BUY CE" else "PE LTP"
    qty, sl_p, tgt_p, ml, tp = calc_trade(ep)

    st.markdown(
        f'<div style="margin-top:10px;padding:10px;background:#1F2937;border-radius:10px;">'
        f'<strong>📌 {lbl} @ {atm_actual}:</strong> {ep} &nbsp;|&nbsp; '
        f'<strong>💰 SL:</strong> {sl_p} &nbsp;|&nbsp; '
        f'<strong>🎯 Target:</strong> {tgt_p} &nbsp;|&nbsp; '
        f'<strong>📦 Qty:</strong> {qty} &nbsp;|&nbsp; '
        f'<strong>🔴 Max Loss:</strong> ₹{ml} &nbsp;|&nbsp; '
        f'<strong>🟢 Target P&L:</strong> ₹{tp}'
        f'</div><br>', unsafe_allow_html=True)

    # Log ONCE per new confirmed signal
    if final_signal != st.session_state.last_signal:
        now = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
        st.session_state.trade_log.insert(0, {
            "Entry Time": now, "Exit Time": None, "Signal": final_signal,
            "Spot": round(spot,2), "Strike": atm_actual,
            "Entry Price": ep, "Live Price": ep, "Exit Price": None,
            "Stop Loss": sl_p, "Target": tgt_p, "Qty": qty,
            "Max Loss ₹": ml, "Target P&L ₹": tp,
            "Actual P&L ₹": None, "Status": "OPEN", "Result": "⏳ OPEN"
        })
        save_log()
        st.session_state.last_signal = final_signal

        # 📨 TELEGRAM ALERT — new signal
        emoji = "🟢" if "CE" in final_signal else "🔴"
        send_telegram(
            f"{emoji} *V12 SIGNAL: {final_signal}*\n"
            f"📍 Strike: `{atm_actual}` | Spot: `{round(spot,2)}`\n"
            f"💰 Entry: `{ep}` | SL: `{sl_p}` | Target: `{tgt_p}`\n"
            f"📦 Qty: `{qty}` | Max Loss: `₹{ml}` | Target P&L: `₹{tp}`\n"
            f"⏰ Time: `{now}`"
        )

    # Audio once per new confirmed signal
    if final_signal != st.session_state.last_played:
        st.markdown('<audio autoplay style="display:none"><source src="https://actions.google.com/sounds/v1/alarms/beep_short.ogg" type="audio/ogg"></audio>', unsafe_allow_html=True)
        st.session_state.last_played = final_signal

    st.success("🚨 HIGH CONFIDENCE TRADE SIGNAL — CONFIRMED")
else:
    if final_signal != st.session_state.last_signal:
        st.session_state.last_signal = final_signal
        st.session_state.last_played = final_signal

# INVESTMENT TRACKER
tracker_hdr, reset_col, test_col = st.columns([4, 1, 1])
with tracker_hdr:
    st.subheader("💼 Investment Tracker (₹20,000 Capital)")
with reset_col:
    st.write("")
    if st.button("🔄 Reset", type="primary", help="Clear all trades and start fresh", use_container_width=True):
        st.session_state.trade_log     = []
        st.session_state.last_signal   = "WAIT"
        st.session_state.last_played   = "WAIT"
        st.session_state.signal_buffer = []
        if os.path.exists(log_file): os.remove(log_file)
        st.success("✅ Tracker reset! Starting fresh.")
        st.rerun()

with test_col:
    st.write("")
    if st.button("📨 Test", help="Send a test Telegram alert", use_container_width=True):
        now_t = datetime.datetime.now(IST).strftime("%I:%M:%S %p")
        result = send_telegram(
            f"🧪 *V12 TEST ALERT*\n"
            f"🟢 SIGNAL: BUY CE\n"
            f"📍 Strike: `{atm_actual}` | Spot: `{round(spot,2)}`\n"
            f"💰 Entry: `{ce_price}` | SL: `{round(ce_price*0.75,2)}` | Target: `{round(ce_price*2,2)}`\n"
            f"⏰ Time: `{now_t}` ← TEST MESSAGE"
        )
        st.success("📨 Test message sent! Check Telegram.")

log_df      = pd.DataFrame(st.session_state.trade_log) if st.session_state.trade_log else pd.DataFrame(columns=LOG_COLS)
closed_only = log_df[log_df["Status"]=="CLOSED"] if not log_df.empty else pd.DataFrame()
realized_pnl= closed_only["Actual P&L ₹"].apply(pd.to_numeric,errors="coerce").sum() if not closed_only.empty else 0
running_cap = CAPITAL + realized_pnl
progress    = max(0.0, min(1.0, realized_pnl / DAILY_TGT))
pc          = "pnl-green" if realized_pnl >= 0 else "pnl-red"

st.markdown(f"""
<div class="tracker-grid">
  <div class="card"><div class="label">Capital</div><div class="kpi">₹{CAPITAL:,}</div></div>
  <div class="card"><div class="label">Closed Trades</div><div class="kpi">{len(closed_only)}</div></div>
  <div class="card"><div class="label">Realized P&L</div><div class="kpi {pc}">₹{realized_pnl:,.0f}</div></div>
  <div class="card"><div class="label">Running Capital</div><div class="kpi">₹{running_cap:,.0f}</div></div>
  <div class="card"><div class="label">Daily Progress</div><div class="kpi">{round(progress*100)}%</div></div>
</div>
""", unsafe_allow_html=True)
st.progress(progress, text=f"₹{realized_pnl:,.0f} / ₹{DAILY_TGT:,} daily target")


# OPTION CHAIN
st.subheader("📊 Option Chain (ATM ±300 | OI Δ)")
disp = df.drop(columns=["dist"], errors="ignore")
def hl(v):
    if isinstance(v,(int,float)):
        if v>0: return "background-color:#064E3B;color:white"
        if v<0: return "background-color:#7F1D1D;color:white"
    return ""
st.dataframe(disp.style.map(hl, subset=["CE OI Δ","PE OI Δ"]), use_container_width=True)

st.subheader("📈 OI Distribution")
st.plotly_chart(px.bar(disp,x="Strike",y=["CE OI","PE OI"],barmode="group",
    color_discrete_map={"CE OI":"#34D399","PE OI":"#F87171"}), use_container_width=True)

st.subheader("⚡ OI Change (Smart Money)")
st.plotly_chart(px.bar(disp,x="Strike",y=["CE OI Δ","PE OI Δ"],barmode="group",
    color_discrete_map={"CE OI Δ":"#6EE7B7","PE OI Δ":"#FCA5A5"}), use_container_width=True)

# TRADE POSITIONS
st.subheader("📜 Trade Positions")
tab_open, tab_hist = st.tabs(["🟢 Open Position","📋 Trade History"])

with tab_open:
    open_trades = [t for t in st.session_state.trade_log if t.get("Status")=="OPEN"]
    if open_trades:
        ot  = open_trades[0]
        ev  = float(ot.get("Entry Price") or 0)
        lv  = float(ot.get("Live Price")  or ev)
        qv  = int(ot.get("Qty") or 0)
        upl = round((lv-ev)*qv,2)
        uc  = "#34D399" if upl>=0 else "#F87171"
        sc  = "#34D399" if "CE" in str(ot.get("Signal")) else "#F87171"
        st.markdown(f"""
        <div class="card" style="border-left:4px solid {sc};">
          <div style="display:flex;gap:32px;flex-wrap:wrap;">
            <div><div class="label">Signal</div><div class="kpi" style="color:{sc};">{ot.get('Signal')}</div></div>
            <div><div class="label">Strike</div><div class="kpi">{ot.get('Strike')}</div></div>
            <div><div class="label">Entry Time</div><div class="kpi" style="font-size:18px;">{ot.get('Entry Time')}</div></div>
            <div><div class="label">Entry Price</div><div class="kpi">₹{ev}</div></div>
            <div><div class="label">Live Price</div><div class="kpi">₹{lv}</div></div>
            <div><div class="label">Stop Loss</div><div class="kpi pnl-red">₹{ot.get('Stop Loss')}</div></div>
            <div><div class="label">Target</div><div class="kpi pnl-green">₹{ot.get('Target')}</div></div>
            <div><div class="label">Qty</div><div class="kpi">{qv}</div></div>
            <div><div class="label">Unrealized P&L</div><div class="kpi" style="color:{uc};">₹{upl:,.0f}</div></div>
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.info("No open position. Waiting for HIGH confidence signal...")

with tab_hist:
    if st.session_state.trade_log:
        show_cols = ["Entry Time","Exit Time","Signal","Strike","Entry Price",
                     "Exit Price","Qty","Actual P&L ₹","Status","Result"]
        hdf = pd.DataFrame(st.session_state.trade_log)
        for c in show_cols:
            if c not in hdf.columns: hdf[c] = None
        hdf = hdf[show_cols]

        def cp(v):
            try:
                f = float(v)
                return "color:#34D399;font-weight:700" if f>=0 else "color:#F87171;font-weight:700"
            except: return ""

        st.dataframe(hdf.style.map(cp, subset=["Actual P&L ₹"]), use_container_width=True)

        pnl_s = hdf["Actual P&L ₹"].apply(pd.to_numeric, errors="coerce")
        wins   = (pnl_s > 0).sum()
        losses = (pnl_s <= 0).sum()
        net    = pnl_s.sum()
        ca, cb, cc2 = st.columns(3)
        ca.metric("Total Trades", len(hdf))
        cb.metric("Wins / Losses", f"{wins} / {losses}")
        cc2.metric("Net P&L", f"₹{net:,.0f}", delta=f"{net:+.0f}")
    else:
        st.info("Waiting for first HIGH confidence signal...")
