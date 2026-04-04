import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
from datetime import datetime

# ==========================================
# 1. SETUP & CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="Indian Market Algo Trading Dashboard",
    page_icon="📈",
    layout="wide"
)

# Initialize Paper Trading Session State
if "capital" not in st.session_state:
    st.session_state.capital = 30000.0
if "positions" not in st.session_state:
    st.session_state.positions = {}
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

# Tickers mapped for Yahoo Finance
TICKERS = {
    "Nifty 50": "^NSEI",
    "Bank Nifty": "^NSEBANK",
    "Finnifty": "NIFTY_FIN_SERVICE.NS"
}

# ==========================================
# 2. DATA FETCHING 
# ==========================================

@st.cache_data(ttl=60)  # cache lives for 60 seconds
def fetch_data(ticker_symbol, interval="1m", period="1d"):
    """
    Fetches live or near real-time data from Yahoo Finance.
    Intervals: 1m, 5m, 15m, etc.
    """
    try:
        df = yf.download(tickers=ticker_symbol, period=period, interval=interval, progress=False)
        if df.empty:
            return pd.DataFrame()
            
        # Standardize column names (yfinance sometimes returns MultiIndex columns)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
            
        return df
    except Exception as e:
        st.error(f"Error fetching data for {ticker_symbol}: {e}")
        return pd.DataFrame()

# ==========================================
# 3. INDICATOR CALCULATION
# ==========================================

def calculate_rsi(data, period=14):
    """Calculates the Relative Strength Index (RSI)."""
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    # Replace inf with large number and calculate RSI
    rs = rs.replace([np.inf, -np.inf], 100)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_vwap(df):
    """
    Calculates Volume Weighted Average Price (VWAP).
    Note: Indices usually lack Volume data on Yahoo Finance,
    so we simulate VWAP as a simple typical price average if Volume is 0.
    """
    q = df.get('Volume', pd.Series(1, index=df.index))
    if q.sum() == 0:
        q = pd.Series(1, index=df.index)
        
    p = (df['High'] + df['Low'] + df['Close']) / 3
    
    try:
        df_copy = df.copy()
        df_copy['Date'] = df_copy.index.date
        vwap = df_copy.groupby('Date', group_keys=False).apply(
            lambda x: (p.loc[x.index] * q.loc[x.index]).cumsum() / q.loc[x.index].cumsum()
        )
        # Ensure vwap aligns with original index and matches length
        if len(vwap) == len(df):
            return vwap
    except Exception:
        pass
        
    # Fallback if groupby fails (just cumulative over the whole period)
    return (p * q).cumsum() / q.cumsum()

