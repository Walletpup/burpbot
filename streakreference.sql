-- Gas Streaks Database Schema
-- Complete schema for all Gas Streaks functionality

-- Table: gas_streak_users
-- Stores user information and streak statistics
CREATE TABLE IF NOT EXISTS gas_streak_users (
    id SERIAL PRIMARY KEY,
    wallet_address VARCHAR(200) UNIQUE NOT NULL,
    current_streak INTEGER DEFAULT 0,
    best_streak INTEGER DEFAULT 0,
    total_streaks_sent INTEGER DEFAULT 0,
    total_burp_spent NUMERIC(20,6) DEFAULT 0,
    total_prizes_won NUMERIC(20,6) DEFAULT 0,
    last_streak_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: gas_streak_transactions  
-- Records all streak transactions
CREATE TABLE IF NOT EXISTS gas_streak_transactions (
    id SERIAL PRIMARY KEY,
    transaction_hash VARCHAR(128) UNIQUE NOT NULL,
    from_address VARCHAR(200),
    to_address VARCHAR(200) NOT NULL,
    amount NUMERIC(20,6) NOT NULL,
    transaction_type VARCHAR(50) NOT NULL,
    related_streak_id INTEGER,
    block_height INTEGER,
    confirmed BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP
);

-- Table: gas_streak_prize_pool
-- Manages the prize pool state
CREATE TABLE IF NOT EXISTS gas_streak_prize_pool (
    id SERIAL PRIMARY KEY,
    total_amount NUMERIC(20,6) NOT NULL DEFAULT 0,
    last_winner_address VARCHAR(200),
    last_win_amount NUMERIC(20,6),
    last_win_date TIMESTAMP,
    total_contributions NUMERIC(20,6) DEFAULT 0,
    total_payouts NUMERIC(20,6) DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: gas_streaks
-- Individual streak records
CREATE TABLE IF NOT EXISTS gas_streaks (
    id SERIAL PRIMARY KEY,
    streak_user_id INTEGER,
    wallet_address VARCHAR(200) NOT NULL,
    transaction_hash VARCHAR(128) UNIQUE NOT NULL,
    streak_number INTEGER NOT NULL,
    burp_amount NUMERIC(20,6) NOT NULL DEFAULT 1.0,
    network_fee NUMERIC(20,6),
    win_chance NUMERIC(5,4) NOT NULL,
    won BOOLEAN DEFAULT false,
    prize_amount NUMERIC(20,6) DEFAULT 0,
    prize_tx_hash VARCHAR(128),
    block_height INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    
    FOREIGN KEY (streak_user_id) REFERENCES gas_streak_users(id) ON DELETE CASCADE
);

-- Table: gas_streak_settings
-- System configuration
CREATE TABLE IF NOT EXISTS gas_streak_settings (
    id SERIAL PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: gas_streak_activity_log
-- Activity logging for debugging and analytics
CREATE TABLE IF NOT EXISTS gas_streak_activity_log (
    id SERIAL PRIMARY KEY,
    user_address VARCHAR(200),
    activity_type VARCHAR(50) NOT NULL,
    description TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE UNIQUE INDEX IF NOT EXISTS gas_streak_users_wallet_address_key ON gas_streak_users(wallet_address);
CREATE UNIQUE INDEX IF NOT EXISTS gas_streak_transactions_transaction_hash_key ON gas_streak_transactions(transaction_hash);
CREATE INDEX IF NOT EXISTS idx_gas_streak_transactions_from_address ON gas_streak_transactions(from_address);
CREATE INDEX IF NOT EXISTS idx_gas_streak_transactions_to_address ON gas_streak_transactions(to_address);
CREATE UNIQUE INDEX IF NOT EXISTS gas_streaks_transaction_hash_key ON gas_streaks(transaction_hash);
CREATE INDEX IF NOT EXISTS idx_gas_streaks_wallet_address ON gas_streaks(wallet_address);
CREATE INDEX IF NOT EXISTS idx_gas_streaks_created_at ON gas_streaks(created_at);
CREATE INDEX IF NOT EXISTS idx_gas_streaks_user_id ON gas_streaks(streak_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS gas_streak_settings_setting_key_key ON gas_streak_settings(setting_key);
CREATE INDEX IF NOT EXISTS idx_gas_streak_activity_log_user_address ON gas_streak_activity_log(user_address);
CREATE INDEX IF NOT EXISTS idx_gas_streak_activity_log_created_at ON gas_streak_activity_log(created_at);

-- Insert default settings
INSERT INTO gas_streak_settings (setting_key, setting_value, description) VALUES
('base_win_chance', '0.001', 'Base win chance (0.1%)'),
('win_chance_increment', '0.001', 'Win chance increment per streak level (0.1%)'),
('max_win_chance', '0.10', 'Maximum win chance (10%)'),
('streak_cost_burp', '1.0', 'Cost per streak in BURP tokens'),
('prize_wallet_address', 'addr1q86ya4z2q5q49vwa6fn7lv52rur6hw58zc0ntl47e5kltr5rh4x6625hnpg0nvdvznz9y4dmyca6y6nmnedq2f805qvsh2x5g6', 'Prize pool wallet address'),
('streak_timeout_hours', '24', 'Hours before streak resets'),
('min_network_confirmations', '3', 'Minimum confirmations required')
ON CONFLICT (setting_key) DO NOTHING;

-- Insert initial prize pool record with 1000 BURP starting amount
INSERT INTO gas_streak_prize_pool (total_amount, total_contributions, total_payouts) VALUES
(1000, 0, 0)
ON CONFLICT DO NOTHING;
