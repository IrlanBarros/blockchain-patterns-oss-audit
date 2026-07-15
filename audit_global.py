from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from audit_common import (
    clean_series,
    counter_to_distribution,
    datetime_series,
    ensure_dir,
    file_metadata,
    hhi,
    iter_csv,
    load_config,
    physical_column,
    read_header,
    repository_full_name,
    require_columns,
    required_column_map,
    write_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile the canonical Web3BlockSet corpus.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_dir(args.output_dir)
    input_path = Path(args.input)
    header = read_header(input_path, config)
    require_columns(header, required_column_map(config))

    owner_col = physical_column(config, "owner")
    repo_col = physical_column(config, "repository")
    category_col = (
        "repository_category_canonical"
        if "repository_category_canonical" in header
        else physical_column(config, "repository_category")
    )
    source_col = physical_column(config, "data_source")
    type_col = physical_column(config, "type")
    state_col = physical_column(config, "state")
    created_col = physical_column(config, "created_at")

    text_logicals = [
        "issue_title",
        "issue_body",
        "concatenated_comments",
        "raw_text",
        "clean_text",
        "stemmed_text",
    ]
    text_columns = {logical: physical_column(config, logical) for logical in text_logicals}

    rows = 0
    repositories: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    types: Counter[str] = Counter()
    states: Counter[str] = Counter()
    years: Counter[str] = Counter()
    months: Counter[str] = Counter()
    category_by_type: Counter[tuple[str, str]] = Counter()
    category_by_source: Counter[tuple[str, str]] = Counter()
    type_by_year: Counter[tuple[str, str]] = Counter()
    completeness: Counter[str] = Counter()
    text_lengths: dict[str, list[int]] = {logical: [] for logical in text_logicals}
    earliest = None
    latest = None

    for chunk in iter_csv(input_path, config):
        rows += len(chunk)
        full_name = repository_full_name(chunk[owner_col], chunk[repo_col])
        category = clean_series(chunk, category_col).replace("", "Unclassified")
        source = clean_series(chunk, source_col).replace("", "Unknown")
        item_type = clean_series(chunk, type_col).replace("", "Unknown")
        state = clean_series(chunk, state_col).replace("", "Unknown")
        created = datetime_series(chunk, created_col)
        year = created.dt.strftime("%Y").fillna("Invalid")
        month = created.dt.strftime("%Y-%m").fillna("Invalid")

        repositories.update(full_name.tolist())
        categories.update(category.tolist())
        sources.update(source.tolist())
        types.update(item_type.tolist())
        states.update(state.tolist())
        years.update(year.tolist())
        months.update(month.tolist())
        category_by_type.update(zip(category.tolist(), item_type.tolist()))
        category_by_source.update(zip(category.tolist(), source.tolist()))
        type_by_year.update(zip(item_type.tolist(), year.tolist()))

        valid_dates = created.dropna()
        if not valid_dates.empty:
            chunk_min = valid_dates.min()
            chunk_max = valid_dates.max()
            earliest = chunk_min if earliest is None or chunk_min < earliest else earliest
            latest = chunk_max if latest is None or chunk_max > latest else latest

        for logical, column in text_columns.items():
            text = clean_series(chunk, column)
            completeness[f"{logical}_empty"] += int(text.eq("").sum())
            text_lengths[logical].extend(text.str.len().astype(int).tolist())

    counter_to_distribution(repositories, "repository_full_name", rows).to_csv(
        output_dir / "repository_distribution.csv", index=False
    )
    counter_to_distribution(categories, "repository_category", rows).to_csv(
        output_dir / "repository_category_distribution.csv", index=False
    )
    counter_to_distribution(sources, "data_source", rows).to_csv(
        output_dir / "data_source_distribution.csv", index=False
    )
    counter_to_distribution(types, "type", rows).to_csv(
        output_dir / "type_distribution.csv", index=False
    )
    counter_to_distribution(states, "state", rows).to_csv(
        output_dir / "state_distribution.csv", index=False
    )
    counter_to_distribution(years, "year", rows).to_csv(
        output_dir / "year_distribution.csv", index=False
    )
    counter_to_distribution(months, "month", rows).to_csv(
        output_dir / "month_distribution.csv", index=False
    )

    pd.DataFrame(
        [(category, item_type, count) for (category, item_type), count in category_by_type.items()],
        columns=["repository_category", "type", "count"],
    ).to_csv(output_dir / "category_by_type.csv", index=False)
    pd.DataFrame(
        [(category, source, count) for (category, source), count in category_by_source.items()],
        columns=["repository_category", "data_source", "count"],
    ).to_csv(output_dir / "category_by_source.csv", index=False)
    pd.DataFrame(
        [(item_type, year, count) for (item_type, year), count in type_by_year.items()],
        columns=["type", "year", "count"],
    ).to_csv(output_dir / "type_by_year.csv", index=False)

    completeness_rows = []
    for logical in text_logicals:
        empty = completeness[f"{logical}_empty"]
        completeness_rows.append(
            {
                "field": logical,
                "empty_count": empty,
                "empty_percent": empty / rows * 100 if rows else 0,
            }
        )
    pd.DataFrame(completeness_rows).to_csv(output_dir / "text_completeness.csv", index=False)

    length_rows: list[dict[str, object]] = []
    thresholds = config.get("integrity", {}).get("text_thresholds", [])
    for logical, values in text_lengths.items():
        array = np.asarray(values, dtype=np.int64)
        if not array.size:
            continue
        base = {
            "field": logical,
            "count": int(array.size),
            "mean": float(np.mean(array)),
            "median": float(np.median(array)),
            "p90": float(np.percentile(array, 90)),
            "p95": float(np.percentile(array, 95)),
            "p99": float(np.percentile(array, 99)),
            "max": int(np.max(array)),
        }
        for threshold in thresholds:
            base[f"above_{int(threshold)}"] = int((array > int(threshold)).sum())
            base[f"above_{int(threshold)}_percent"] = float((array > int(threshold)).mean() * 100)
        length_rows.append(base)
    pd.DataFrame(length_rows).to_csv(output_dir / "text_length_summary.csv", index=False)

    concentration = [
        {"metric": "repository_hhi", "value": hhi(repositories)},
        {"metric": "top_1_repository_percent", "value": repositories.most_common(1)[0][1] / rows * 100 if rows else 0},
        {"metric": "top_5_repositories_percent", "value": sum(v for _, v in repositories.most_common(5)) / rows * 100 if rows else 0},
        {"metric": "top_10_repositories_percent", "value": sum(v for _, v in repositories.most_common(10)) / rows * 100 if rows else 0},
        {"metric": "top_20_repositories_percent", "value": sum(v for _, v in repositories.most_common(20)) / rows * 100 if rows else 0},
    ]
    pd.DataFrame(concentration).to_csv(output_dir / "concentration_metrics.csv", index=False)

    pd.DataFrame(
        [
            {"metric": "total_rows", "value": rows},
            {"metric": "unique_repositories", "value": len(repositories)},
            {"metric": "unique_categories", "value": len(categories)},
            {"metric": "unique_sources", "value": len(sources)},
            {"metric": "unique_types", "value": len(types)},
            {"metric": "earliest_created_at", "value": earliest.isoformat() if earliest is not None else ""},
            {"metric": "latest_created_at", "value": latest.isoformat() if latest is not None else ""},
        ]
    ).to_csv(output_dir / "audit_summary.csv", index=False)

    write_json(
        {
            "input": file_metadata(input_path, include_sha256=True),
            "rows": rows,
            "category_field_used": category_col,
            "repository_identity": "owner/repository",
            "text_fields_profiled": text_columns,
        },
        output_dir / "audit_metadata.json",
    )
    print(f"Global profiling completed: {rows} rows. Outputs: {output_dir}")


if __name__ == "__main__":
    main()