def apply_indicators(df):
    """Calculates and appends all required indicators to the dataframe."""
    if df.empty or len(df) < 50:
        return df
        
    df['VWAP'] = calculate_vwap(df)
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['RSI_14'] = calculate_rsi(df, period=14)
    
    # Calculate ATR (Average True Range) for professional Stop Loss and Target calculations
    df['TR'] = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift()).abs(),
        (df['Low'] - df['Close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['ATR_14'] = df['TR'].rolling(window=14).mean()
    
    # Drop rows with NaN if needed, but for live trading we keep them 
    # to show the timeline properly.
    return df

# ==========================================
# 4. SIGNAL GENERATION
# ==========================================

def generate_signal(row):
    """
    Determines trading signals based on predefined rules:
    - BUY CE: Price > VWAP, 20 EMA > 50 EMA, RSI > 60
    - BUY PE: Price < VWAP, 20 EMA < 50 EMA, RSI < 40
    """
    price = row['Close']
    vwap = row['VWAP']
    ema20 = row['EMA_20']
    ema50 = row['EMA_50']
    rsi = row['RSI_14']
    atr = row.get('ATR_14', 0)
    
    sl = None
    target1 = None
    target2 = None
    
    if pd.isna(vwap) or pd.isna(ema50) or pd.isna(rsi):
         return "NO TRADE", "Sideways", sl, target1, target2
         
    if price > vwap and ema20 > ema50 and rsi > 60:
        # CE Setup - Bullish (Risk/Reward 1:2 and 1:4) using exact 1% Stop Loss
        sl = price * 0.99 
        risk = price - sl
        target1 = price + (risk * 2.0)
        target2 = price + (risk * 4.0)
        return "BUY CE", "Bullish", sl, target1, target2
    elif price < vwap and ema20 < ema50 and rsi < 40:
        # PE Setup - Bearish using exact 1% Stop Loss
        sl = price * 1.01
        risk = sl - price
        target1 = price - (risk * 2.0)
        target2 = price - (risk * 4.0)
        return "BUY PE", "Bearish", sl, target1, target2
    else:
        # Determine trend roughly even if no signal
        if ema20 > ema50:
            trend = "Mild Bullish"
        elif ema20 < ema50:
            trend = "Mild Bearish"
        else:
            trend = "Sideways"
        return "NO TRADE", trend, sl, target1, target2

# ==========================================
# 5. PAPER TRADING ENGINE
# ==========================================

def manage_paper_trading(index_name, latest_price, signal, sl, target1, target2):
    """Manages the simulated 30,000 INR portfolio."""
    LOT_SIZE = 15 if "Bank" in index_name else 25
    DELTA = 0.5  # Assumed ATM Delta
    
    positions = st.session_state.positions
    timestamp = datetime.now().strftime("%H:%M:%S")

    # Check Exits
    if index_name in positions and positions[index_name] is not None:
        pos = positions[index_name]
        trade_type = pos['type']
        entry_price = pos['entry']
        pos_sl = pos['sl']
        
        exit_triggered = False
        exit_price = 0
        reason = ""
        
        if trade_type == "BUY CE":
            if latest_price <= pos_sl:
                exit_triggered, exit_price, reason = True, pos_sl, "Stop Loss Hit"
            elif latest_price >= pos['target1'] or latest_price >= pos['target2']:
                exit_triggered, exit_price, reason = True, latest_price, "Target Hit"
        elif trade_type == "BUY PE":
            if latest_price >= pos_sl:
                exit_triggered, exit_price, reason = True, pos_sl, "Stop Loss Hit"
            elif latest_price <= pos['target1'] or latest_price <= pos['target2']:
                exit_triggered, exit_price, reason = True, latest_price, "Target Hit"
                
        if exit_triggered:
            points = (exit_price - entry_price) if trade_type == "BUY CE" else (entry_price - exit_price)
            pnl = points * DELTA * LOT_SIZE
            st.session_state.capital += pnl
            
            st.session_state.trade_history.append({
                "time": timestamp,
                "index": index_name,
                "type": trade_type,
                "entry": round(entry_price, 2),
                "exit": round(exit_price, 2),
                "pnl": round(pnl, 2),
                "reason": reason
            })
            positions[index_name] = None
            st.success(f"Trade Closed: {index_name} | {reason} | P&L: ₹{pnl:.2f}")

    # Check Entries
    if (index_name not in positions or positions[index_name] is None) and signal in ["BUY CE", "BUY PE"]:
        positions[index_name] = {
            "type": signal,
            "entry": latest_price,
            "sl": sl,
            "target1": target1,
            "target2": target2,
            "time": timestamp
        }
        st.info(f"Trade Opened: {index_name} | {signal} at ₹{latest_price:.2f}")

# ==========================================
# 6. UI COMPONENTS 
# ==========================================

def plot_chart(df, index_name):
    """Plots interactive Candlestick chart with EMA and VWAP using Plotly."""
    fig = go.Figure()

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'],
        high=df['High'],
        low=df['Low'],
        close=df['Close'],
        name='Price'
    ))

    # Indicators
    if 'VWAP' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['VWAP'], line=dict(color='blue', width=2), name='VWAP'))
    if 'EMA_20' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_20'], line=dict(color='orange', width=2), name='EMA 20'))
    if 'EMA_50' in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], line=dict(color='purple', width=2), name='EMA 50'))

    fig.update_layout(
        title=f"{index_name} Live Chart (1-Min)",
        yaxis_title="Price",
        xaxis_title="Time",
        template="plotly_dark",
        height=400,
        margin=dict(l=0, r=0, t=40, b=0),
        xaxis_rangeslider_visible=False
    )
    return fig

