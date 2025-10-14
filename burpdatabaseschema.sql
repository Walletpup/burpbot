-- ============================================================================
-- DATABASE SCHEMA EXPORT
-- Generated: 2025-10-14 20:20:24
-- ============================================================================

-- Drop existing objects (uncomment if needed)
-- DROP SCHEMA public CASCADE;
-- CREATE SCHEMA public;

-- ============================================================================
-- SEQUENCES
-- ============================================================================

CREATE SEQUENCE IF NOT EXISTS burp_counter_id_seq;

CREATE SEQUENCE IF NOT EXISTS burp_sessions_id_seq;

CREATE SEQUENCE IF NOT EXISTS burp_slots_jackpots_id_seq;

CREATE SEQUENCE IF NOT EXISTS burp_slots_spins_id_seq;

CREATE SEQUENCE IF NOT EXISTS burp_slots_topups_id_seq;

CREATE SEQUENCE IF NOT EXISTS burp_slots_users_id_seq;

CREATE SEQUENCE IF NOT EXISTS burp_users_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_admin_activity_log_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_admin_auth_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_admin_settings_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_global_settings_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streak_activity_log_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streak_prize_pool_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streak_settings_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streak_topups_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streak_transactions_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streak_users_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streak_withdrawals_id_seq;

CREATE SEQUENCE IF NOT EXISTS gas_streaks_id_seq;

-- ============================================================================
-- TABLES
-- ============================================================================

-- Table: burp_counter
CREATE TABLE burp_counter (
    id INTEGER NOT NULL DEFAULT nextval('burp_counter_id_seq'::regclass),
    total_burps BIGINT NOT NULL DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT 2200_24595_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24595_2_not_null CHECK (total_burps IS NOT NULL)
);

-- Table: burp_sessions
CREATE TABLE burp_sessions (
    id INTEGER NOT NULL DEFAULT nextval('burp_sessions_id_seq'::regclass),
    session_burps INTEGER NOT NULL,
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    user_agent TEXT,
    ip_address INET,
    PRIMARY KEY (id),
    CONSTRAINT 2200_24604_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24604_2_not_null CHECK (session_burps IS NOT NULL)
);

-- Table: burp_slots_jackpots
CREATE TABLE burp_slots_jackpots (
    id INTEGER NOT NULL DEFAULT nextval('burp_slots_jackpots_id_seq'::regclass),
    wallet_address VARCHAR(255) NOT NULL,
    symbols JSONB NOT NULL,
    payout INTEGER NOT NULL,
    bet_amount INTEGER NOT NULL,
    multiplier INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT 2200_24613_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24613_2_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24613_3_not_null CHECK (symbols IS NOT NULL),
    CONSTRAINT 2200_24613_4_not_null CHECK (payout IS NOT NULL),
    CONSTRAINT 2200_24613_5_not_null CHECK (bet_amount IS NOT NULL),
    CONSTRAINT 2200_24613_6_not_null CHECK (multiplier IS NOT NULL)
);

-- Table: burp_slots_spins
CREATE TABLE burp_slots_spins (
    id INTEGER NOT NULL DEFAULT nextval('burp_slots_spins_id_seq'::regclass),
    wallet_address VARCHAR(255) NOT NULL,
    bet_amount INTEGER NOT NULL,
    symbols JSONB NOT NULL,
    payout INTEGER DEFAULT 0,
    timestamp BIGINT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    transaction_hash VARCHAR(255),
    PRIMARY KEY (id),
    CONSTRAINT 2200_24622_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24622_2_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24622_3_not_null CHECK (bet_amount IS NOT NULL),
    CONSTRAINT 2200_24622_4_not_null CHECK (symbols IS NOT NULL),
    CONSTRAINT 2200_24622_6_not_null CHECK (timestamp IS NOT NULL)
);

