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


class RankerConfig(_Frozen):
    min_score_to_act: float
    min_score_to_exit: float
    min_data_completeness: float


class ScoringConfig(_Frozen):
    score_min: float
    score_max: float
    weights: dict[str, float]


class MaTrendParams(_Frozen):
    kind: Literal["sma", "ema"]
    period: int
    sensitivity: float


class RsiParams(_Frozen):
    period: int
    overbought: float
    oversold: float


class AtrParams(_Frozen):
    period: int
    sensitivity: float


class IndicatorParams(_Frozen):
    ma_trend: MaTrendParams
    rsi: RsiParams
    atr: AtrParams


class StrategyConfig(_Frozen):
    version: str
    ranker: RankerConfig
    scoring: ScoringConfig
    indicators: IndicatorParams

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