def render_dashboard_section(index_name, ticker_symbol):
    """Renders the data, indicators, signals, and charts for a specific index."""
    st.subheader(f"📊 {index_name}")
    
    df = fetch_data(ticker_symbol)
    if df is not None and not df.empty:
        df = apply_indicators(df)
        
        if len(df) < 50:
            st.warning("Not enough data to calculate all indicators.")
            return

        latest = df.iloc[-1]
        
        signal, trend, sl, target1, target2 = generate_signal(latest)
        
        # Execute Paper Trading Simulation
        manage_paper_trading(index_name, latest['Close'], signal, sl, target1, target2)
        
        # Color coding for signals
        signal_color = "gray"
        bg_color = "rgba(128, 128, 128, 0.2)"
        if signal == "BUY CE":
            signal_color = "#00ff00"  # Green
            bg_color = "rgba(0, 255, 0, 0.2)"
        elif signal == "BUY PE":
            signal_color = "#ff0000"  # Red
            bg_color = "rgba(255, 0, 0, 0.2)"
            
        # Display Metrics in columns
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("LTP (Close)", f"₹{latest['Close']:.2f}")
        with col2:
            st.metric("VWAP", f"₹{latest['VWAP']:.2f}")
        with col3:
            st.metric("EMA (20 / 50)", f"₹{latest['EMA_20']:.0f} / ₹{latest['EMA_50']:.0f}")
        with col4:
            st.metric("RSI (14)", f"{latest['RSI_14']:.2f}")
        with col5:
            # Styled Signal Box
            if signal != "NO TRADE":
                st.markdown(
                    f"""
                    <div style="background-color: {bg_color}; padding: 10px; border-radius: 5px; text-align: center; border: 1px solid {signal_color};">
                        <h4 style="margin:0; font-size: 16px; color: {signal_color};">🔥 {signal}</h4>
                        <p style="margin:2px 0 0 0; font-size: 12px; font-weight: bold; color: {signal_color};">Spot SL: ₹{sl:.0f}</p>
                        <p style="margin:0; font-size: 12px; font-weight: bold; color: {signal_color};">Spot T1: ₹{target1:.0f}</p>
                    </div>
                    """, unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"""
                    <div style="background-color: {bg_color}; padding: 10px; border-radius: 5px; text-align: center; border: 1px solid {signal_color};">
                        <h4 style="margin:0; color: {signal_color};">{signal}</h4>
                        <p style="margin:0; font-size: 14px;">Trend: {trend}</p>
                    </div>
                    """, unsafe_allow_html=True
                )
            
            # Sound/Visual Popup Logic (Optional)
            if signal in ["BUY CE", "BUY PE"]:
                # Display an alert toast if signal is generated
                st.toast(f"🚨 {index_name} Alert: {signal}!", icon="📣")
        
        # Chart
        st.plotly_chart(plot_chart(df, index_name), use_container_width=True)
        
        # Additional Insights (Bonus)
        with st.expander(f"✨ {index_name} Pro Options Trader Analysis & ATM Hint"):
            atm_strike = round(latest['Close'] / 50) * 50 if "Nifty" in index_name else round(latest['Close'] / 100) * 100
            st.markdown(f"**Current Spot Price:** ₹{latest['Close']:.2f} | **Suggested ATM Strike:** {atm_strike}")
            if signal != "NO TRADE":
                st.info(f"**PRO {signal} SETUP TRIGGRED**\n\nThe market is showing a **{trend}** setup. "
                        f"As an options buyer, strictly trail your Stop Loss.\n\n"
                        f"- **Spot Entry Area**: ₹{latest['Close']:.2f}\n"
                        f"- **Spot Stop Loss**: ₹{sl:.2f} (Strict 1% Risk)\n"
                        f"- **Spot Target 1**: ₹{target1:.2f} (Scale out 50% here)\n"
                        f"- **Spot Target 2**: ₹{target2:.2f} (Runner target)\n\n"
                        f"⚠️ Execute using the **{atm_strike} Strike** based on your delta preference.")
            else:
                st.write("Market is currently chopping or in a transition phase. "
                         "Wait for high probability 20/50 EMA & VWAP crossover with RSI confirmation. "
                         "Don't force a trade!")
            
    else:
        st.error(f"Failed to fetch data for {index_name}. Market might be closed or API is down.")

def render_testing_dashboard():
    """Renders the top live testing dashboard UI."""
    st.markdown("### 🏦 Live Testing & Paper Trading")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Available Capital", f"₹{st.session_state.capital:,.2f}")
    
    total_trades = len(st.session_state.trade_history)
    wins = sum(1 for t in st.session_state.trade_history if t['pnl'] > 0)
    net_pnl = st.session_state.capital - 30000.0
    
    col2.metric("Total Trades", total_trades)
    col3.metric("Winning Trades", wins)
    col4.metric("Net P&L", f"₹{net_pnl:,.2f}", delta=round(net_pnl, 2))
    
    active = {k: v for k, v in st.session_state.positions.items() if v is not None}
    if active:
        st.markdown("**Active Positions:**")
        st.json(active)
        
    with st.expander("Trade Execution History"):
        if total_trades > 0:
            df_history = pd.DataFrame(st.session_state.trade_history)
            st.dataframe(df_history, use_container_width=True)
        else:
            st.write("No executed trades yet.")
    st.divider()

# ==========================================
# 7. MAIN APP LOOP 
# ==========================================

def main():
    st.title("⚡ Indian Market Algo Trading Dashboard")
    st.markdown("Monitoring Nifty 50, Bank Nifty, and Finnifty for High-Probability Option Trades.")

    # Render top dashboard
    render_testing_dashboard()

    # Auto Refresh Logic (Every 60 Seconds)
    # Using streamlit's autorefresh mechanism via query params or session state workaround,
    # Here we use an empty placeholder to continuously rerun the script loop or simply st.rerun
    
    # Check if user wants auto-refresh
    auto_refresh = st.sidebar.checkbox("Auto Refresh Data (1 Min)", value=True)
    if auto_refresh:
        st.sidebar.info("Auto refresh is ON. App will refresh every 60 seconds.")
        
    # App containers
    col_nifty, col_banknifty, col_finnifty = st.tabs(["Nifty 50", "Bank Nifty", "Finnifty"])
    
    with st.spinner("Fetching Data and calculating indicators..."):
        with col_nifty:
            render_dashboard_section("Nifty 50", TICKERS["Nifty 50"])
        with col_banknifty:
            render_dashboard_section("Bank Nifty", TICKERS["Bank Nifty"])
        with col_finnifty:
            render_dashboard_section("Finnifty", TICKERS["Finnifty"])
    
    # Auto-refresh mechanism
    if auto_refresh:
        time.sleep(60)
        st.rerun()

if __name__ == "__main__":
    main()