-- Table: burp_slots_topups
CREATE TABLE burp_slots_topups (
    id INTEGER NOT NULL DEFAULT nextval('burp_slots_topups_id_seq'::regclass),
    wallet_address VARCHAR(255) NOT NULL,
    amount INTEGER NOT NULL,
    transaction_hash VARCHAR(255) NOT NULL,
    timestamp BIGINT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    output_index INTEGER DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT burp_slots_topups_transaction_hash_key UNIQUE ({, t, r, a, n, s, a, c, t, i, o, n, _, h, a, s, h, }),
    CONSTRAINT unique_utxo_output UNIQUE ({, t, r, a, n, s, a, c, t, i, o, n, _, h, a, s, h, ,, o, u, t, p, u, t, _, i, n, d, e, x, ,, w, a, l, l, e, t, _, a, d, d, r, e, s, s, }),
    CONSTRAINT 2200_24632_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24632_2_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24632_3_not_null CHECK (amount IS NOT NULL),
    CONSTRAINT 2200_24632_4_not_null CHECK (transaction_hash IS NOT NULL),
    CONSTRAINT 2200_24632_5_not_null CHECK (timestamp IS NOT NULL)
);

-- Table: burp_slots_users
CREATE TABLE burp_slots_users (
    id INTEGER NOT NULL DEFAULT nextval('burp_slots_users_id_seq'::regclass),
    wallet_address VARCHAR(255) NOT NULL,
    balance_backup INTEGER DEFAULT 0,
    total_spins INTEGER DEFAULT 0,
    total_wins INTEGER DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    last_spin TIMESTAMP WITHOUT TIME ZONE,
    pending_winnings INTEGER DEFAULT 0,
    last_topup TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT burp_slots_users_wallet_address_key UNIQUE ({, w, a, l, l, e, t, _, a, d, d, r, e, s, s, }),
    CONSTRAINT 2200_24646_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24646_2_not_null CHECK (wallet_address IS NOT NULL)
);

-- Table: burp_users
CREATE TABLE burp_users (
    id INTEGER NOT NULL DEFAULT nextval('burp_users_id_seq'::regclass),
    wallet_address VARCHAR(200) NOT NULL,
    balance NUMERIC(20,6) NOT NULL DEFAULT 0,
    total_topups NUMERIC(20,6) NOT NULL DEFAULT 0,
    total_withdrawals NUMERIC(20,6) NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_wallet_burp_balance NUMERIC(20,6) DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT burp_users_wallet_address_key UNIQUE ({, w, a, l, l, e, t, _, a, d, d, r, e, s, s, }),
    CONSTRAINT 2200_24659_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24659_2_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24659_3_not_null CHECK (balance IS NOT NULL),
    CONSTRAINT 2200_24659_4_not_null CHECK (total_topups IS NOT NULL),
    CONSTRAINT 2200_24659_5_not_null CHECK (total_withdrawals IS NOT NULL)
);

-- Table: gas_admin_activity_log
CREATE TABLE gas_admin_activity_log (
    id INTEGER NOT NULL DEFAULT nextval('gas_admin_activity_log_id_seq'::regclass),
    admin_wallet VARCHAR(200) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    pool_id VARCHAR(50),
    old_values JSONB,
    new_values JSONB,
    description TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT 2200_24673_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24673_2_not_null CHECK (admin_wallet IS NOT NULL),
    CONSTRAINT 2200_24673_3_not_null CHECK (action_type IS NOT NULL)
);

-- Table: gas_admin_auth
CREATE TABLE gas_admin_auth (
    id INTEGER NOT NULL DEFAULT nextval('gas_admin_auth_id_seq'::regclass),
    wallet_address VARCHAR(200) NOT NULL,
    signature_message TEXT NOT NULL,
    signature_hex TEXT NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT true,
    PRIMARY KEY (id),
    CONSTRAINT 2200_24682_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24682_2_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24682_3_not_null CHECK (signature_message IS NOT NULL),
    CONSTRAINT 2200_24682_4_not_null CHECK (signature_hex IS NOT NULL),
    CONSTRAINT 2200_24682_5_not_null CHECK (expires_at IS NOT NULL)
);

