from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from audit_common import (
    clean_series,
    compile_regex,
    ensure_dir,
    file_digest,
    load_config,
    physical_column,
    read_header,
    repository_full_name,
    write_json,
)

ANNOTATION_COLUMNS = [
    "annotator_id",
    "relevant_to_pattern_study",
    "patterns_present",
    "adoption_status",
    "issue_activity_type",
    "challenge_categories",
    "evidence_text",
    "evidence_location",
    "false_friend_detected",
    "overlapping_patterns",
    "insufficient_context",
    "confidence",
    "human_notes",
    "annotation_date",
]

PAIR_COLUMNS = [
    "issue_id",
    "repository_full_name",
    "issue_number",
    "pattern",
    "annotator_id",
    "human_verdict",
    "evidence_text",
    "evidence_location",
    "justification",
    "alternative_pattern",
    "overlap_with",
    "adoption_status",
    "confidence",
    "notes",
]


def sample_rows(
    pool: pd.DataFrame,
    count: int,
    rng: np.random.Generator,
    used_issue_ids: set[str],
    used_hashes: set[str],
    group_name: str,
) -> pd.DataFrame:
    available = pool[
        ~pool["issue_id"].isin(used_issue_ids)
        & ~pool["raw_text_sha256"].isin(used_hashes)
    ].copy()
    if len(available) < count:
        raise RuntimeError(
            f"Not enough records for {group_name}: requested {count}, available {len(available)}. "
            "Broaden the configured regex or use a larger development partition."
        )
    positions = rng.choice(available.index.to_numpy(), size=count, replace=False)
    selected = available.loc[positions].copy()
    selected["sample_group"] = group_name
    used_issue_ids.update(selected["issue_id"].tolist())
    used_hashes.update(selected["raw_text_sha256"].tolist())
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate exact, reproducible smoke-test or pilot annotation samples."
    )
    parser.add_argument("--input", required=True, help="Development partition CSV")
    parser.add_argument("--mode", choices=["smoke", "pilot"], required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = ensure_dir(args.output_dir)
    input_path = Path(args.input)
    header = read_header(input_path, config)
    for required in ["raw_text_sha256", "repository_full_name"]:
        if required not in header:
            raise ValueError(f"Canonical/evaluation input required. Missing: {required}")

    frame = pd.read_csv(input_path, dtype=str, keep_default_na=False, low_memory=False)
    cols = {name: physical_column(config, name) for name in config.get("columns", {})}
    frame["issue_id"] = clean_series(frame, cols["issue_id"])
    frame["issue_number"] = clean_series(frame, cols["issue_number"])
    frame["repository_full_name"] = clean_series(frame, "repository_full_name")
    frame["raw_text_sha256"] = clean_series(frame, "raw_text_sha256")
    frame["screening_text"] = (
        clean_series(frame, cols["issue_title"])
        + "\n"
        + clean_series(frame, cols["issue_body"])
        + "\n"
        + clean_series(frame, cols["concatenated_comments"])
    )
    frame = frame.drop_duplicates(subset=["raw_text_sha256"], keep="first").copy()

    candidate_regex = compile_regex(config, "pattern_candidate_regex")
    false_regex = compile_regex(config, "false_friend_regex")
    candidate_mask = frame["screening_text"].str.contains(candidate_regex, na=False)
    false_mask = frame["screening_text"].str.contains(false_regex, na=False)
    candidate_pool = frame.loc[candidate_mask].copy()
    false_pool = frame.loc[false_mask].copy()

    seed = args.seed if args.seed is not None else int(config.get("sampling", {}).get("seed", 42))
    rng = np.random.default_rng(seed + (0 if args.mode == "smoke" else 1000))
    used_issue_ids: set[str] = set()
    used_hashes: set[str] = set()
    selected_frames: list[pd.DataFrame] = []

    cfg = config.get("sampling", {}).get(args.mode, {})
    if args.mode == "smoke":
        false_count = int(cfg.get("false_friend", 10))
        enriched_count = int(cfg.get("pattern_enriched", 10))
        random_count = int(cfg.get("random_control", 10))
        selected_frames.append(
            sample_rows(false_pool, false_count, rng, used_issue_ids, used_hashes, "false_friend")
        )
        selected_frames.append(
            sample_rows(candidate_pool, enriched_count, rng, used_issue_ids, used_hashes, "pattern_enriched")
        )
        selected_frames.append(
            sample_rows(frame, random_count, rng, used_issue_ids, used_hashes, "random_control")
        )
    else:
        enriched_count = int(cfg.get("pattern_enriched", 100))
        random_count = int(cfg.get("random_control", 100))
        selected_frames.append(
            sample_rows(candidate_pool, enriched_count, rng, used_issue_ids, used_hashes, "pattern_enriched")
        )
        selected_frames.append(
            sample_rows(frame, random_count, rng, used_issue_ids, used_hashes, "random_control")
        )

    selected = pd.concat(selected_frames, ignore_index=True)
    selected["selection_trigger"] = ""
    for index, row in selected.iterrows():
        regex = false_regex if row["sample_group"] == "false_friend" else candidate_regex
        match = regex.search(str(row["screening_text"]))
        selected.at[index, "selection_trigger"] = match.group(0) if match else ""

    output_columns = [
        cols["issue_id"],
        "repository_full_name",
        cols["issue_number"],
        cols["type"],
        cols["state"],
        cols["created_at"],
        cols["closed_at"],
        cols["labels"],
        cols["repository_category"],
        "repository_category_canonical",
        cols["data_source"],
        cols["issue_title"],
        cols["issue_body"],
        cols["concatenated_comments"],
        cols["comments_count"],
        cols["comments_count_filtered"],
        cols["commits_count"],
        "raw_text_sha256",
        "sample_group",
        "selection_trigger",
    ]
    output_columns = [column for column in output_columns if column in selected.columns]
    result = selected[output_columns].copy()
    for column in ANNOTATION_COLUMNS:
        result[column] = ""

    output_path = output_dir / f"{args.mode}_annotation_sample.csv"
    result.to_csv(output_path, index=False, encoding=config.get("output", {}).get("csv_encoding", "utf-8"))
    pd.DataFrame(columns=PAIR_COLUMNS).to_csv(
        output_dir / f"{args.mode}_pair_annotation_template.csv", index=False
    )
    summary = result["sample_group"].value_counts().rename_axis("sample_group").reset_index(name="selected")
    summary.to_csv(output_dir / f"{args.mode}_sample_summary.csv", index=False)

    write_json(
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "input": str(input_path.resolve()),
            "input_sha256": file_digest(input_path, "sha256"),
            "mode": args.mode,
            "seed": seed,
            "rows": len(result),
            "group_counts": result["sample_group"].value_counts().to_dict(),
            "raw_text_hash_unique": bool(result["raw_text_sha256"].is_unique),
        },
        output_dir / f"{args.mode}_sample_manifest.json",
    )
    print(f"{args.mode.capitalize()} sample generated: {len(result)} rows. Output: {output_path}")


if __name__ == "__main__":
    main()
