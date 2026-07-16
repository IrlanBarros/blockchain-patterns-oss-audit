# Relatório consolidado de auditoria do Web3BlockSet

## 1. Verificação do arquivo bruto

| check                                              | status   |   observed |   expected | notes                                                               |
|:---------------------------------------------------|:---------|-----------:|-----------:|:--------------------------------------------------------------------|
| required_schema                                    | pass     |         29 |         21 | All configured research fields are present.                         |
| row_count                                          | pass     |     391596 |     391596 | nan                                                                 |
| blank_issue_id                                     | pass     |          0 |          0 | Canonicalization requires a non-empty issue_id.                     |
| duplicate_issue_id_rows_after_first                | warning  |        175 |          0 | Cross-source duplicates are resolved by canonicalize_dataset.py.    |
| duplicate_owner_repository_number_rows_after_first | warning  |        175 |          0 | Should agree with duplicate issue_id groups after canonicalization. |
| exact_duplicate_rows_after_first                   | pass     |          0 |          0 | Exact duplicate rows are not silently removed.                      |

## 2. Canonicalização

- Linhas brutas: **391596**
- Linhas canônicas: **391421**
- Linhas duplicadas removidas: **175**
- Grupos duplicados: **175**
- Comparações conflitantes: **0**
- SHA-256 do corpus canônico: `bbf62adcc959b595b18145731953f18b97238dc7557c9fe80f6b679775a9a75a`

### Conflitos entre fontes

_Arquivo ausente ou sem linhas._

## 3. Integridade do corpus canônico

| metric                                             |   value | status   | notes                                                                            |
|:---------------------------------------------------|--------:|:---------|:---------------------------------------------------------------------------------|
| total_rows                                         |  391421 | info     | nan                                                                              |
| duplicate_issue_id_rows_after_first                |       0 | pass     | Canonical corpus must have one row per issue_id.                                 |
| duplicate_owner_repository_number_rows_after_first |       0 | pass     | GitHub identity must also be unique.                                             |
| exact_duplicate_rows_after_first                   |       0 | pass     | nan                                                                              |
| repeated_raw_text_groups                           |    1111 | info     | Legitimate templates may repeat; evaluation partitions group by raw_text_sha256. |
| rows_in_repeated_raw_text_groups                   |    3180 | info     | nan                                                                              |
| missing_repository_full_name                       |       0 | pass     | nan                                                                              |
| missing_canonical_issue_key                        |       0 | pass     | nan                                                                              |
| missing_repository_category_canonical              |       0 | pass     | nan                                                                              |
| missing_raw_text_sha256                            |       0 | pass     | nan                                                                              |
| missing_data_sources_seen                          |       0 | pass     | nan                                                                              |
| missing_duplicate_group_size                       |       0 | pass     | nan                                                                              |
| missing_duplicate_resolution                       |       0 | pass     | nan                                                                              |

## 4. Perfil global do corpus canônico

| metric              | value                     |
|:--------------------|:--------------------------|
| total_rows          | 391421                    |
| unique_repositories | 4019                      |
| unique_categories   | 34                        |
| unique_sources      | 2                         |
| unique_types        | 2                         |
| earliest_created_at | 2011-09-20T03:02:33+00:00 |
| latest_created_at   | 2025-10-18T10:15:19+00:00 |

### Concentração por repositório

| metric                      |      value |
|:----------------------------|-----------:|
| repository_hhi              |  0.0170068 |
| top_1_repository_percent    |  6.49378   |
| top_5_repositories_percent  | 20.4435    |
| top_10_repositories_percent | 31.426     |
| top_20_repositories_percent | 47.1658    |

## 5. Prontidão das questões de pesquisa

| research_question             | status   | evidence                                                                 |
|:------------------------------|:---------|:-------------------------------------------------------------------------|
| RQ1_pattern_frequency         | ready    | raw_text present in 391421/391421 records                                |
| RQ2_issue_activity_type       | ready    | 2 normalized type values; labels present in 190047/391421                |
| RQ3_resolution_and_discussion | ready    | 361439 valid resolution intervals; comment text present in 240076/391421 |

### Completude dos campos científicos

| field                 |   empty_count |   empty_percent |
|:----------------------|--------------:|----------------:|
| clean_text            |             0 |      0          |
| closed_at             |         29981 |      7.65953    |
| concatenated_comments |        151345 |     38.6655     |
| issue_body            |         10589 |      2.70527    |
| issue_title           |             4 |      0.00102192 |
| labels                |        201374 |     51.4469     |
| raw_text              |             0 |      0          |
| repository_category   |             0 |      0          |
| stemmed_text          |             0 |      0          |

