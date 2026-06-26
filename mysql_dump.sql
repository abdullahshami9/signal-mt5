CREATE DATABASE IF NOT EXISTS trading_bot;
USE trading_bot;

CREATE TABLE IF NOT EXISTS access_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
);

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
);

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
);

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
);

CREATE TABLE IF NOT EXISTS signal_executions (
    account_id INT NOT NULL,
    signal_id INT NOT NULL,
    status VARCHAR(50) NOT NULL,
    error_msg TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, signal_id),
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    user_id INT NOT NULL,
    `key` VARCHAR(255) NOT NULL,
    `value` TEXT NOT NULL,
    PRIMARY KEY (user_id, `key`),
    FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(50) NOT NULL,
    sender VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    user_id INT,
    FOREIGN KEY (user_id) REFERENCES access_users(id) ON DELETE CASCADE
);

-- Seed default user (password: vendor123)
INSERT IGNORE INTO access_users (id, username, password_hash) VALUES 
(1, 'vendor1', '80ceca5bc8fc465d836e553be3868bf9:258d5300cf9d750c8227b68e98de24a9197e88d0718698ca1104e1bc2a9beabf');

-- Seed default settings
INSERT IGNORE INTO settings (user_id, `key`, `value`) VALUES 
(1, 'api_id', ''),
(1, 'api_hash', ''),
(1, 'phone', ''),
(1, 'monitored_channels', '[]'),
(1, 'telegram_status', 'disconnected');
