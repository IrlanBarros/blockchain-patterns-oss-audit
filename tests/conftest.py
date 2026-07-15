from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def make_row(index: int, *, issue_id: str | None = None, source: str = "provider") -> dict[str, str]:
    kind = "pull_request" if index % 3 == 0 else "issue"
    state = "closed" if index % 2 == 0 else "open"
    created = f"2024-01-{(index % 28) + 1:02d}T00:00:00Z"
    closed = f"2024-02-{(index % 28) + 1:02d}T00:00:00Z" if state == "closed" else ""
    if index % 4 == 0:
        title = f"Proxy upgrade and delegatecall {index}"
        body = "Preserve storage layout while changing the implementation contract."
    elif index % 4 == 1:
        title = f"Router signature snapshot issue {index}"
        body = "The frontend router generated a test snapshot and function signature."
    else:
        title = f"General issue {index}"
        body = "Routine software maintenance and tests."
    comments = "Oracle and mutex discussion in a network client." if index % 5 == 0 else ""
    return {
        "repository": f"repo-{index % 9}",
        "owner": f"org-{index % 5}",
        "issue_id": issue_id or str(100000 + index),
        "issue_number": str(index + 1),
        "issue_title": title,
        "issue_body": body,
        "state": state,
        "created_at": created,
        "updated_at": created,
        "closed_at": closed,
        "author": f"user-{index % 11}",
        "author_id": str(500000 + index),
        "locked": "false",
        "comments_count": "1" if comments else "0",
        "commits_count": "2" if kind == "pull_request" else "0",
        "labels": '["bug", "security"]' if index % 4 == 0 else "[]",
        "type": kind,
        "concatenated_comments": comments,
        "comment_authors": '["maintainer"]' if comments else "[]",
        "comments_count_filtered": "1" if comments else "0",
        "repository_category": "" if index % 13 == 0 else ("wallet" if index % 2 else "protocol"),
        "year": "2024",
        "raw_text": title + "\n" + body,
        "clean_text": (title + " " + body).lower(),
        "stemmed_text": "software issue pattern",
        "data_source": source,
        "owner_used": f"org-{index % 5}",
        "matching_keywords": "[]",
        "matching_mandatory_keywords": "[]",
    }


@pytest.fixture
def synthetic_dataset(tmp_path: Path) -> Path:
    rows = [make_row(index) for index in range(120)]
    for index in [3, 20, 47]:
        duplicate = rows[index].copy()
        duplicate["data_source"] = "community"
        duplicate["created_at"] = duplicate["created_at"].replace("Z", "+00:00")
        duplicate["updated_at"] = duplicate["updated_at"].replace("Z", "+00:00")
        duplicate["owner_used"] = ""
        rows.append(duplicate)
    path = tmp_path / "issues_prs.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


@pytest.fixture
def test_config(project_root: Path, tmp_path: Path) -> Path:
    config = yaml.safe_load((project_root / "config.yaml").read_text(encoding="utf-8"))
    config["zenodo"]["expected_total_records"] = 123
    config["integrity"]["expected_slice_size"] = 11
    config["partitions"]["partition_size"] = 20
    config["sampling"]["smoke"] = {
        "random_control": 2,
        "pattern_enriched": 2,
        "false_friend": 2,
    }
    config["sampling"]["pilot"] = {
        "random_control": 5,
        "pattern_enriched": 5,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path
