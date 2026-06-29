import os
import sys
import json
import hashlib
import uuid
from datetime import datetime
from dotenv import load_dotenv
import time

# Load env variables from .env in executable/script directory
is_frozen = getattr(sys, 'frozen', False)
if is_frozen:
    exe_dir = os.path.dirname(sys.executable)
    dotenv_path = os.path.join(exe_dir, ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
    else:
        load_dotenv()
else:
    load_dotenv()

default_prod = "True" if is_frozen else "False"
PROD_DB = os.getenv("PROD_DB", default_prod).lower() in ("true", "1", "t", "yes")

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


import sqlite3
import pymysql
import pymysql.err

class SQLiteRow:
    def __init__(self, cursor, row):
        self._keys = [col[0] for col in cursor.description] if cursor.description else []
        self._values = row
        self._dict = dict(zip(self._keys, row))
        
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


class SQLiteCursorAdapter:
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
        self._cursor.execute(sql, parameters)
        return self

    def executemany(self, sql, seq_of_parameters):
        self._cursor.executemany(sql, seq_of_parameters)
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


class SQLiteConnectionAdapter:
    def __init__(self, conn):
        self._conn = conn
        self.row_factory = None

    def cursor(self):
        return SQLiteCursorAdapter(self._conn.cursor(), self.row_factory)

    def execute(self, sql, parameters=()):
        sql_upper = sql.strip().upper() if isinstance(sql, str) else ""
        if any(sql_upper.startswith(w) for w in ["INSERT", "UPDATE", "DELETE", "REPLACE"]):
            global _local_changes_pending
            _local_changes_pending = True
        cursor = self.cursor()
        cursor.execute(sql, parameters)
        return cursor

    def executemany(self, sql, seq_of_parameters):
        sql_upper = sql.strip().upper() if isinstance(sql, str) else ""
        if any(sql_upper.startswith(w) for w in ["INSERT", "UPDATE", "DELETE", "REPLACE"]):
            global _local_changes_pending
            _local_changes_pending = True
        cursor = self.cursor()
        cursor.executemany(sql, seq_of_parameters)
        return cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


if PROD_DB:
    DB_HOST = os.getenv("DB_HOST_PROD", "13.49.223.231")
    DB_PORT = int(os.getenv("DB_PORT_PROD", 3306))
    DB_USER = os.getenv("DB_USER_PROD", "trading_user")
    DB_PASSWORD = os.getenv("DB_PASSWORD_PROD", "trading_pass123")
    DB_NAME = os.getenv("DB_NAME_PROD", "trading_bot")
else:
    DB_HOST = os.getenv("DB_HOST_LOCAL")
    DB_PORT = int(os.getenv("DB_PORT_LOCAL", 3306))
    DB_USER = os.getenv("DB_USER_LOCAL")
    DB_PASSWORD = os.getenv("DB_PASSWORD_LOCAL")
    DB_NAME = os.getenv("DB_NAME_LOCAL")

# Unified exceptions that work with both databases
OperationalError = (sqlite3.OperationalError, pymysql.err.OperationalError)
IntegrityError = (sqlite3.IntegrityError, pymysql.err.IntegrityError)
DatabaseError = (sqlite3.DatabaseError, pymysql.err.DatabaseError)

_local_changes_pending = True
_last_sync_time = 0.0

def get_local_db_path():
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    return os.path.join(base_dir, "local_storage.db")

def get_local_db_connection():
    db_path = get_local_db_path()
    raw_conn = sqlite3.connect(db_path, timeout=30.0)
    raw_conn.execute("PRAGMA foreign_keys = ON")
    raw_conn.execute("PRAGMA journal_mode = WAL")
    raw_conn.execute("PRAGMA synchronous = NORMAL")
    raw_conn.execute("PRAGMA temp_store = MEMORY")
    raw_conn.execute("PRAGMA cache_size = -2000")
    conn = SQLiteConnectionAdapter(raw_conn)
    conn.row_factory = SQLiteRow
    return conn

def get_live_db_connection():
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
    conn.row_factory = MySQLRow
    return conn

def get_db_connection():
    # Rerouted operational connection to local SQLite
    return get_local_db_connection()

def init_live_db():
    conn = get_live_db_connection()
    cursor = conn.cursor()
    
    # Access Users table for parent login
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS access_users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        is_blocked BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Ensure is_blocked column exists in case table was created already
    try:
        cursor.execute("ALTER TABLE access_users ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE")
    except OperationalError:
        pass

    # User Sessions table for tracking login sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        session_id VARCHAR(255) PRIMARY KEY,
        user_id INT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)



    # Accounts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        login BIGINT NOT NULL,
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
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE,
        UNIQUE KEY login_user_id (login, user_id)
    )
    """)

    # Migrate live DB schema if old unique index 'login' exists
    try:
        cursor.execute("SHOW INDEX FROM accounts WHERE Key_name = 'login_user_id'")
        has_new_index = cursor.fetchone()
        cursor.execute("SHOW INDEX FROM accounts WHERE Key_name = 'login'")
        has_old_index = cursor.fetchone()
        
        if has_old_index and not has_new_index:
            print("Migrating MySQL accounts table unique constraint...")
            cursor.execute("ALTER TABLE accounts DROP INDEX login")
            cursor.execute("ALTER TABLE accounts ADD UNIQUE KEY login_user_id (login, user_id)")
            conn.commit()
            print("MySQL accounts table migration completed successfully.")
    except Exception as e:
        print(f"Warning: Could not alter MySQL accounts table index: {e}")
    
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

def init_local_sqlite_db():
    db_path = get_local_db_path()
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("PRAGMA foreign_keys = ON")
    cursor = raw_conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS access_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_blocked INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        session_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)

    # Check if accounts table exists and contains the old 'login INTEGER UNIQUE' constraint
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'")
    accounts_table = cursor.fetchone()
    if accounts_table and "login INTEGER UNIQUE" in accounts_table[0]:
        print("Migrating SQLite accounts table unique constraint...")
        try:
            # Disable foreign keys temporarily for renaming
            raw_conn.execute("PRAGMA foreign_keys = OFF")
            raw_conn.execute("ALTER TABLE accounts RENAME TO accounts_old")
            
            # Create new table with UNIQUE (login, user_id)
            raw_conn.execute("""
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login INTEGER NOT NULL,
                password TEXT NOT NULL,
                server TEXT NOT NULL,
                terminal_path TEXT NOT NULL,
                risk_pct REAL DEFAULT 1.0,
                is_active INTEGER DEFAULT 1,
                balance REAL DEFAULT 0.0,
                equity REAL DEFAULT 0.0,
                connection_status TEXT DEFAULT 'disconnected',
                last_error TEXT,
                name TEXT,
                payment_date TEXT,
                user_id INTEGER,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE,
                UNIQUE (login, user_id)
            )
            """)
            
            # Copy data
            raw_conn.execute("""
            INSERT INTO accounts (id, login, password, server, terminal_path, risk_pct, is_active, balance, equity, connection_status, last_error, name, payment_date, user_id, last_updated)
            SELECT id, login, password, server, terminal_path, risk_pct, is_active, balance, equity, connection_status, last_error, name, payment_date, user_id, last_updated
            FROM accounts_old
            """)
            
            raw_conn.execute("DROP TABLE accounts_old")
            raw_conn.commit()
            print("SQLite accounts table migration completed successfully.")
        except Exception as e:
            raw_conn.rollback()
            print(f"Error migrating SQLite accounts table: {e}")
        finally:
            raw_conn.execute("PRAGMA foreign_keys = ON")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        login INTEGER NOT NULL,
        password TEXT NOT NULL,
        server TEXT NOT NULL,
        terminal_path TEXT NOT NULL,
        risk_pct REAL DEFAULT 1.0,
        is_active INTEGER DEFAULT 1,
        balance REAL DEFAULT 0.0,
        equity REAL DEFAULT 0.0,
        connection_status TEXT DEFAULT 'disconnected',
        last_error TEXT,
        name TEXT,
        payment_date TEXT,
        user_id INTEGER,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE,
        UNIQUE (login, user_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_msg_id INTEGER,
        channel_id INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_text TEXT NOT NULL,
        action TEXT NOT NULL,
        symbol TEXT NOT NULL,
        sl REAL,
        tp1 REAL,
        tp2 REAL,
        tp3 REAL,
        entry_min REAL,
        entry_max REAL,
        status TEXT DEFAULT 'pending',
        user_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        signal_id INTEGER NOT NULL,
        ticket INTEGER,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        volume REAL NOT NULL,
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
        status TEXT DEFAULT 'open',
        open_price REAL,
        close_price REAL,
        pnl REAL DEFAULT 0.0,
        error_msg TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS signal_executions (
        account_id INTEGER NOT NULL,
        signal_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        error_msg TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (account_id, signal_id),
        FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (user_id, key),
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        level TEXT NOT NULL,
        sender TEXT NOT NULL,
        message TEXT NOT NULL,
        user_id INTEGER,
        synced INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
    )
    """)

    raw_conn.commit()
    raw_conn.close()

