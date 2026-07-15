from __future__ import annotations

import argparse
import glob
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from audit_common import (
    clean_series,
    datetime_series,
    ensure_dir,
    iter_csv,
    load_config,
    physical_column,
    read_header,
    repository_full_name,
    require_columns,
    required_column_map,
    total_variation_distance,
)

SLICE_NAME = re.compile(r"^slice_\d{4,}\.csv$")


def profile_file(path: str, config: dict, header: list[str]) -> dict[str, object]:
    owner_col = physical_column(config, "owner")
    repo_col = physical_column(config, "repository")
    category_col = (
        "repository_category_canonical"
        if "repository_category_canonical" in header
        else physical_column(config, "repository_category")
    )
    source_col = physical_column(config, "data_source")
    type_col = physical_column(config, "type")
    created_col = physical_column(config, "created_at")
    raw_col = physical_column(config, "raw_text")

    rows = 0
    repositories: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    types: Counter[str] = Counter()
    years: Counter[str] = Counter()
    text_lengths: list[int] = []
    earliest = None
    latest = None

    for chunk in iter_csv(path, config):
        rows += len(chunk)
        repo = repository_full_name(chunk[owner_col], chunk[repo_col])
        category = clean_series(chunk, category_col).replace("", "Unclassified")
        source = clean_series(chunk, source_col).replace("", "Unknown")
        item_type = clean_series(chunk, type_col).replace("", "Unknown")
        created = datetime_series(chunk, created_col)
        year = created.dt.strftime("%Y").fillna("Invalid")
        repositories.update(repo.tolist())
        categories.update(category.tolist())
        sources.update(source.tolist())
        types.update(item_type.tolist())
        years.update(year.tolist())
        text_lengths.extend(clean_series(chunk, raw_col).str.len().astype(int).tolist())
        valid = created.dropna()
        if not valid.empty:
            earliest = valid.min() if earliest is None or valid.min() < earliest else earliest
            latest = valid.max() if latest is None or valid.max() > latest else latest

    array = np.asarray(text_lengths, dtype=np.int64)
    top_repo_count = repositories.most_common(1)[0][1] if repositories else 0
    return {
        "rows": rows,
        "unique_repositories": len(repositories),
        "unique_categories": len(categories),
        "unique_sources": len(sources),
        "unique_types": len(types),
        "earliest_created_at": earliest.isoformat() if earliest is not None else "",
        "latest_created_at": latest.isoformat() if latest is not None else "",
        "median_text_chars": float(np.median(array)) if array.size else None,
        "p95_text_chars": float(np.percentile(array, 95)) if array.size else None,
        "top_repository_percent": top_repo_count / rows * 100 if rows else 0,
        "repositories": repositories,
        "categories": categories,
        "sources": sources,
        "types": types,
        "years": years,
    }


