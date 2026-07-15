from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

from audit_common import (
    clean_series,
    ensure_dir,
    iter_csv,
    load_config,
    physical_column,
    read_header,
    require_columns,
    required_column_map,
)

CANONICAL_REQUIRED = [
    "repository_full_name",
    "canonical_issue_key",
    "repository_category_canonical",
    "raw_text_sha256",
    "data_sources_seen",
    "duplicate_group_size",
    "duplicate_resolution",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the integrity of the canonical corpus.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_dir(args.output_dir)
    input_path = Path(args.input)
    header = read_header(input_path, config)
    require_columns(header, required_column_map(config))
    missing_canonical = [column for column in CANONICAL_REQUIRED if column not in header]
    if missing_canonical:
        raise ValueError("Missing canonical columns: " + ", ".join(missing_canonical))

    issue_id_col = physical_column(config, "issue_id")
    owner_col = physical_column(config, "owner")
    repository_col = physical_column(config, "repository")
    issue_number_col = physical_column(config, "issue_number")

    issue_ids: Counter[str] = Counter()
    github_keys: Counter[str] = Counter()
    text_hashes: Counter[str] = Counter()
    exact_rows: Counter[int] = Counter()
    missing_counts: Counter[str] = Counter()
    total_rows = 0

    for chunk in iter_csv(input_path, config):
        total_rows += len(chunk)
        issue_id = clean_series(chunk, issue_id_col)
        issue_ids.update(issue_id.tolist())
        github_key = (
            clean_series(chunk, owner_col)
            + "\u241f"
            + clean_series(chunk, repository_col)
            + "\u241f"
            + clean_series(chunk, issue_number_col)
        )
        github_keys.update(github_key.tolist())
        text_hashes.update(clean_series(chunk, "raw_text_sha256").tolist())
        row_hash = pd.util.hash_pandas_object(chunk.fillna("").astype(str), index=False)
        exact_rows.update(int(value) for value in row_hash.tolist())
        for column in CANONICAL_REQUIRED:
            missing_counts[column] += int(clean_series(chunk, column).eq("").sum())

    duplicate_issue_rows = sum(count - 1 for value, count in issue_ids.items() if value and count > 1)
    duplicate_github_rows = sum(count - 1 for value, count in github_keys.items() if value.strip("\u241f") and count > 1)
    exact_duplicate_rows = sum(count - 1 for count in exact_rows.values() if count > 1)
    repeated_text_rows = sum(count for value, count in text_hashes.items() if value and count > 1)
    repeated_text_groups = sum(1 for value, count in text_hashes.items() if value and count > 1)

    checks = [
        {"metric": "total_rows", "value": total_rows, "status": "info", "notes": ""},
        {"metric": "duplicate_issue_id_rows_after_first", "value": duplicate_issue_rows, "status": "pass" if not duplicate_issue_rows else "error", "notes": "Canonical corpus must have one row per issue_id."},
        {"metric": "duplicate_owner_repository_number_rows_after_first", "value": duplicate_github_rows, "status": "pass" if not duplicate_github_rows else "error", "notes": "GitHub identity must also be unique."},
        {"metric": "exact_duplicate_rows_after_first", "value": exact_duplicate_rows, "status": "pass" if not exact_duplicate_rows else "error", "notes": ""},
        {"metric": "repeated_raw_text_groups", "value": repeated_text_groups, "status": "info", "notes": "Legitimate templates may repeat; evaluation partitions group by raw_text_sha256."},
        {"metric": "rows_in_repeated_raw_text_groups", "value": repeated_text_rows, "status": "info", "notes": ""},
    ]
    for column in CANONICAL_REQUIRED:
        checks.append(
            {
                "metric": f"missing_{column}",
                "value": missing_counts[column],
                "status": "pass" if not missing_counts[column] else "error",
                "notes": "",
            }
        )
    pd.DataFrame(checks).to_csv(output_dir / "canonical_integrity_summary.csv", index=False)

    repeated_frame = pd.DataFrame(
        [
            {"raw_text_sha256": value, "count": count}
            for value, count in text_hashes.items()
            if value and count > 1
        ],
        columns=["raw_text_sha256", "count"],
    )
    if not repeated_frame.empty:
        repeated_frame = repeated_frame.sort_values("count", ascending=False)
    repeated_frame.to_csv(output_dir / "repeated_text_groups.csv", index=False)

    pd.DataFrame(
        [
            {"issue_id": value, "count": count, "exception": "duplicate_issue_id"}
            for value, count in issue_ids.items()
            if value and count > 1
        ]
        + [
            {"issue_id": value, "count": count, "exception": "duplicate_github_identity"}
            for value, count in github_keys.items()
            if value.strip("\u241f") and count > 1
        ],
        columns=["issue_id", "count", "exception"],
    ).to_csv(output_dir / "canonical_key_exceptions.csv", index=False)

    print(f"Canonical integrity audit completed: {total_rows} rows. Outputs: {output_dir}")


if __name__ == "__main__":
    main()
