from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

from conftest import make_row


def test_equivalent_cross_source_duplicates_are_merged(
    project_root: Path,
    synthetic_dataset: Path,
    test_config: Path,
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical.csv"
    output_dir = tmp_path / "canonicalization"
    subprocess.run(
        [
            sys.executable,
            str(project_root / "canonicalize_dataset.py"),
            "--input",
            str(synthetic_dataset),
            "--output",
            str(canonical),
            "--config",
            str(test_config),
            "--output-dir",
            str(output_dir),
            "--conflict-policy",
            "fail",
        ],
        check=True,
        cwd=project_root,
    )
    frame = pd.read_csv(canonical, dtype=str)
    assert len(frame) == 120
    assert frame["issue_id"].is_unique
    assert "repository_full_name" in frame.columns
    assert "raw_text_sha256" in frame.columns
    merged = pd.read_csv(output_dir / "merged_duplicate_groups.csv")
    assert len(merged) == 3
    assert merged["conflict_count"].sum() == 0


def test_substantive_conflict_stops_by_default(
    project_root: Path,
    test_config: Path,
    tmp_path: Path,
) -> None:
    first = make_row(1, issue_id="999")
    second = first.copy()
    second["data_source"] = "community"
    second["issue_body"] = "Different substantive content."
    second["raw_text"] = second["issue_title"] + "\n" + second["issue_body"]
    raw = tmp_path / "conflict.csv"
    pd.DataFrame([first, second]).to_csv(raw, index=False)
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "canonicalize_dataset.py"),
            "--input",
            str(raw),
            "--output",
            str(tmp_path / "canonical.csv"),
            "--config",
            str(test_config),
            "--output-dir",
            str(tmp_path / "out"),
            "--conflict-policy",
            "fail",
        ],
        cwd=project_root,
    )
    assert result.returncode != 0
    conflicts = pd.read_csv(tmp_path / "out" / "duplicate_conflicts.csv")
    assert "issue_body" in set(conflicts["column"])