def load_master(path: str, config: dict, header: list[str]) -> tuple[set[str], dict[str, Counter[str]], int]:
    issue_id_col = physical_column(config, "issue_id")
    category_col = (
        "repository_category_canonical"
        if "repository_category_canonical" in header
        else physical_column(config, "repository_category")
    )
    source_col = physical_column(config, "data_source")
    type_col = physical_column(config, "type")
    created_col = physical_column(config, "created_at")
    keys: set[str] = set()
    distributions = {
        "repository_category": Counter(),
        "data_source": Counter(),
        "type": Counter(),
        "year": Counter(),
    }
    rows = 0
    for chunk in iter_csv(path, config):
        rows += len(chunk)
        keys.update(clean_series(chunk, issue_id_col).tolist())
        distributions["repository_category"].update(
            clean_series(chunk, category_col).replace("", "Unclassified").tolist()
        )
        distributions["data_source"].update(
            clean_series(chunk, source_col).replace("", "Unknown").tolist()
        )
        distributions["type"].update(
            clean_series(chunk, type_col).replace("", "Unknown").tolist()
        )
        distributions["year"].update(
            datetime_series(chunk, created_col).dt.strftime("%Y").fillna("Invalid").tolist()
        )
    return keys, distributions, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate operational slices against the canonical master corpus.")
    parser.add_argument("--master", required=True)
    parser.add_argument("--slices", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--coverage-mode", choices=["full", "subset"], default="full")
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_dir(args.output_dir)
    required = required_column_map(config)
    master_header = read_header(args.master, config)
    require_columns(master_header, required)

    matched = sorted(glob.glob(args.slices))
    slice_paths = [path for path in matched if SLICE_NAME.match(Path(path).name)]
    ignored = [path for path in matched if path not in slice_paths]
    if not slice_paths:
        raise FileNotFoundError(f"No slice_####.csv file matched: {args.slices}")

    expected_size = int(config.get("integrity", {}).get("expected_slice_size", 1835))
    allow_smaller_last = bool(config.get("integrity", {}).get("allow_smaller_last_slice", True))
    issue_id_col = physical_column(config, "issue_id")

    master_keys, master_distributions, master_rows = load_master(args.master, config, master_header)
    all_seen: dict[str, str] = {}
    union_keys: set[str] = set()
    overlaps: list[dict[str, str]] = []
    extras: set[str] = set()
    profiles: list[dict[str, object]] = []
    drifts: list[dict[str, object]] = []
    schema_mismatches = 0
    duplicate_within_total = 0
    invalid_size_count = 0
    total_slice_rows = 0

    for index, slice_path in enumerate(slice_paths):
        path = Path(slice_path)
        header = read_header(path, config)
        require_columns(header, required)
        schema_match = header == master_header
        schema_mismatches += int(not schema_match)
        profile = profile_file(slice_path, config, header)
        total_slice_rows += int(profile["rows"])
        is_last = index == len(slice_paths) - 1
        size_valid = int(profile["rows"]) == expected_size or (
            is_last and allow_smaller_last and 0 < int(profile["rows"]) <= expected_size
        )
        invalid_size_count += int(not size_valid)

        slice_keys: list[str] = []
        for chunk in iter_csv(slice_path, config, usecols=[issue_id_col]):
            slice_keys.extend(clean_series(chunk, issue_id_col).tolist())
        counts = Counter(slice_keys)
        duplicate_within = sum(count - 1 for count in counts.values() if count > 1)
        duplicate_within_total += duplicate_within
        unique_keys = set(slice_keys)

        for key in unique_keys:
            if key in all_seen:
                overlaps.append(
                    {"issue_id": key, "first_slice": all_seen[key], "second_slice": path.name}
                )
            else:
                all_seen[key] = path.name
        union_keys.update(unique_keys)
        extras.update(unique_keys - master_keys)

        profiles.append(
            {
                "slice": path.name,
                "rows": profile["rows"],
                "unique_issue_ids": len(unique_keys),
                "duplicate_issue_ids_within_after_first": duplicate_within,
                "schema_exactly_matches_master": schema_match,
                "size_valid": size_valid,
                "unique_repositories": profile["unique_repositories"],
                "unique_categories": profile["unique_categories"],
                "unique_sources": profile["unique_sources"],
                "unique_types": profile["unique_types"],
                "earliest_created_at": profile["earliest_created_at"],
                "latest_created_at": profile["latest_created_at"],
                "median_text_chars": profile["median_text_chars"],
                "p95_text_chars": profile["p95_text_chars"],
                "top_repository_percent": profile["top_repository_percent"],
            }
        )
        observed = {
            "repository_category": profile["categories"],
            "data_source": profile["sources"],
            "type": profile["types"],
            "year": profile["years"],
        }
        for dimension in master_distributions:
            drifts.append(
                {
                    "slice": path.name,
                    "dimension": dimension,
                    "total_variation_distance": total_variation_distance(
                        master_distributions[dimension], observed[dimension]
                    ),
                }
            )

    missing = master_keys - union_keys
    checks = [
        {"metric": "master_rows", "value": master_rows, "status": "info", "notes": ""},
        {"metric": "master_unique_issue_ids", "value": len(master_keys), "status": "info", "notes": ""},
        {"metric": "slice_file_count", "value": len(slice_paths), "status": "info", "notes": ""},
        {"metric": "ignored_glob_matches", "value": len(ignored), "status": "info", "notes": "Only slice_####.csv files are validated."},
        {"metric": "slice_total_rows", "value": total_slice_rows, "status": "info", "notes": ""},
        {"metric": "slice_union_unique_issue_ids", "value": len(union_keys), "status": "info", "notes": ""},
        {"metric": "schema_mismatch_files", "value": schema_mismatches, "status": "pass" if not schema_mismatches else "error", "notes": ""},
        {"metric": "invalid_slice_sizes", "value": invalid_size_count, "status": "pass" if not invalid_size_count else "warning", "notes": f"Expected {expected_size}; final slice may be smaller."},
        {"metric": "duplicate_issue_ids_within_slices_after_first", "value": duplicate_within_total, "status": "pass" if not duplicate_within_total else "error", "notes": ""},
        {"metric": "issue_ids_overlapping_between_slices", "value": len(overlaps), "status": "pass" if not overlaps else "error", "notes": ""},
        {"metric": "issue_ids_not_found_in_master", "value": len(extras), "status": "pass" if not extras else "error", "notes": ""},
        {"metric": "master_issue_ids_missing_from_slices", "value": len(missing), "status": "pass" if args.coverage_mode == "subset" or not missing else "error", "notes": f"Coverage mode: {args.coverage_mode}"},
    ]

    pd.DataFrame(checks).to_csv(output_dir / "validation_summary.csv", index=False)
    pd.DataFrame(profiles).to_csv(output_dir / "slice_profile.csv", index=False)
    pd.DataFrame(drifts).to_csv(output_dir / "slice_drift_metrics.csv", index=False)
    pd.DataFrame(overlaps, columns=["issue_id", "first_slice", "second_slice"]).to_csv(
        output_dir / "overlap_between_slices.csv", index=False
    )
    pd.DataFrame({"issue_id": sorted(missing)}).to_csv(output_dir / "missing_from_slices.csv", index=False)
    pd.DataFrame({"issue_id": sorted(extras)}).to_csv(output_dir / "extra_in_slices.csv", index=False)

    print(f"Slice validation completed: {len(slice_paths)} files, {total_slice_rows} rows. Outputs: {output_dir}")


if __name__ == "__main__":
    main()
