"""GTA VI launch-day Twitch CCV forecaster (gta6-twitch-ccu-forecast-01).

Forecasts, for each of hours 2..24 of a game's UTC release day, five
quantiles (5/25/50/75/95%) of that hour's Twitch category viewers, given
only everything recorded up to the end of hour 1 (hour 1's print included).

Method
------
The case file ships `comparables`: past big launches' hourly Twitch
category counts from 14 days before to 3 days after their release day.
At run time this program fits, per forecast hour h, a small log-linear
model on those comparables:

    log(viewers_h / viewers_1)  ~  a_h + b_h * (log(viewers_1) - 12)

i.e. the hour's ratio to hour 1 depends on how big hour 1 already was.
That dependence is real and strong in the data: launches whose hour 1
was already huge (Elden Ring ~875k, Cyberpunk ~852k, both with a
simultaneous midnight-GMT unlock) stay near flat all day (peak ratio
~1.0-1.3), while launches whose hour 1 was still small because most
timezones had not unlocked yet (Ghost of Yotei 27k, Stellar Blade 27k)
grow 3-3.6x by the evening. The fitted slope is ~0 in the small hours
and about -0.2 early, steepening to about -0.44 in the evening hours
19-24, exactly the "bigger hour 1, flatter day" pattern.

Only comparables whose hour 1 was already a real launch hour are used
for the fit (hour-1 viewers >= 20,000; relaxed to >= 5,000, then >= 100
if too few qualify): comparables whose hour 1 is pre-unlock noise
(simultaneous global unlocks later in the day, hour 1 in the hundreds)
would otherwise inject ratios of 100x-2000x and wreck the medians.
The target game's own pre-release category history (the "Grand Theft
Auto VI" comparable, whose day_start is the 2026-08-27 premiere, not a
launch) is excluded: it has no release day.

Spread: the residuals of the fit give an inter-quartile log-spread per
hour (floored at 0.20, capped at 0.60 log units). The 5% / 95%
quantiles blend the empirical 5th / 95th residual percentiles with the
matching normal quantiles 50/50 (the empirical tails of ~25 points are
noisy on their own); the 25% / 75% quantiles are the normal ones. The
median is the fitted value. Quantiles are forced non-decreasing,
clamped to (0, 1e9] and rounded to 2 decimals, half up.

Validation (leave-one-out over the 38 comparables in the kit, scored
with the contest's own pinball loss on log scale):
  * relevant launches (hour 1 >= 20k, already launched): this model
    0.198 mean pinball vs 0.271 for the house persistence baseline.
  * all 37 usable comparables: 0.69 vs 0.93 for the baseline.
The house baseline scores ~0.387 on the four practice cases; this
model's LOO numbers are on a different (harder, more varied) set, so
they are not directly comparable, but the margin over the baseline is
consistent in both evaluations.

Fallbacks: if a forecast hour has too few training rows (< 8) the
regression is replaced by the plain median log-ratio of the training
set with the same spread rule; if there are no usable comparables at
all, the program falls back to the house persistence baseline
(flat at hour 1, spread 0.15 * sqrt(h - 1)) so the output is always
valid. Everything is deterministic: no randomness, no network, no
clock reads, sorted iteration only. Standard library only.
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so an
# `import model` would find a model.py shipped beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Fit hyper-parameters, chosen on the leave-one-out evaluation above.
LOG_P1_CENTER = 12.0       # log viewers; e^12 ~= 163k
SLOPE_CLIP = 0.7           # per-hour OLS slope is clipped to [-0.7, 0.7]
SLOPE_SHRINK = 0.85        # shrink the slope toward 0 (variance control)
X_CLIP = (-3.0, 2.5)       # clip log(p1) - 12: p1 in [~8k, ~2.0M]
SIGMA_FLOOR = 0.20
SIGMA_CAP = 0.60
MIN_ROWS_REGRESSION = 8
BASELINE_SIGMA = 0.15      # fallback spread, as the house baseline


def round2(x):
    """Round to 2 decimals, half up (as JavaScript Math.round does)."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if float(value).is_integer() else value