-- Table: gas_admin_settings
CREATE TABLE gas_admin_settings (
    id INTEGER NOT NULL DEFAULT nextval('gas_admin_settings_id_seq'::regclass),
    pool_id VARCHAR(50) NOT NULL,
    pool_name VARCHAR(100) NOT NULL DEFAULT 'BURP Pool'::character varying,
    base_prize_pool NUMERIC(12,2) NOT NULL DEFAULT 1000,
    current_prize_pool NUMERIC(12,2) NOT NULL DEFAULT 1000,
    prize_token_name VARCHAR(50) NOT NULL DEFAULT 'BURP'::character varying,
    prize_token_symbol VARCHAR(10) NOT NULL DEFAULT 'BURP'::character varying,
    burp_policy_id VARCHAR(128) NOT NULL,
    burp_token_name_hex VARCHAR(128) NOT NULL,
    burp_tokens_per_release NUMERIC(10,2) NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    pool_order INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(200),
    pool_win_chance_boost NUMERIC(8,2) NOT NULL DEFAULT 0.00,
    is_fifty_fifty_pool BOOLEAN DEFAULT false,
    PRIMARY KEY (id),
    CONSTRAINT gas_admin_settings_pool_id_key UNIQUE ({, p, o, o, l, _, i, d, }),
    CONSTRAINT 2200_24692_10_not_null CHECK (burp_tokens_per_release IS NOT NULL),
    CONSTRAINT 2200_24692_11_not_null CHECK (is_active IS NOT NULL),
    CONSTRAINT 2200_24692_12_not_null CHECK (pool_order IS NOT NULL),
    CONSTRAINT 2200_24692_16_not_null CHECK (pool_win_chance_boost IS NOT NULL),
    CONSTRAINT 2200_24692_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24692_2_not_null CHECK (pool_id IS NOT NULL),
    CONSTRAINT 2200_24692_3_not_null CHECK (pool_name IS NOT NULL),
    CONSTRAINT 2200_24692_4_not_null CHECK (base_prize_pool IS NOT NULL),
    CONSTRAINT 2200_24692_5_not_null CHECK (current_prize_pool IS NOT NULL),
    CONSTRAINT 2200_24692_6_not_null CHECK (prize_token_name IS NOT NULL),
    CONSTRAINT 2200_24692_7_not_null CHECK (prize_token_symbol IS NOT NULL),
    CONSTRAINT 2200_24692_8_not_null CHECK (burp_policy_id IS NOT NULL),
    CONSTRAINT 2200_24692_9_not_null CHECK (burp_token_name_hex IS NOT NULL)
);

-- Table: gas_global_settings
CREATE TABLE gas_global_settings (
    id INTEGER NOT NULL DEFAULT nextval('gas_global_settings_id_seq'::regclass),
    base_win_chance NUMERIC(10,6) NOT NULL DEFAULT 0.001,
    win_chance_increment NUMERIC(10,6) NOT NULL DEFAULT 0.0002,
    max_win_chance NUMERIC(10,6) NOT NULL DEFAULT 0.10,
    updated_by VARCHAR(255),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT 2200_24714_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24714_2_not_null CHECK (base_win_chance IS NOT NULL),
    CONSTRAINT 2200_24714_3_not_null CHECK (win_chance_increment IS NOT NULL),
    CONSTRAINT 2200_24714_4_not_null CHECK (max_win_chance IS NOT NULL)
);

-- Table: gas_streak_activity_log
CREATE TABLE gas_streak_activity_log (
    id INTEGER NOT NULL DEFAULT nextval('gas_streak_activity_log_id_seq'::regclass),
    user_address VARCHAR(200),
    activity_type VARCHAR(50) NOT NULL,
    description TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT 2200_24725_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24725_3_not_null CHECK (activity_type IS NOT NULL)
);

-- Table: gas_streak_prize_pool
CREATE TABLE gas_streak_prize_pool (
    id INTEGER NOT NULL DEFAULT nextval('gas_streak_prize_pool_id_seq'::regclass),
    pool_id VARCHAR(50) NOT NULL DEFAULT 'burp_default'::character varying,
    total_amount NUMERIC(20,6) NOT NULL DEFAULT 0,
    last_winner_address VARCHAR(200),
    last_win_amount NUMERIC(20,6),
    last_win_date TIMESTAMP WITHOUT TIME ZONE,
    total_contributions NUMERIC(20,6) DEFAULT 0,
    total_payouts NUMERIC(20,6) DEFAULT 0,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT gas_streak_prize_pool_pool_id_key UNIQUE ({, p, o, o, l, _, i, d, }),
    CONSTRAINT 2200_24734_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24734_2_not_null CHECK (pool_id IS NOT NULL),
    CONSTRAINT 2200_24734_3_not_null CHECK (total_amount IS NOT NULL)
);

-- Table: gas_streak_settings
CREATE TABLE gas_streak_settings (
    id INTEGER NOT NULL DEFAULT nextval('gas_streak_settings_id_seq'::regclass),
    setting_key VARCHAR(100) NOT NULL,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT gas_streak_settings_setting_key_key UNIQUE ({, s, e, t, t, i, n, g, _, k, e, y, }),
    CONSTRAINT 2200_24747_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24747_2_not_null CHECK (setting_key IS NOT NULL),
    CONSTRAINT 2200_24747_3_not_null CHECK (setting_value IS NOT NULL)
);

