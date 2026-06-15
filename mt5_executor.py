import sys
import os
import argparse
import time
import shutil
import psutil
import subprocess
import MetaTrader5 as mt5
from utils.db import (
    get_account, update_account_status, get_pending_signals_for_account,
    mark_signal_executed, add_trade, get_open_trades_for_account,
    update_trade_tp_status, add_log
)
from utils.mt5_helpers import calculate_lot_size, divide_lots, get_filling_mode

def parse_args():
    parser = argparse.ArgumentParser(description="MT5 Account Executor Worker")
    parser.add_argument("--account-id", type=int, required=True, help="Database Account ID")
    return parser.parse_args()

def connect_mt5(account):
    """
    Initializes MT5 connection and logs into the account.
    Runs directly from the configured terminal path.
    """
    login = int(account["login"])
    password = account["password"]
    server = account["server"]
    path = account["terminal_path"]
    
    # Check if terminal path exists
    if path and not os.path.exists(path):
        add_log("ERROR", f"executor_acc_{login}", f"Terminal path does not exist: {path}")
        update_account_status(login, 0, 0, "disconnected", f"Path not found: {path}")
        return False

    add_log("INFO", f"executor_acc_{login}", "Initializing MT5 connection...")
    
    # On Windows, we run directly from the configured terminal path in standard mode.
    # On Linux/Wine (VPS), we run in portable mode to support isolated instances.
    init_params = {}
    if path:
        init_params["path"] = path
        
    if os.name != 'nt':
        init_params["portable"] = True
        
    # Pass credentials directly inside initialize to auto-login and bypass wizard
    init_params["login"] = login
    init_params["password"] = password
    init_params["server"] = server
    init_params["timeout"] = 15000 # 15 seconds to connect
    
    if not mt5.initialize(**init_params):
        err = mt5.last_error()
        add_log("ERROR", f"executor_acc_{login}", f"MT5 initialize failed: {err}")
        update_account_status(login, 0, 0, "disconnected", f"Init failed: {err}")
        return False
        
    # Attempt Login as a backup to verify connection
    if not mt5.login(login=login, password=password, server=server):
        err = mt5.last_error()
        add_log("ERROR", f"executor_acc_{login}", f"MT5 login failed: {err}")
        update_account_status(login, 0, 0, "disconnected", f"Login failed: {err}")
        mt5.shutdown()
        return False
        
    # Update account info
    acc_info = mt5.account_info()
    if acc_info:
        update_account_status(login, acc_info.balance, acc_info.equity, "connected")
        add_log("INFO", f"executor_acc_{login}", f"Logged in. Balance: {acc_info.balance}, Equity: {acc_info.equity}")
        return True
    else:
        err = mt5.last_error()
        add_log("ERROR", f"executor_acc_{login}", f"Failed to get account info: {err}")
        update_account_status(login, 0, 0, "connected", f"Account info failed: {err}")
        return True

def resolve_symbol(symbol):
    """
    Resolves the symbol name by checking if it exists directly on the account.
    If not, tries prefix and suffix matches (e.g. 'XAUUSD' -> 'XAUUSD.c').
    """
    # Try exact match first
    if mt5.symbol_select(symbol, True):
        return symbol
        
    # Standardize input symbol
    clean = symbol.upper().replace("/", "").replace("-", "").strip()
    if clean == "GOLD":
        clean = "XAUUSD"
        
    # Try match with normalized symbol
    if mt5.symbol_select(clean, True):
        return clean
        
    # If still not found, search the broker's symbols list
    symbols = mt5.symbols_get()
    if symbols:
        # Match exactly normalized
        for s in symbols:
            name_upper = s.name.upper()
            if name_upper == clean:
                if mt5.symbol_select(s.name, True):
                    return s.name
                    
        # Match by prefix/suffix
        for s in symbols:
            name_upper = s.name.upper()
            if name_upper.startswith(clean) or clean.startswith(name_upper):
                if mt5.symbol_select(s.name, True):
                    return s.name
                    
    return symbol

