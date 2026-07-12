-- V2 telemetry schema (build report section 7, trimmed: no pgvector).
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS portfolio_telemetry (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol TEXT NOT NULL DEFAULT 'BTC',
    equity NUMERIC NOT NULL,
    balance NUMERIC,
    unrealized_pnl NUMERIC,
    day_start_equity NUMERIC NOT NULL,
    distance_to_daily_floor NUMERIC,
    distance_to_static_floor NUMERIC,
    engine_state TEXT NOT NULL DEFAULT 'PAUSED'
);
CREATE INDEX IF NOT EXISTS idx_portfolio_telemetry_symbol_ts
    ON portfolio_telemetry (symbol, ts DESC);

CREATE TABLE IF NOT EXISTS trade_execution_ledger (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol TEXT NOT NULL DEFAULT 'BTC',
    intent_id TEXT NOT NULL UNIQUE,
    order_group_id TEXT,
    purpose TEXT NOT NULL,           -- entry | stop_loss | take_profit | close | kill_close | cancel:*
    side TEXT NOT NULL,
    position_side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    price NUMERIC,
    trigger_price NUMERIC,
    reduce_only BOOLEAN NOT NULL DEFAULT false,
    close_position BOOLEAN NOT NULL DEFAULT false,
    -- risk context (entry intents carry these for the floor-guard trigger)
    risk_entry_price NUMERIC,
    risk_stop_price NUMERIC,
    risk_usd NUMERIC,
    attenuation_applied NUMERIC,
    dry_run BOOLEAN NOT NULL,
    dispatched BOOLEAN NOT NULL DEFAULT false,
    -- fill data (populated from WS/trades after execution)
    fill_price NUMERIC,
    slippage_bps NUMERIC,
    fees NUMERIC,
    r_result NUMERIC,
    indicators_snapshot JSONB        -- Fisher/OBV/bias at signal time: the audit trail
);
CREATE INDEX IF NOT EXISTS idx_trade_execution_ledger_symbol_ts
    ON trade_execution_ledger (symbol, ts DESC);

CREATE TABLE IF NOT EXISTS risk_events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,        -- circuit_breaker_trip | guardian_soft_halt | guardian_hard_flatten
                                     -- | kill_invoked | risk_param_change | db_trigger_block
    detail JSONB
);

-- Single-row cross-process engine state (ACTIVE / PAUSED / KILLED).
-- Deployment-agnostic shared state between engine, guardian, and telegram.
CREATE TABLE IF NOT EXISTS engine_state (
    id INT PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'PAUSED', 'KILLED')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
INSERT INTO engine_state (id, state, updated_by)
    VALUES (1, 'PAUSED', 'schema-init')
    ON CONFLICT (id) DO NOTHING;

