from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    print("\n$ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the complete Web3BlockSet research audit workflow."
    )
    parser.add_argument("--master", required=True, help="Raw issues_prs.csv")
    parser.add_argument("--canonical-output", default="data/canonical/issues_prs_canonical.csv")
    parser.add_argument("--slices-dir", default="data/slices")
    parser.add_argument("--evaluation-dir", default="data/evaluation")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--dataset-mode", choices=["full", "subset"], default="full")
    parser.add_argument("--conflict-policy", choices=["fail", "prefer-complete"], default="fail")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--slice-size", type=int, default=None)
    parser.add_argument("--split-seed", type=int, default=None)
    parser.add_argument("--partition-size", type=int, default=None)
    parser.add_argument("--partition-seed", type=int, default=None)
    parser.add_argument("--reuse-canonical", action="store_true")
    parser.add_argument("--reuse-slices", action="store_true")
    parser.add_argument("--reuse-evaluation", action="store_true")
    parser.add_argument("--skip-slices", action="store_true")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--skip-samples", action="store_true")
    args = parser.parse_args()

    python = sys.executable
    root = Path(args.output_root)
    verification_dir = root / "verification"
    canonicalization_dir = root / "canonicalization"
    canonical_integrity_dir = root / "canonical_integrity"
    global_dir = root / "global"
    research_dir = root / "research_fields"
    slices_output_dir = root / "slices"
    evaluation_output_dir = root / "evaluation"
    samples_dir = root / "samples"

    for path in [
        verification_dir,
        canonicalization_dir,
        canonical_integrity_dir,
        global_dir,
        research_dir,
        slices_output_dir,
        evaluation_output_dir,
        samples_dir,
        Path(args.canonical_output).parent,
        Path(args.slices_dir),
        Path(args.evaluation_dir),
    ]:
        path.mkdir(parents=True, exist_ok=True)

    run(
        [
            python,
            "verify_dataset.py",
            "--input",
            args.master,
            "--config",
            args.config,
            "--output-dir",
            str(verification_dir),
            "--dataset-mode",
            args.dataset_mode,
        ]
    )

    canonical_path = Path(args.canonical_output)
    if not (args.reuse_canonical and canonical_path.exists()):
        command = [
            python,
            "canonicalize_dataset.py",
            "--input",
            args.master,
            "--output",
            str(canonical_path),
            "--config",
            args.config,
            "--output-dir",
            str(canonicalization_dir),
            "--conflict-policy",
            args.conflict_policy,
        ]
        if args.overwrite:
            command.append("--overwrite")
        run(command)
    else:
        print(f"\nReusing canonical corpus: {canonical_path}")

    run(
        [
            python,
            "audit_canonical_integrity.py",
            "--input",
            str(canonical_path),
            "--config",
            args.config,
            "--output-dir",
            str(canonical_integrity_dir),
        ]
    )

    run(
        [
            python,
            "audit_global.py",
            "--input",
            str(canonical_path),
            "--config",
            args.config,
            "--output-dir",
            str(global_dir),
        ]
    )
    run(
        [
            python,
            "audit_research_fields.py",
            "--input",
            str(canonical_path),
            "--config",
            args.config,
            "--output-dir",
            str(research_dir),
        ]
    )

    if not args.skip_slices:
        slices_dir = Path(args.slices_dir)
        existing_slices = list(slices_dir.glob("slice_[0-9][0-9][0-9][0-9].csv"))
        if not (args.reuse_slices and existing_slices):
            command = [
                python,
                "split_dataset.py",
                "--input",
                str(canonical_path),
                "--output-dir",
                str(slices_dir),
                "--strategy",
                "random",
                "--config",
                args.config,
            ]
            if args.slice_size is not None:
                command += ["--slice-size", str(args.slice_size)]
            if args.split_seed is not None:
                command += ["--seed", str(args.split_seed)]
            if args.overwrite:
                command.append("--overwrite")
            run(command)
        else:
            print(f"\nReusing {len(existing_slices)} operational slices in {slices_dir}")

        run(
            [
                python,
                "validate_slices.py",
                "--master",
                str(canonical_path),
                "--slices",
                str(slices_dir / "slice_*.csv"),
                "--coverage-mode",
                "full",
                "--config",
                args.config,
                "--output-dir",
                str(slices_output_dir),
            ]
        )

    if not args.skip_evaluation:
        evaluation_dir = Path(args.evaluation_dir)
        development_path = evaluation_dir / "development.csv"
        if not (args.reuse_evaluation and development_path.exists()):
            command = [
                python,
                "build_evaluation_partitions.py",
                "--input",
                str(canonical_path),
                "--config",
                args.config,
                "--output-dir",
                str(evaluation_dir),
            ]
            if args.partition_size is not None:
                command += ["--partition-size", str(args.partition_size)]
            if args.partition_seed is not None:
                command += ["--seed", str(args.partition_seed)]
            if args.overwrite:
                command.append("--overwrite")
            run(command)
        else:
            print(f"\nReusing evaluation partitions in {evaluation_dir}")

        for filename in [
            "partition_profile.csv",
            "partition_drift_metrics.csv",
            "raw_text_hash_overlap.csv",
            "evaluation_partition_manifest.json",
        ]:
            source = evaluation_dir / filename
            target = evaluation_output_dir / filename
            if source.exists():
                target.write_bytes(source.read_bytes())

        if not args.skip_samples:
            run(
                [
                    python,
                    "generate_annotation_samples.py",
                    "--input",
                    str(development_path),
                    "--mode",
                    "smoke",
                    "--config",
                    args.config,
                    "--output-dir",
                    str(samples_dir),
                ]
            )
            run(
                [
                    python,
                    "generate_annotation_samples.py",
                    "--input",
                    str(development_path),
                    "--mode",
                    "pilot",
                    "--config",
                    args.config,
                    "--output-dir",
                    str(samples_dir),
                ]
            )

    run(
        [
            python,
            "generate_report.py",
            "--output-root",
            str(root),
            "--output",
            str(root / "audit_report.md"),
        ]
    )
    print("\nAudit workflow completed. Review outputs/audit_report.md before running the LLM pipeline.")


if __name__ == "__main__":
    main()
