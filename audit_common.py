from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np
import pandas as pd
import yaml

UNIT_SEPARATOR = "\u241f"


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def csv_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    csv_cfg = config.get("csv", {})
    return {
        "encoding": csv_cfg.get("encoding", "utf-8"),
        "sep": csv_cfg.get("delimiter", ","),
        "dtype": str,
        "keep_default_na": False,
        "na_filter": False,
        "on_bad_lines": "error" if csv_cfg.get("strict_bad_lines", True) else "warn",
        "low_memory": False,
    }


def iter_csv(
    path: str | Path,
    config: dict[str, Any],
    *,
    usecols: list[str] | None = None,
) -> Iterator[pd.DataFrame]:
    chunksize = int(config.get("csv", {}).get("chunksize", 5000))
    kwargs = csv_kwargs(config)
    if usecols is not None:
        kwargs["usecols"] = usecols
    yield from pd.read_csv(path, chunksize=chunksize, **kwargs)


def read_header(path: str | Path, config: dict[str, Any]) -> list[str]:
    return list(pd.read_csv(path, nrows=0, **csv_kwargs(config)).columns)


def physical_column(config: dict[str, Any], logical_name: str) -> str:
    value = config.get("columns", {}).get(logical_name)
    if not value:
        raise KeyError(f"Column mapping missing for logical field: {logical_name}")
    return str(value)


def mapped_columns(config: dict[str, Any], logical_names: Iterable[str]) -> list[str]:
    return [physical_column(config, name) for name in logical_names]


def required_column_map(config: dict[str, Any]) -> dict[str, str]:
    logical_names = config.get("required_columns", [])
    if not logical_names:
        logical_names = list(config.get("columns", {}).keys())
    return {name: physical_column(config, name) for name in logical_names}


def require_columns(actual_columns: Iterable[str], required: dict[str, str]) -> None:
    actual = set(actual_columns)
    missing = [
        f"{logical} -> {physical}"
        for logical, physical in required.items()
        if physical not in actual
    ]
    if missing:
        raise ValueError("Required columns are absent: " + ", ".join(missing))


def clean_series(df: pd.DataFrame, column: str) -> pd.Series:
    return df[column].fillna("").astype(str).str.strip()


def is_blank(value: Any) -> bool:
    return str(value if value is not None else "").strip() == ""


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def normalize_timestamp(value: Any) -> str:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return ""
    parsed = pd.to_datetime(raw, errors="coerce", utc=True)
    if pd.isna(parsed):
        return raw
    return parsed.isoformat()


def normalize_numeric(value: Any) -> str:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return ""
    number = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
    if pd.isna(number):
        return raw
    number = float(number)
    return str(int(number)) if number.is_integer() else format(number, ".15g")


def parse_listish(value: Any) -> list[str]:
    raw = str(value if value is not None else "").strip()
    if not raw or raw.lower() in {"none", "null", "nan", "[]", "{}"}:
        return []

    parsed: Any = None
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
            break
        except Exception:
            pass

    if isinstance(parsed, dict):
        values = list(parsed.keys())
    elif isinstance(parsed, (list, tuple, set)):
        values = list(parsed)
    elif parsed is not None and not isinstance(parsed, str):
        values = [parsed]
    else:
        delimiter = "|" if "|" in raw else ","
        values = raw.split(delimiter)

    normalized: list[str] = []
    for item in values:
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("login") or json.dumps(item, sort_keys=True)
        else:
            candidate = item
        text = normalize_space(candidate)
        if text:
            normalized.append(text)
    return normalized


def normalize_listish(value: Any) -> str:
    return "|".join(sorted(set(parse_listish(value)), key=str.casefold))


def normalize_for_comparison(
    column: str,
    value: Any,
    *,
    timestamp_columns: set[str],
    numeric_columns: set[str],
    list_like_columns: set[str],
) -> str:
    if column in timestamp_columns:
        return normalize_timestamp(value)
    if column in numeric_columns:
        return normalize_numeric(value)
    if column in list_like_columns:
        return normalize_listish(value)
    return normalize_space(value)


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_json(data: Any, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)


