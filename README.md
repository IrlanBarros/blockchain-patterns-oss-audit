# Web3BlockSet Research Audit v3

Projeto de auditoria e preparação do corpus para o artigo **An Empirical Study of the Adoption and Challenges of Blockchain Design Patterns in OSS Projects**.

Esta versão considera o esquema completo do `issues_prs.csv`, resolve as duplicatas entre fontes, audita os campos necessários às questões de pesquisa e cria partições de avaliação sem vazamento de textos idênticos.

## Por que existe uma v3

A auditoria anterior revelou que o corpus possui 29 colunas e que algumas issues aparecem duas vezes, uma em `provider` e outra em `community`. Contar essas linhas como ocorrências independentes introduziria viés. A v3 cria um corpus canônico antes de qualquer recorte ou chamada à LLM.

## Fluxo correto

```text
issues_prs.csv bruto
        ↓
verificação e fingerprint
        ↓
canonicalização por issue_id
        ↓
auditoria do corpus canônico
        ↓
auditoria dos campos científicos
        ↓
recortes operacionais de 1.835
        ↓
development / validation / holdout
        ↓
smoke test e piloto humano
        ↓
pipeline de classificação por LLM
```

## Estrutura

```text
web3blockset_audit_v3/
├── data/
│   ├── raw/
│   │   └── issues_prs.csv
│   ├── canonical/
│   │   └── issues_prs_canonical.csv
│   ├── slices/
│   │   ├── slice_0001.csv
│   │   └── ...
│   └── evaluation/
│       ├── development.csv
│       ├── validation.csv
│       └── holdout.csv
├── outputs/
├── templates/
├── tests/
├── config.yaml
├── dataset_manifest.yaml
├── audit_common.py
├── verify_dataset.py
├── canonicalize_dataset.py
├── audit_canonical_integrity.py
├── audit_global.py
├── audit_research_fields.py
├── split_dataset.py
├── validate_slices.py
├── build_evaluation_partitions.py
├── generate_annotation_samples.py
├── generate_report.py
└── run_all.py
```

## Instalação

```bash
cd web3blockset_audit_v3
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Coloque somente o CSV em:

```text
data/raw/issues_prs.csv
```

O ZIP original não é necessário.

# Execução recomendada

## Primeira execução completa

```bash
python run_all.py \
  --master data/raw/issues_prs.csv \
  --canonical-output data/canonical/issues_prs_canonical.csv \
  --slices-dir data/slices \
  --evaluation-dir data/evaluation \
  --dataset-mode full \
  --conflict-policy fail \
  --config config.yaml \
  --output-root outputs
```

A política `fail` é deliberadamente conservadora: se duas linhas da mesma issue divergirem em campos substantivos, o processo para e gera `duplicate_conflicts.csv`.

Depois de revisar e documentar conflitos reais, a continuação pode ser feita conscientemente com:

```bash
python run_all.py \
  --master data/raw/issues_prs.csv \
  --canonical-output data/canonical/issues_prs_canonical.csv \
  --conflict-policy prefer-complete \
  --overwrite \
  --config config.yaml \
  --output-root outputs
```

Não use `prefer-complete` apenas para fazer o erro desaparecer.

## Reutilizar artefatos já produzidos

```bash
python run_all.py \
  --master data/raw/issues_prs.csv \
  --canonical-output data/canonical/issues_prs_canonical.csv \
  --slices-dir data/slices \
  --evaluation-dir data/evaluation \
  --reuse-canonical \
  --reuse-slices \
  --reuse-evaluation \
  --config config.yaml \
  --output-root outputs
```

# Etapas individuais

## 1. Verificar o dataset bruto

```bash
python verify_dataset.py \
  --input data/raw/issues_prs.csv \
  --dataset-mode full \
  --config config.yaml \
  --output-dir outputs/verification
```

Saídas:

- `verification_checks.csv`
- `dataset_fingerprint.json`

Duplicatas de `issue_id` são alerta nessa etapa, porque ainda serão resolvidas.

## 2. Criar o corpus canônico

```bash
python canonicalize_dataset.py \
  --input data/raw/issues_prs.csv \
  --output data/canonical/issues_prs_canonical.csv \
  --config config.yaml \
  --output-dir outputs/canonicalization \
  --conflict-policy fail
```

Colunas adicionadas:

```text
repository_full_name
canonical_issue_key
repository_category_canonical
raw_text_sha256
data_sources_seen
duplicate_group_size
duplicate_resolution
```

Saídas de auditoria:

- `merged_duplicate_groups.csv`
- `duplicate_conflicts.csv`
- `canonicalization_manifest.json`

## 3. Auditar a integridade canônica

```bash
python audit_canonical_integrity.py \
  --input data/canonical/issues_prs_canonical.csv \
  --config config.yaml \
  --output-dir outputs/canonical_integrity
```

Gates principais:

```text
duplicate_issue_id_rows_after_first = 0
duplicate_owner_repository_number_rows_after_first = 0
exact_duplicate_rows_after_first = 0
```

Textos repetidos não são removidos. Eles são agrupados na divisão de avaliação.

## 4. Perfilar o corpus canônico

```bash
python audit_global.py \
  --input data/canonical/issues_prs_canonical.csv \
  --config config.yaml \
  --output-dir outputs/global
