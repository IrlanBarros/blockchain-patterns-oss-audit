from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def table(frame: pd.DataFrame, limit: int = 20) -> str:
    if frame.empty:
        return "_Arquivo ausente ou sem linhas._"
    return frame.head(limit).to_markdown(index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a consolidated Markdown audit report.")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.output_root)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    verification = read_csv(root / "verification" / "verification_checks.csv")
    canonical_manifest_path = root / "canonicalization" / "canonicalization_manifest.json"
    canonical_manifest = (
        json.loads(canonical_manifest_path.read_text(encoding="utf-8"))
        if canonical_manifest_path.exists()
        else {}
    )
    conflicts = read_csv(root / "canonicalization" / "duplicate_conflicts.csv")
    canonical_integrity = read_csv(root / "canonical_integrity" / "canonical_integrity_summary.csv")
    global_summary = read_csv(root / "global" / "audit_summary.csv")
    concentration = read_csv(root / "global" / "concentration_metrics.csv")
    readiness = read_csv(root / "research_fields" / "analysis_readiness_checks.csv")
    field_completeness = read_csv(root / "research_fields" / "research_field_completeness.csv")
    exceptions = read_csv(root / "research_fields" / "exception_summary.csv")
    slice_validation = read_csv(root / "slices" / "validation_summary.csv")
    partition_profile = read_csv(root / "evaluation" / "partition_profile.csv")
    partition_drift = read_csv(root / "evaluation" / "partition_drift_metrics.csv")
    partition_overlap = read_csv(root / "evaluation" / "raw_text_hash_overlap.csv")

    lines = [
        "# Relatório consolidado de auditoria do Web3BlockSet",
        "",
        "## 1. Verificação do arquivo bruto",
        "",
        table(verification, 50),
        "",
        "## 2. Canonicalização",
        "",
    ]
    if canonical_manifest:
        lines.extend(
            [
                f"- Linhas brutas: **{canonical_manifest.get('raw_rows', '')}**",
                f"- Linhas canônicas: **{canonical_manifest.get('canonical_rows', '')}**",
                f"- Linhas duplicadas removidas: **{canonical_manifest.get('removed_duplicate_rows', '')}**",
                f"- Grupos duplicados: **{canonical_manifest.get('duplicate_group_count', '')}**",
                f"- Comparações conflitantes: **{canonical_manifest.get('substantive_conflict_comparisons', '')}**",
                f"- SHA-256 do corpus canônico: `{canonical_manifest.get('output_sha256', '')}`",
                "",
            ]
        )
    lines.extend(
        [
            "### Conflitos entre fontes",
            "",
            table(conflicts, 20),
            "",
            "## 3. Integridade do corpus canônico",
            "",
            table(canonical_integrity, 40),
            "",
            "## 4. Perfil global do corpus canônico",
            "",
            table(global_summary, 30),
            "",
            "### Concentração por repositório",
            "",
            table(concentration, 20),
            "",
            "## 5. Prontidão das questões de pesquisa",
            "",
            table(readiness, 20),
            "",
            "### Completude dos campos científicos",
            "",
            table(field_completeness, 30),
            "",
            "### Exceções e inconsistências",
            "",
            table(exceptions.sort_values("count", ascending=False) if not exceptions.empty and "count" in exceptions else exceptions, 30),
            "",
            "## 6. Recortes operacionais",
            "",
            table(slice_validation, 30),
            "",
            "## 7. Partições de avaliação",
            "",
            table(partition_profile, 20),
            "",
            "### Distância em relação ao corpus",
            "",
            table(partition_drift, 30),
            "",
            "### Vazamento por texto repetido",
            "",
            f"Grupos `raw_text_sha256` presentes em mais de uma partição: **{len(partition_overlap)}**.",
            "",
            "## 8. Gates recomendados",
            "",
            "A execução da LLM só deve avançar quando:",
            "",
            "1. O corpus canônico não contiver `issue_id` duplicado.",
            "2. Conflitos substantivos entre fontes estiverem zerados ou documentados.",
            "3. Os recortes operacionais cobrirem integralmente o corpus, sem sobreposição.",
            "4. Development, validation e holdout não compartilharem `raw_text_sha256`.",
            "5. Os campos necessários às RQs tiverem completude e consistência aceitáveis.",
            "6. As amostras humanas forem geradas exclusivamente a partir da partição de desenvolvimento.",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report generated: {output}")


if __name__ == "__main__":
    main()
