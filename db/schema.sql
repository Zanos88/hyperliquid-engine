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

    floor_binding := GREATEST(latest.day_start_equity - 3000, 94000);
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
