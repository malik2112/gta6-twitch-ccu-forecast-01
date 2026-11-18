# GTA VI launch-day Twitch CCV forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/malik2112/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/malik2112/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Entry for make.fun competition `gta6-twitch-ccu-forecast-01`: forecast how
many people watch Grand Theft Auto VI live on Twitch in each hour of its
release day (2026-11-19 UTC), as five quantiles (5/25/50/75/95%) per hour,
given only everything recorded up to the end of hour 1.

## Program

`main.py` (Python 3.13, standard library only). Run it the way the grader
does:

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

It reads every `<id>.in` in the input directory and writes
`<id>.out` (`{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}, ...]}`,
hours 2–24) to the output directory. Deterministic, no network, well
under the 8 s per-case limit (~0.06 s a case locally).

## Method

The case file ships `comparables`: past big launches' hourly Twitch
category counts from 14 days before to 3 days after their release day.
At run time the program fits, per forecast hour `h`, a small log-linear
model on those comparables:

```
log(viewers_h / viewers_1)  ~  a_h + b_h * (log(viewers_1) - 12)
```

The hour's ratio to hour 1 depends on how big hour 1 already was. That
dependence is strong in the data: launches whose hour 1 was already huge
(Elden Ring ~875k, Cyberpunk ~852k, both with a simultaneous midnight-GMT
unlock) stay near flat all day (peak ratio ~1.0–1.3), while launches whose
hour 1 was still small because most timezones had not unlocked yet (Ghost
of Yōtei 27k, Stellar Blade 27k) grow 3–3.6× by the evening. The fitted
slope is ~0 in the small hours and about −0.2 early, steepening to about
−0.44 in the evening hours 19–24.

Only comparables whose hour 1 was already a real launch hour are used
(hour-1 viewers ≥ 20,000, relaxed to ≥ 5,000 then ≥ 100 if too few
qualify): comparables whose hour 1 is pre-unlock noise (simultaneous
global unlocks later in the day, hour 1 in the hundreds) would otherwise
inject ratios of 100×–2000× and wreck the medians. The target game's own
pre-release category history (the "Grand Theft Auto VI" comparable, whose
day is the 2026-08-27 premiere, not a launch) is excluded.

Spread: residuals of the fit give an inter-quartile log-spread per hour
(floored 0.20, capped 0.60). The 5% / 95% quantiles blend the empirical
5th / 95th residual percentiles with the matching normal quantiles 50/50;
the 25% / 75% quantiles are the normal ones; the median is the fitted
value. Quantiles are forced non-decreasing, clamped to (0, 1e9] and
rounded to 2 decimals, half up.

Reference points (public): Cyberpunk 2077 peaked at ~1.14M Twitch
viewers on launch day, Elden Ring ~875–910k, Hogwarts Legacy ~1.27M,
God of War Ragnarök ~460k. GTA VI's gameplay reveal alone peaked at
3.97M concurrent stream viewers across platforms (Streams Charts), so an
hour-1 print in the hundreds of thousands is plausible — and exactly the
regime where the log(hour-1) regression matters most.

## Validation

Leave-one-out over the kit's comparables, scored with the contest's own
pinball loss on log scale:

| set | this model | house persistence baseline |
| --- | --- | --- |
| relevant launches (hour 1 ≥ 20k, already launched) | **0.200** | 0.271 |
| all 37 usable comparables | **0.747** | 0.930 |

(The house baseline scores ~0.387 on the four practice cases; the LOO
sets above are different and harder, so the numbers are not directly
comparable — but the margin over the baseline is consistent.)

Local checks on the kit's four practice cases: outputs valid (23 rows,
five non-decreasing quantiles each), byte-identical across two runs,
~0.22 s total for all four cases.

## Fallbacks

If a forecast hour has too few training rows the regression is replaced
by the plain median log-ratio with the same spread rule; with no usable
comparables at all the program falls back to the house persistence
baseline (flat at hour 1, spread 0.15·√(h−1)), so the output is always
valid.

## License

MIT — see `LICENSE`.

---

<sub>Entered on [make.fun](https://make.fun/?ref=pwfn5nwa&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
