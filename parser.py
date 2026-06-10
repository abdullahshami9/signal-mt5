import re

def parse_signal(text):
    """
    Parses a Telegram signal text to extract trading details.
    
    Supported types:
    1. Trade: BUY/SELL symbol, SL, TP1, TP2, TP3
    2. Close: CLOSE symbol
    3. Modify: MODIFY symbol, new SL, new TP1/TP2/TP3
    
    Returns a dictionary of parsed details or None if not a valid signal.
    """
    if not text:
        return None
        
    # Standardize spaces and uppercase
    text_upper = text.upper().strip()
    
    # --- Check for BUY / SELL action ---
    # Matches "BUY GBPUSD", "SELL XAUUSD", "BUY LIMIT EURUSD", etc.
    # Note: We support market orders, limit/stop orders can be parsed but for MVP we focus on execution as market orders.
    action_match = re.search(r'\b(BUY|SELL)\b(?:\s+(?:LIMIT|STOP))?\s+([A-Z0-9\.\-_#]+)', text_upper)
    
    if action_match:
        action = action_match.group(1)
        symbol = action_match.group(2)
        
        # Extract SL (e.g. SL: 1.2700, SL 1.2700, SL-1.2700, Stop Loss 1.2700)
        sl_match = re.search(r'(?:\bSL\b|\bSTOP LOSS\b)\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        sl = float(sl_match.group(1)) if sl_match else None
        
        # Extract TPs
        # Check specifically for TP1, TP2, TP3
        tp1_match = re.search(r'\bTP1\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        tp2_match = re.search(r'\bTP2\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        tp3_match = re.search(r'\bTP3\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        
        tp1 = float(tp1_match.group(1)) if tp1_match else None
        tp2 = float(tp2_match.group(1)) if tp2_match else None
        tp3 = float(tp3_match.group(1)) if tp3_match else None
        
        # If no TP1/2/3 but a generic TP is found, assign it to TP1
        if not tp1:
            tp_match = re.search(r'\bTP\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
            if tp_match:
                tp1 = float(tp_match.group(1))
                
        return {
            "type": "trade",
            "action": action,
            "symbol": symbol,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3
        }
        
    # --- Check for CLOSE action ---
    # Matches "CLOSE GBPUSD", "EXIT GBPUSD"
    close_match = re.search(r'\b(CLOSE|EXIT)\b\s+([A-Z0-9\.\-_#]+)', text_upper)
    if close_match:
        action = "CLOSE"
        symbol = close_match.group(2)
        return {
            "type": "close",
            "action": action,
            "symbol": symbol
        }
        
    # --- Check for MODIFY action ---
    # Matches "MODIFY GBPUSD SL 1.2750", "UPDATE GBPUSD TP1 1.2800"
    modify_match = re.search(r'\b(MODIFY|UPDATE)\b\s+([A-Z0-9\.\-_#]+)', text_upper)
    if modify_match:
        symbol = modify_match.group(2)
        
        sl_match = re.search(r'(?:\bSL\b|\bSTOP LOSS\b)\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        sl = float(sl_match.group(1)) if sl_match else None
        
        tp1_match = re.search(r'\bTP1\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        tp2_match = re.search(r'\bTP2\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        tp3_match = re.search(r'\bTP3\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        
        tp1 = float(tp1_match.group(1)) if tp1_match else None
        tp2 = float(tp2_match.group(1)) if tp2_match else None
        tp3 = float(tp3_match.group(1)) if tp3_match else None
        
        if not tp1:
            tp_match = re.search(r'\bTP\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
            if tp_match:
                tp1 = float(tp_match.group(1))
                
        return {
            "type": "modify",
            "action": "MODIFY",
            "symbol": symbol,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3
        }
        
    return None