def process_trade_signal(account, signal):
    """
    Executes a BUY/SELL signal with 1% risk-based lot sizing.
    """
    login = int(account["login"])
    account_id = account["id"]
    symbol = resolve_symbol(signal["symbol"])
    action = signal["action"]
    sl = signal["sl"]
    
    is_test = "TEST_SIGNAL" in signal.get("raw_text", "")
    
    # SL is mandatory for risk-based lot calculations (except for test signals)
    if not sl and not is_test:
        add_log("WARNING", f"executor_acc_{login}", f"Skipped Signal {signal['id']}: Stop Loss (SL) is required for 1% risk calculation.")
        mark_signal_executed(account_id, signal["id"], "skipped", "Missing mandatory Stop Loss")
        return
        
    # Select symbol
    if not mt5.symbol_select(symbol, True):
        add_log("ERROR", f"executor_acc_{login}", f"Failed to select symbol: {symbol}")
        mark_signal_executed(account_id, signal["id"], "failed", f"Symbol {symbol} not found")
        return
        
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        add_log("ERROR", f"executor_acc_{login}", f"Failed to get symbol info: {symbol}")
        mark_signal_executed(account_id, signal["id"], "failed", f"Symbol {symbol} info unavailable")
        return
        
    # Check current tick prices
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        add_log("ERROR", f"executor_acc_{login}", f"Failed to get current ticks for {symbol}")
        mark_signal_executed(account_id, signal["id"], "failed", f"Ticker price unavailable")
        return
        
    entry_price = tick.ask if action == "BUY" else tick.bid
    
    # Enforce entry price range validation
    entry_min = signal.get("entry_min")
    entry_max = signal.get("entry_max")
    
    if entry_min is not None and entry_max is not None:
        if entry_min == entry_max:
            point = symbol_info.point if symbol_info.point > 0 else 0.00001
            tolerance = 100 * point
            allowed_min = entry_min - tolerance
            allowed_max = entry_max + tolerance
        else:
            allowed_min = entry_min
            allowed_max = entry_max
            
        if not (allowed_min <= entry_price <= allowed_max):
            msg = f"Skipped: Current price ({entry_price}) outside range ({allowed_min} - {allowed_max})"
            add_log("WARNING", f"executor_acc_{login}", f"Signal {signal['id']} skipped. {msg}")
            mark_signal_executed(account_id, signal["id"], "skipped", msg)
            return
            
    acc_info = mt5.account_info()
    if not acc_info:
        add_log("ERROR", f"executor_acc_{login}", "Failed to retrieve account info for lot calculation")
        mark_signal_executed(account_id, signal["id"], "failed", "Account info unavailable")
        return
        
    # Calculate Lot size based on 1% risk or override for test signal
    if is_test:
        total_lots = 0.01
        tp1_lots, tp2_lots, tp3_lots = 0.01, 0.0, 0.0
    else:
        risk_pct = account.get("risk_pct", 1.0)
        total_lots = calculate_lot_size(acc_info.balance, risk_pct, symbol_info, entry_price, sl)
        
        if not total_lots or total_lots <= 0:
            add_log("ERROR", f"executor_acc_{login}", f"Lot calculation failed for {symbol}. Raw value too small or invalid parameters.")
            mark_signal_executed(account_id, signal["id"], "failed", "Invalid calculated volume")
            return
            
        # Divide lot sizes for TP1/TP2/TP3
        tp1_lots, tp2_lots, tp3_lots = divide_lots(total_lots, symbol_info.volume_step)
    
    # Broker side safety: Set broker TP to the furthest TP (TP3, TP2, or TP1)
    broker_tp = None
    if signal["tp3"]:
        broker_tp = signal["tp3"]
    elif signal["tp2"]:
        broker_tp = signal["tp2"]
    elif signal["tp1"]:
        broker_tp = signal["tp1"]
        
    # Construct MT5 Trade Request
    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    filling_mode = get_filling_mode(symbol_info)
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": total_lots,
        "type": order_type,
        "price": entry_price,
        "sl": float(sl) if sl else 0.0,
        "deviation": 20,
        "magic": 100000 + account_id,
        "comment": f"Antigravity Copier S{signal['id']}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode
    }
    
    if broker_tp:
        request["tp"] = float(broker_tp)
        
    add_log("INFO", f"executor_acc_{login}", f"Sending order: {action} {total_lots} {symbol} SL: {sl} TP: {broker_tp}")
    
    result = mt5.order_send(request)
    
    if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
        err_msg = f"Order failed. Code: {result.retcode if result else 'unknown'}, Comment: {result.comment if result else ''}"
        add_log("ERROR", f"executor_acc_{login}", err_msg)
        mark_signal_executed(account_id, signal["id"], "failed", err_msg)
    else:
        ticket = result.order
        add_log("INFO", f"executor_acc_{login}", f"Order execution successful. Ticket: {ticket}")
        
        # Save open trade in SQLite
        add_trade(
            account_id=account_id,
            signal_id=signal["id"],
            ticket=ticket,
            symbol=symbol,
            action=action,
            volume=total_lots,
            sl=sl,
            tp1=signal["tp1"],
            tp2=signal["tp2"],
            tp3=signal["tp3"],
            tp1_lots=tp1_lots,
            tp2_lots=tp2_lots,
            tp3_lots=tp3_lots,
            open_price=result.price
        )
        
        mark_signal_executed(account_id, signal["id"], "executed")

