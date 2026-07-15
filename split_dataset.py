from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from audit_common import (
    csv_kwargs,
    ensure_dir,
    file_digest,
    file_metadata,
    iter_csv,
    load_config,
    read_header,
    require_columns,
    required_column_map,
)

TEMP_ORDER_COLUMN = "__slice_order__"


def count_rows(path: str | Path, config: dict) -> int:
    return sum(len(chunk) for chunk in iter_csv(path, config))


def clear_previous_outputs(output_dir: Path, prefix: str) -> None:
    for pattern in (
        f"{prefix}_*.csv",
        f".{prefix}_*.tmp.csv",
        "slices_manifest.csv",
        "split_manifest.json",
    ):
        for path in output_dir.glob(pattern):
            if path.is_file():
                path.unlink()


def build_assignment(
    total_rows: int,
    slice_size: int,
    seed: int,
    strategy: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Map every original row position to a slice and an order inside it."""
    if strategy == "random":
        rng = np.random.default_rng(seed)
        permutation = rng.permutation(total_rows)
        rank_by_position = np.empty(total_rows, dtype=np.int64)
        rank_by_position[permutation] = np.arange(total_rows, dtype=np.int64)
    elif strategy == "sequential":
        rank_by_position = np.arange(total_rows, dtype=np.int64)
    else:
        raise ValueError(f"Unsupported strategy: {strategy}")

    return rank_by_position // slice_size, rank_by_position % slice_size


def append_partition(
    frame: pd.DataFrame,
    path: Path,
    first_write: bool,
    config: dict,
) -> None:
    frame.to_csv(
        path,
        index=False,
        mode="w" if first_write else "a",
        header=first_write,
        encoding=config.get("output", {}).get("csv_encoding", "utf-8"),
    )


def finalize_slice(
    temp_path: Path,
    final_path: Path,
    original_columns: list[str],
    config: dict,
) -> int:
    frame = pd.read_csv(temp_path, **csv_kwargs(config))
    frame[TEMP_ORDER_COLUMN] = pd.to_numeric(
        frame[TEMP_ORDER_COLUMN], errors="raise"
    )
    frame = frame.sort_values(TEMP_ORDER_COLUMN, kind="stable")
    frame = frame.drop(columns=[TEMP_ORDER_COLUMN])
    frame = frame[original_columns]
    frame.to_csv(
        final_path,
        index=False,
        encoding=config.get("output", {}).get("csv_encoding", "utf-8"),
    )
    row_count = len(frame)
    temp_path.unlink()
    return row_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create deterministic, non-overlapping CSV slices without filtering "
            "records or changing the original schema."
        )
    )
    parser.add_argument("--input", required=True, help="Master issues_prs.csv")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--slice-size", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--strategy",
        choices=["random", "sequential"],
        default="random",
    )
    parser.add_argument("--prefix", default="slice")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    output_dir = ensure_dir(args.output_dir)
    prefix = args.prefix.strip()
    if not prefix:
        raise ValueError("--prefix cannot be empty")

    existing = list(output_dir.glob(f"{prefix}_*.csv"))
    if existing and not args.overwrite:
        raise FileExistsError(
            f"{len(existing)} prior slice file(s) found in {output_dir}. "
            "Use --overwrite only after confirming they can be replaced."
        )
    if args.overwrite:
        clear_previous_outputs(output_dir, prefix)

    original_columns = read_header(input_path, config)
    require_columns(original_columns, required_column_map(config))

    slice_size = args.slice_size or int(
        config.get("integrity", {}).get("expected_slice_size", 1835)
    )
    seed = (
        args.seed
        if args.seed is not None
        else int(config.get("sampling", {}).get("seed", 42))
    )
    if slice_size <= 0:
        raise ValueError("--slice-size must be greater than zero")

    print("Pass 1/3: counting rows...")
    total_rows = count_rows(input_path, config)
    if total_rows == 0:
        raise ValueError("The input CSV contains no data rows")

    number_of_slices = math.ceil(total_rows / slice_size)
    last_slice_size = total_rows - slice_size * (number_of_slices - 1)
    print(
        f"Creating {number_of_slices} slices: "
        f"{number_of_slices - 1} with {slice_size} rows and "
        f"the last with {last_slice_size} rows."
    )

    slice_by_position, order_by_position = build_assignment(
        total_rows, slice_size, seed, args.strategy
    )

    print("Pass 2/3: writing temporary partitions...")
    offset = 0
    initialized: set[int] = set()

    for chunk in iter_csv(input_path, config):
        positions = np.arange(offset, offset + len(chunk), dtype=np.int64)
        chunk = chunk.copy()
        chunk["_target_slice"] = slice_by_position[positions]
        chunk[TEMP_ORDER_COLUMN] = order_by_position[positions]

        for slice_index, group in chunk.groupby("_target_slice", sort=False):
            slice_index = int(slice_index)
            temp_path = output_dir / f".{prefix}_{slice_index + 1:04d}.tmp.csv"
            append_partition(
                group.drop(columns=["_target_slice"]),
                temp_path,
                first_write=slice_index not in initialized,
                config=config,
            )
            initialized.add(slice_index)

        offset += len(chunk)

    if offset != total_rows:
        raise RuntimeError(
            f"Row count changed between passes: {total_rows} -> {offset}"
        )

    print("Pass 3/3: finalizing slices and manifests...")
    manifest_rows: list[dict[str, object]] = []
    total_written = 0

    for slice_index in range(number_of_slices):
        temp_path = output_dir / f".{prefix}_{slice_index + 1:04d}.tmp.csv"
        final_path = output_dir / f"{prefix}_{slice_index + 1:04d}.csv"
        if not temp_path.exists():
            raise RuntimeError(f"Temporary slice missing: {temp_path}")

        row_count = finalize_slice(
            temp_path, final_path, original_columns, config
        )
        expected = (
            last_slice_size
            if slice_index == number_of_slices - 1
            else slice_size
        )
        if row_count != expected:
            raise RuntimeError(
                f"{final_path.name}: got {row_count} rows, expected {expected}"
            )
        total_written += row_count

        manifest_rows.append(
            {
                "slice_index": slice_index + 1,
                "slice_file": final_path.name,
                "row_count": row_count,
                "expected_row_count": expected,
                "is_last_slice": slice_index == number_of_slices - 1,
                "sha256": file_digest(final_path, "sha256"),
                "size_bytes": final_path.stat().st_size,
            }
        )

    if total_written != total_rows:
        raise RuntimeError(
            f"Output total differs from input: {total_written} != {total_rows}"
        )

    pd.DataFrame(manifest_rows).to_csv(
        output_dir / "slices_manifest.csv",
        index=False,
        encoding=config.get("output", {}).get("csv_encoding", "utf-8"),
    )

    split_manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": file_metadata(input_path, include_sha256=True),
        "input_columns": original_columns,
        "total_rows": total_rows,
        "slice_size": slice_size,
        "number_of_slices": number_of_slices,
        "last_slice_size": last_slice_size,
        "strategy": args.strategy,
        "seed": seed if args.strategy == "random" else None,
        "prefix": prefix,
        "output_directory": str(output_dir.resolve()),
        "total_rows_written": total_written,
        "schema_preserved": True,
        "records_filtered": 0,
        "notes": (
            "Every input row is preserved exactly once. Random mode changes "
            "only slice membership and row order, never field contents."
        ),
    }
    with (output_dir / "split_manifest.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(split_manifest, handle, ensure_ascii=False, indent=2)

    print(
        f"Completed: {number_of_slices} slices and {total_written} rows."
    )


if __name__ == "__main__":
    main()
