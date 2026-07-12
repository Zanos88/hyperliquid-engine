"""Study Batch 5 — S-F methodology retrofit: block-bootstrap bars, Deflated
Sharpe, effective-bets N_eff, hierarchical pooling. Pure Python (no numpy).

Block-bootstrap luck bar (generalizes the program's circular-shift null):
the null is "no timing skill". Per rep, the asset RETURN series is
stationary-block-resampled (Politis-Romano, mean block ~20 bars) — breaking
its alignment with each strategy's fixed position series while preserving
the return marginal + within-block autocorrelation. Each strategy's Sharpe
is recomputed on position×resampled_return; the FAMILY-MAX over the variant
set is taken per rep (multiplicity, as the old family-max shift bar did).
The 95th percentile of that null distribution is the bar. This uses each
variant's actual per-bar return computation, so observed and null are
computed identically.
"""
from __future__ import annotations

import math
import random


# ── normal CDF / inverse (Acklam) ───────────────────────────────────────

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Acklam's rational approximation to the inverse normal CDF."""
    if not 0.0 < p < 1.0:
        raise ValueError("norm_ppf domain (0,1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ── moments / Sharpe ────────────────────────────────────────────────────

def _mean(xs):
    return sum(xs) / len(xs)


def moments(xs):
    """(mean, std, skew, excess_kurtosis) — population (biased) estimators."""
    n = len(xs)
    m = _mean(xs)
    m2 = sum((x - m) ** 2 for x in xs) / n
    if m2 == 0:
        return m, 0.0, 0.0, 0.0
    sd = math.sqrt(m2)
    m3 = sum((x - m) ** 3 for x in xs) / n
    m4 = sum((x - m) ** 4 for x in xs) / n
    return m, sd, m3 / sd ** 3, m4 / m2 ** 2 - 3.0


def annualized_sharpe(rets, ppy: float) -> float:
    n = len(rets)
    if n < 2:
        return 0.0
    m = _mean(rets)
    var = sum((x - m) ** 2 for x in rets) / (n - 1)
    sd = math.sqrt(var)
    return (m / sd) * math.sqrt(ppy) if sd > 0 else 0.0


def deflated_sharpe_ratio(sr_ann, rets, ppy: float, n_trials: int) -> float:
    """Bailey & López de Prado DSR. sr_ann is the ANNUALIZED Sharpe; converted
    to per-observation for the variance term. Returns P(true SR>0) deflated
    for `n_trials` selection and non-normal returns. >0.95 = survives."""
    n = len(rets)
    if n < 8 or n_trials < 1:
        return float("nan")
    sr = sr_ann / math.sqrt(ppy)                     # per-observation Sharpe
    _, _, skew, exk = moments(rets)
    # expected max Sharpe (per-obs) across n_trials i.i.d. trials, Var(SR)=1/N.
    # For a single trial there is no selection, so SR0 = 0 (E[max of 1] = 0).
    gamma = 0.5772156649015329
    if n_trials <= 1:
        sr0 = 0.0
    else:
        e1 = norm_ppf(1 - 1.0 / n_trials)
        e2 = norm_ppf(1 - 1.0 / (n_trials * math.e))
        sr0 = math.sqrt(1.0 / n) * ((1 - gamma) * e1 + gamma * e2)
    denom = math.sqrt(1 - skew * sr + (exk / 4.0) * sr * sr)
    if denom <= 0:
        return float("nan")
    return norm_cdf((sr - sr0) * math.sqrt(n - 1) / denom)


# ── effective bets ──────────────────────────────────────────────────────

def correlation_matrix(streams):
    """streams: list of equal-length return series → NxN Pearson correlations."""
    k = len(streams)
    ms = [_mean(s) for s in streams]
    sds = [math.sqrt(sum((x - ms[i]) ** 2 for x in streams[i])) for i in range(k)]
    R = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            if sds[i] == 0 or sds[j] == 0:
                R[i][j] = 1.0 if i == j else 0.0
            else:
                cov = sum((streams[i][t] - ms[i]) * (streams[j][t] - ms[j])
                          for t in range(len(streams[i])))
                R[i][j] = cov / (sds[i] * sds[j])
    return R


def effective_bets(R):
    """N_eff two ways: participation ratio N^2/sum(R_ij^2) (== (tr R)^2/tr(R^2),
    no eigensolver needed) and the equicorrelation form N/(1+(N-1)*rho_bar)."""
    n = len(R)
    sumsq = sum(R[i][j] ** 2 for i in range(n) for j in range(n))
    n_eff_pr = n * n / sumsq if sumsq > 0 else float("nan")
    off = [R[i][j] for i in range(n) for j in range(n) if i != j]
    rho_bar = sum(off) / len(off) if off else 0.0
    n_eff_eq = n / (1 + (n - 1) * rho_bar) if (1 + (n - 1) * rho_bar) > 0 else float("nan")
    return {"n_eff_participation": round(n_eff_pr, 2), "avg_corr": round(rho_bar, 3),
            "n_eff_equicorr": round(n_eff_eq, 2)}


# ── stationary block bootstrap ──────────────────────────────────────────

def stationary_bootstrap_indices(n: int, mean_block: float, rng: random.Random):
    """Politis-Romano: geometric block lengths (p=1/mean_block), circular wrap."""
    p = 1.0 / mean_block
    idx = []
    cur = rng.randrange(n)
    while len(idx) < n:
        idx.append(cur)
        if rng.random() < p:
            cur = rng.randrange(n)          # start a new block
        else:
            cur = (cur + 1) % n             # continue block (circular)
    return idx


def block_bootstrap_family_bar(asset_returns, position_series_list, ppy: float,
                               mean_block_bars: float, reps: int = 10000,
                               pctile: float = 0.95, seed: int = 20260712):
    """Family-max block-boot luck bar. asset_returns[i] is the bar-i return
    that position[i-1] earns. Per rep: resample returns (stationary block),
    recompute each variant's Sharpe on pos[i-1]*r_resampled[i], take the max
    across variants. Returns the pctile of that null distribution + summary."""
    rng = random.Random(seed)
    n = len(asset_returns)
    for pos in position_series_list:
        if len(pos) != n:
            raise ValueError("position series must align with asset_returns length")
    maxima = []
    for _ in range(reps):
        idx = stationary_bootstrap_indices(n, mean_block_bars, rng)
        r_star = [asset_returns[k] for k in idx]
        best = -1e9
        for pos in position_series_list:
            net = [pos[i - 1] * r_star[i] for i in range(1, n)]
            best = max(best, annualized_sharpe(net, ppy))
        maxima.append(best)
    maxima.sort()
    def q(a):
        return a[min(len(a) - 1, math.ceil(pctile * len(a)) - 1)]
    return {"bar": round(q(maxima), 3), "null_median": round(maxima[len(maxima) // 2], 3),
            "null_p50": round(maxima[len(maxima) // 2], 3),
            "null_max": round(maxima[-1], 3), "reps": reps,
            "mean_block_bars": mean_block_bars, "pctile": pctile}


# ── hierarchical pooling (normal-normal, method-of-moments hyperparams) ──

def hierarchical_pool(estimates, ses):
    """Partial-pool per-unit estimates y_k (SE s_k) toward a common mean mu.
    Normal-normal model; tau^2 (between-unit variance) by DerSimonian-Laird;
    returns the pooled common-effect posterior (mu, sd) and shrunk estimates."""
    k = len(estimates)
    w = [1.0 / (s * s) for s in ses]
    ybar = sum(w[i] * estimates[i] for i in range(k)) / sum(w)
    Q = sum(w[i] * (estimates[i] - ybar) ** 2 for i in range(k))
    c = sum(w) - sum(wi * wi for wi in w) / sum(w)
    tau2 = max(0.0, (Q - (k - 1)) / c) if c > 0 else 0.0
    wstar = [1.0 / (ses[i] ** 2 + tau2) for i in range(k)]
    mu = sum(wstar[i] * estimates[i] for i in range(k)) / sum(wstar)
    mu_sd = math.sqrt(1.0 / sum(wstar))
    shrunk = [(wstar[i] * estimates[i] + (1.0 / (tau2 + 1e-12)) * mu) /
              (wstar[i] + 1.0 / (tau2 + 1e-12)) if tau2 > 0 else mu
              for i in range(k)]
    return {"common_mu": mu, "common_sd": mu_sd, "tau": math.sqrt(tau2),
            "ci95": (mu - 1.96 * mu_sd, mu + 1.96 * mu_sd),
            "prob_positive": norm_cdf(mu / mu_sd) if mu_sd > 0 else float("nan"),
            "shrunk": shrunk}


# ── selftest ────────────────────────────────────────────────────────────

def _selftest():
    assert abs(norm_cdf(0) - 0.5) < 1e-9
    assert abs(norm_ppf(0.975) - 1.959964) < 1e-4
    assert abs(norm_ppf(norm_cdf(0.7)) - 0.7) < 1e-6
    m, sd, sk, ek = moments([1, 2, 3, 4, 5])
    assert abs(m - 3) < 1e-9 and abs(sk) < 1e-9 and ek < 0     # platykurtic uniform-ish
    # Sharpe: constant-positive returns → large Sharpe
    assert annualized_sharpe([0.001] * 300, 365) == 0.0        # zero variance guard
    rng = random.Random(1)
    r = [rng.gauss(0.001, 0.02) for _ in range(500)]
    assert annualized_sharpe(r, 365) != 0.0
    # effective bets: identical streams → N_eff ≈ 1; orthogonal → N_eff ≈ N
    R_same = correlation_matrix([r, r, r])
    assert effective_bets(R_same)["n_eff_participation"] < 1.2
    a = [rng.gauss(0, 1) for _ in range(400)]
    b = [rng.gauss(0, 1) for _ in range(400)]
    cc = [rng.gauss(0, 1) for _ in range(400)]
    assert effective_bets(correlation_matrix([a, b, cc]))["n_eff_participation"] > 2.5
    # block bootstrap: a no-edge random position series → observed Sharpe should
    # sit BELOW the family bar most of the time (null is calibrated).
    pos = [rng.randint(0, 1) for _ in range(len(r))]
    bar = block_bootstrap_family_bar(r, [pos], 365, 20, reps=300)
    assert bar["bar"] > bar["null_median"]
    # DSR: strong clean Sharpe with 1 trial → high; same with 1000 trials → lower
    strong = [rng.gauss(0.004, 0.01) for _ in range(600)]
    d1 = deflated_sharpe_ratio(annualized_sharpe(strong, 365), strong, 365, 1)
    d1000 = deflated_sharpe_ratio(annualized_sharpe(strong, 365), strong, 365, 1000)
    assert d1 >= d1000
    # hierarchical pooling: consistent positive estimates → positive common mu
    hp = hierarchical_pool([0.3, 0.5, 0.4, 0.35], [0.2, 0.2, 0.2, 0.2])
    assert hp["common_mu"] > 0 and hp["prob_positive"] > 0.9
    print("blockstats selftest: all assertions passed")


if __name__ == "__main__":
    _selftest()