def init_db():
    init_local_sqlite_db()
    try:
        init_live_db()
    except Exception as e:
        print(f"Warning: Could not initialize live DB on AWS: {e}")

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
            rows = conn.execute("""
                SELECT a.*, GROUP_CONCAT(au.username) AS other_vendors
                FROM accounts a
                LEFT JOIN accounts a2 ON a.login = a2.login AND a.user_id != a2.user_id
                LEFT JOIN access_users au ON a2.user_id = au.id
                WHERE a.user_id = ?
                GROUP BY a.id
                ORDER BY a.login ASC
            """, (user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM accounts ORDER BY login ASC").fetchall()
            
        result = []
        for r in rows:
            d = dict(r)
            if "other_vendors" in d and d["other_vendors"]:
                d["other_vendors"] = [u.strip() for u in d["other_vendors"].split(",") if u.strip()]
            else:
                d["other_vendors"] = []
            result.append(d)
        return result
    finally:
        conn.close()

def get_account(account_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def update_account_status(account_id, balance, equity, status, error=None):
    conn = get_db_connection()
    user_id = None
    login = None
    try:
        # Fetch user_id and login for logging
        account = conn.execute("SELECT user_id, login FROM accounts WHERE id = ?", (int(account_id),)).fetchone()
        if account:
            user_id = account["user_id"]
            login = account["login"]

        conn.execute("""
        UPDATE accounts
        SET balance = ?, equity = ?, connection_status = ?, last_error = ?, last_updated = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (float(balance), float(equity), status, error, int(account_id)))
        conn.commit()
    except Exception as e:
        login_str = f"ID {account_id}" if not login else f"{login}"
        add_log("ERROR", "system", f"Failed to update status for account {login_str}: {e}", user_id=user_id)
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
                cursor.execute("INSERT OR IGNORE INTO settings (user_id, `key`, `value`) VALUES (?, ?, ?)", (user_id, k, v))
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

_session_cache = {}

def sync_user_to_local(user_data):
    local_conn = get_local_db_connection()
    try:
        # Check if user already exists to avoid REPLACE (which causes ON DELETE CASCADE in SQLite)
        exists = local_conn.execute("SELECT 1 FROM access_users WHERE id = ?", (user_data["id"],)).fetchone()
        if exists:
            local_conn.execute("""
                UPDATE access_users 
                SET username = ?, password_hash = ?, is_blocked = ?
                WHERE id = ?
            """, (user_data["username"], user_data["password_hash"], user_data["is_blocked"], user_data["id"]))
        else:
            local_conn.execute("""
                INSERT INTO access_users (id, username, password_hash, is_blocked)
                VALUES (?, ?, ?, ?)
            """, (user_data["id"], user_data["username"], user_data["password_hash"], user_data["is_blocked"]))
        local_conn.commit()
    except Exception as e:
        print(f"Error syncing user to local: {e}")
    finally:
        local_conn.close()

def sync_session_to_local(session_token, user_id):
    local_conn = get_local_db_connection()
    try:
        # Check if session already exists to avoid REPLACE
        exists = local_conn.execute("SELECT 1 FROM user_sessions WHERE session_id = ?", (session_token,)).fetchone()
        if exists:
            local_conn.execute("""
                UPDATE user_sessions SET user_id = ? WHERE session_id = ?
            """, (user_id, session_token))
        else:
            local_conn.execute("""
                INSERT INTO user_sessions (session_id, user_id)
                VALUES (?, ?)
            """, (session_token, user_id))
        local_conn.commit()
    except Exception as e:
        print(f"Error syncing session to local: {e}")
    finally:
        local_conn.close()

def update_local_user_block_status(user_id, is_blocked):
    local_conn = get_local_db_connection()
    try:
        local_conn.execute("UPDATE access_users SET is_blocked = ? WHERE id = ?", (is_blocked, user_id))
        local_conn.commit()
    except Exception as e:
        print(f"Error updating local user block status: {e}")
    finally:
        local_conn.close()

def pull_data_from_live(user_id):
    """
    Pulls data (settings, accounts, signals, trades, executions) from the live database
    to the local database. This is used when a user logs in, to ensure they don't have
    an empty local database that would overwrite/delete cloud data during subsequent syncs.
    """
    try:
        live_conn = get_live_db_connection()
    except Exception as e:
        print(f"Warning: Could not connect to live AWS DB to pull data: {e}")
        return False

    local_conn = get_local_db_connection()
    try:
        # Disable changes pending trigger while pulling
        global _local_changes_pending
        original_pending = _local_changes_pending
        
        # 1. Pull settings
        live_settings = live_conn.execute("SELECT * FROM settings WHERE user_id = %s", (user_id,)).fetchall()
        for s in live_settings:
            local_conn.execute("""
                INSERT OR REPLACE INTO settings (user_id, `key`, `value`)
                VALUES (?, ?, ?)
            """, (user_id, s["key"], s["value"]))

        # 2. Pull accounts
        live_accounts = live_conn.execute("SELECT * FROM accounts WHERE user_id = %s", (user_id,)).fetchall()
        live_account_ids = []
        for acc in live_accounts:
            live_account_ids.append(acc["id"])
            existing = local_conn.execute("SELECT id FROM accounts WHERE login = ? AND user_id = ?", (acc["login"], user_id)).fetchone()
            if existing:
                local_conn.execute("""
                    UPDATE accounts SET
                        password = ?, server = ?, terminal_path = ?, risk_pct = ?, is_active = ?,
                        balance = ?, equity = ?, connection_status = ?, last_error = ?, name = ?,
                        payment_date = ?
                    WHERE login = ? AND user_id = ?
                """, (
                    acc["password"], acc["server"], acc["terminal_path"], acc["risk_pct"], acc["is_active"],
                    acc["balance"], acc["equity"], acc["connection_status"], acc["last_error"], acc["name"],
                    acc["payment_date"], acc["login"], user_id
                ))
            else:
                local_conn.execute("""
                    INSERT INTO accounts (id, login, password, server, terminal_path, risk_pct, is_active, balance, equity, connection_status, last_error, name, payment_date, user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    acc["id"], acc["login"], acc["password"], acc["server"], acc["terminal_path"], acc["risk_pct"], acc["is_active"],
                    acc["balance"], acc["equity"], acc["connection_status"], acc["last_error"], acc["name"],
                    acc["payment_date"], user_id
                ))

        # 3. Pull signals
        live_signals = live_conn.execute("SELECT * FROM signals WHERE user_id = %s", (user_id,)).fetchall()
        live_signal_ids = []
        for sig in live_signals:
            live_signal_ids.append(sig["id"])
            existing = local_conn.execute("SELECT id FROM signals WHERE id = ?", (sig["id"],)).fetchone()
            if existing:
                local_conn.execute("""
                    UPDATE signals SET
                        telegram_msg_id = ?, channel_id = ?, timestamp = ?, raw_text = ?, action = ?,
                        symbol = ?, sl = ?, tp1 = ?, tp2 = ?, tp3 = ?, entry_min = ?, entry_max = ?,
                        status = ?, user_id = ?
                    WHERE id = ?
                """, (
                    sig["telegram_msg_id"], sig["channel_id"], sig["timestamp"], sig["raw_text"], sig["action"],
                    sig["symbol"], sig["sl"], sig["tp1"], sig["tp2"], sig["tp3"], sig["entry_min"], sig["entry_max"],
                    sig["status"], user_id, sig["id"]
                ))
            else:
                local_conn.execute("""
                    INSERT INTO signals (id, telegram_msg_id, channel_id, timestamp, raw_text, action, symbol, sl, tp1, tp2, tp3, entry_min, entry_max, status, user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sig["id"], sig["telegram_msg_id"], sig["channel_id"], sig["timestamp"], sig["raw_text"], sig["action"],
                    sig["symbol"], sig["sl"], sig["tp1"], sig["tp2"], sig["tp3"], sig["entry_min"], sig["entry_max"],
                    sig["status"], user_id
                ))

        # 4. Pull trades
        if live_account_ids:
            placeholders = ", ".join(["%s"] * len(live_account_ids))
            live_trades = live_conn.execute(f"SELECT * FROM trades WHERE account_id IN ({placeholders})", live_account_ids).fetchall()
            for t in live_trades:
                existing = local_conn.execute("SELECT id FROM trades WHERE id = ?", (t["id"],)).fetchone()
                if existing:
                    local_conn.execute("""
                        UPDATE trades SET
                            account_id = ?, signal_id = ?, ticket = ?, symbol = ?, action = ?, volume = ?,
                            sl = ?, tp1 = ?, tp2 = ?, tp3 = ?, tp1_lots = ?, tp2_lots = ?, tp3_lots = ?,
                            tp1_hit = ?, tp2_hit = ?, tp3_hit = ?, status = ?, open_price = ?, close_price = ?,
                            pnl = ?, error_msg = ?
                        WHERE id = ?
                    """, (
                        t["account_id"], t["signal_id"], t["ticket"], t["symbol"], t["action"], t["volume"],
                        t["sl"], t["tp1"], t["tp2"], t["tp3"], t["tp1_lots"], t["tp2_lots"], t["tp3_lots"],
                        t["tp1_hit"], t["tp2_hit"], t["tp3_hit"], t["status"], t["open_price"], t["close_price"],
                        t["pnl"], t["error_msg"], t["id"]
                    ))
                else:
                    local_conn.execute("""
                        INSERT INTO trades (id, account_id, signal_id, ticket, symbol, action, volume, sl, tp1, tp2, tp3, tp1_lots, tp2_lots, tp3_lots, tp1_hit, tp2_hit, tp3_hit, status, open_price, close_price, pnl, error_msg)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        t["id"], t["account_id"], t["signal_id"], t["ticket"], t["symbol"], t["action"], t["volume"],
                        t["sl"], t["tp1"], t["tp2"], t["tp3"], t["tp1_lots"], t["tp2_lots"], t["tp3_lots"],
                        t["tp1_hit"], t["tp2_hit"], t["tp3_hit"], t["status"], t["open_price"], t["close_price"],
                        t["pnl"], t["error_msg"]
                    ))

        # 5. Pull signal_executions
        if live_account_ids:
            placeholders = ", ".join(["%s"] * len(live_account_ids))
            live_execs = live_conn.execute(f"SELECT * FROM signal_executions WHERE account_id IN ({placeholders})", live_account_ids).fetchall()
            for ex in live_execs:
                local_conn.execute("""
                    INSERT OR REPLACE INTO signal_executions (account_id, signal_id, status, error_msg, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (ex["account_id"], ex["signal_id"], ex["status"], ex["error_msg"], ex["timestamp"]))

        local_conn.commit()
        # Restore changes pending flag since this was a pull (not new client-side edits)
        _local_changes_pending = original_pending
        return True
    except Exception as e:
        print(f"Error pulling data from live DB: {e}")
        return False
    finally:
        local_conn.close()
        live_conn.close()

def create_user(username, password):
    # Registration runs on live AWS DB
    conn = get_live_db_connection()
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
    # Login authentication runs on live AWS DB
    conn = get_live_db_connection()
    try:
        row = conn.execute("SELECT * FROM access_users WHERE username = ?", (username,)).fetchone()
        if row and verify_password(password, row["password_hash"]):
            if row["is_blocked"] or row["is_blocked"] == 1:
                update_local_user_block_status(row["id"], 1)
                return {"blocked": True}
            
            user_data = dict(row)
            sync_user_to_local(user_data)
            pull_data_from_live(user_data["id"])
            return user_data
        return None
    finally:
        conn.close()

def create_session(user_id):
    # Session creation runs on live AWS DB
    conn = get_live_db_connection()
    try:
        session_token = uuid.uuid4().hex
        conn.execute("INSERT INTO user_sessions (session_id, user_id) VALUES (?, ?)", (session_token, user_id))
        conn.commit()
        
        # Sync session locally
        sync_session_to_local(session_token, user_id)
        return session_token
    finally:
        conn.close()

def verify_session(session_token):
    # Check cache first (15 second in-memory cache to avoid heavy live DB connection on every request)
    now = time.time()
    if session_token in _session_cache:
        user_id, expiry = _session_cache[session_token]
        if now < expiry:
            return user_id
            
    # Session verification runs on live AWS DB
    conn = None
    try:
        conn = get_live_db_connection()
        row = conn.execute("""
            SELECT us.user_id, au.username, au.password_hash, au.is_blocked 
            FROM user_sessions us
            JOIN access_users au ON us.user_id = au.id
            WHERE us.session_id = ?
        """, (session_token,)).fetchone()
        if row:
            user_id = row["user_id"]
            is_blocked = 1 if row["is_blocked"] else 0
            
            if is_blocked:
                update_local_user_block_status(user_id, 1)
                _session_cache.pop(session_token, None)
                return None
                
            # Sync user/session locally
            sync_user_to_local({
                "id": user_id,
                "username": row["username"],
                "password_hash": row["password_hash"],
                "is_blocked": is_blocked
            })
            sync_session_to_local(session_token, user_id)
            
            # If local database has 0 accounts for this user, pull from live AWS to populate local DB.
            # This prevents a fresh local DB from accidentally wiping live DB on the next sync cycle.
            local_conn = get_local_db_connection()
            try:
                local_acc_count = local_conn.execute("SELECT COUNT(*) FROM accounts WHERE user_id = ?", (user_id,)).fetchone()[0]
                if local_acc_count == 0:
                    pull_data_from_live(user_id)
            except Exception as pe:
                print(f"Error checking accounts during session verification: {pe}")
            finally:
                local_conn.close()
            
            # Cache session for 15 seconds
            _session_cache[session_token] = (user_id, now + 15)
            return user_id
            
        _session_cache.pop(session_token, None)
        return None
    except Exception as e:
        # Fallback to local session verification in case of network or AWS database issues
        print(f"Warning: AWS session verification failed, falling back to local DB: {e}")
        local_conn = get_local_db_connection()
        try:
            local_row = local_conn.execute("""
                SELECT us.user_id, au.is_blocked
                FROM user_sessions us
                JOIN access_users au ON us.user_id = au.id
                WHERE us.session_id = ?
            """, (session_token,)).fetchone()
            if local_row:
                if local_row["is_blocked"] or local_row["is_blocked"] == 1:
                    return None
                return local_row["user_id"]
            return None
        except Exception:
            return None
        finally:
            local_conn.close()
    finally:
        if conn:
            conn.close()

def delete_session(session_token):
    # Session deletion runs on live AWS DB
    _session_cache.pop(session_token, None)
    
    # Delete locally first
    local_conn = get_local_db_connection()
    try:
        local_conn.execute("DELETE FROM user_sessions WHERE session_id = ?", (session_token,))
        local_conn.commit()
    except Exception:
        pass
    finally:
        local_conn.close()
        
    conn = get_live_db_connection()
    try:
        conn.execute("DELETE FROM user_sessions WHERE session_id = ?", (session_token,))
        conn.commit()
        return True
    finally:
        conn.close()

def sync_data_to_live(user_id, force=False):
    global _last_sync_time, _local_changes_pending
    now = time.time()
    
    # Rate limit check: skip if force=False and we synced in the last 60 seconds
    if not force and (now - _last_sync_time < 60):
        return True, "Sync skipped due to rate limiting (once per 60 seconds)."
        
    if not force and not _local_changes_pending:
        return True, "No local changes to sync."
        
    local_conn = get_local_db_connection()
    try:
        live_conn = get_live_db_connection()
    except Exception as e:
        local_conn.close()
        return False, f"Could not connect to live AWS database: {e}"
        
    try:
        # 0. Sync block status from live to local
        live_user = live_conn.execute("SELECT is_blocked FROM access_users WHERE id = %s", (user_id,)).fetchone()
        if live_user:
            is_blocked = 1 if live_user["is_blocked"] else 0
            local_conn.execute("UPDATE access_users SET is_blocked = ? WHERE id = ?", (is_blocked, user_id))
            local_conn.commit()
            if is_blocked:
                # User is blocked, stop sync
                return True, "Sync aborted: User is blocked centrally."
                
        # 1. Sync settings
        local_settings = local_conn.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,)).fetchall()
        for s in local_settings:
            live_conn.execute("""
                INSERT INTO settings (user_id, `key`, `value`)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
            """, (user_id, s["key"], s["value"]))
            
        # 2. Sync accounts
        local_accounts = local_conn.execute("SELECT * FROM accounts WHERE user_id = ?", (user_id,)).fetchall()
        local_logins = []
        for acc in local_accounts:
            login = acc["login"]
            local_logins.append(login)
            live_conn.execute("""
                INSERT INTO accounts (login, password, server, terminal_path, risk_pct, is_active, balance, equity, connection_status, last_error, name, payment_date, user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    password = VALUES(password),
                    server = VALUES(server),
                    terminal_path = VALUES(terminal_path),
                    risk_pct = VALUES(risk_pct),
                    is_active = VALUES(is_active),
                    balance = VALUES(balance),
                    equity = VALUES(equity),
                    connection_status = VALUES(connection_status),
                    last_error = VALUES(last_error),
                    name = VALUES(name),
                    payment_date = VALUES(payment_date),
                    last_updated = CURRENT_TIMESTAMP
            """, (
                login, acc["password"], acc["server"], acc["terminal_path"],
                acc["risk_pct"], acc["is_active"], acc["balance"], acc["equity"],
                acc["connection_status"], acc["last_error"], acc["name"], acc["payment_date"], user_id
            ))
            
        # Delete from live DB any accounts that were deleted locally
        if local_logins:
            placeholders = ", ".join(["%s"] * len(local_logins))
            query = f"DELETE FROM accounts WHERE user_id = %s AND login NOT IN ({placeholders})"
            live_conn.execute(query, [user_id] + local_logins)
        else:
            live_conn.execute("DELETE FROM accounts WHERE user_id = %s", (user_id,))
            
        # Map local account IDs to live account IDs (essential for trades/signal executions mapping)
        live_accs = live_conn.execute("SELECT id, login FROM accounts WHERE user_id = %s", (user_id,)).fetchall()
        live_acc_map = {r["login"]: r["id"] for r in live_accs}
        local_acc_map = {acc["id"]: live_acc_map[acc["login"]] for acc in local_accounts if acc["login"] in live_acc_map}
        
        # 3. Sync signals
        local_signals = local_conn.execute("SELECT * FROM signals WHERE user_id = ?", (user_id,)).fetchall()
        local_sig_map = {} # local_signal_id -> live_signal_id
        for sig in local_signals:
            live_sig = None
            if sig["telegram_msg_id"] not in (8888, 9999) and sig["channel_id"] != 0:
                live_sig = live_conn.execute("""
                    SELECT id FROM signals 
                    WHERE user_id = %s AND channel_id = %s AND telegram_msg_id = %s
                """, (user_id, sig["channel_id"], sig["telegram_msg_id"])).fetchone()
            else:
                live_sig = live_conn.execute("""
                    SELECT id FROM signals 
                    WHERE user_id = %s AND telegram_msg_id = %s AND action = %s AND symbol = %s 
                      AND ABS(TIMESTAMPDIFF(SECOND, timestamp, %s)) < 3600
                """, (user_id, sig["telegram_msg_id"], sig["action"], sig["symbol"], sig["timestamp"])).fetchone()
                
            if live_sig:
                live_sig_id = live_sig["id"]
            else:
                cursor = live_conn.cursor()
                cursor.execute("""
                    INSERT INTO signals (telegram_msg_id, channel_id, timestamp, raw_text, action, symbol, sl, tp1, tp2, tp3, entry_min, entry_max, status, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    sig["telegram_msg_id"], sig["channel_id"], sig["timestamp"], sig["raw_text"],
                    sig["action"], sig["symbol"], sig["sl"], sig["tp1"], sig["tp2"], sig["tp3"],
                    sig["entry_min"], sig["entry_max"], sig["status"], user_id
                ))
                live_sig_id = cursor.lastrowid
                cursor.close()
                
            local_sig_map[sig["id"]] = live_sig_id
            
        # 4. Sync trades
        local_trades = []
        if local_accounts:
            local_acc_ids = [acc["id"] for acc in local_accounts]
            placeholders = ", ".join(["?"] * len(local_acc_ids))
            local_trades = local_conn.execute(f"SELECT * FROM trades WHERE account_id IN ({placeholders})", local_acc_ids).fetchall()
            
        for t in local_trades:
            live_acc_id = local_acc_map.get(t["account_id"])
            live_sig_id = local_sig_map.get(t["signal_id"])
            
            if not live_acc_id or not live_sig_id:
                continue
                
            live_trade = None
            if t["ticket"] and t["ticket"] != 0:
                live_trade = live_conn.execute("""
                    SELECT id FROM trades WHERE account_id = %s AND ticket = %s
                """, (live_acc_id, t["ticket"])).fetchone()
            else:
                live_trade = live_conn.execute("""
                    SELECT id FROM trades WHERE account_id = %s AND signal_id = %s AND ticket IS NULL
                """, (live_acc_id, live_sig_id)).fetchone()
                
            if live_trade:
                live_conn.execute("""
                    UPDATE trades SET
                        ticket = %s, symbol = %s, action = %s, volume = %s, sl = %s, tp1 = %s, tp2 = %s, tp3 = %s,
                        tp1_lots = %s, tp2_lots = %s, tp3_lots = %s, tp1_hit = %s, tp2_hit = %s, tp3_hit = %s,
                        status = %s, open_price = %s, close_price = %s, pnl = %s, error_msg = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    t["ticket"], t["symbol"], t["action"], t["volume"], t["sl"], t["tp1"], t["tp2"], t["tp3"],
                    t["tp1_lots"], t["tp2_lots"], t["tp3_lots"], t["tp1_hit"], t["tp2_hit"], t["tp3_hit"],
                    t["status"], t["open_price"], t["close_price"], t["pnl"], t["error_msg"], live_trade["id"]
                ))
            else:
                live_conn.execute("""
                    INSERT INTO trades (
                        account_id, signal_id, ticket, symbol, action, volume, sl, tp1, tp2, tp3,
                        tp1_lots, tp2_lots, tp3_lots, tp1_hit, tp2_hit, tp3_hit, status, open_price,
                        close_price, pnl, error_msg
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    live_acc_id, live_sig_id, t["ticket"], t["symbol"], t["action"], t["volume"],
                    t["sl"], t["tp1"], t["tp2"], t["tp3"], t["tp1_lots"], t["tp2_lots"], t["tp3_lots"],
                    t["tp1_hit"], t["tp2_hit"], t["tp3_hit"], t["status"], t["open_price"],
                    t["close_price"], t["pnl"], t["error_msg"]
                ))
                
        # 5. Sync signal_executions
        local_executions = []
        if local_accounts:
            local_acc_ids = [acc["id"] for acc in local_accounts]
            placeholders = ", ".join(["?"] * len(local_acc_ids))
            local_executions = local_conn.execute(f"SELECT * FROM signal_executions WHERE account_id IN ({placeholders})", local_acc_ids).fetchall()
            
        for ex in local_executions:
            live_acc_id = local_acc_map.get(ex["account_id"])
            live_sig_id = local_sig_map.get(ex["signal_id"])
            if live_acc_id and live_sig_id:
                live_conn.execute("""
                    INSERT INTO signal_executions (account_id, signal_id, status, error_msg, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        error_msg = VALUES(error_msg),
                        timestamp = VALUES(timestamp)
                """, (live_acc_id, live_sig_id, ex["status"], ex["error_msg"], ex["timestamp"]))
                
        # 6. Sync logs incrementally
        local_logs = local_conn.execute("SELECT * FROM logs WHERE user_id = ? AND (synced = 0 OR synced IS NULL)", (user_id,)).fetchall()
        for log in local_logs:
            live_conn.execute("""
                INSERT INTO logs (timestamp, level, sender, message, user_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (log["timestamp"], log["level"], log["sender"], log["message"], user_id))
            
        if local_logs:
            log_ids = [l["id"] for l in local_logs]
            placeholders = ", ".join(["?"] * len(log_ids))
            local_conn.execute(f"UPDATE logs SET synced = 1 WHERE id IN ({placeholders})", log_ids)
            local_conn.commit()
            
        # Reset local changes flag and update last sync timestamp on success
        _local_changes_pending = False
        _last_sync_time = now
        return True, "Data synced to AWS successfully."
    except Exception as e:
        return False, f"Sync error: {e}"
    finally:
        local_conn.close()
        live_conn.close()

def sync_all_local_users_to_live():
    global _local_changes_pending
    if not _local_changes_pending:
        return
        
    local_users = get_all_users()
    synced_any = False
    for u in local_users:
        user_id = u["id"]
        if not u["is_blocked"]:
            try:
                success, msg = sync_data_to_live(user_id)
                if success and "synced" in msg.lower():
                    synced_any = True
            except Exception as e:
                print(f"Background sync failed for user {user_id}: {e}")
                
    if synced_any:
        _local_changes_pending = False
