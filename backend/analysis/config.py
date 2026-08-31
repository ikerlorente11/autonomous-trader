"""Strategy configuration loader.

Single source of the resolved, typed strategy config the analysis engine runs on.
Resolution order (lowest to highest priority):

1. ``config/strategy.yaml`` (version-controlled defaults).
2. Environment variables ``STRATEGY__<SECTION>__<KEY>`` (double underscore nests).

The result is validated into a frozen pydantic model so the engine can fail fast at
startup on a bad config, and the Experiment Tracker can serialise the exact object
(``.model_dump()``) into ``experiment_runs.config`` (experiment-framework §1.3).

``strategy_version`` is ``"{semver}+{config_hash}"``: the ``version`` key is the
deliberate human semver; the hash is six hex chars of a SHA-256 over the canonical
resolved config, so an edited weight with a forgotten bump still records distinctly
(experiment-framework §2.1).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import MutableMapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

_ENV_PREFIX = "STRATEGY__"
_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_DEFAULT_PATH = _CONFIG_DIR / "strategy.yaml"
# A "strategy version" is a named overlay file in config/strategies/<label>.yaml,
# deep-merged onto the base strategy.yaml. This is the A/B seam: portfolios pick a
# label and the engine runs that config. The base ("v1") is the default; a label
# whose overlay is empty resolves identically to the base.
_VARIANTS_DIR = _CONFIG_DIR / "strategies"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MarketFilterConfig(_Frozen):
    # "Wait for a good moment" gate: block NEW entries (BUY -> HOLD) on days the
    # benchmark closes below its own long moving average — i.e. when the broad
    # market's primary trend is down. Exits and holds are never blocked, so a
    # downtrend still lets positions be cut. Universe-wide and absolute, so it
    # governs the FIRST run exactly like any other (a freshly reset portfolio
    # stays in cash until the market trend is up), independent of which names
    # rank best — the piece the per-symbol score (absolute or rank-normalized)
    # could not provide. None = off. Fail-open: if the benchmark bar/history is
    # missing, entries are allowed (never block on absent data).
    benchmark: str = "SPY"
    ma_period: int = 200
    kind: Literal["sma", "ema"] = "sma"


class RankerConfig(_Frozen):
    min_score_to_act: float
    min_score_to_exit: float
    min_data_completeness: float
    market_filter: MarketFilterConfig | None = None
    # v11 (10-plan-momentum-mensual §3.1): when "monthly", signal-driven BUY/SELL act
    # only on the first session of each month (detected statelessly: the month of
    # `asof` differs from the month of the universe's latest bar — with market-on-open
    # fills that is exactly the first session after a month boundary). Non-rebalance
    # days emit HOLDs; protective stops never pass through here and stay intraday.
    # None = act every day (current behaviour).
    rebalance_cadence: Literal["monthly"] | None = None


class RegimeMultiplierConfig(_Frozen):
    # P11 phase 2: scale every composite by the day's macro regime score before the
    # action thresholds — risk-off damps entries, risk-on lets them through. Linear:
    # regime 0 -> `floor`, regime 100 -> `ceil`; unknown regime -> 1.0 (no effect).
    floor: float = 0.75
    ceil: float = 1.05


class ScoringConfig(_Frozen):
    score_min: float
    score_max: float
    weights: dict[str, float]
    # Diagnostics P7: when True, each weighted sub-score is replaced by its percentile
    # rank across the day's universe before weighting, so the buy/exit gate is relative
    # to the universe instead of an absolute, biased threshold (synthesis §3.4). The
    # normalization happens one layer above the per-symbol scorer (engine.score_universe).
    # False = current behaviour (raw sub-scores); the base/v1/v2 configs leave it off.
    rank_normalize: bool = False
    # P11 phase 2 (v5+): None = off (base behaviour, multiplier 1.0).
    regime_multiplier: RegimeMultiplierConfig | None = None


class MaTrendParams(_Frozen):
    kind: Literal["sma", "ema"]
    period: int
    sensitivity: float
    # Diagnostics P5: cap how far above the MA still adds score (a trend gate, not a
    # "how extended" reward). None = uncapped (current behaviour).
    extension_cap: float | None = None


class RsiParams(_Frozen):
    period: int
    overbought: float
    oversold: float
    # Diagnostics P4: "passthrough" = raw RSI (high RSI -> high score, buys strength);
    # "mean_reversion" = 100 - RSI (oversold scores high, contrarian).
    mode: Literal["passthrough", "mean_reversion"] = "passthrough"


class AtrParams(_Frozen):
    period: int
    sensitivity: float


class MomentumParams(_Frozen):
    # P11 §3.1: return over `period` bars ending `skip` bars ago (12-1 style — the
    # skip sidesteps the short-term reversal month). With rank_normalize (P7) its
    # percentile is cross-sectional relative momentum.
    period: int
    skip: int = 21
    sensitivity: float = 5.0


class IndicatorParams(_Frozen):
    ma_trend: MaTrendParams
    rsi: RsiParams
    atr: AtrParams
    # Optional so configs predating the signal stay valid; the engine only builds
    # the indicator when the section exists.
    momentum: MomentumParams | None = None


class TradingConfig(_Frozen):
    """Per-version trading knobs. Every field defaults to None, meaning "fall back to
    the env/default the code already uses" — so the base config (no ``trading`` block)
    leaves execution byte-for-byte unchanged, and a version overlay only changes what
    it explicitly sets. Diagnostics: P2 (cooldown), P3 (stop floor), P6 (pyramiding)."""

    stop_reentry_cooldown_days: int | None = None
    stop_min_distance_pct: float | None = None
    stop_atr_multiple: float | None = None
    allow_pyramiding: bool | None = None
    # Equal-risk sizing: risk this fraction of portfolio value per position, with the
    # position's stop distance (ATR × stop multiple) as the risk unit — a calm name
    # sizes bigger than a volatile one for the same euro risk. None = fixed-fractional
    # sizing (current behaviour). MAX_POSITION_PCT stays as the notional ceiling.
    vol_target_pct: float | None = None
    # Micro m3 anti-churn knobs (both None = off, no daily path change):
    # cap on signal-driven BUY entries per session, and a minimum holding time before
    # a signal exit may close a position (protective stops / EOD flatten are exempt —
    # risk controls must never wait).
    max_trades_per_day: int | None = None
    min_hold_minutes: int | None = None
    # v11 (10-plan-momentum-mensual §3.2): per-version sizing envelope. The env
    # globals (MAX_POSITION_PCT 5% / MIN_CASH_PCT 20% / MAX_OPEN_POSITIONS 10) cap
    # structural exposure at ~50%, which a concentrated monthly top-N cannot live
    # under. None = env fallback, so every existing version is byte-for-byte intact.
    max_position_pct: float | None = None
    min_cash_pct: float | None = None
    max_open_positions: int | None = None


class RegimeSwitchConfig(_Frozen):
    """v8: pick a whole sub-strategy by the benchmark's primary trend. On days the
    benchmark closes at/above its MA the ``trend`` label's config scores the universe
    (momentum logic wins in trends); below it, ``chop``'s (mean-reversion wins in
    ranges) — the live A/B's core finding: v1 won 2024-25 trending, v3 wins 2026 chop.
    Sub-labels must not themselves declare a regime_switch (no nesting). Fail-open:
    missing benchmark history resolves to ``chop`` (the defensive leg)."""

    benchmark: str = "SPY"
    ma_period: int = 100
    kind: Literal["sma", "ema"] = "sma"
    trend: str
    chop: str
    # v9: when True, the day's ENTRY discipline (pyramiding, cooldown, per-day caps,
    # vol sizing) comes from the ACTIVE LEG's trading config instead of this
    # version's own — v1's live loss was execution-not-signal, but its backtest
    # trend gains came precisely from the churn that discipline forbids; this lets
    # each regime run the execution style that historically won it. Protective-stop
    # parameters do NOT switch: they stay on this version's own trading block
    # (protection is constant, entries adapt).
    trading_from_leg: bool = False
    # v10: extra confirmation before the TREND leg engages. The MA100 test alone
    # cannot tell an advancing market from one drifting sideways above its (still
    # rising) average — the failure that sank v9 (07-plan §9). When set, the trend
    # leg additionally requires the benchmark's return over the last
    # ``confirm_momentum_sessions`` bars to exceed ``confirm_min_return``;
    # otherwise the day runs the chop leg. None = price-vs-MA only (v8/v9 rule).
    confirm_momentum_sessions: int | None = None
    confirm_min_return: float = 0.0


class StrategyConfig(_Frozen):
    version: str
    ranker: RankerConfig
    scoring: ScoringConfig
    indicators: IndicatorParams
    trading: TradingConfig = TradingConfig()
    regime_switch: RegimeSwitchConfig | None = None

    @property
    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:6]

    @property
    def strategy_version(self) -> str:
        return f"{self.version}+{self.config_hash}"


def _set_nested(tree: MutableMapping[str, Any], path: list[str], value: str) -> None:
    cursor: MutableMapping[str, Any] = tree
    for key in path[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, MutableMapping):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    cursor[path[-1]] = value


def _apply_env_overrides(tree: dict[str, Any]) -> dict[str, Any]:
    for env_key, raw in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        path = [p.lower() for p in env_key[len(_ENV_PREFIX) :].split("__") if p]
        if path:
            _set_nested(tree, path, raw)
    return tree


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"strategy config must be a mapping: {path}")
    return raw


def _load(path: Path, label: str | None) -> StrategyConfig:
    if not path.is_file():
        raise FileNotFoundError(f"strategy config not found: {path}")
    raw = _read_yaml_mapping(path)
    if label:
        overlay_path = _VARIANTS_DIR / f"{label}.yaml"
        if not overlay_path.is_file():
            raise FileNotFoundError(f"unknown strategy version: {label!r}")
        raw = _deep_merge(raw, _read_yaml_mapping(overlay_path))
    merged = _apply_env_overrides(raw)
    return StrategyConfig.model_validate(merged)


@lru_cache(maxsize=16)
def _cached(path_str: str, label: str | None) -> StrategyConfig:
    return _load(Path(path_str), label)


def load_strategy_config(
    path: str | os.PathLike[str] | None = None, *, label: str | None = None
) -> StrategyConfig:
    """Return the resolved, validated config (cached per resolved path + label).

    Path priority: explicit arg > ``STRATEGY_CONFIG_PATH`` env > packaged default.
    ``label`` selects a ``config/strategies/<label>.yaml`` overlay deep-merged onto
    the base (the A/B version seam); ``None`` is the base config.
    """
    chosen = Path(path) if path else Path(os.environ.get("STRATEGY_CONFIG_PATH", _DEFAULT_PATH))
    return _cached(str(chosen.resolve()), label)


def list_strategy_versions() -> list[str]:
    """Available version labels — the stems of ``config/strategies/*.yaml``, sorted.

    These are the values a portfolio's ``strategy_label`` may take (plus ``None`` =
    base). Empty if the variants directory does not exist.
    """
    if not _VARIANTS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _VARIANTS_DIR.glob("*.yaml"))
