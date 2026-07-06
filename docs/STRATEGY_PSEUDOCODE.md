# Strategy Pseudocode

Written and checked for internal consistency before any Python was
written, per the build spec's Section 4.4.

```
# ==== Run once per closed candle (scheduler triggers this on 1H close;
#      4H bias is recomputed whenever a 4H candle also just closed) ====

on 4H candle close:
    swings = detect_swings(4h_candles, method="fractal", fractal_width=2)
    # fractal_width=2: a bar is a swing high if it is the highest of the
    # 2 bars before and 2 bars after it (and symmetrically for swing low)
    last_swing = most_recent_completed(swings)   # requires 2 bars of
                                                  # confirmation after it,
                                                  # so it never repaints
    fib_levels = fibonacci_levels(last_swing.start, last_swing.end)
    # 0.236 / 0.382 / 0.5 / 0.618 / 0.786 retracement,
    # 1.272 / 1.618 extension beyond the swing
    sr_levels = horizontal_sr(swings, lookback=20)  # prior swing highs/lows

    price = 4h_candles[-1].close
    nearest_sr = closest_level(sr_levels, price)

    if last_swing.direction == "up":
        if price > fib_levels["0.618"] and price > nearest_sr.support:
            bias = BULLISH
        else:
            bias = NEUTRAL
    elif last_swing.direction == "down":
        if price < fib_levels["0.618"] and price < nearest_sr.resistance:
            bias = BEARISH
        else:
            bias = NEUTRAL
    else:
        bias = NEUTRAL

    store(current_4h_bias = bias, fib_levels, sr_levels, last_swing)


# ==== 1H trigger, evaluated only on 1H candle close ====

on 1H candle close:
    fisher, trigger_line = fisher_transform(1h_candles, period=9)
    obv = on_balance_volume(1h_candles)
    obv_sma = sma(obv, period=20)

    bullish_cross = fisher[-2] <= trigger_line[-2] and fisher[-1] > trigger_line[-1]
    bearish_cross = fisher[-2] >= trigger_line[-2] and fisher[-1] < trigger_line[-1]

    obv_rising  = obv[-1] > obv_sma[-1] and obv[-1] > obv[-2]
    obv_falling = obv[-1] < obv_sma[-1] and obv[-1] < obv[-2]

    bias = current_4h_bias   # set by the 4H block above

    if bullish_cross and obv_rising and bias == BULLISH:
        raw_direction = LONG
    elif bearish_cross and obv_falling and bias == BEARISH:
        raw_direction = SHORT
    else:
        raw_direction = None
        log_if_any_trigger_fired_against_or_without_bias(bullish_cross, bearish_cross, bias)

    if raw_direction is None:
        return   # no signal this bar

    # ---- exits ----
    entry_price = 1h_candles[-1].close   # decision made on close, entry
                                          # price is that same close (no
                                          # intra-candle fill assumption)

    if raw_direction == LONG:
        stop = nearest_sr.support - buffer   # structural: just beyond the
                                              # 4H support/swing-low that
                                              # underpins the BULLISH bias
        target = next_opposing_level_above(fib_levels, sr_levels, entry_price)
    else:  # SHORT
        stop = nearest_sr.resistance + buffer
        target = next_opposing_level_below(fib_levels, sr_levels, entry_price)

    risk = abs(entry_price - stop)
    reward = abs(target - entry_price)
    rr = reward / risk

    if rr < 2.0:
        log_suppressed_signal(raw_direction, entry_price, stop, target, rr)
        return   # R:R gate: suppress and log, no alert

    # ---- circuit breaker gate ----
    if circuit_breaker.is_halted():
        log_suppressed_signal_due_to_halt(raw_direction, entry_price, stop, target, rr)
        return

    # ---- sizing ----
    qty = size(equity=ledger.current_equity(), entry_price, stop, risk_pct=config.risk_pct)

    signal = Signal(
        direction=raw_direction, entry=entry_price, stop=stop, target=target,
        rr=rr, quantity=qty, timestamp=utcnow(), bias_reason=..., trigger_reason=...,
    )

    ledger.open_hypothetical_position(signal)
    alerts.send_entry_signal(signal)


# ==== Every tick (or on each new candle poll), independent of the above ====

on price_update(price):
    for pos in ledger.open_positions():
        if pos.direction == LONG:
            if price <= pos.stop:
                ledger.close_position(pos, exit_price=pos.stop, reason="stop")
                alerts.send_exit_alert(pos, "stop")
            elif price >= pos.target:
                ledger.close_position(pos, exit_price=pos.target, reason="target")
                alerts.send_exit_alert(pos, "target")
        else:  # SHORT
            if price >= pos.stop:
                ledger.close_position(pos, exit_price=pos.stop, reason="stop")
                alerts.send_exit_alert(pos, "stop")
            elif price <= pos.target:
                ledger.close_position(pos, exit_price=pos.target, reason="target")
                alerts.send_exit_alert(pos, "target")

    circuit_breaker.update(ledger.daily_pnl(), ledger.day_start_equity())
    if circuit_breaker.just_tripped():
        alerts.send_halt_alert(ledger.daily_pnl())


# ==== 00:00 UTC rollover ====

on daily_rollover():
    alerts.send_daily_summary(ledger.today_stats())
    ledger.start_new_day(equity=ledger.current_equity())
    circuit_breaker.reset_for_new_day()


# ==== every 4 hours ====

on heartbeat_tick():
    alerts.send_heartbeat(current_4h_bias, last_data_timestamp, feed_errors_since_last_heartbeat)
```