### Exceções e inconsistências

| exception                             |   count |     percent |
|:--------------------------------------|--------:|------------:|
| filtered_comments_exceed_total        |      70 | 0.0178836   |
| filtered_comment_count_without_text   |       2 | 0.000510959 |
| closed_at_before_created_at           |       1 | 0.000255479 |
| updated_at_before_created_at          |       1 | 0.000255479 |
| comment_text_with_zero_filtered_count |       0 | 0           |
| closed_state_without_closed_at        |       0 | 0           |
| invalid_closed_at                     |       0 | 0           |
| invalid_comments_count_filtered       |       0 | 0           |
| invalid_comments_count                |       0 | 0           |
| invalid_created_at                    |       0 | 0           |
| invalid_updated_at                    |       0 | 0           |
| issue_with_positive_commits_count     |       0 | 0           |
| invalid_commits_count                 |       0 | 0           |
| negative_comments_count               |       0 | 0           |
| negative_comments_count_filtered      |       0 | 0           |
| open_state_with_closed_at             |       0 | 0           |
| negative_commits_count                |       0 | 0           |
| pull_request_missing_commits_count    |       0 | 0           |
| raw_text_does_not_contain_body        |       0 | 0           |
| raw_text_does_not_contain_title       |       0 | 0           |
| year_mismatch                         |       0 | 0           |

## 6. Recortes operacionais

| metric                                        |   value | status   | notes                                      |
|:----------------------------------------------|--------:|:---------|:-------------------------------------------|
| master_rows                                   |  391421 | info     | nan                                        |
| master_unique_issue_ids                       |  391421 | info     | nan                                        |
| slice_file_count                              |     214 | info     | nan                                        |
| ignored_glob_matches                          |       0 | info     | Only slice_####.csv files are validated.   |
| slice_total_rows                              |  391421 | info     | nan                                        |
| slice_union_unique_issue_ids                  |  391421 | info     | nan                                        |
| schema_mismatch_files                         |       0 | pass     | nan                                        |
| invalid_slice_sizes                           |       0 | pass     | Expected 1835; final slice may be smaller. |
| duplicate_issue_ids_within_slices_after_first |       0 | pass     | nan                                        |
| issue_ids_overlapping_between_slices          |       0 | pass     | nan                                        |
| issue_ids_not_found_in_master                 |       0 | pass     | nan                                        |
| master_issue_ids_missing_from_slices          |       0 | pass     | Coverage mode: full                        |

## 7. Partições de avaliação

| partition   |   rows |   unique_repositories |   top_repository_percent |   unique_raw_text_hashes | sha256                                                           |
|:------------|-------:|----------------------:|-------------------------:|-------------------------:|:-----------------------------------------------------------------|
| development |   1835 |                   248 |                  6.21253 |                     1835 | a931dc946ae5364aece1e93c1a649ac9000f03bb84b9e167a2595d8caf72468c |
| validation  |   1835 |                   251 |                  6.59401 |                     1835 | 7da64ea31998f18ca151eec8f273b09e6fc4628280c37c8419e79fe5d51553f5 |
| holdout     |   1835 |                   241 |                  6.53951 |                     1835 | b336d08019c7343974ca82547d86b17e88cd40f858ccaf82d3c18f2ffc910bfe |

### Distância em relação ao corpus

| partition   | dimension                     |   total_variation_distance |
|:------------|:------------------------------|---------------------------:|
| development | repository_category_canonical |                 0.00690374 |
| development | type                          |                 0.00200229 |
| development | data_source                   |                 0.00145165 |
| development | year                          |                 0.0240223  |
| validation  | repository_category_canonical |                 0.00690374 |
| validation  | type                          |                 0.00200229 |
| validation  | data_source                   |                 0.00145165 |
| validation  | year                          |                 0.0191987  |
| holdout     | repository_category_canonical |                 0.00690374 |
| holdout     | type                          |                 0.00200229 |
| holdout     | data_source                   |                 0.00145165 |
| holdout     | year                          |                 0.0314523  |

### Vazamento por texto repetido

Grupos `raw_text_sha256` presentes em mais de uma partição: **0**.

## 8. Gates recomendados

A execução da LLM só deve avançar quando:

1. O corpus canônico não contiver `issue_id` duplicado.
2. Conflitos substantivos entre fontes estiverem zerados ou documentados.
3. Os recortes operacionais cobrirem integralmente o corpus, sem sobreposição.
4. Development, validation e holdout não compartilharem `raw_text_sha256`.
5. Os campos necessários às RQs tiverem completude e consistência aceitáveis.
6. As amostras humanas forem geradas exclusivamente a partir da partição de desenvolvimento.
