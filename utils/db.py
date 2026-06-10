import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "trading_bot.db"))

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Accounts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        login INTEGER UNIQUE NOT NULL,
        password TEXT NOT NULL,
        server TEXT NOT NULL,
        terminal_path TEXT NOT NULL,
        risk_pct REAL DEFAULT 1.0,
        is_active INTEGER DEFAULT 1,
        balance REAL DEFAULT 0.0,
        equity REAL DEFAULT 0.0,
        connection_status TEXT DEFAULT 'disconnected',
        last_error TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Signals table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_msg_id INTEGER,
        channel_id INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_text TEXT NOT NULL,
        action TEXT NOT NULL, -- BUY, SELL, CLOSE, MODIFY
        symbol TEXT NOT NULL,
        sl REAL,
        tp1 REAL,
        tp2 REAL,
        tp3 REAL,
        status TEXT DEFAULT 'pending' -- pending, processed
    )
    """)
    
    # Trades table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        signal_id INTEGER NOT NULL,
        ticket INTEGER, -- MT5 position ticket
        symbol TEXT NOT NULL,
        action TEXT NOT NULL, -- BUY, SELL
        volume REAL NOT NULL, -- Initial lot size
        sl REAL,
        tp1 REAL,
        tp2 REAL,
        tp3 REAL,
        tp1_lots REAL DEFAULT 0.0,
        tp2_lots REAL DEFAULT 0.0,
        tp3_lots REAL DEFAULT 0.0,
        tp1_hit INTEGER DEFAULT 0,
        tp2_hit INTEGER DEFAULT 0,
        tp3_hit INTEGER DEFAULT 0,
        status TEXT DEFAULT 'open', -- open, closed, failed
        open_price REAL,
        close_price REAL,
        pnl REAL DEFAULT 0.0,
        error_msg TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
    )
    """)
    
    # Signal executions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signal_executions (
        account_id INTEGER NOT NULL,
        signal_id INTEGER NOT NULL,
        status TEXT NOT NULL, -- executed, failed, skipped
        error_msg TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (account_id, signal_id),
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
    )
    """)
    
    # Settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)
    
    # Logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        level TEXT NOT NULL, -- INFO, WARNING, ERROR, DEBUG
        sender TEXT NOT NULL, -- listener, executor_<login>, dashboard, system
        message TEXT NOT NULL
    )
    """)
    
    # Seed default settings
    default_settings = {
        "api_id": "",
        "api_hash": "",
        "phone": "",
        "monitored_channels": "[]", # JSON list of channel IDs or usernames
        "telegram_status": "disconnected"
    }
    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()

# Logs helpers
def add_log(level, sender, message):
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO logs (level, sender, message) VALUES (?, ?, ?)", (level, str(sender), message))
        conn.commit()
    except Exception as e:
        print(f"Database error while adding log: {e}")
    finally:
        conn.close()

def get_recent_logs(limit=100):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# Accounts management
def add_account(login, password, server, terminal_path, risk_pct=1.0):
    conn = get_db_connection()
    try:
        conn.execute("""
        INSERT INTO accounts (login, password, server, terminal_path, risk_pct)
        VALUES (?, ?, ?, ?, ?)
        """, (int(login), password, server, terminal_path, float(risk_pct)))
        conn.commit()
        add_log("INFO", "system", f"Added MT5 account {login} on server {server}")
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_accounts():
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM accounts ORDER BY login ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_account(account_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def update_account_status(login, balance, equity, status, error=None):
    conn = get_db_connection()
    try:
        conn.execute("""
        UPDATE accounts
        SET balance = ?, equity = ?, connection_status = ?, last_error = ?, last_updated = CURRENT_TIMESTAMP
        WHERE login = ?
        """, (float(balance), float(equity), status, error, int(login)))
        conn.commit()
    except Exception as e:
        add_log("ERROR", "system", f"Failed to update status for account {login}: {e}")
    finally:
        conn.close()

def delete_account(account_id):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
        add_log("INFO", "system", f"Deleted account ID {account_id} from database")
        return True
    finally:
        conn.close()

def set_account_active(account_id, is_active):
    conn = get_db_connection()
    try:
        conn.execute("UPDATE accounts SET is_active = ? WHERE id = ?", (1 if is_active else 0, account_id))
        conn.commit()
        return True
    finally:
        conn.close()

# Settings helpers
def get_settings():
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()

def save_settings(settings_dict):
    conn = get_db_connection()
    try:
        for k, v in settings_dict.items():
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
        conn.commit()
        add_log("INFO", "system", "Updated system settings")
        return True
    finally:
        conn.close()

# Signals management
def add_signal(telegram_msg_id, channel_id, raw_text, action, symbol, sl=None, tp1=None, tp2=None, tp3=None):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO signals (telegram_msg_id, channel_id, raw_text, action, symbol, sl, tp1, tp2, tp3)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_msg_id, channel_id, raw_text, action, symbol, sl, tp1, tp2, tp3))
        signal_id = cursor.lastrowid
        conn.commit()
        add_log("INFO", "listener", f"Inserted parsed signal {signal_id} ({action} {symbol}) from Telegram")
        return signal_id
    finally:
        conn.close()

