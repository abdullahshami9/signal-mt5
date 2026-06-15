import re

def expand_price_range(num1_str, num2_str):
    try:
        val1 = float(num1_str)
        val2 = float(num2_str)
        if val2 >= val1:
            return val1, val2
            
        # Suffix expansion (e.g. 4530-32 -> 4532)
        suffix_len = len(num2_str)
        chars1 = list(num1_str)
        replaced = 0
        for i in range(len(chars1) - 1, -1, -1):
            if chars1[i].isdigit():
                replaced += 1
                chars1[i] = num2_str[-replaced]
                if replaced == suffix_len:
                    break
        expanded_str = "".join(chars1)
        val2 = float(expanded_str)
        if val2 >= val1:
            return val1, val2
            
        return val1, val1
    except Exception:
        return None

def parse_signal(text):
    """
    Parses a Telegram signal text to extract trading details.
    
    Supported types:
    1. Trade: BUY/SELL symbol, SL, TP1, TP2, TP3, and optional Entry Price Range
    2. Close: CLOSE symbol
    3. Modify: MODIFY symbol, new SL, new TP1/TP2/TP3
    
    Returns a dictionary of parsed details or None if not a valid signal.
    """
    if not text:
        return None
        
    # Standardize spaces and uppercase
    text_upper = text.upper().strip()
    
    # --- Check for BUY / SELL action ---
    action_match = re.search(r'\b(BUY|SELL)\b(?:\s+(?:LIMIT|STOP))?\s+([A-Z0-9\.\-_#]+)', text_upper)
    
    if action_match:
        action = action_match.group(1)
        symbol = action_match.group(2)
        
        # Parse Entry Price Range
        entry_min = None
        entry_max = None
        
        # Find the line containing action and symbol
        line_match = re.search(rf'\b({action})\b(?:\s+(?:LIMIT|STOP))?\s+({symbol})([^\n]*)', text_upper)
        if line_match:
            line_after = line_match.group(3)
            # Try to match range like "4530-4532" or "4530-32" or "(4530-32)"
            range_match = re.search(r'(?:PRICE|AT|@)?\s*\(?\s*([0-9\.]+)\s*-\s*([0-9\.]+)\s*\)?', line_after)
            if range_match:
                expanded = expand_price_range(range_match.group(1), range_match.group(2))
                if expanded:
                    entry_min, entry_max = expanded
            else:
                # Try to match single entry price like "@ 4530" or "at 4530"
                single_match = re.search(r'(?:PRICE|AT|@)\s*\(?\s*([0-9\.]+)\s*\)?', line_after)
                if single_match:
                    val = float(single_match.group(1))
                    entry_min, entry_max = val, val
        
        # Extract SL (e.g. SL: 1.2700, SL 1.2700, SL-1.2700, Stop Loss 1.2700)
        sl_match = re.search(r'(?:\bSL\b|\bSTOP LOSS\b)\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        sl = float(sl_match.group(1)) if sl_match else None
        
        # Extract TPs
        tp1_match = re.search(r'\bTP1\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        tp2_match = re.search(r'\bTP2\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        tp3_match = re.search(r'\bTP3\b\s*[:=\-]?\s*([0-9\.]+)', text_upper)
        
        tp1 = float(tp1_match.group(1)) if tp1_match else None
        tp2 = float(tp2_match.group(1)) if tp2_match else None
        tp3 = float(tp3_match.group(1)) if tp3_match else None
        
        # Fallback if no TP1/2/3 but generic TP is found
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
            "tp3": tp3,
            "entry_min": entry_min,
            "entry_max": entry_max
        }
        
    # --- Check for CLOSE action ---
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
