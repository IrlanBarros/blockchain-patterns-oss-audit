from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

from audit_common import (
    clean_series,
    ensure_dir,
    file_metadata,
    iter_csv,
    load_config,
    physical_column,
    read_header,
    require_columns,
    required_column_map,
    write_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the local Web3BlockSet CSV and generate a reproducible fingerprint."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-mode", choices=["full", "subset"], default="full")
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_dir(args.output_dir)
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    header = read_header(input_path, config)
    required = required_column_map(config)
    require_columns(header, required)

    issue_id_col = physical_column(config, "issue_id")
    owner_col = physical_column(config, "owner")
    repository_col = physical_column(config, "repository")
    issue_number_col = physical_column(config, "issue_number")

    rows = 0
    issue_ids: Counter[str] = Counter()
    github_keys: Counter[str] = Counter()
    exact_hashes: Counter[int] = Counter()

    for chunk in iter_csv(input_path, config):
        rows += len(chunk)
        issue_id = clean_series(chunk, issue_id_col)
        issue_ids.update(issue_id.tolist())
        keys = (
            clean_series(chunk, owner_col)
            + "\u241f"
            + clean_series(chunk, repository_col)
            + "\u241f"
            + clean_series(chunk, issue_number_col)
        )
        github_keys.update(keys.tolist())
        hashes = pd.util.hash_pandas_object(chunk.fillna("").astype(str), index=False)
        exact_hashes.update(int(value) for value in hashes.tolist())

    expected = int(config.get("zenodo", {}).get("expected_total_records", 0) or 0)
    duplicate_issue_rows = sum(count - 1 for value, count in issue_ids.items() if value and count > 1)
    duplicate_github_rows = sum(count - 1 for value, count in github_keys.items() if value.strip("\u241f") and count > 1)
    exact_duplicate_rows = sum(count - 1 for count in exact_hashes.values() if count > 1)
    blank_issue_ids = issue_ids.get("", 0)

    checks = [
        {
            "check": "required_schema",
            "status": "pass",
            "observed": len(header),
            "expected": len(required),
            "notes": "All configured research fields are present.",
        },
        {
            "check": "row_count",
            "status": "pass" if args.dataset_mode == "subset" or not expected or rows == expected else "warning",
            "observed": rows,
            "expected": expected,
            "notes": "Subset mode does not enforce the Zenodo total." if args.dataset_mode == "subset" else "",
        },
        {
            "check": "blank_issue_id",
            "status": "pass" if blank_issue_ids == 0 else "error",
            "observed": blank_issue_ids,
            "expected": 0,
            "notes": "Canonicalization requires a non-empty issue_id.",
        },
        {
            "check": "duplicate_issue_id_rows_after_first",
            "status": "warning" if duplicate_issue_rows else "pass",
            "observed": duplicate_issue_rows,
            "expected": 0,
            "notes": "Cross-source duplicates are resolved by canonicalize_dataset.py.",
        },
        {
            "check": "duplicate_owner_repository_number_rows_after_first",
            "status": "warning" if duplicate_github_rows else "pass",
            "observed": duplicate_github_rows,
            "expected": 0,
            "notes": "Should agree with duplicate issue_id groups after canonicalization.",
        },
        {
            "check": "exact_duplicate_rows_after_first",
            "status": "warning" if exact_duplicate_rows else "pass",
            "observed": exact_duplicate_rows,
            "expected": 0,
            "notes": "Exact duplicate rows are not silently removed.",
        },
    ]

    pd.DataFrame(checks).to_csv(output_dir / "verification_checks.csv", index=False)
    write_json(
        {
            "project": config.get("project", {}),
            "zenodo": config.get("zenodo", {}),
            "dataset_mode": args.dataset_mode,
            "local_csv": file_metadata(input_path, include_sha256=True),
            "rows": rows,
            "columns": header,
            "required_column_mapping": required,
            "duplicate_issue_id_rows_after_first": duplicate_issue_rows,
            "duplicate_owner_repository_number_rows_after_first": duplicate_github_rows,
            "exact_duplicate_rows_after_first": exact_duplicate_rows,
        },
        output_dir / "dataset_fingerprint.json",
    )
    print(f"Dataset verification completed: {rows} rows. Outputs: {output_dir}")


if __name__ == "__main__":
    main()