-- Runtime-adjustable risk parameters (set via /risk, read by the engine
-- each cycle). Single row; every change is also logged to risk_events.
CREATE TABLE IF NOT EXISTS risk_params (
    id INT PRIMARY KEY CHECK (id = 1),
    risk_pct NUMERIC NOT NULL CHECK (risk_pct >= 0.0025 AND risk_pct <= 0.01),
    alpha NUMERIC NOT NULL CHECK (alpha >= 1.0),
    max_concurrent INT NOT NULL CHECK (max_concurrent >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
INSERT INTO risk_params (id, risk_pct, alpha, max_concurrent, updated_by)
    VALUES (1, 0.0075, 1.5, 1, 'schema-init')
    ON CONFLICT (id) DO NOTHING;

-- Strategy mode + timeframe combos (set via /settings, read by the engine
-- each cycle). Single row; changes logged to risk_events. Test timeframes
-- are configurable but only via their own /settings submenu — never the
-- production selection path.
CREATE TABLE IF NOT EXISTS strategy_settings (
    id INT PRIMARY KEY CHECK (id = 1),
    mode TEXT NOT NULL CHECK (mode IN ('production', 'test')),
    prod_bias_tf TEXT NOT NULL
        CHECK (prod_bias_tf IN ('15m','30m','1h','4h','8h','12h','1d','3d','1w')),
    prod_trigger_tf TEXT NOT NULL
        CHECK (prod_trigger_tf IN ('15m','30m','1h','4h','8h','12h','1d','3d','1w')),
    test_bias_tf TEXT NOT NULL
        CHECK (test_bias_tf IN ('1m','3m','5m','15m','30m','1h')),
    test_trigger_tf TEXT NOT NULL
        CHECK (test_trigger_tf IN ('1m','3m','5m','15m','30m','1h')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
INSERT INTO strategy_settings (id, mode, prod_bias_tf, prod_trigger_tf,
                               test_bias_tf, test_trigger_tf, updated_by)
    VALUES (1, 'production', '4h', '1h', '5m', '1m', 'schema-init')
    ON CONFLICT (id) DO NOTHING;

-- Pending signal frames (Frame A): the engine writes a row + posts the
-- Telegram frame; the control-plane process resolves the row when a
-- button is tapped. Cross-process by design.
CREATE TABLE IF NOT EXISTS pending_signals (
    signal_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    entry NUMERIC NOT NULL,
    stop NUMERIC NOT NULL,
    target NUMERIC NOT NULL,
    reward_risk NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'taken', 'skipped', 'expired')),
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT
);

-- Confluence indicator toggles (set via /settings -> Indicators, read by
-- the engine each cycle). Defaults preserve the original 3-indicator
-- behavior: bias_sr/fisher/obv on, rsi/ichimoku off.
CREATE TABLE IF NOT EXISTS indicator_config (
    id INT PRIMARY KEY CHECK (id = 1),
    bias_sr BOOLEAN NOT NULL DEFAULT true,
    fisher BOOLEAN NOT NULL DEFAULT true,
    obv BOOLEAN NOT NULL DEFAULT true,
    rsi BOOLEAN NOT NULL DEFAULT false,
    ichimoku BOOLEAN NOT NULL DEFAULT false,
    ichimoku_variant TEXT NOT NULL DEFAULT 'standard'
        CHECK (ichimoku_variant IN ('standard', 'crypto')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
INSERT INTO indicator_config (id, updated_by)
    VALUES (1, 'schema-init')
    ON CONFLICT (id) DO NOTHING;

-- Backtest-review data: full indicator snapshot per SIGNAL (not just per
-- taken intent) — added for the indicator-toggle feature.
ALTER TABLE pending_signals ADD COLUMN IF NOT EXISTS indicators_snapshot JSONB;

-- Latest market/structural state, written by the engine each bias cycle,
-- read by the control plane's manual trade panel (strategy-anchored
-- Buy/Sell needs current S/R levels cross-process).
CREATE TABLE IF NOT EXISTS market_state (
    id INT PRIMARY KEY CHECK (id = 1),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol TEXT NOT NULL DEFAULT 'BTC',
    last_price NUMERIC NOT NULL,
    bias TEXT NOT NULL,
    long_stop NUMERIC,      -- structural stop for a manual long (nearest support - buffer)
    long_target NUMERIC,    -- next opposing level above
    short_stop NUMERIC,     -- nearest resistance + buffer
    short_target NUMERIC    -- next opposing level below
);

-- V2.1 additions (idempotent): cross-process paper state for the
-- Telegram/web dashboards — the exact level that set the bias, paper
-- position count, at-stop open risk, and breaker state.
ALTER TABLE market_state ADD COLUMN IF NOT EXISTS bias_reason TEXT;
-- Live per-indicator readings (same shape as indicators_snapshot),
-- refreshed every trigger close — powers the confluence insight cards.
ALTER TABLE market_state ADD COLUMN IF NOT EXISTS readings JSONB;
ALTER TABLE portfolio_telemetry ADD COLUMN IF NOT EXISTS open_positions INT;
ALTER TABLE portfolio_telemetry ADD COLUMN IF NOT EXISTS open_risk_usd NUMERIC;
ALTER TABLE portfolio_telemetry ADD COLUMN IF NOT EXISTS cb_halted BOOLEAN;

-- V2.3 go-live (idempotent): signal geometry the engine passes to
-- evaluate_signal. Defaults reproduce pre-V2.3 behavior exactly, so the
-- existing live row is unchanged until explicitly set. The engine only
-- honors these on the 4h/1h combo (see main.py effective_signal_geometry);
-- fib_extension_preferred was the only positive cell in the V2.3 sweep
-- (docs/V2_3_TARGET_EXTENSION.md) and it lost on 15m/5m and 1d/4h.
ALTER TABLE strategy_settings ADD COLUMN IF NOT EXISTS target_model TEXT
    NOT NULL DEFAULT 'nearest_structure'
    CHECK (target_model IN ('nearest_structure', 'fib_extension_preferred', 'blue_sky_atr'));
ALTER TABLE strategy_settings ADD COLUMN IF NOT EXISTS stop_model TEXT
    NOT NULL DEFAULT 'structural'
    CHECK (stop_model IN ('structural', 'hybrid'));

-- Backtest results (SIMULATED data — kept strictly separate from the
-- live/forward tables; every consumer must label these as simulation).
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    bias_tf TEXT NOT NULL,
    trigger_tf TEXT NOT NULL,
    indicator_config JSONB NOT NULL,
    candles_from TIMESTAMPTZ,
    candles_to TIMESTAMPTZ,
    bars_evaluated INT,
    trades INT, wins INT, losses INT, unresolved INT, suppressed_rr INT,
    gross_r NUMERIC, net_r NUMERIC, avg_net_r NUMERIC,
    win_rate NUMERIC, profit_factor NUMERIC, max_drawdown_r NUMERIC,
    fees_model TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS backtest_trades (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    entry_ts TIMESTAMPTZ,
    exit_ts TIMESTAMPTZ,
    direction TEXT,
    entry NUMERIC, stop NUMERIC, target NUMERIC,
    reward_risk NUMERIC,
    exit_reason TEXT,          -- target | stop | unresolved
    gross_r NUMERIC, net_r NUMERIC,
    bars_held INT,
    indicators_snapshot JSONB
);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades (run_id);

-- Track 2 (idempotent): which strategy produced a backtest run, so the
-- trend system and the counter-trend module are directly comparable in
-- one table. Existing runs default to 'trend'; counter-trend runs tag
-- 'counter_trend'.
ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS strategy_type TEXT
    NOT NULL DEFAULT 'trend'
    CHECK (strategy_type IN ('trend', 'counter_trend'));

-- Track 3 (idempotent): widen the strategy_type CHECK to admit
-- 'fisher_cycle'. The original inline CHECK above is auto-named by
-- Postgres; drop whatever CHECK references strategy_type by lookup (name-
-- agnostic) then re-add the widened, explicitly-named constraint. Safe to
-- re-run: the second pass finds and drops backtest_runs_strategy_type_chk
-- and re-adds it identically.
DO $$
DECLARE c text;
BEGIN
    SELECT conname INTO c FROM pg_constraint
     WHERE conrelid = 'backtest_runs'::regclass AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%strategy_type%';
    IF c IS NOT NULL THEN
        EXECUTE format('ALTER TABLE backtest_runs DROP CONSTRAINT %I', c);
    END IF;
END $$;
ALTER TABLE backtest_runs ADD CONSTRAINT backtest_runs_strategy_type_chk
    CHECK (strategy_type IN ('trend', 'counter_trend', 'fisher_cycle'));

-- ── Floor guard: the LAST line of defense (build report section 6.3) ──
-- BEFORE INSERT on order intents. Blocks ENTRY intents whose worst case
-- (stop-out at risk_stop_price) crosses the binding floor + $200 hard
-- buffer, computed from the LATEST telemetry row. Fires even if the
-- in-process gate and the guardian both have bugs, because the execution
-- service records the intent row BEFORE dispatching to Propr.
--
-- NEVER blocks risk-REDUCING intents (reduceOnly/closePosition/cancels/
-- kill closes) — blocking a kill would be worse than any entry bug.
-- Fails CLOSED: entry intents with no telemetry or missing risk prices
-- are rejected.
CREATE OR REPLACE FUNCTION enforce_floor_guard() RETURNS TRIGGER AS $$
DECLARE
    latest RECORD;
    cfg RECORD;
    hwm_val NUMERIC;
    dd_base NUMERIC;
    dd_floor NUMERIC;
    worst_case NUMERIC;
    floor_binding NUMERIC;
BEGIN
    IF NEW.reduce_only OR NEW.close_position OR NEW.purpose <> 'entry' THEN
        RETURN NEW;
    END IF;

    IF NEW.risk_entry_price IS NULL OR NEW.risk_stop_price IS NULL THEN
        RAISE EXCEPTION 'floor guard: entry intent % missing risk_entry_price/risk_stop_price (fail closed)',
            NEW.intent_id;
    END IF;

    SELECT equity, day_start_equity INTO latest
    FROM portfolio_telemetry
    ORDER BY ts DESC, id DESC
    LIMIT 1;

    IF latest IS NULL THEN
        RAISE EXCEPTION 'floor guard: no telemetry rows — refusing entry intent % (fail closed)',
            NEW.intent_id;
    END IF;

    -- Tier-parameterized floors (challenge_config + equity_hwm; static seed
    -- reproduces the historical GREATEST(day_start - 3000, 94000) exactly).
    -- Fail CLOSED when the config row is missing.
    SELECT drawdown_type, max_drawdown_pct, daily_loss_pct, initial_balance
        INTO cfg FROM challenge_config WHERE id = 1;
    IF cfg IS NULL THEN
        RAISE EXCEPTION 'floor guard: challenge_config missing — refusing entry intent % (fail closed)',
            NEW.intent_id;
    END IF;
    SELECT hwm INTO hwm_val FROM equity_hwm WHERE id = 1;

    dd_base := CASE WHEN cfg.drawdown_type = 'trailing'
                    THEN GREATEST(COALESCE(hwm_val, cfg.initial_balance), cfg.initial_balance)
                    ELSE cfg.initial_balance END;
    dd_floor := dd_base * (1 - cfg.max_drawdown_pct / 100);
    floor_binding := GREATEST(
        latest.day_start_equity - cfg.initial_balance * cfg.daily_loss_pct / 100,
        dd_floor);
    worst_case := latest.equity - ABS(NEW.risk_entry_price - NEW.risk_stop_price) * NEW.quantity;

    IF worst_case <= floor_binding + 200 THEN
        RAISE EXCEPTION 'floor guard: intent % worst-case equity % crosses binding floor % + 200 buffer',
            NEW.intent_id, round(worst_case, 2), floor_binding;
    END IF;

    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_floor_guard ON trade_execution_ledger;
CREATE TRIGGER trg_floor_guard
    BEFORE INSERT ON trade_execution_ledger
    FOR EACH ROW EXECUTE FUNCTION enforce_floor_guard();

-- ── Trend dry-run forward test (paper only; docs/TREND_FORWARD_TEST.md) ──
-- SEPARATE from the live/forward tables by design. Experiment processes
-- must NEVER write portfolio_telemetry: the floor-guard trigger above reads
-- its latest row with no writer filter, so a paper-equity row would change
-- what the LIVE engine's entry intents are validated against.
CREATE TABLE IF NOT EXISTS trend_forward_marks (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    bar_open_time_ms BIGINT NOT NULL,
    bar_close_utc TIMESTAMPTZ NOT NULL,
    strategy TEXT NOT NULL,            -- tsmom30 | sma50 | buy_hold
    symbol TEXT NOT NULL DEFAULT 'BTC',
    close NUMERIC NOT NULL,
    position INT NOT NULL,             -- position held INTO this bar (0/1);
                                       -- inception rows: position held FROM here
    bar_log_return NUMERIC NOT NULL,   -- net of fees for this bar
    equity NUMERIC NOT NULL,
    flipped BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (strategy, bar_open_time_ms)
);
CREATE INDEX IF NOT EXISTS idx_trend_forward_marks_strategy
    ON trend_forward_marks (strategy, bar_open_time_ms DESC);

-- ── Challenge tier parameterization (docs/GOLD_2STEP_REPARAMETERIZATION.md) ──
-- Single source of truth for account-level safety thresholds. Seeded with the
-- CURRENT posture (static 6% @ initial 100k -> $94,000 floor; daily 3% of
-- initial -> day_start - $3,000) so applying this schema changes NO behavior.
-- Flipping to Gold 2-Step (trailing 8% / daily 5%) is an explicit, user-gated
-- UPDATE at Step-4 sign-off — never part of a code deploy.
CREATE TABLE IF NOT EXISTS challenge_config (
    id INT PRIMARY KEY CHECK (id = 1),
    drawdown_type TEXT NOT NULL CHECK (drawdown_type IN ('static', 'trailing')),
    max_drawdown_pct NUMERIC NOT NULL CHECK (max_drawdown_pct > 0 AND max_drawdown_pct <= 20),
    daily_loss_pct NUMERIC NOT NULL CHECK (daily_loss_pct > 0 AND daily_loss_pct <= 10),
    initial_balance NUMERIC NOT NULL CHECK (initial_balance > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
INSERT INTO challenge_config (id, drawdown_type, max_drawdown_pct, daily_loss_pct,
                              initial_balance, updated_by)
    VALUES (1, 'static', 6, 3, 100000, 'schema-init')
    ON CONFLICT (id) DO NOTHING;

-- Persisted equity high-water mark: the trailing floor's base. Written ONLY
-- via GREATEST (db/store.update_hwm) so it can never move down — restart-safe
-- by living in Postgres, not process memory. Re-initialize from the real
-- Propr account equity at challenge activation (no active attempt exists yet).
CREATE TABLE IF NOT EXISTS equity_hwm (
    id INT PRIMARY KEY CHECK (id = 1),
    hwm NUMERIC NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO equity_hwm (id, hwm) VALUES (1, 100000)
    ON CONFLICT (id) DO NOTHING;

-- ── Order-book snapshots (interim forward logging; paper-research only) ──
-- One row per 1H bar close, captured LIVE within 120s of the boundary
-- (scripts/orderbook_logger.py — the contemporaneity guard is hard; a
-- stale snapshot stamped to a boundary would corrupt the future imbalance
-- test). Consumed later by the pre-registered order-book imbalance layer
-- (docs/ORDERBOOK_IMBALANCE_LAYER.md — definition locked at top-10, ±0.15;
-- raw levels are provenance, NOT a re-tuning surface).
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    bar_close_ms BIGINT NOT NULL,      -- the 1H boundary this row represents
    coin TEXT NOT NULL DEFAULT 'BTC',
    imbalance_top10 NUMERIC NOT NULL,  -- (bid10-ask10)/(bid10+ask10)
    bid_vol_top10 NUMERIC NOT NULL,
    ask_vol_top10 NUMERIC NOT NULL,
    best_bid NUMERIC NOT NULL,
    best_ask NUMERIC NOT NULL,
    levels JSONB NOT NULL,             -- raw 20x2 book (provenance)
    UNIQUE (coin, bar_close_ms)
);
CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_coin_bar
    ON orderbook_snapshots (coin, bar_close_ms DESC);