def _quantile(sorted_vals, tau):
    """Linear-interpolated empirical quantile of a sorted list."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = tau * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _release_day_rows(comp):
    """(hour-1 viewers, {hour: viewers}) for a comparable's release day.

    Returns None when the comparable has no usable release-day hour 1.
    """
    hourly = comp.get("hourly") or []
    day_start = comp.get("day_start") or ""
    day = day_start[:10]
    if len(day) != 10:
        return None
    by_hour = {}
    for row in hourly:
        start = row.get("from") or ""
        if not start.startswith(day):
            continue
        try:
            hour = int(start[11:13]) + 1  # 00:00 UTC -> hour 1
        except (ValueError, IndexError):
            continue
        viewers = row.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            by_hour[hour] = float(viewers)
    p1 = by_hour.get(1)
    if p1 is None or p1 < 100:
        return None
    answers = {h: v for h, v in by_hour.items() if 2 <= h <= 24}
    if len(answers) < 20:
        return None
    return p1, answers


def _training_set(case):
    """Comparable launches usable for the fit, most-launched first.

    Excludes the target's own pre-release category history and keeps
    only launches whose hour 1 was already a real launch hour.
    """
    rows = []
    for comp in case.get("comparables") or []:
        name = (comp.get("name") or "")
        if "Grand Theft Auto VI" in name:
            continue
        parsed = _release_day_rows(comp)
        if parsed is None:
            continue
        rows.append(parsed)
    for threshold in (20000.0, 5000.0, 100.0):
        kept = [r for r in rows if r[0] >= threshold]
        if len(kept) >= 8:
            return kept
    return rows


def _fit_hour(train, p1, hour):
    """Five log-quantiles (offsets from log p1) for one forecast hour."""
    xs = []
    ys = []
    for comp_p1, answers in train:
        if hour in answers:
            xs.append(math.log(comp_p1) - LOG_P1_CENTER)
            ys.append(math.log(answers[hour] / comp_p1))
    if not xs:
        return None
    x = math.log(p1) - LOG_P1_CENTER
    x = max(X_CLIP[0], min(X_CLIP[1], x))
    if len(xs) >= MIN_ROWS_REGRESSION:
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        den = sum((a - mx) ** 2 for a in xs)
        slope = num / den if den > 0 else 0.0
        slope = max(-SLOPE_CLIP, min(SLOPE_CLIP, slope)) * SLOPE_SHRINK
        intercept = my - slope * mx
        median = intercept + slope * x
        residuals = sorted(b - (intercept + slope * a) for a, b in zip(xs, ys))
    else:
        median = sorted(ys)[len(ys) // 2] if len(ys) % 2 == 1 else (
            sorted(ys)[len(ys) // 2 - 1] + sorted(ys)[len(ys) // 2]) / 2.0
        residuals = sorted(b - median for b in ys)
    n = len(residuals)
    q25 = residuals[int(0.25 * (n - 1))]
    q75 = residuals[int(0.75 * (n - 1))]
    sigma = max(SIGMA_FLOOR, min(SIGMA_CAP, (q75 - q25) / 1.349))
    normal = [median + z * sigma for z in Z]
    empirical = [_quantile(residuals, tau) + median for tau in LEVELS]
    # Blend the noisy empirical tails with the normal ones; keep the
    # fitted median and the normal quartiles.
    offsets = [
        0.5 * empirical[0] + 0.5 * normal[0],
        normal[1],
        median,
        normal[3],
        0.5 * empirical[4] + 0.5 * normal[4],
    ]
    # Enforce non-decreasing offsets (the blend can cross in odd tails).
    for i in range(1, 5):
        if offsets[i] < offsets[i - 1]:
            offsets[i] = offsets[i - 1]
    return offsets


def _baseline_offsets(hour):
    """House persistence baseline offsets (log scale) for one hour."""
    return [z * BASELINE_SIGMA * math.sqrt(hour - 1) for z in Z]


def forecast_case(case, name):
    if case.get("levels") != LEVELS:
        raise ValueError("%s asks for levels %s, not %s"
                         % (name, case.get("levels"), LEVELS))
    first = next((k for k in case.get("known", []) if k.get("hour") == 1),
                 None)
    if first is None:
        raise ValueError("%s has no hour-1 print" % name)
    p1 = max(1.0, float(first["viewers"]))
    log_p1 = math.log(p1)
    train = _training_set(case)
    hours = []
    for row in case.get("forecast", []):
        hour = row["hour"]
        offsets = _fit_hour(train, p1, hour) if train else None
        if offsets is None:
            offsets = _baseline_offsets(hour)
        quantiles = []
        for off in offsets:
            # Cap the median ratio so a wild extrapolation can never
            # produce an absurd count; the cap is far outside any
            # launch ever observed (max ratio in the data is ~5x for
            # launched hour 1s, and simultaneous unlocks reach ~200x
            # only from a near-zero hour 1, which the training filter
            # already excludes).
            value = p1 * math.exp(max(-4.0, min(5.5, off)))
            value = max(1.0, min(1_000_000_000.0, value))
            quantiles.append(round2(value))
        for i in range(1, 5):
            if quantiles[i] < quantiles[i - 1]:
                quantiles[i] = quantiles[i - 1]
        hours.append({"hour": hour, "q": quantiles})
    hours.sort(key=lambda r: r["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