```

O projeto usa `owner/repository`, não apenas `repository`, para identificar projetos.

## 5. Auditar os campos das RQs

```bash
python audit_research_fields.py \
  --input data/canonical/issues_prs_canonical.csv \
  --config config.yaml \
  --output-dir outputs/research_fields
```

A etapa verifica:

- `type` e separação issue/PR;
- `state`, `created_at`, `updated_at`, `closed_at`;
- tempo de resolução;
- `comments_count` e `comments_count_filtered`;
- consistência entre contagens e `concatenated_comments`;
- `commits_count` em PRs;
- labels e autores dos comentários;
- coerência entre `year` e `created_at`;
- disponibilidade de título, corpo, comentários e textos processados;
- prontidão de RQ1, RQ2 e RQ3.

Saídas principais:

- `analysis_readiness_checks.csv`
- `research_field_completeness.csv`
- `exception_summary.csv`
- `research_field_exceptions.csv`
- `numeric_field_summary.csv`
- `metrics_by_type.csv`
- `label_distribution.csv`
- `text_component_availability.csv`

## 6. Criar os recortes operacionais

```bash
python split_dataset.py \
  --input data/canonical/issues_prs_canonical.csv \
  --output-dir data/slices \
  --slice-size 1835 \
  --seed 42 \
  --strategy random \
  --config config.yaml
```

O último recorte pode ser menor. O script gera:

- `slice_0001.csv`, etc.;
- `slices_manifest.csv`;
- `split_manifest.json`.

## 7. Validar os recortes

```bash
python validate_slices.py \
  --master data/canonical/issues_prs_canonical.csv \
  --slices 'data/slices/slice_*.csv' \
  --coverage-mode full \
  --config config.yaml \
  --output-dir outputs/slices
```

O validador ignora automaticamente CSVs cujo nome não siga `slice_####.csv`.

Gates:

```text
schema_mismatch_files = 0
duplicate_issue_ids_within_slices_after_first = 0
issue_ids_overlapping_between_slices = 0
issue_ids_not_found_in_master = 0
master_issue_ids_missing_from_slices = 0
```

## 8. Criar development, validation e holdout

```bash
python build_evaluation_partitions.py \
  --input data/canonical/issues_prs_canonical.csv \
  --config config.yaml \
  --output-dir data/evaluation
```

Cada partição possui 1.835 registros por padrão. O algoritmo:

- mantém todos os registros com o mesmo `raw_text_sha256` na mesma partição;
- aproxima a distribuição global por categoria, tipo, fonte e período;
- impede vazamento de templates idênticos entre development, validation e holdout.

Saídas:

- `development.csv`
- `validation.csv`
- `holdout.csv`
- `partition_profile.csv`
- `partition_drift_metrics.csv`
- `raw_text_hash_overlap.csv`
- `evaluation_partition_manifest.json`

O gate obrigatório é:

```text
raw_text_hash_overlap.csv = 0 linhas
```

## 9. Gerar o smoke test

```bash
python generate_annotation_samples.py \
  --input data/evaluation/development.csv \
  --mode smoke \
  --config config.yaml \
  --output-dir outputs/samples
```

Produz exatamente:

- 10 controles aleatórios;
- 10 candidatos enriquecidos;
- 10 falsos-amigos/casos ambíguos.

O script falha em vez de gerar silenciosamente menos registros.

## 10. Gerar o piloto humano

```bash
python generate_annotation_samples.py \
  --input data/evaluation/development.csv \
  --mode pilot \
  --config config.yaml \
  --output-dir outputs/samples
```

Produz:

- 100 controles aleatórios;
- 100 candidatos enriquecidos.

Esses números podem ser alterados no `config.yaml`.

## 11. Gerar o relatório

```bash
python generate_report.py \
  --output-root outputs \
  --output outputs/audit_report.md
```

# Interpretação dos artefatos

## Recortes operacionais versus partições científicas

Eles não são a mesma coisa.

- `data/slices/`: lotes para processamento progressivo e checkpoints.
- `data/evaluation/`: conjuntos independentes para ajuste e avaliação do classificador.

Não escolha `slice_0001.csv` como holdout. Use as partições dedicadas.

## Corpus bruto versus canônico

- O bruto permanece imutável.
- O canônico é o corpus científico com uma linha por issue.
- Resultados de Stage 1 e Stage 2 devem usar o corpus canônico.

## `repository_category_canonical`

Mantém a categoria original quando presente e usa `Unclassified` quando ausente. A coluna original não é sobrescrita.

# Testes

```bash
pytest -q
```

Os testes usam dados sintéticos e cobrem:

- canonicalização de duplicatas equivalentes;
- interrupção diante de conflito substantivo;
- recortes sem perda ou sobreposição;
- partições sem vazamento de `raw_text_sha256`;
- geração das amostras com contagens exatas.

# Próximo gate após a auditoria

Não execute o corpus inteiro na LLM apenas porque o relatório foi gerado. O próximo marco é:

1. anotar manualmente o smoke test;
2. executar Stage 1 e Stage 2 nas 30 amostras;
3. classificar os erros;
4. refinar prompts e scripts;
5. realizar piloto humano de 200–300 casos;
6. medir recall, precisão e F1;
7. avaliar em validation;
8. usar holdout apenas no fim.
