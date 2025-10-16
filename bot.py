import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time, yaml
from datetime import datetime, timedelta

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf8") as f:
        return yaml.safe_load(f)

def connect_mt5(cfg):
    path_term = cfg["mt5"].get("path_terminal")
    if not mt5.initialize(path_term):
        raise RuntimeError("Fallo inicializando MetaTrader5:", mt5.last_error())
    if cfg["mt5"].get("login"):
        mt5.login(int(cfg["mt5"]["login"]), password=cfg["mt5"]["password"], server=cfg["mt5"]["server"])

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def get_rates(symbol, timeframe="H1", n=500):
    tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
              "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    rates = mt5.copy_rates_from_pos(symbol, tf_map[timeframe], 0, n)
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df

def find_swing(df, direction="up", w=20):
    if direction == "up":
        idx = df["low"].tail(w).idxmin()
    else:
        idx = df["high"].tail(w).idxmax()
    return df.loc[idx]

def calc_lots(symbol, stop_pips, balance, risk_fraction):
    info = mt5.symbol_info(symbol)
    if info is None or stop_pips <= 0: return 0.01
    contract = info.trade_contract_size or 100000
    point = info.point or 0.0001
    risk_money = balance * risk_fraction
    pip_value_per_lot = contract * point
    lots = risk_money / (stop_pips / point * pip_value_per_lot)
    step = info.volume_step or 0.01
    return round(max(step, np.floor(lots / step) * step), 2)

def trade_once(cfg):
    acc = mt5.account_info()
    if acc is None: raise RuntimeError("No hay conexión con MT5")
    balance = acc.balance
    tf = cfg["timeframe"]
    ema_period = cfg["strategy"]["ema_period"]
    fib_level = cfg["strategy"]["fib_retrace"]
    risk = cfg["risk"]["max_risk_per_trade"]
    for sym in cfg["symbols"]:
        df = get_rates(sym, tf)
        if len(df) < ema_period + 10: continue
        df["ema"] = ema(df["close"], ema_period)
        trend = "up" if df["ema"].iloc[-1] > df["ema"].iloc[-2] else "down"
        tick = mt5.symbol_info_tick(sym)
        bid, ask = tick.bid, tick.ask
        if trend == "up":
            swing = find_swing(df, "up")
            low = swing["low"]; high = df["high"].iloc[-1]
            fib = low + (high - low) * fib_level
            if bid <= fib and df["close"].iloc[-1] > df["open"].iloc[-1]:
                stop = low - (mt5.symbol_info(sym).point * 10)
                stop_pips = abs(bid - stop)
                lots = calc_lots(sym, stop_pips, balance, risk)
                req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=sym, volume=lots,
                           type=mt5.ORDER_TYPE_BUY, price=ask, sl=stop, type_filling=mt5.ORDER_FILLING_FOK)
                print("BUY", sym, lots, "at", ask)
                mt5.order_send(req)
        else:
            swing = find_swing(df, "down")
            high = swing["high"]; low = df["low"].iloc[-1]
            fib = high - (high - low) * fib_level
            if ask >= fib and df["close"].iloc[-1] < df["open"].iloc[-1]:
                stop = high + (mt5.symbol_info(sym).point * 10)
                stop_pips = abs(stop - ask)
                lots = calc_lots(sym, stop_pips, balance, risk)
                req = dict(action=mt5.TRADE_ACTION_DEAL, symbol=sym, volume=lots,
                           type=mt5.ORDER_TYPE_SELL, price=bid, sl=stop, type_filling=mt5.ORDER_FILLING_FOK)
                print("SELL", sym, lots, "at", bid)
                mt5.order_send(req)

def main():
    cfg = load_config("config.yaml")
    connect_mt5(cfg)
    while True:
        trade_once(cfg)
        time.sleep(60)

if __name__ == "__main__":
    main()
