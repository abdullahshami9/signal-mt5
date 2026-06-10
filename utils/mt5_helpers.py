import math

def calculate_lot_size(balance, risk_pct, symbol_info, entry_price, sl_price):
    """
    Calculates the lot size based on standard risk management:
    Risk Amount = Balance * (Risk Percentage / 100)
    Loss per 1 Lot = |Entry Price - SL Price| * (trade_tick_value / trade_tick_size)
    Lot Size = Risk Amount / Loss per Lot
    
    Then rounds the lot size according to symbol volume requirements.
    """
    if not symbol_info:
        return None
        
    price_change = abs(entry_price - sl_price)
    if price_change == 0:
        return None
        
    tick_size = symbol_info.trade_tick_size
    tick_value = symbol_info.trade_tick_value
    
    if tick_size == 0 or tick_value == 0:
        return None
        
    # Calculate how much 1 lot moves for this price change in deposit currency
    loss_per_lot = price_change * (tick_value / tick_size)
    if loss_per_lot == 0:
        return None
        
    risk_amount = balance * (risk_pct / 100.0)
    raw_lot = risk_amount / loss_per_lot
    
    # Check volume step and constraints
    step = symbol_info.volume_step
    if step <= 0:
        return None
        
    # Round division to 6 decimal places to prevent float inaccuracies before flooring
    lot = math.floor(round(raw_lot / step, 6)) * step
    
    # Clamp between volume min and max
    lot = max(symbol_info.volume_min, min(symbol_info.volume_max, lot))
    
    # Clean float precision issue (e.g. 0.100000000001 -> 0.1)
    step_str = str(step)
    if '.' in step_str:
        decimals = len(step_str.split('.')[1])
        lot = round(lot, decimals)
    else:
        lot = int(lot)
        
    return lot

def divide_lots(total_lots, step):
    """
    Divides the total lots into three segments for TP1 (50%), TP2 (30%), and TP3 (20%).
    Ensures that:
    1. Each segment respects the symbol's volume step.
    2. The sum of the parts equals total_lots.
    3. If total_lots is too small to split, prioritizes TP1, then TP2, then TP3.
    """
    if total_lots < step:
        return 0.0, 0.0, 0.0
        
    # Express calculations as number of volume steps (integers)
    total_steps = int(round(total_lots / step))
    
    # Use standard rounding (adding 0.5 and flooring) to handle 0.5 consistently
    tp1_steps = int(math.floor((0.50 * total_steps) + 0.5))
    tp2_steps = int(math.floor((0.30 * total_steps) + 0.5))
    
    # Prevent exceeding total steps
    tp1_steps = min(total_steps, tp1_steps)
    tp2_steps = min(total_steps - tp1_steps, tp2_steps)
    tp3_steps = total_steps - tp1_steps - tp2_steps
    
    tp1_lots = tp1_steps * step
    tp2_lots = tp2_steps * step
    tp3_lots = tp3_steps * step
    
    # Format precision
    step_str = str(step)
    if '.' in step_str:
        decimals = len(step_str.split('.')[1])
        tp1_lots = round(tp1_lots, decimals)
        tp2_lots = round(tp2_lots, decimals)
        tp3_lots = round(tp3_lots, decimals)
    else:
        tp1_lots = int(tp1_lots)
        tp2_lots = int(tp2_lots)
        tp3_lots = int(tp3_lots)
        
    return tp1_lots, tp2_lots, tp3_lots

def get_filling_mode(symbol_info):
    """
    Selects the correct filling mode from the broker's supported types.
    FOK -> IOC -> RETURN.
    """
    import MetaTrader5 as mt5
    
    if not symbol_info:
        return mt5.ORDER_FILLING_IOC
        
    filling = symbol_info.filling_mode
    if filling & mt5.SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    elif filling & mt5.SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    else:
        return mt5.ORDER_FILLING_RETURN