def process_close_signal(account, signal):
    """
    Closes all open positions of the given symbol.
    """
    login = int(account["login"])
    account_id = account["id"]
    symbol = resolve_symbol(signal["symbol"])
    
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        add_log("INFO", f"executor_acc_{login}", f"No open positions to close for symbol {symbol}")
        mark_signal_executed(account_id, signal["id"], "executed")
        return
        
    success_count = 0
    for pos in positions:
        # Check if the position was opened by this bot (magic number check is optional, close all matches is safer as requested)
        ticket = pos.ticket
        vol = pos.volume
        order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
        filling_mode = get_filling_mode(mt5.symbol_info(symbol))
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": vol,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": pos.magic,
            "comment": "Close Position",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode
        }
        
        add_log("INFO", f"executor_acc_{login}", f"Closing position ticket {ticket} ({symbol} {vol} lots)")
        res = mt5.order_send(request)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            success_count += 1
            # Update trade in database
            # We'll update the database record matching this ticket if we have one
            # Note: Active monitoring loop will also pick this up and mark it closed
        else:
            add_log("ERROR", f"executor_acc_{login}", f"Failed to close ticket {ticket}: {res.comment if res else 'unknown'}")
            
    mark_signal_executed(account_id, signal["id"], "executed" if success_count > 0 else "failed")

def process_modify_signal(account, signal):
    """
    Modifies Stop Loss and Take Profit of open positions.
    """
    login = int(account["login"])
    account_id = account["id"]
    symbol = resolve_symbol(signal["symbol"])
    new_sl = signal["sl"]
    new_tp1 = signal["tp1"]
    new_tp2 = signal["tp2"]
    new_tp3 = signal["tp3"]
    
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        add_log("INFO", f"executor_acc_{login}", f"No open positions of {symbol} found to modify")
        mark_signal_executed(account_id, signal["id"], "executed")
        return
        
    success_count = 0
    for pos in positions:
        ticket = pos.ticket
        
        # New SL (if provided)
        sl = float(new_sl) if new_sl else pos.sl
        
        # Update broker TP to new TP3, TP2, or TP1
        tp = pos.tp
        if new_tp3:
            tp = float(new_tp3)
        elif new_tp2:
            tp = float(new_tp2)
        elif new_tp1:
            tp = float(new_tp1)
            
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": sl,
            "tp": tp
        }
        
        add_log("INFO", f"executor_acc_{login}", f"Modifying SL/TP for ticket {ticket}: SL={sl}, TP={tp}")
        res = mt5.order_send(request)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            success_count += 1
        else:
            add_log("ERROR", f"executor_acc_{login}", f"Failed to modify ticket {ticket}: {res.comment if res else 'unknown'}")
            
    mark_signal_executed(account_id, signal["id"], "executed" if success_count > 0 else "failed")

def execute_pending_signals(account):
    """
    Checks DB for signals this account has not executed yet, and processes them.
    """
    account_id = account["id"]
    pending = get_pending_signals_for_account(account_id)
    
    for sig in pending:
        try:
            if sig["action"] in ["BUY", "SELL"]:
                process_trade_signal(account, sig)
            elif sig["action"] == "CLOSE":
                process_close_signal(account, sig)
            elif sig["action"] == "MODIFY":
                process_modify_signal(account, sig)
        except Exception as e:
            login = account["login"]
            add_log("ERROR", f"executor_acc_{login}", f"Exception processing signal {sig['id']}: {e}")
            mark_signal_executed(account_id, sig["id"], "failed", str(e))

