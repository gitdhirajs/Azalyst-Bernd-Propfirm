import os
import pandas as pd
import mplfinance as mpf
from pathlib import Path

def generate_chart(signal: dict, ohlcv_cache: dict) -> str:
    try:
        sym = signal.get("symbol")
        if not sym or not ohlcv_cache or sym not in ohlcv_cache:
            return None
        
        ltf = signal.get("ltf", "1d")
        if ltf in ohlcv_cache[sym]:
            data = ohlcv_cache[sym][ltf]
        else:
            return None
            
        if not data:
            return None
            
        df = pd.DataFrame(data)
        if "timestamp" not in df.columns:
            return None
            
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df.set_index("timestamp", inplace=True)
        df = df[-90:] 
        
        entry = float(signal.get("entry_price", 0))
        stop = float(signal.get("stop_price", 0))
        targets = [float(t) for t in signal.get("targets", [])]
        
        if not entry or not stop:
            return None
            
        hline_vals = [entry, stop]
        colors = ['#4A90E2', '#E74C3C']
        widths = [1.5, 1.5]
        styles = ['-', '-']
        for t in targets[:3]:
            if t:
                hline_vals.append(t)
                colors.append('#2ECC71')
                widths.append(1.0)
                styles.append('--')
        hlines = dict(hlines=hline_vals, colors=colors, linewidths=widths, linestyle=styles, alpha=0.8)
        
        fill_dict = dict(y1=entry, y2=stop, color="gray", alpha=0.2)
        
        out_path = f"chart_{sym.replace('=', '_').replace('^', '')}.png"
        
        mc = mpf.make_marketcolors(up='g',down='r',edge='inherit',wick='inherit',volume='in',ohlc='i')
        s  = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=True, facecolor='#2B2D31', edgecolor='white', figcolor='#2B2D31', rc={'text.color': 'white', 'axes.labelcolor': 'white', 'xtick.color': 'white', 'ytick.color': 'white'})
        
        mpf.plot(df, type='candle', style=s, hlines=hlines, fill_between=fill_dict,
                 title=f"{sym} ({ltf})", savefig=out_path, figsize=(10, 6))
                 
        return out_path
    except Exception as e:
        print(f"Failed to generate chart for {signal.get('symbol')}: {e}")
        return None