def file_digest(path: str | Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(value: Any) -> str:
    return hashlib.sha256(str(value if value is not None else "").encode("utf-8")).hexdigest()


def text_hash_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).map(text_sha256)


def file_metadata(path: str | Path, include_sha256: bool = True) -> dict[str, Any]:
    target = Path(path)
    stat = target.stat()
    output: dict[str, Any] = {
        "path": str(target.resolve()),
        "size_bytes": stat.st_size,
        "modified_at_epoch": stat.st_mtime,
    }
    if include_sha256:
        output["sha256"] = file_digest(target, "sha256")
    return output


def append_csv(
    df: pd.DataFrame,
    path: str | Path,
    *,
    first_write: bool,
    config: dict[str, Any],
) -> None:
    df.to_csv(
        path,
        index=False,
        mode="w" if first_write else "a",
        header=first_write,
        encoding=config.get("output", {}).get("csv_encoding", "utf-8"),
    )


def counter_to_distribution(counter: Counter[str], label: str, total: int) -> pd.DataFrame:
    frame = pd.DataFrame(counter.items(), columns=[label, "count"])
    if frame.empty:
        return frame
    frame = frame.sort_values(["count", label], ascending=[False, True]).reset_index(drop=True)
    frame["percent"] = frame["count"] / total * 100 if total else 0.0
    frame["cumulative_percent"] = frame["percent"].cumsum()
    return frame


def total_variation_distance(reference: Counter[str], observed: Counter[str]) -> float:
    keys = set(reference) | set(observed)
    ref_total = sum(reference.values())
    obs_total = sum(observed.values())
    if not ref_total or not obs_total:
        return 1.0 if ref_total != obs_total else 0.0
    return 0.5 * sum(
        abs(reference.get(key, 0) / ref_total - observed.get(key, 0) / obs_total)
        for key in keys
    )


def hhi(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if not total:
        return 0.0
    return sum((value / total) ** 2 for value in counter.values())


def numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    raw = clean_series(df, column)
    return pd.to_numeric(raw.where(raw.ne("")), errors="coerce")


def datetime_series(df: pd.DataFrame, column: str) -> pd.Series:
    raw = clean_series(df, column)
    return pd.to_datetime(raw.where(raw.ne("")), errors="coerce", utc=True)


def quantile_rows(values: Iterable[float], metric: str, percentiles: Iterable[int]) -> list[dict[str, Any]]:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    if not array.size:
        return [{"metric": metric, "statistic": "count", "value": 0}]
    rows: list[dict[str, Any]] = [
        {"metric": metric, "statistic": "count", "value": int(array.size)},
        {"metric": metric, "statistic": "mean", "value": float(np.mean(array))},
        {"metric": metric, "statistic": "min", "value": float(np.min(array))},
        {"metric": metric, "statistic": "max", "value": float(np.max(array))},
    ]
    for percentile in percentiles:
        rows.append(
            {
                "metric": metric,
                "statistic": f"p{int(percentile)}",
                "value": float(np.percentile(array, percentile)),
            }
        )
    return rows


def repository_full_name(owner: pd.Series, repository: pd.Series) -> pd.Series:
    owner_clean = owner.fillna("").astype(str).str.strip()
    repo_clean = repository.fillna("").astype(str).str.strip()
    return owner_clean + "/" + repo_clean


def compile_regex(config: dict[str, Any], name: str) -> re.Pattern[str]:
    expression = str(config.get("patterns", {}).get(name, "(?!)"))
    return re.compile(expression)


def boolish(value: Any) -> bool | None:
    raw = str(value if value is not None else "").strip().lower()
    if raw in {"true", "1", "yes", "y"}:
        return True
    if raw in {"false", "0", "no", "n"}:
        return False
    return None


def infer_item_kind(value: Any, config: dict[str, Any]) -> str:
    raw = normalize_space(value).lower()
    pr_markers = {str(x).lower() for x in config.get("research_fields", {}).get("pull_request_markers", [])}
    issue_markers = {str(x).lower() for x in config.get("research_fields", {}).get("issue_markers", [])}
    if raw in pr_markers or "pull" in raw:
        return "pull_request"
    if raw in issue_markers:
        return "issue"
    return raw or "unknown"
