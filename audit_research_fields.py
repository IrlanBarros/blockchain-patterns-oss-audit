from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from audit_common import (
    append_csv,
    clean_series,
    counter_to_distribution,
    datetime_series,
    ensure_dir,
    infer_item_kind,
    iter_csv,
    load_config,
    numeric_series,
    parse_listish,
    physical_column,
    quantile_rows,
    read_header,
    repository_full_name,
    require_columns,
    required_column_map,
)


def add_exception_rows(
    output_rows: list[dict[str, Any]],
    frame: pd.DataFrame,
    mask: pd.Series,
    exception: str,
    details: pd.Series | str,
) -> None:
    if not mask.any():
        return
    selected = frame.loc[mask]
    if isinstance(details, pd.Series):
        detail_values = details.loc[mask].astype(str).tolist()
    else:
        detail_values = [details] * len(selected)
    for (_, row), detail in zip(selected.iterrows(), detail_values):
        output_rows.append(
            {
                "issue_id": row["__issue_id__"],
                "repository_full_name": row["__repository_full_name__"],
                "issue_number": row["__issue_number__"],
                "exception": exception,
                "details": detail,
            }
        )


def summarize_numeric(values: list[float], metric: str, percentiles: list[int]) -> list[dict[str, Any]]:
    return quantile_rows(values, metric, percentiles)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit fields needed for RQ1, RQ2, and RQ3."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_dir(args.output_dir)
    input_path = Path(args.input)
    header = read_header(input_path, config)
    require_columns(header, required_column_map(config))

    cols = {name: physical_column(config, name) for name in config.get("columns", {})}
    category_col = (
        "repository_category_canonical"
        if "repository_category_canonical" in header
        else cols["repository_category"]
    )

    type_counter: Counter[str] = Counter()
    state_counter: Counter[str] = Counter()
    locked_counter: Counter[str] = Counter()
    label_counter: Counter[str] = Counter()
    labels_per_item: list[float] = []
    comment_authors_per_item: list[float] = []
    resolution_days: list[float] = []
    comments_total_values: list[float] = []
    comments_filtered_values: list[float] = []
    commits_values: list[float] = []
    resolution_by_type: dict[str, list[float]] = defaultdict(list)
    comments_by_type: dict[str, list[float]] = defaultdict(list)
    field_empty: Counter[str] = Counter()
    exception_counts: Counter[str] = Counter()
    total_rows = 0
    exception_path = output_dir / "research_field_exceptions.csv"
    first_exception_write = True

    text_component_rows: Counter[str] = Counter()

    for chunk in iter_csv(input_path, config):
        total_rows += len(chunk)
        chunk = chunk.copy()
        chunk["__issue_id__"] = clean_series(chunk, cols["issue_id"])
        chunk["__issue_number__"] = clean_series(chunk, cols["issue_number"])
        chunk["__repository_full_name__"] = repository_full_name(
            chunk[cols["owner"]], chunk[cols["repository"]]
        )

        raw_type = clean_series(chunk, cols["type"])
        item_kind = raw_type.map(lambda value: infer_item_kind(value, config))
        state = clean_series(chunk, cols["state"]).str.lower().replace("", "unknown")
        type_counter.update(item_kind.tolist())
        state_counter.update(state.tolist())
        locked = clean_series(chunk, cols["locked"]).str.lower().replace("", "unknown")
        locked_counter.update(locked.tolist())

        created_raw = clean_series(chunk, cols["created_at"])
        updated_raw = clean_series(chunk, cols["updated_at"])
        closed_raw = clean_series(chunk, cols["closed_at"])
        created = datetime_series(chunk, cols["created_at"])
        updated = datetime_series(chunk, cols["updated_at"])
        closed = datetime_series(chunk, cols["closed_at"])

        comments_raw = clean_series(chunk, cols["comments_count"])
        comments_filtered_raw = clean_series(chunk, cols["comments_count_filtered"])
        commits_raw = clean_series(chunk, cols["commits_count"])
        comments_total = numeric_series(chunk, cols["comments_count"])
        comments_filtered = numeric_series(chunk, cols["comments_count_filtered"])
        commits = numeric_series(chunk, cols["commits_count"])

        comments_text = clean_series(chunk, cols["concatenated_comments"])
        title = clean_series(chunk, cols["issue_title"])
        body = clean_series(chunk, cols["issue_body"])
        raw_text = clean_series(chunk, cols["raw_text"])
        clean_text = clean_series(chunk, cols["clean_text"])
        stemmed_text = clean_series(chunk, cols["stemmed_text"])

        exception_rows: list[dict[str, Any]] = []

        invalid_created = created_raw.ne("") & created.isna()
        invalid_updated = updated_raw.ne("") & updated.isna()
        invalid_closed = closed_raw.ne("") & closed.isna()
        closed_before_created = created.notna() & closed.notna() & (closed < created)
        updated_before_created = created.notna() & updated.notna() & (updated < created)
        closed_without_date = state.eq("closed") & closed.isna()
        open_with_closed_date = state.eq("open") & closed.notna()

        invalid_comments = comments_raw.ne("") & comments_total.isna()
        invalid_filtered = comments_filtered_raw.ne("") & comments_filtered.isna()
        invalid_commits = commits_raw.ne("") & commits.isna()
        negative_comments = comments_total.notna() & comments_total.lt(0)
        negative_filtered = comments_filtered.notna() & comments_filtered.lt(0)
        negative_commits = commits.notna() & commits.lt(0)
        filtered_gt_total = (
            comments_total.notna()
            & comments_filtered.notna()
            & comments_filtered.gt(comments_total)
        )
        count_with_empty_text = comments_filtered.fillna(0).gt(0) & comments_text.eq("")
        text_with_zero_filtered_count = comments_text.ne("") & comments_filtered.fillna(0).eq(0)
        pr_missing_commits = item_kind.eq("pull_request") & commits_raw.eq("")
        issue_with_positive_commits = item_kind.eq("issue") & commits.fillna(0).gt(0)

        declared_year = numeric_series(chunk, cols["year"])
        created_year = created.dt.year.astype("Float64")
        year_mismatch = declared_year.notna() & created_year.notna() & declared_year.ne(created_year)

        title_missing_from_raw = title.ne("") & ~pd.Series(
            [t.lower() in r.lower() for t, r in zip(title.tolist(), raw_text.tolist())],
            index=chunk.index,
        )
        body_missing_from_raw = body.ne("") & ~pd.Series(
            [b.lower() in r.lower() for b, r in zip(body.tolist(), raw_text.tolist())],
            index=chunk.index,
        )

        conditions: list[tuple[str, pd.Series, pd.Series | str]] = [
            ("invalid_created_at", invalid_created, created_raw),
            ("invalid_updated_at", invalid_updated, updated_raw),
            ("invalid_closed_at", invalid_closed, closed_raw),
            ("closed_at_before_created_at", closed_before_created, "closed_at < created_at"),
            ("updated_at_before_created_at", updated_before_created, "updated_at < created_at"),
            ("closed_state_without_closed_at", closed_without_date, state),
            ("open_state_with_closed_at", open_with_closed_date, state),
            ("invalid_comments_count", invalid_comments, comments_raw),
            ("invalid_comments_count_filtered", invalid_filtered, comments_filtered_raw),
            ("invalid_commits_count", invalid_commits, commits_raw),
            ("negative_comments_count", negative_comments, comments_raw),
            ("negative_comments_count_filtered", negative_filtered, comments_filtered_raw),
            ("negative_commits_count", negative_commits, commits_raw),
            ("filtered_comments_exceed_total", filtered_gt_total, comments_filtered_raw + ">" + comments_raw),
            ("filtered_comment_count_without_text", count_with_empty_text, comments_filtered_raw),
            ("comment_text_with_zero_filtered_count", text_with_zero_filtered_count, comments_filtered_raw),
            ("pull_request_missing_commits_count", pr_missing_commits, commits_raw),
            ("issue_with_positive_commits_count", issue_with_positive_commits, commits_raw),
            ("year_mismatch", year_mismatch, declared_year.astype(str) + " vs " + created_year.astype(str)),
            ("raw_text_does_not_contain_title", title_missing_from_raw, title.str.slice(0, 120)),
            ("raw_text_does_not_contain_body", body_missing_from_raw, body.str.slice(0, 120)),
        ]

        for name, mask, details in conditions:
            count = int(mask.sum())
            exception_counts[name] += count
            add_exception_rows(exception_rows, chunk, mask, name, details)

        if exception_rows:
            frame = pd.DataFrame(exception_rows)
            append_csv(
                frame,
                exception_path,
                first_write=first_exception_write,
                config=config,
            )
            first_exception_write = False

        valid_resolution = created.notna() & closed.notna() & closed.ge(created)
        resolution = (closed[valid_resolution] - created[valid_resolution]).dt.total_seconds() / 86400
        resolution_days.extend(resolution.astype(float).tolist())
        for kind, values in resolution.groupby(item_kind[valid_resolution]):
            resolution_by_type[str(kind)].extend(values.astype(float).tolist())

        valid_comments = comments_total.dropna().astype(float)
        valid_filtered_comments = comments_filtered.dropna().astype(float)
        valid_commits = commits.dropna().astype(float)
        comments_total_values.extend(valid_comments.tolist())
        comments_filtered_values.extend(valid_filtered_comments.tolist())
        commits_values.extend(valid_commits.tolist())
        for kind, values in comments_filtered.dropna().groupby(item_kind[comments_filtered.notna()]):
            comments_by_type[str(kind)].extend(values.astype(float).tolist())

        for value in clean_series(chunk, cols["labels"]).tolist():
            labels = parse_listish(value)
            labels_per_item.append(float(len(labels)))
            label_counter.update(label.casefold() for label in labels)
        for value in clean_series(chunk, cols["comment_authors"]).tolist():
            comment_authors_per_item.append(float(len(parse_listish(value))))

        for logical, series in {
            "issue_title": title,
            "issue_body": body,
            "concatenated_comments": comments_text,
            "raw_text": raw_text,
            "clean_text": clean_text,
            "stemmed_text": stemmed_text,
            "labels": clean_series(chunk, cols["labels"]),
            "closed_at": closed_raw,
            "repository_category": clean_series(chunk, category_col),
        }.items():
            field_empty[logical] += int(series.eq("").sum())

        text_component_rows["title_only"] += int(title.ne("").mul(body.eq("")).mul(comments_text.eq("")).sum())
        text_component_rows["title_and_body_no_comments"] += int(title.ne("").mul(body.ne("")).mul(comments_text.eq("")).sum())
        text_component_rows["has_comments_text"] += int(comments_text.ne("").sum())
        text_component_rows["has_title"] += int(title.ne("").sum())
        text_component_rows["has_body"] += int(body.ne("").sum())

    if first_exception_write:
        pd.DataFrame(
            columns=["issue_id", "repository_full_name", "issue_number", "exception", "details"]
        ).to_csv(exception_path, index=False)

    counter_to_distribution(type_counter, "type_normalized", total_rows).to_csv(
        output_dir / "type_distribution.csv", index=False
    )
    counter_to_distribution(state_counter, "state", total_rows).to_csv(
        output_dir / "state_distribution.csv", index=False
    )
    counter_to_distribution(locked_counter, "locked", total_rows).to_csv(
        output_dir / "locked_distribution.csv", index=False
    )

    top_labels = int(config.get("research_fields", {}).get("top_labels", 250))
    label_frame = counter_to_distribution(label_counter, "label_normalized", sum(label_counter.values()))
    label_frame.head(top_labels).to_csv(output_dir / "label_distribution.csv", index=False)

    resolution_percentiles = list(
        config.get("research_fields", {}).get("resolution_percentiles", [25, 50, 75, 90, 95, 99])
    )
    comment_percentiles = list(
        config.get("research_fields", {}).get("comment_percentiles", [25, 50, 75, 90, 95, 99])
    )

    metric_rows: list[dict[str, Any]] = []
    metric_rows.extend(summarize_numeric(resolution_days, "resolution_days", resolution_percentiles))
    metric_rows.extend(summarize_numeric(comments_total_values, "comments_count", comment_percentiles))
    metric_rows.extend(summarize_numeric(comments_filtered_values, "comments_count_filtered", comment_percentiles))
    metric_rows.extend(summarize_numeric(commits_values, "commits_count", comment_percentiles))
    metric_rows.extend(summarize_numeric(labels_per_item, "labels_per_item", comment_percentiles))
    metric_rows.extend(summarize_numeric(comment_authors_per_item, "parsed_comment_authors_per_item", comment_percentiles))
    pd.DataFrame(metric_rows).to_csv(output_dir / "numeric_field_summary.csv", index=False)

    grouped_rows: list[dict[str, Any]] = []
    for kind, values in sorted(resolution_by_type.items()):
        for row in summarize_numeric(values, "resolution_days", resolution_percentiles):
            row["group"] = kind
            grouped_rows.append(row)
    for kind, values in sorted(comments_by_type.items()):
        for row in summarize_numeric(values, "comments_count_filtered", comment_percentiles):
            row["group"] = kind
            grouped_rows.append(row)
    pd.DataFrame(grouped_rows).to_csv(output_dir / "metrics_by_type.csv", index=False)

    pd.DataFrame(
        [
            {
                "field": field,
                "empty_count": count,
                "empty_percent": count / total_rows * 100 if total_rows else 0,
            }
            for field, count in sorted(field_empty.items())
        ]
    ).to_csv(output_dir / "research_field_completeness.csv", index=False)

    pd.DataFrame(
        [
            {
                "exception": name,
                "count": count,
                "percent": count / total_rows * 100 if total_rows else 0,
            }
            for name, count in sorted(exception_counts.items())
        ]
    ).to_csv(output_dir / "exception_summary.csv", index=False)

    pd.DataFrame(
        [
            {
                "metric": name,
                "count": count,
                "percent": count / total_rows * 100 if total_rows else 0,
            }
            for name, count in sorted(text_component_rows.items())
        ]
    ).to_csv(output_dir / "text_component_availability.csv", index=False)

    closed_count = state_counter.get("closed", 0)
    comments_available = total_rows - field_empty.get("concatenated_comments", 0)
    labels_available = total_rows - field_empty.get("labels", 0)
    readiness = [
        {
            "research_question": "RQ1_pattern_frequency",
            "status": "ready" if total_rows and not field_empty.get("raw_text", 0) else "blocked",
            "evidence": f"raw_text present in {total_rows - field_empty.get('raw_text', 0)}/{total_rows} records",
        },
        {
            "research_question": "RQ2_issue_activity_type",
            "status": "ready" if len(type_counter) > 1 else "warning",
            "evidence": f"{len(type_counter)} normalized type values; labels present in {labels_available}/{total_rows}",
        },
        {
            "research_question": "RQ3_resolution_and_discussion",
            "status": "ready" if closed_count and resolution_days else "warning",
            "evidence": f"{len(resolution_days)} valid resolution intervals; comment text present in {comments_available}/{total_rows}",
        },
    ]
    pd.DataFrame(readiness).to_csv(output_dir / "analysis_readiness_checks.csv", index=False)

    print(f"Research-field audit completed: {total_rows} rows. Outputs: {output_dir}")


if __name__ == "__main__":
    main()