def get_recent_signals(limit=20):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_pending_signals_for_account(account_id):
    """
    Get signals that have NOT been processed by this account yet.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute("""
        SELECT s.* FROM signals s
        LEFT JOIN signal_executions se ON s.id = se.signal_id AND se.account_id = ?
        WHERE se.signal_id IS NULL
        ORDER BY s.id ASC
        """, (account_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# Signal executions
def mark_signal_executed(account_id, signal_id, status, error_msg=None):
    conn = get_db_connection()
    try:
        conn.execute("""
        INSERT OR REPLACE INTO signal_executions (account_id, signal_id, status, error_msg, timestamp)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (account_id, signal_id, status, error_msg))
        conn.commit()
    finally:
        conn.close()

# Trades management
def add_trade(account_id, signal_id, ticket, symbol, action, volume, sl, tp1, tp2, tp3, tp1_lots, tp2_lots, tp3_lots, open_price):
    conn = get_db_connection()
    try:
        conn.execute("""
        INSERT INTO trades (
            account_id, signal_id, ticket, symbol, action, volume, sl, tp1, tp2, tp3,
            tp1_lots, tp2_lots, tp3_lots, open_price, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """, (
            account_id, signal_id, ticket, symbol, action, float(volume),
            float(sl) if sl else None, float(tp1) if tp1 else None,
            float(tp2) if tp2 else None, float(tp3) if tp3 else None,
            float(tp1_lots), float(tp2_lots), float(tp3_lots), float(open_price)
        ))
        conn.commit()
        add_log("INFO", f"executor_acc_{account_id}", f"Recorded open trade ticket {ticket} ({symbol} {action}) in DB")
    except Exception as e:
        add_log("ERROR", f"executor_acc_{account_id}", f"Failed to record trade ticket {ticket} in DB: {e}")
    finally:
        conn.close()

def get_open_trades_for_account(account_id):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM trades WHERE account_id = ? AND status = 'open'", (account_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def update_trade_tp_status(trade_id, tp1_hit=None, tp2_hit=None, tp3_hit=None, status=None, close_price=None, pnl=None):
    conn = get_db_connection()
    try:
        updates = []
        params = []
        if tp1_hit is not None:
            updates.append("tp1_hit = ?")
            params.append(1 if tp1_hit else 0)
        if tp2_hit is not None:
            updates.append("tp2_hit = ?")
            params.append(1 if tp2_hit else 0)
        if tp3_hit is not None:
            updates.append("tp3_hit = ?")
            params.append(1 if tp3_hit else 0)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if close_price is not None:
            updates.append("close_price = ?")
            params.append(float(close_price))
        if pnl is not None:
            updates.append("pnl = ?")
            params.append(float(pnl))
            
        updates.append("last_updated = CURRENT_TIMESTAMP")
        
        query = f"UPDATE trades SET {', '.join(updates)} WHERE id = ?"
        params.append(trade_id)
        
        conn.execute(query, params)
        conn.commit()
    except Exception as e:
        add_log("ERROR", "system", f"Failed to update trade ID {trade_id}: {e}")
    finally:
        conn.close()

def get_recent_trades(limit=50):
    conn = get_db_connection()
    try:
        rows = conn.execute("""
        SELECT t.*, a.login as account_login FROM trades t
        JOIN accounts a ON t.account_id = a.id
        ORDER BY t.id DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
