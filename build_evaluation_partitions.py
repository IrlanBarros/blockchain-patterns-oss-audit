from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from audit_common import (
    append_csv,
    clean_series,
    datetime_series,
    ensure_dir,
    file_digest,
    iter_csv,
    load_config,
    physical_column,
    read_header,
    repository_full_name,
    total_variation_distance,
    write_json,
)


def year_bucket(series: pd.Series, size: int) -> pd.Series:
    years = pd.to_numeric(series, errors="coerce")
    start = (years // size * size).astype("Int64")
    end = start + size - 1
    output = start.astype(str) + "-" + end.astype(str)
    return output.where(years.notna(), "Invalid")


def desired_counts(counter: Counter[str], target: int) -> dict[str, int]:
    total = sum(counter.values())
    if not total:
        return {}
    exact = {key: value / total * target for key, value in counter.items()}
    result = {key: int(np.floor(value)) for key, value in exact.items()}
    remainder = target - sum(result.values())
    order = sorted(exact, key=lambda key: (exact[key] - result[key], counter[key]), reverse=True)
    for key in order[:remainder]:
        result[key] += 1
    return result


def choose_groups_for_partition(
    groups: pd.DataFrame,
    available_hashes: set[str],
    target_size: int,
    global_strata: Counter[str],
    seed: int,
) -> list[str]:
    rng = np.random.default_rng(seed)
    desired = desired_counts(global_strata, target_size)
    by_stratum: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in groups.itertuples(index=False):
        if row.raw_text_sha256 in available_hashes:
            by_stratum[str(row.stratum)].append((str(row.raw_text_sha256), int(row.group_size)))
    for values in by_stratum.values():
        rng.shuffle(values)
        values.sort(key=lambda pair: pair[1])

    selected: list[str] = []
    selected_set: set[str] = set()
    selected_rows = 0

    for stratum, target_rows in sorted(desired.items(), key=lambda item: item[1], reverse=True):
        current = 0
        for hash_value, group_size in by_stratum.get(stratum, []):
            if hash_value in selected_set or hash_value not in available_hashes:
                continue
            if selected_rows + group_size > target_size:
                continue
            if current + group_size > target_rows and group_size > 1:
                continue
            selected.append(hash_value)
            selected_set.add(hash_value)
            selected_rows += group_size
            current += group_size
            if current >= target_rows or selected_rows >= target_size:
                break
        if selected_rows >= target_size:
            break

    if selected_rows < target_size:
        remaining = groups[
            groups["raw_text_sha256"].isin(available_hashes - selected_set)
        ].copy()
        remaining["random"] = rng.random(len(remaining))
        remaining = remaining.sort_values(["group_size", "random"])
        for row in remaining.itertuples(index=False):
            group_size = int(row.group_size)
            if selected_rows + group_size > target_size:
                continue
            selected.append(str(row.raw_text_sha256))
            selected_set.add(str(row.raw_text_sha256))
            selected_rows += group_size
            if selected_rows == target_size:
                break

    if selected_rows != target_size:
        raise RuntimeError(
            f"Could not build an exact partition of {target_size} rows; selected {selected_rows}. "
            "This usually means a large repeated-text group prevents an exact fit."
        )
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build development, validation, and holdout partitions without repeated-text leakage."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--partition-size", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_dir(args.output_dir)
    input_path = Path(args.input)
    header = read_header(input_path, config)
    required_extra = ["raw_text_sha256", "repository_full_name", "repository_category_canonical"]
    missing = [column for column in required_extra if column not in header]
    if missing:
        raise ValueError(
            "Canonical corpus is required. Missing columns: " + ", ".join(missing)
        )

    partition_cfg = config.get("partitions", {})
    names = [str(value) for value in partition_cfg.get("names", ["development", "validation", "holdout"])]
    target_size = args.partition_size or int(partition_cfg.get("partition_size", 1835))
    seed = args.seed if args.seed is not None else int(partition_cfg.get("seed", 73))
    bucket_size = int(partition_cfg.get("year_bucket_size", 3))

    for name in names:
        path = output_dir / f"{name}.csv"
        if path.exists() and not args.overwrite:
            raise FileExistsError(f"Partition already exists: {path}. Use --overwrite intentionally.")
        if path.exists():
            path.unlink()

    metadata_rows: list[pd.DataFrame] = []
    usecols = [
        physical_column(config, "issue_id"),
        physical_column(config, "owner"),
        physical_column(config, "repository"),
        physical_column(config, "type"),
        physical_column(config, "data_source"),
        physical_column(config, "created_at"),
        "repository_full_name",
        "repository_category_canonical",
        "raw_text_sha256",
    ]
    usecols = list(dict.fromkeys(usecols))
    for chunk in iter_csv(input_path, config, usecols=usecols):
        created = datetime_series(chunk, physical_column(config, "created_at"))
        year = created.dt.year.astype("Int64")
        part = pd.DataFrame(
            {
                "issue_id": clean_series(chunk, physical_column(config, "issue_id")),
                "repository_full_name": clean_series(chunk, "repository_full_name"),
                "repository_category_canonical": clean_series(chunk, "repository_category_canonical").replace("", "Unclassified"),
                "type": clean_series(chunk, physical_column(config, "type")).replace("", "Unknown"),
                "data_source": clean_series(chunk, physical_column(config, "data_source")).replace("", "Unknown"),
                "year": year.astype(str).replace("<NA>", "Invalid"),
                "year_bucket": year_bucket(year, bucket_size),
                "raw_text_sha256": clean_series(chunk, "raw_text_sha256"),
            }
        )
        part["stratum"] = (
            part["repository_category_canonical"]
            + "\u241f"
            + part["type"]
            + "\u241f"
            + part["data_source"]
            + "\u241f"
            + part["year_bucket"]
        )
        metadata_rows.append(part)

    metadata = pd.concat(metadata_rows, ignore_index=True)
    if metadata["issue_id"].duplicated().any():
        raise ValueError("Canonical corpus still contains duplicate issue_id values")

    group_records: list[dict[str, Any]] = []
    for hash_value, group in metadata.groupby("raw_text_sha256", sort=False):
        mode_stratum = group["stratum"].mode()
        stratum = str(mode_stratum.iloc[0]) if not mode_stratum.empty else str(group.iloc[0]["stratum"])
        group_records.append(
            {
                "raw_text_sha256": str(hash_value),
                "group_size": len(group),
                "stratum": stratum,
            }
        )
    groups = pd.DataFrame(group_records)
    global_strata = Counter(metadata["stratum"].tolist())
    available_hashes = set(groups["raw_text_sha256"].tolist())
    partition_hashes: dict[str, list[str]] = {}

    for index, name in enumerate(names):
        selected = choose_groups_for_partition(
            groups,
            available_hashes,
            target_size,
            global_strata,
            seed + index,
        )
        partition_hashes[name] = selected
        available_hashes.difference_update(selected)

    hash_to_partition: dict[str, str] = {}
    for name, hashes in partition_hashes.items():
        for value in hashes:
            if value in hash_to_partition:
                raise RuntimeError("Repeated-text group assigned to multiple partitions")
            hash_to_partition[value] = name

    first_write = {name: True for name in names}
    row_counts = Counter()
    for chunk in iter_csv(input_path, config):
        assignments = clean_series(chunk, "raw_text_sha256").map(hash_to_partition)
        for name in names:
            selected = chunk.loc[assignments.eq(name)]
            if selected.empty:
                continue
            append_csv(
                selected,
                output_dir / f"{name}.csv",
                first_write=first_write[name],
                config=config,
            )
            first_write[name] = False
            row_counts[name] += len(selected)

    for name in names:
        if row_counts[name] != target_size:
            raise RuntimeError(f"Partition {name} has {row_counts[name]} rows; expected {target_size}")

    global_distributions = {
        dimension: Counter(metadata[dimension].tolist())
        for dimension in [
            "repository_category_canonical",
            "type",
            "data_source",
            "year",
        ]
    }
    profile_rows: list[dict[str, Any]] = []
    drift_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}

    for name in names:
        selected_metadata = metadata[
            metadata["raw_text_sha256"].isin(partition_hashes[name])
        ]
        repo_counts = Counter(selected_metadata["repository_full_name"].tolist())
        profile_rows.append(
            {
                "partition": name,
                "rows": len(selected_metadata),
                "unique_repositories": len(repo_counts),
                "top_repository_percent": repo_counts.most_common(1)[0][1] / len(selected_metadata) * 100,
                "unique_raw_text_hashes": selected_metadata["raw_text_sha256"].nunique(),
                "sha256": file_digest(output_dir / f"{name}.csv", "sha256"),
            }
        )
        for dimension, reference in global_distributions.items():
            observed = Counter(selected_metadata[dimension].tolist())
            drift_rows.append(
                {
                    "partition": name,
                    "dimension": dimension,
                    "total_variation_distance": total_variation_distance(reference, observed),
                }
            )
        for hash_value in selected_metadata["raw_text_sha256"].unique():
            if hash_value in seen_hashes:
                overlap_rows.append(
                    {
                        "raw_text_sha256": hash_value,
                        "first_partition": seen_hashes[hash_value],
                        "second_partition": name,
                    }
                )
            seen_hashes[hash_value] = name

    pd.DataFrame(profile_rows).to_csv(output_dir / "partition_profile.csv", index=False)
    pd.DataFrame(drift_rows).to_csv(output_dir / "partition_drift_metrics.csv", index=False)
    pd.DataFrame(
        overlap_rows,
        columns=["raw_text_sha256", "first_partition", "second_partition"],
    ).to_csv(output_dir / "raw_text_hash_overlap.csv", index=False)

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path.resolve()),
        "input_sha256": file_digest(input_path, "sha256"),
        "partition_names": names,
        "partition_size": target_size,
        "seed": seed,
        "grouping_rule": "All identical raw_text_sha256 values remain in the same evaluation partition.",
        "assigned_rows": dict(row_counts),
        "raw_text_hash_overlap_count": len(overlap_rows),
    }
    write_json(manifest, output_dir / "evaluation_partition_manifest.json")
    print(f"Evaluation partitions completed: {dict(row_counts)}. Outputs: {output_dir}")


if __name__ == "__main__":
    main()
