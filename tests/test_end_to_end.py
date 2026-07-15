from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd


def run(project_root: Path, *args: str) -> None:
    subprocess.run([sys.executable, *args], check=True, cwd=project_root)


def test_post_canonical_workflow(
    project_root: Path,
    synthetic_dataset: Path,
    test_config: Path,
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical.csv"
    run(
        project_root,
        str(project_root / "canonicalize_dataset.py"),
        "--input",
        str(synthetic_dataset),
        "--output",
        str(canonical),
        "--config",
        str(test_config),
        "--output-dir",
        str(tmp_path / "canonicalization"),
    )
    run(
        project_root,
        str(project_root / "audit_canonical_integrity.py"),
        "--input",
        str(canonical),
        "--config",
        str(test_config),
        "--output-dir",
        str(tmp_path / "integrity"),
    )
    slices = tmp_path / "slices"
    run(
        project_root,
        str(project_root / "split_dataset.py"),
        "--input",
        str(canonical),
        "--output-dir",
        str(slices),
        "--slice-size",
        "11",
        "--seed",
        "42",
        "--strategy",
        "random",
        "--config",
        str(test_config),
    )
    run(
        project_root,
        str(project_root / "validate_slices.py"),
        "--master",
        str(canonical),
        "--slices",
        str(slices / "*.csv"),
        "--coverage-mode",
        "full",
        "--config",
        str(test_config),
        "--output-dir",
        str(tmp_path / "slice_audit"),
    )
    checks = pd.read_csv(tmp_path / "slice_audit" / "validation_summary.csv")
    errors = checks[(checks["status"] == "error") & (checks["value"].astype(str) != "0")]
    assert errors.empty

    evaluation = tmp_path / "evaluation"
    run(
        project_root,
        str(project_root / "build_evaluation_partitions.py"),
        "--input",
        str(canonical),
        "--config",
        str(test_config),
        "--output-dir",
        str(evaluation),
        "--partition-size",
        "20",
    )
    overlap = pd.read_csv(evaluation / "raw_text_hash_overlap.csv")
    assert overlap.empty
    for name in ["development", "validation", "holdout"]:
        assert len(pd.read_csv(evaluation / f"{name}.csv")) == 20

    samples = tmp_path / "samples"
    run(
        project_root,
        str(project_root / "generate_annotation_samples.py"),
        "--input",
        str(evaluation / "development.csv"),
        "--mode",
        "smoke",
        "--config",
        str(test_config),
        "--output-dir",
        str(samples),
    )
    smoke = pd.read_csv(samples / "smoke_annotation_sample.csv")
    assert len(smoke) == 6
    assert smoke["raw_text_sha256"].is_unique
