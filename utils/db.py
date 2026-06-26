import os
import json
import hashlib
import uuid
from datetime import datetime
from dotenv import load_dotenv

# Load env variables from .env
load_dotenv()

PROD_DB = os.getenv("PROD_DB", "False").lower() in ("true", "1", "t", "yes")

class MySQLRow:
    def __init__(self, cursor, values):
        self._keys = [col[0] for col in cursor.description] if cursor.description else []
        self._values = values
        self._dict = dict(zip(self._keys, values))
        
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._dict[key]
        
    def keys(self):
        return self._keys
        
    def values(self):
        return self._values
        
    def items(self):
        return self._dict.items()
        
    def __iter__(self):
        return iter(self._values)
        
    def __len__(self):
        return len(self._values)
        
    def __repr__(self):
        return repr(self._values)


class MySQLCursorAdapter:
    def __init__(self, cursor, row_factory=None):
        self._cursor = cursor
        self.row_factory = row_factory

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def execute(self, sql, parameters=()):
        if isinstance(sql, str):
            sql = sql.replace('?', '%s')
        self._cursor.execute(sql, parameters)
        return self

    def executemany(self, sql, seq_of_parameters):
        if isinstance(sql, str):
            sql = sql.replace('?', '%s')
        self._cursor.executemany(sql, seq_of_parameters)
        return self

    def executescript(self, sql_script):
        for statement in sql_script.split(';'):
            statement = statement.strip()
            if statement:
                self.execute(statement)
        return self

    def _wrap_row(self, row):
        if row is None:
            return None
        if self.row_factory:
            return self.row_factory(self, row)
        return row

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._wrap_row(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [self._wrap_row(r) for r in rows]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        return [self._wrap_row(r) for r in rows]

    def close(self):
        self._cursor.close()


class MySQLConnectionAdapter:
    def __init__(self, conn):
        self._conn = conn
        self.row_factory = None

    def cursor(self):
        return MySQLCursorAdapter(self._conn.cursor(), self.row_factory)

    def execute(self, sql, parameters=()):
        cursor = self.cursor()
        cursor.execute(sql, parameters)
        return cursor

    def executemany(self, sql, seq_of_parameters):
        cursor = self.cursor()
        cursor.executemany(sql, seq_of_parameters)
        return cursor

    def executescript(self, sql_script):
        cursor = self.cursor()
        cursor.executescript(sql_script)
        return cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


if PROD_DB:
    DB_HOST = os.getenv("DB_HOST_PROD")
    DB_PORT = int(os.getenv("DB_PORT_PROD", 3306))
    DB_USER = os.getenv("DB_USER_PROD")
    DB_PASSWORD = os.getenv("DB_PASSWORD_PROD")
    DB_NAME = os.getenv("DB_NAME_PROD")
else:
    DB_HOST = os.getenv("DB_HOST_LOCAL")
    DB_PORT = int(os.getenv("DB_PORT_LOCAL", 3306))
    DB_USER = os.getenv("DB_USER_LOCAL")
    DB_PASSWORD = os.getenv("DB_PASSWORD_LOCAL")
    DB_NAME = os.getenv("DB_NAME_LOCAL")

import pymysql
import pymysql.err

OperationalError = pymysql.err.OperationalError
IntegrityError = pymysql.err.IntegrityError
DatabaseError = pymysql.err.DatabaseError
RowFactory = MySQLRow

def get_db_connection():
    raw_conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True
    )
    with raw_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}`")
    raw_conn.select_db(DB_NAME)
    
    conn = MySQLConnectionAdapter(raw_conn)
    conn.row_factory = RowFactory
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Access Users table for parent login
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS access_users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # User Sessions table for tracking login sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        session_id VARCHAR(255) PRIMARY KEY,
        user_id INT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)

    # Seed default user if access_users is empty
    cursor.execute("SELECT COUNT(*) FROM access_users")
    if cursor.fetchone()[0] == 0:
        default_username = "vendor1"
        default_pwd_hash = hash_password("vendor123")
        cursor.execute("INSERT INTO access_users (username, password_hash) VALUES (?, ?)", (default_username, default_pwd_hash))

    # Accounts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        login BIGINT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        server VARCHAR(255) NOT NULL,
        terminal_path TEXT NOT NULL,
        risk_pct DOUBLE DEFAULT 1.0,
        is_active INT DEFAULT 1,
        balance DOUBLE DEFAULT 0.0,
        equity DOUBLE DEFAULT 0.0,
        connection_status VARCHAR(50) DEFAULT 'disconnected',
        last_error TEXT,
        name VARCHAR(255),
        payment_date VARCHAR(50),
        user_id INT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)
    
    # Signals table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INT AUTO_INCREMENT PRIMARY KEY,
        telegram_msg_id BIGINT,
        channel_id BIGINT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_text TEXT NOT NULL,
        action VARCHAR(50) NOT NULL,
        symbol VARCHAR(50) NOT NULL,
        sl DOUBLE,
        tp1 DOUBLE,
        tp2 DOUBLE,
        tp3 DOUBLE,
        entry_min DOUBLE,
        entry_max DOUBLE,
        status VARCHAR(50) DEFAULT 'pending',
        user_id INT,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)
    
    # Ensure columns exist in signals table in case table was created already
    try:
        cursor.execute("ALTER TABLE signals ADD COLUMN entry_min DOUBLE")
    except OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE signals ADD COLUMN entry_max DOUBLE")
    except OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE signals ADD COLUMN user_id INT REFERENCES access_users(id) ON DELETE CASCADE")
    except OperationalError:
        pass
        
    cursor.execute("UPDATE signals SET user_id = 1 WHERE user_id IS NULL")
        
    # Ensure columns exist in accounts table in case table was created already
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN name VARCHAR(255)")
    except OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN payment_date VARCHAR(50)")
    except OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN user_id INT REFERENCES access_users(id) ON DELETE CASCADE")
    except OperationalError:
        pass
    
    # Trades table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INT AUTO_INCREMENT PRIMARY KEY,
        account_id INT NOT NULL,
        signal_id INT NOT NULL,
        ticket BIGINT,
        symbol VARCHAR(50) NOT NULL,
        action VARCHAR(50) NOT NULL,
        volume DOUBLE NOT NULL,
        sl DOUBLE,
        tp1 DOUBLE,
        tp2 DOUBLE,
        tp3 DOUBLE,
        tp1_lots DOUBLE DEFAULT 0.0,
        tp2_lots DOUBLE DEFAULT 0.0,
        tp3_lots DOUBLE DEFAULT 0.0,
        tp1_hit INT DEFAULT 0,
        tp2_hit INT DEFAULT 0,
        tp3_hit INT DEFAULT 0,
        status VARCHAR(50) DEFAULT 'open',
        open_price DOUBLE,
        close_price DOUBLE,
        pnl DOUBLE DEFAULT 0.0,
        error_msg TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
    )
    """)
    
    # Signal executions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signal_executions (
        account_id INT NOT NULL,
        signal_id INT NOT NULL,
        status VARCHAR(50) NOT NULL,
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
        user_id INT NOT NULL,
        `key` VARCHAR(255) NOT NULL,
        `value` TEXT NOT NULL,
        PRIMARY KEY (user_id, `key`),
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)
        
    # Seed default settings for user_id = 1
    cursor.execute("SELECT COUNT(*) FROM settings WHERE user_id = 1")
    if cursor.fetchone()[0] == 0:
        default_settings = {
            "api_id": "",
            "api_hash": "",
            "phone": "",
            "monitored_channels": "[]", # JSON list of channel IDs or usernames
            "telegram_status": "disconnected"
        }
        for k, v in default_settings.items():
            cursor.execute("INSERT IGNORE INTO settings (user_id, `key`, `value`) VALUES (1, ?, ?)", (k, v))
    
    # Logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        level VARCHAR(50) NOT NULL,
        sender VARCHAR(255) NOT NULL,
        message TEXT NOT NULL,
        user_id INT,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)
    
    # Ensure logs has user_id column
    try:
        cursor.execute("ALTER TABLE logs ADD COLUMN user_id INT REFERENCES access_users(id) ON DELETE CASCADE")
    except OperationalError:
        pass
        
    cursor.execute("UPDATE logs SET user_id = 1 WHERE user_id IS NULL")
        
    conn.commit()
    conn.close()

# Logs helpers
def add_log(level, sender, message, user_id=None):
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO logs (level, sender, message, user_id) VALUES (?, ?, ?, ?)", (level, str(sender), message, user_id))
        conn.commit()
    except Exception as e:
        print(f"Database error while adding log: {e}")
    finally:
        conn.close()

def get_recent_logs(limit=100, user_id=None):
    conn = get_db_connection()
    try:
        if user_id is not None:
            rows = conn.execute("SELECT * FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
            return [dict(r) for r in rows]
        else:
            rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()

# Accounts management
def add_account(login, password, server, terminal_path, risk_pct=1.0, name=None, payment_date=None, user_id=None):
    conn = get_db_connection()
    try:
        conn.execute("""
        INSERT INTO accounts (login, password, server, terminal_path, risk_pct, name, payment_date, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (int(login), password, server, terminal_path or "", float(risk_pct), name, payment_date, user_id))
        conn.commit()
        add_log("INFO", "system", f"Added MT5 account {login} on server {server} for user {user_id}", user_id=user_id)
        return True
    except IntegrityError:
        return False
    finally:
        conn.close()

def get_accounts(user_id=None):
    conn = get_db_connection()
    try:
        if user_id is not None:
            rows = conn.execute("SELECT * FROM accounts WHERE user_id = ? ORDER BY login ASC", (user_id,)).fetchall()
        else:
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
    user_id = None
    try:
        # Fetch user_id for logging
        account = conn.execute("SELECT user_id FROM accounts WHERE login = ?", (int(login),)).fetchone()
        if account:
            user_id = account["user_id"]

        conn.execute("""
        UPDATE accounts
        SET balance = ?, equity = ?, connection_status = ?, last_error = ?, last_updated = CURRENT_TIMESTAMP
        WHERE login = ?
        """, (float(balance), float(equity), status, error, int(login)))
        conn.commit()
    except Exception as e:
        add_log("ERROR", "system", f"Failed to update status for account {login}: {e}", user_id=user_id)
    finally:
        conn.close()

def delete_account(account_id):
    conn = get_db_connection()
    try:
        # Get user_id before deleting
        account = conn.execute("SELECT user_id FROM accounts WHERE id = ?", (account_id,)).fetchone()
        user_id = account["user_id"] if account else None

        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
        add_log("INFO", "system", f"Deleted account ID {account_id} from database", user_id=user_id)
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
def get_settings(user_id=None):
    if user_id is None:
        user_id = 1
    conn = get_db_connection()
    try:
        # Seed default settings if they don't exist for this user_id
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM settings WHERE user_id = ?", (user_id,))
        if cursor.fetchone()[0] == 0:
            default_settings = {
                "api_id": "",
                "api_hash": "",
                "phone": "",
                "monitored_channels": "[]", # JSON list of channel IDs or usernames
                "telegram_status": "disconnected"
            }
            for k, v in default_settings.items():
                cursor.execute("INSERT IGNORE INTO settings (user_id, `key`, `value`) VALUES (?, ?, ?)", (user_id, k, v))
            conn.commit()

        rows = conn.execute("SELECT `key`, `value` FROM settings WHERE user_id = ?", (user_id,)).fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        conn.close()

def save_settings(settings_dict, user_id=None):
    if user_id is None:
        user_id = 1
    conn = get_db_connection()
    try:
        for k, v in settings_dict.items():
            conn.execute("REPLACE INTO settings (user_id, `key`, `value`) VALUES (?, ?, ?)", (user_id, k, str(v)))
        conn.commit()
        add_log("INFO", "system", "Updated system settings", user_id=user_id)
        return True
    finally:
        conn.close()

# Signals management
def add_signal(telegram_msg_id, channel_id, raw_text, action, symbol, sl=None, tp1=None, tp2=None, tp3=None, entry_min=None, entry_max=None, user_id=None):
    if user_id is None:
        user_id = 1
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO signals (telegram_msg_id, channel_id, raw_text, action, symbol, sl, tp1, tp2, tp3, entry_min, entry_max, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_msg_id, channel_id, raw_text, action, symbol, sl, tp1, tp2, tp3, entry_min, entry_max, user_id))
        signal_id = cursor.lastrowid
        conn.commit()
        add_log("INFO", "listener", f"Inserted parsed signal {signal_id} ({action} {symbol}) from Telegram", user_id=user_id)
        return signal_id
    finally:
        conn.close()

def get_recent_signals(limit=20, user_id=None):
    conn = get_db_connection()
    try:
        if user_id is not None:
            rows = conn.execute("SELECT * FROM signals WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_pending_signals_for_account(account_id):
    """
    Get signals that have NOT been processed by this account yet, and belong to the account's owner.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute("""
        SELECT s.* FROM signals s
        JOIN accounts a ON a.id = ?
        LEFT JOIN signal_executions se ON s.id = se.signal_id AND se.account_id = a.id
        WHERE se.signal_id IS NULL AND s.user_id = a.user_id
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
        REPLACE INTO signal_executions (account_id, signal_id, status, error_msg, timestamp)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (account_id, signal_id, status, error_msg))
        conn.commit()
    finally:
        conn.close()

# Trades management
def add_trade(account_id, signal_id, ticket, symbol, action, volume, sl, tp1, tp2, tp3, tp1_lots, tp2_lots, tp3_lots, open_price, status='open'):
    conn = get_db_connection()
    try:
        # Get user_id for logging
        account = conn.execute("SELECT user_id FROM accounts WHERE id = ?", (account_id,)).fetchone()
        user_id = account["user_id"] if account else None

        conn.execute("""
        INSERT INTO trades (
            account_id, signal_id, ticket, symbol, action, volume, sl, tp1, tp2, tp3,
            tp1_lots, tp2_lots, tp3_lots, open_price, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            account_id, signal_id, ticket, symbol, action, float(volume),
            float(sl) if sl else None, float(tp1) if tp1 else None,
            float(tp2) if tp2 else None, float(tp3) if tp3 else None,
            float(tp1_lots), float(tp2_lots), float(tp3_lots), float(open_price), status
        ))
        conn.commit()
        add_log("INFO", f"executor_acc_{account_id}", f"Recorded {status} trade ticket {ticket} ({symbol} {action}) in DB", user_id=user_id)
    except Exception as e:
        add_log("ERROR", f"executor_acc_{account_id}", f"Failed to record trade ticket {ticket} in DB: {e}", user_id=user_id if 'user_id' in locals() else None)
    finally:
        conn.close()

def get_open_trades_for_account(account_id):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM trades WHERE account_id = ? AND status = 'open'", (account_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_pending_trades_for_account(account_id):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM trades WHERE account_id = ? AND status = 'pending'", (account_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_cancel_requested_trades_for_account(account_id):
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM trades WHERE account_id = ? AND status = 'cancel_requested'", (account_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def update_trade_tp_status(trade_id, tp1_hit=None, tp2_hit=None, tp3_hit=None, status=None, close_price=None, pnl=None, open_price=None, error_msg=None):
    conn = get_db_connection()
    try:
        # Get user_id for logging
        trade = conn.execute("SELECT account_id FROM trades WHERE id = ?", (trade_id,)).fetchone()
        user_id = None
        if trade:
            account = conn.execute("SELECT user_id FROM accounts WHERE id = ?", (trade["account_id"],)).fetchone()
            if account:
                user_id = account["user_id"]

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
        if open_price is not None:
            updates.append("open_price = ?")
            params.append(float(open_price))
        if error_msg is not None:
            updates.append("error_msg = ?")
            params.append(error_msg)
            
        updates.append("last_updated = CURRENT_TIMESTAMP")
        
        query = f"UPDATE trades SET {', '.join(updates)} WHERE id = ?"
        params.append(trade_id)
        
        conn.execute(query, params)
        conn.commit()
    except Exception as e:
        add_log("ERROR", "system", f"Failed to update trade ID {trade_id}: {e}", user_id=user_id if 'user_id' in locals() else None)
    finally:
        conn.close()

def get_recent_trades(limit=50, user_id=None):
    conn = get_db_connection()
    try:
        if user_id is not None:
            rows = conn.execute("""
            SELECT t.*, a.login as account_login FROM trades t
            JOIN accounts a ON t.account_id = a.id
            WHERE a.user_id = ?
            ORDER BY t.id DESC LIMIT ?
            """, (user_id, limit)).fetchall()
        else:
            rows = conn.execute("""
            SELECT t.*, a.login as account_login FROM trades t
            JOIN accounts a ON t.account_id = a.id
            ORDER BY t.id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# User & Session management helpers
def get_all_users():
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM access_users").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def hash_password(password: str, salt: str = None) -> str:
    if salt is None:
        salt = uuid.uuid4().hex
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}:{pwd_hash.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, pwd_hash_hex = stored_hash.split(":", 1)
        pwd_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return pwd_hash.hex() == pwd_hash_hex
    except Exception:
        return False

def create_user(username, password):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        pwd_hash = hash_password(password)
        cursor.execute("INSERT INTO access_users (username, password_hash) VALUES (?, ?)", (username, pwd_hash))
        conn.commit()
        return True
    except IntegrityError:
        return False
    finally:
        conn.close()

def authenticate_user(username, password):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM access_users WHERE username = ?", (username,)).fetchone()
        if row and verify_password(password, row["password_hash"]):
            return dict(row)
        return None
    finally:
        conn.close()

def create_session(user_id):
    conn = get_db_connection()
    try:
        session_token = uuid.uuid4().hex
        conn.execute("INSERT INTO user_sessions (session_id, user_id) VALUES (?, ?)", (session_token, user_id))
        conn.commit()
        return session_token
    finally:
        conn.close()

def verify_session(session_token):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT user_id FROM user_sessions WHERE session_id = ?", (session_token,)).fetchone()
        return row["user_id"] if row else None
    finally:
        conn.close()

def delete_session(session_token):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM user_sessions WHERE session_id = ?", (session_token,))
        conn.commit()
        return True
    finally:
        conn.close()