-- Table: gas_streak_topups
CREATE TABLE gas_streak_topups (
    id INTEGER NOT NULL DEFAULT nextval('gas_streak_topups_id_seq'::regclass),
    wallet_address VARCHAR(200) NOT NULL,
    amount INTEGER NOT NULL,
    transaction_hash VARCHAR(200) NOT NULL,
    timestamp BIGINT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    output_index INTEGER DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT gas_streak_topups_transaction_hash_key UNIQUE ({, t, r, a, n, s, a, c, t, i, o, n, _, h, a, s, h, }),
    CONSTRAINT 2200_24758_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24758_2_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24758_3_not_null CHECK (amount IS NOT NULL),
    CONSTRAINT 2200_24758_4_not_null CHECK (transaction_hash IS NOT NULL)
);

-- Table: gas_streak_transactions
CREATE TABLE gas_streak_transactions (
    id INTEGER NOT NULL DEFAULT nextval('gas_streak_transactions_id_seq'::regclass),
    transaction_hash VARCHAR(128) NOT NULL,
    from_address VARCHAR(200),
    to_address VARCHAR(200) NOT NULL,
    amount NUMERIC(20,6) NOT NULL,
    transaction_type VARCHAR(50) NOT NULL,
    related_streak_id INTEGER,
    block_height INTEGER,
    confirmed BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT gas_streak_transactions_transaction_hash_key UNIQUE ({, t, r, a, n, s, a, c, t, i, o, n, _, h, a, s, h, }),
    CONSTRAINT 2200_24768_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24768_2_not_null CHECK (transaction_hash IS NOT NULL),
    CONSTRAINT 2200_24768_4_not_null CHECK (to_address IS NOT NULL),
    CONSTRAINT 2200_24768_5_not_null CHECK (amount IS NOT NULL),
    CONSTRAINT 2200_24768_6_not_null CHECK (transaction_type IS NOT NULL)
);

-- Table: gas_streak_users
CREATE TABLE gas_streak_users (
    id INTEGER NOT NULL DEFAULT nextval('gas_streak_users_id_seq'::regclass),
    wallet_address VARCHAR(200) NOT NULL,
    current_streak INTEGER DEFAULT 0,
    best_streak INTEGER DEFAULT 0,
    total_streaks_sent INTEGER DEFAULT 0,
    total_burp_spent NUMERIC(20,6) DEFAULT 0,
    total_prizes_won NUMERIC(20,6) DEFAULT 0,
    last_streak_date TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    balance_backup INTEGER DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT gas_streak_users_wallet_address_key UNIQUE ({, w, a, l, l, e, t, _, a, d, d, r, e, s, s, }),
    CONSTRAINT 2200_24780_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24780_2_not_null CHECK (wallet_address IS NOT NULL)
);

-- Table: gas_streak_withdrawals
CREATE TABLE gas_streak_withdrawals (
    id INTEGER NOT NULL DEFAULT nextval('gas_streak_withdrawals_id_seq'::regclass),
    wallet_address VARCHAR(200) NOT NULL,
    amount INTEGER NOT NULL,
    transaction_hash VARCHAR(200) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT gas_streak_withdrawals_transaction_hash_key UNIQUE ({, t, r, a, n, s, a, c, t, i, o, n, _, h, a, s, h, }),
    CONSTRAINT 2200_24796_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24796_2_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24796_3_not_null CHECK (amount IS NOT NULL),
    CONSTRAINT 2200_24796_4_not_null CHECK (transaction_hash IS NOT NULL)
);

