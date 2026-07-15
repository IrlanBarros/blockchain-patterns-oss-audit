# Migração da v2 para a v3

A v2 tratava apenas seis campos. A v3 usa o esquema completo do Web3BlockSet e muda a ordem correta do trabalho.

## Mudanças principais

1. O arquivo bruto de 391.596 linhas é apenas a fonte de entrada.
2. `canonicalize_dataset.py` cria um corpus com uma linha por `issue_id`.
3. Os recortes antigos devem ser descartados e recriados a partir do corpus canônico.
4. `repository_full_name = owner/repository` substitui o nome isolado do repositório nas análises.
5. `audit_research_fields.py` valida campos de RQ2 e RQ3.
6. Development, validation e holdout são criados diretamente do corpus canônico e agrupados por `raw_text_sha256`.
7. As amostras humanas são geradas apenas de `development.csv`.

## O que não reaproveitar

- Recortes gerados a partir do CSV bruto com duplicatas.
- Smoke sample e pilot sample da v2.
- Ranking de recortes anterior à canonicalização.

## O que pode ser preservado

- O arquivo bruto `issues_prs.csv`.
- O SHA-256 do arquivo bruto.
- Os relatórios da v2 como evidência de diagnóstico histórico.