def monitor_open_trades(account):
    """
    Monitors active positions in MT5 to manage partial closes (TP1 & TP2)
    and updates trade status when hit by SL, TP3, or closed manually.
    """
    account_id = account["id"]
    login = int(account["login"])
    open_trades = get_open_trades_for_account(account_id)
    
    if not open_trades:
        return
        
    for trade in open_trades:
        ticket = trade["ticket"]
        
        # Get position details from MT5
        positions = mt5.positions_get(ticket=ticket)
        
        if not positions:
            # Trade was closed externally (hit SL/TP3 on broker side, or closed manually)
            add_log("INFO", f"executor_acc_{login}", f"Trade ticket {ticket} is no longer open in MT5. Querying history...")
            
            # Request history deals for this position
            history_deals = mt5.history_deals_get(position=ticket)
            close_price = None
            pnl = 0.0
            
            if history_deals:
                # Find the deal representing the close of this position (entry deal has entry type, exit deal has exit type)
                # Sort deals by time
                sorted_deals = sorted(history_deals, key=lambda d: d.time)
                # The last deal in history is usually the exit deal
                exit_deal = sorted_deals[-1]
                close_price = exit_deal.price
                
                # Sum PnL of all deals for this position
                pnl = sum(d.profit + d.swap + getattr(d, 'commission', 0.0) for d in history_deals)
                
            update_trade_tp_status(
                trade_id=trade["id"],
                status="closed",
                close_price=close_price,
                pnl=pnl
            )
            add_log("INFO", f"executor_acc_{login}", f"Archived closed trade ticket {ticket}. Final PnL: {pnl:.2f}")
            continue
            
        # Position is active
        pos = positions[0]
        symbol = pos.symbol
        price_current = pos.price_current
        pnl = pos.profit + pos.swap + getattr(pos, 'commission', 0.0)
        
        # Update live PnL in database
        update_trade_tp_status(trade_id=trade["id"], pnl=pnl)
        
        # Check partial closes
        tp1 = trade["tp1"]
        tp2 = trade["tp2"]
        tp1_hit = trade["tp1_hit"]
        tp2_hit = trade["tp2_hit"]
        tp1_lots = trade["tp1_lots"]
        tp2_lots = trade["tp2_lots"]
        
        is_buy = pos.type == mt5.ORDER_TYPE_BUY
        
        # --- Check TP1 Hit ---
        if tp1 and not tp1_hit and tp1_lots > 0:
            hit = (price_current >= tp1) if is_buy else (price_current <= tp1)
            if hit:
                add_log("INFO", f"executor_acc_{login}", f"TP1 ({tp1}) hit for ticket {ticket}. Initiating partial close of {tp1_lots} lots.")
                
                order_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(symbol)
                price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
                filling_mode = get_filling_mode(mt5.symbol_info(symbol))
                
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": ticket,
                    "symbol": symbol,
                    "volume": tp1_lots,
                    "type": order_type,
                    "price": price,
                    "deviation": 20,
                    "magic": pos.magic,
                    "comment": "Partial Close TP1",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": filling_mode
                }
                
                res = mt5.order_send(request)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    update_trade_tp_status(trade_id=trade["id"], tp1_hit=True)
                    add_log("INFO", f"executor_acc_{login}", f"Successfully closed TP1 portion ({tp1_lots} lots) for ticket {ticket}")
                    # If this closed the remainder of the position, it will be marked closed in the next tick loop
                else:
                    add_log("ERROR", f"executor_acc_{login}", f"Failed to execute partial close for TP1: {res.comment if res else 'unknown'}")
                    
        # --- Check TP2 Hit ---
        if tp2 and not tp2_hit and tp2_lots > 0:
            hit = (price_current >= tp2) if is_buy else (price_current <= tp2)
            if hit:
                add_log("INFO", f"executor_acc_{login}", f"TP2 ({tp2}) hit for ticket {ticket}. Initiating partial close of {tp2_lots} lots.")
                
                order_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(symbol)
                price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
                filling_mode = get_filling_mode(mt5.symbol_info(symbol))
                
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": ticket,
                    "symbol": symbol,
                    "volume": tp2_lots,
                    "type": order_type,
                    "price": price,
                    "deviation": 20,
                    "magic": pos.magic,
                    "comment": "Partial Close TP2",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": filling_mode
                }
                
                res = mt5.order_send(request)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    update_trade_tp_status(trade_id=trade["id"], tp2_hit=True)
                    add_log("INFO", f"executor_acc_{login}", f"Successfully closed TP2 portion ({tp2_lots} lots) for ticket {ticket}")
                else:
                    add_log("ERROR", f"executor_acc_{login}", f"Failed to execute partial close for TP2: {res.comment if res else 'unknown'}")

def main():
    args = parse_args()
    account_id = args.account_id
    
    # Load Account Details
    account = get_account(account_id)
    if not account:
        print(f"Error: Account with ID {account_id} not found in database.", file=sys.stderr)
        sys.exit(1)
        
    login = int(account["login"])
    
    # Connect and Login
    if not connect_mt5(account):
        print(f"Error: Failed to connect or login for account {login}.", file=sys.stderr)
        sys.exit(1)
        
    add_log("INFO", f"executor_acc_{login}", f"Executor process active for account {login}.")
    
    last_balance_update = time.time()
    
    try:
        while True:
            # 1. Periodically check account status (every 10s)
            now = time.time()
            if now - last_balance_update >= 10.0:
                acc_info = mt5.account_info()
                if acc_info:
                    update_account_status(login, acc_info.balance, acc_info.equity, "connected")
                else:
                    err = mt5.last_error()
                    update_account_status(login, 0, 0, "disconnected", f"Lost connection: {err}")
                    add_log("WARNING", f"executor_acc_{login}", f"Lost connection to MT5 terminal. Reconnecting...")
                    
                    # Try to reconnect
                    if not connect_mt5(account):
                        time.sleep(5)
                        continue
                last_balance_update = now
                
            # 2. Check and execute signals
            execute_pending_signals(account)
            
            # 3. Monitor active positions for partial closes
            monitor_open_trades(account)
            
            # Sleep to minimize CPU usage
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        add_log("INFO", f"executor_acc_{login}", f"Executor process stopped for account {login}.")
    finally:
        mt5.shutdown()

if __name__ == "__main__":
    main()