-- Table: gas_streaks
CREATE TABLE gas_streaks (
    id INTEGER NOT NULL DEFAULT nextval('gas_streaks_id_seq'::regclass),
    streak_user_id INTEGER NOT NULL,
    pool_id VARCHAR(50) NOT NULL DEFAULT 'burp_default'::character varying,
    wallet_address VARCHAR(200) NOT NULL,
    transaction_hash VARCHAR(128) NOT NULL,
    streak_number INTEGER NOT NULL,
    burp_amount NUMERIC(20,6) NOT NULL DEFAULT 1.0,
    network_fee NUMERIC(20,6) DEFAULT 0,
    win_chance NUMERIC(10,6) NOT NULL,
    won BOOLEAN DEFAULT false,
    prize_amount NUMERIC(20,6) DEFAULT 0,
    prize_tx_hash VARCHAR(128),
    block_height INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT gas_streaks_transaction_hash_key UNIQUE ({, t, r, a, n, s, a, c, t, i, o, n, _, h, a, s, h, }),
    CONSTRAINT 2200_24805_1_not_null CHECK (id IS NOT NULL),
    CONSTRAINT 2200_24805_2_not_null CHECK (streak_user_id IS NOT NULL),
    CONSTRAINT 2200_24805_3_not_null CHECK (pool_id IS NOT NULL),
    CONSTRAINT 2200_24805_4_not_null CHECK (wallet_address IS NOT NULL),
    CONSTRAINT 2200_24805_5_not_null CHECK (transaction_hash IS NOT NULL),
    CONSTRAINT 2200_24805_6_not_null CHECK (streak_number IS NOT NULL),
    CONSTRAINT 2200_24805_7_not_null CHECK (burp_amount IS NOT NULL),
    CONSTRAINT 2200_24805_9_not_null CHECK (win_chance IS NOT NULL)
);

-- ============================================================================
-- FOREIGN KEYS
-- ============================================================================

ALTER TABLE gas_streaks ADD CONSTRAINT gas_streaks_streak_user_id_fkey FOREIGN KEY (streak_user_id) REFERENCES gas_streak_users(id) ON DELETE CASCADE;
-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX idx_burp_sessions_submitted_at ON public.burp_sessions USING btree (submitted_at);
CREATE INDEX idx_slots_jackpots_created_at ON public.burp_slots_jackpots USING btree (created_at DESC);
CREATE INDEX idx_slots_jackpots_payout ON public.burp_slots_jackpots USING btree (payout DESC);
CREATE INDEX idx_slots_big_wins ON public.burp_slots_spins USING btree (payout) WHERE (payout >= 50);
CREATE INDEX idx_slots_spins_created_at ON public.burp_slots_spins USING btree (created_at DESC);
CREATE INDEX idx_slots_spins_payout ON public.burp_slots_spins USING btree (payout DESC);
CREATE INDEX idx_slots_spins_payout_time ON public.burp_slots_spins USING btree (payout DESC, created_at DESC);
CREATE INDEX idx_slots_spins_tx_hash ON public.burp_slots_spins USING btree (transaction_hash);
CREATE INDEX idx_slots_spins_wallet ON public.burp_slots_spins USING btree (wallet_address);
CREATE UNIQUE INDEX burp_slots_topups_transaction_hash_key ON public.burp_slots_topups USING btree (transaction_hash);
CREATE UNIQUE INDEX unique_utxo_output ON public.burp_slots_topups USING btree (transaction_hash, output_index, wallet_address);
CREATE UNIQUE INDEX burp_slots_users_wallet_address_key ON public.burp_slots_users USING btree (wallet_address);
CREATE UNIQUE INDEX burp_users_wallet_address_key ON public.burp_users USING btree (wallet_address);
CREATE UNIQUE INDEX gas_admin_settings_pool_id_key ON public.gas_admin_settings USING btree (pool_id);
CREATE UNIQUE INDEX gas_streak_prize_pool_pool_id_key ON public.gas_streak_prize_pool USING btree (pool_id);
CREATE UNIQUE INDEX gas_streak_settings_setting_key_key ON public.gas_streak_settings USING btree (setting_key);
CREATE UNIQUE INDEX gas_streak_topups_transaction_hash_key ON public.gas_streak_topups USING btree (transaction_hash);
CREATE UNIQUE INDEX gas_streak_transactions_transaction_hash_key ON public.gas_streak_transactions USING btree (transaction_hash);
CREATE UNIQUE INDEX gas_streak_users_wallet_address_key ON public.gas_streak_users USING btree (wallet_address);
CREATE UNIQUE INDEX gas_streak_withdrawals_transaction_hash_key ON public.gas_streak_withdrawals USING btree (transaction_hash);
CREATE UNIQUE INDEX gas_streaks_transaction_hash_key ON public.gas_streaks USING btree (transaction_hash);

-- ============================================================================
-- FUNCTIONS/PROCEDURES
-- ============================================================================

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- ============================================================================
-- VIEWS
-- ============================================================================
