# Escopo da auditoria v3

## Incluído

- Verificação do arquivo bruto local e geração de fingerprint SHA-256.
- Canonicalização de registros duplicados entre `provider` e `community`.
- Uso de `owner/repository` como identidade de projeto.
- Uma linha canônica por `issue_id`.
- Preservação da proveniência em `data_sources_seen`.
- Auditoria de todos os campos necessários às RQs: tipo, estado, datas, comentários, commits, labels e componentes textuais.
- Auditoria explícita do corpus canônico.
- Criação e validação dos recortes operacionais de 1.835 registros.
- Criação de development, validation e holdout sem vazamento de textos repetidos.
- Geração de amostras humanas reproduzíveis para smoke test e piloto.
- Relatório consolidado e manifests com hashes.

## Excluído

- Repetir a seleção dos repositórios Web3 feita pelos autores do dataset.
- Refazer a coleta via GitHub.
- Refazer a remoção upstream de bots.
- Refazer limpeza, stemming ou normalização textual upstream.
- Excluir textos curtos, longos ou repetidos apenas por heurística.
- Classificar padrões de blockchain; isso pertence ao pipeline científico posterior.
- Alterar silenciosamente conflitos entre fontes.

## Princípio central

O projeto audita e prepara o corpus para o estudo. Ele não transforma problemas de qualidade em decisões silenciosas. Conflitos substantivos entre duplicatas interrompem a canonicalização por padrão e precisam ser documentados.
