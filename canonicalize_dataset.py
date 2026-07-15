from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from audit_common import (
    append_csv,
    clean_series,
    ensure_dir,
    file_digest,
    file_metadata,
    iter_csv,
    load_config,
    normalize_for_comparison,
    physical_column,
    read_header,
    repository_full_name,
    require_columns,
    required_column_map,
    text_hash_series,
    write_json,
)

CANONICAL_COLUMNS = [
    "repository_full_name",
    "canonical_issue_key",
    "repository_category_canonical",
    "raw_text_sha256",
    "data_sources_seen",
    "duplicate_group_size",
    "duplicate_resolution",
]


def count_issue_ids(input_path: Path, config: dict[str, Any]) -> tuple[Counter[str], int]:
    issue_id_col = physical_column(config, "issue_id")
    counts: Counter[str] = Counter()
    total = 0
    for chunk in iter_csv(input_path, config, usecols=[issue_id_col]):
        values = clean_series(chunk, issue_id_col)
        counts.update(values.tolist())
        total += len(chunk)
    return counts, total


def enrich_rows(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    owner_col = physical_column(config, "owner")
    repository_col = physical_column(config, "repository")
    issue_id_col = physical_column(config, "issue_id")
    category_col = physical_column(config, "repository_category")
    raw_text_col = physical_column(config, "raw_text")
    source_col = physical_column(config, "data_source")
    missing_category = str(
        config.get("canonicalization", {}).get("missing_category_label", "Unclassified")
    )

    result = frame.copy()
    result["repository_full_name"] = repository_full_name(
        result[owner_col], result[repository_col]
    )
    result["canonical_issue_key"] = clean_series(result, issue_id_col)
    category = clean_series(result, category_col)
    result["repository_category_canonical"] = category.where(
        category.ne(""), missing_category
    )
    result["raw_text_sha256"] = text_hash_series(result[raw_text_col])
    result["data_sources_seen"] = clean_series(result, source_col)
    result["duplicate_group_size"] = 1
    result["duplicate_resolution"] = "unique"
    return result


def completeness_score(row: pd.Series, columns: list[str]) -> tuple[int, int]:
    nonempty = 0
    chars = 0
    for column in columns:
        value = str(row.get(column, "") or "").strip()
        if value:
            nonempty += 1
            chars += len(value)
    return nonempty, chars


def source_rank(value: Any, priority: list[str]) -> int:
    raw = str(value if value is not None else "").strip().lower()
    normalized = [str(item).strip().lower() for item in priority]
    try:
        return normalized.index(raw)
    except ValueError:
        return len(normalized)


def compare_group(
    group: pd.DataFrame,
    original_columns: list[str],
    config: dict[str, Any],
) -> tuple[list[str], dict[str, list[str]]]:
    canonical_cfg = config.get("canonicalization", {})
    ignored = {
        physical_column(config, logical)
        for logical in canonical_cfg.get("comparison_ignore_columns", [])
    }
    timestamp_columns = {
        physical_column(config, logical)
        for logical in canonical_cfg.get("timestamp_columns", [])
    }
    numeric_columns = {
        physical_column(config, logical)
        for logical in canonical_cfg.get("numeric_columns", [])
    }
    list_like_columns = {
        physical_column(config, logical)
        for logical in canonical_cfg.get("list_like_columns", [])
    }
    ignored.add(physical_column(config, "data_source"))

    conflicts: list[str] = []
    normalized_values: dict[str, list[str]] = {}
    for column in original_columns:
        if column in ignored:
            continue
        values = [
            normalize_for_comparison(
                column,
                value,
                timestamp_columns=timestamp_columns,
                numeric_columns=numeric_columns,
                list_like_columns=list_like_columns,
            )
            for value in group[column].tolist()
        ]
        unique = sorted(set(values))
        normalized_values[column] = unique
        if len(unique) > 1:
            conflicts.append(column)
    return conflicts, normalized_values


def resolve_group(
    issue_id: str,
    group: pd.DataFrame,
    original_columns: list[str],
    config: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    canonical_cfg = config.get("canonicalization", {})
    source_col = physical_column(config, "data_source")
    priority = list(canonical_cfg.get("source_priority", ["provider", "community"]))
    completeness_columns = [
        physical_column(config, logical)
        for logical in canonical_cfg.get("completeness_columns", [])
    ]

    conflicts, normalized_values = compare_group(group, original_columns, config)
    identity_columns = [
        physical_column(config, logical)
        for logical in canonical_cfg.get("identity_columns", [])
    ]
    identity_conflicts = [column for column in conflicts if column in identity_columns]

    ranked: list[tuple[tuple[int, int, int, int], int]] = []
    for position, (_, row) in enumerate(group.iterrows()):
        nonempty, chars = completeness_score(row, completeness_columns)
        rank = source_rank(row.get(source_col, ""), priority)
        ranked.append(((-nonempty, -chars, rank, position), position))
    ranked.sort()
    selected_position = ranked[0][1]
    selected = group.iloc[[selected_position]].copy()
    selected = selected.drop(columns=["__original_position__"], errors="ignore")

    sources = sorted(
        {str(value).strip() for value in group[source_col].tolist() if str(value).strip()},
        key=lambda value: (source_rank(value, priority), value.casefold()),
    )
    selected = enrich_rows(selected, config)
    selected["data_sources_seen"] = "|".join(sources)
    selected["duplicate_group_size"] = len(group)
    selected["duplicate_resolution"] = (
        "merged_equivalent_cross_source" if not conflicts else "selected_preferred_with_conflicts"
    )

    group_summary = {
        "issue_id": issue_id,
        "group_size": len(group),
        "sources_seen": "|".join(sources),
        "selected_source": str(group.iloc[selected_position].get(source_col, "")),
        "selected_original_position": int(group.iloc[selected_position]["__original_position__"]),
        "conflict_count": len(conflicts),
        "conflict_columns": "|".join(conflicts),
        "identity_conflict": bool(identity_conflicts),
        "identity_conflict_columns": "|".join(identity_conflicts),
        "resolution": str(selected.iloc[0]["duplicate_resolution"]),
    }

    conflict_rows: list[dict[str, Any]] = []
    for column in conflicts:
        conflict_rows.append(
            {
                "issue_id": issue_id,
                "column": column,
                "normalized_values": json.dumps(
                    normalized_values.get(column, []), ensure_ascii=False
                ),
                "sources_seen": "|".join(sources),
                "is_identity_column": column in identity_columns,
            }
        )
    return selected, group_summary, conflict_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a canonical one-row-per-issue corpus from cross-source duplicates."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True, help="Directory for manifests and conflict reports.")
    parser.add_argument(
        "--conflict-policy",
        choices=["fail", "prefer-complete"],
        default=None,
        help="fail is recommended. prefer-complete records conflicts and continues.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_dir = ensure_dir(args.output_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Output already exists: {output_path}. Use --overwrite intentionally.")

    original_columns = read_header(input_path, config)
    require_columns(original_columns, required_column_map(config))
    overlap = set(original_columns) & set(CANONICAL_COLUMNS)
    if overlap:
        raise ValueError(f"Input already contains canonical columns: {sorted(overlap)}")

    conflict_policy = args.conflict_policy or str(
        config.get("canonicalization", {}).get("conflict_policy", "fail")
    )
    issue_id_col = physical_column(config, "issue_id")

    print("Pass 1/3: counting issue_id occurrences...")
    issue_counts, total_rows = count_issue_ids(input_path, config)
    duplicate_ids = {value for value, count in issue_counts.items() if value and count > 1}
    blank_ids = issue_counts.get("", 0)
    if blank_ids:
        raise ValueError(f"Cannot canonicalize {blank_ids} rows with blank issue_id")

    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_output.exists():
        temp_output.unlink()

    duplicate_frames: list[pd.DataFrame] = []
    first_write = True
    original_position = 0
    unique_rows_written = 0

    print("Pass 2/3: streaming unique rows and collecting duplicate groups...")
    for chunk in iter_csv(input_path, config):
        chunk = chunk.copy()
        chunk["__original_position__"] = range(original_position, original_position + len(chunk))
        original_position += len(chunk)
        issue_ids = clean_series(chunk, issue_id_col)
        duplicate_mask = issue_ids.isin(duplicate_ids)

        if duplicate_mask.any():
            duplicate_frames.append(chunk.loc[duplicate_mask].copy())
        unique = chunk.loc[~duplicate_mask].drop(columns=["__original_position__"])
        if not unique.empty:
            enriched = enrich_rows(unique, config)
            append_csv(enriched, temp_output, first_write=first_write, config=config)
            first_write = False
            unique_rows_written += len(enriched)

    duplicate_rows = (
        pd.concat(duplicate_frames, ignore_index=True)
        if duplicate_frames
        else pd.DataFrame(columns=original_columns + ["__original_position__"])
    )

    print(f"Pass 3/3: resolving {len(duplicate_ids)} duplicate groups...")
    merged_rows: list[pd.DataFrame] = []
    group_summaries: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []

    for issue_id, group in duplicate_rows.groupby(issue_id_col, sort=True):
        selected, summary, group_conflicts = resolve_group(
            str(issue_id), group, original_columns, config
        )
        merged_rows.append(selected)
        group_summaries.append(summary)
        conflict_rows.extend(group_conflicts)

    conflicts_df = pd.DataFrame(
        conflict_rows,
        columns=[
            "issue_id",
            "column",
            "normalized_values",
            "sources_seen",
            "is_identity_column",
        ],
    )
    summaries_df = pd.DataFrame(group_summaries)
    summaries_df.to_csv(output_dir / "merged_duplicate_groups.csv", index=False)
    conflicts_df.to_csv(output_dir / "duplicate_conflicts.csv", index=False)

    substantive_conflicts = len(conflicts_df)
    identity_conflicts = int(conflicts_df.get("is_identity_column", pd.Series(dtype=bool)).astype(str).str.lower().eq("true").sum())
    if substantive_conflicts and conflict_policy == "fail":
        if temp_output.exists():
            temp_output.unlink()
        raise RuntimeError(
            f"Canonicalization stopped: {substantive_conflicts} conflicting field comparisons "
            f"across duplicate groups ({identity_conflicts} identity conflicts). "
            f"Inspect {output_dir / 'duplicate_conflicts.csv'} and rerun with "
            "--conflict-policy prefer-complete only after documenting the decision."
        )

    if merged_rows:
        merged = pd.concat(merged_rows, ignore_index=True)
        append_csv(merged, temp_output, first_write=first_write, config=config)
        first_write = False

    canonical_rows = unique_rows_written + len(merged_rows)
    expected_rows = total_rows - sum(count - 1 for count in issue_counts.values() if count > 1)
    if canonical_rows != expected_rows:
        if temp_output.exists():
            temp_output.unlink()
        raise RuntimeError(
            f"Canonical row count mismatch: observed={canonical_rows}, expected={expected_rows}"
        )

    if output_path.exists():
        output_path.unlink()
    os.replace(temp_output, output_path)

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": file_metadata(input_path, include_sha256=True),
        "output": file_metadata(output_path, include_sha256=True),
        "raw_rows": total_rows,
        "canonical_rows": canonical_rows,
        "removed_duplicate_rows": total_rows - canonical_rows,
        "duplicate_group_count": len(duplicate_ids),
        "duplicate_input_rows": len(duplicate_rows),
        "substantive_conflict_comparisons": substantive_conflicts,
        "identity_conflict_comparisons": identity_conflicts,
        "conflict_policy": conflict_policy,
        "source_priority": config.get("canonicalization", {}).get("source_priority", []),
        "canonical_columns_added": CANONICAL_COLUMNS,
        "output_sha256": file_digest(output_path, "sha256"),
    }
    write_json(manifest, output_dir / "canonicalization_manifest.json")

    print(
        f"Canonicalization completed: {total_rows} -> {canonical_rows} rows. "
        f"Output: {output_path}"
    )


if __name__ == "__main__":
    main()
