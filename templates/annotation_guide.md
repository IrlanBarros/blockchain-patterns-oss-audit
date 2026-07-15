# Guia mínimo de anotação

## Unidade de anotação

1. **Issue/PR:** determina se o texto contém alguma discussão substantiva de blockchain design pattern.
2. **Par `(issue_id, pattern)`:** confirma ou refuta cada padrão candidato individualmente.

## Veredito por padrão

- `yes`: o texto discute o mecanismo, problema ou decisão de design do padrão.
- `no`: existe apenas sobreposição lexical, falso-amigo ou outro mecanismo.
- `uncertain`: há indício, mas o contexto não sustenta uma decisão segura.

## Status de adoção

- `implemented`
- `implementation_proposed`
- `implementation_in_progress`
- `problem_with_implementation`
- `replacement_or_removal`
- `conceptual_discussion`
- `superficial_mention`
- `not_related`

## Evidência

Copie um trecho literal curto. Registre a localização:

- `title`
- `body`
- `comment`
- `pull_request_description`

A palavra-chave isolada não é evidência suficiente.

## Tipos de atividade

- `bug`
- `feature`
- `refactoring`
- `security`
- `performance`
- `documentation`
- `testing`
- `build_dependency`
- `support_question`
- `other`

## Confiança

- `high`
- `medium`
- `low`

## Regras de independência

- Os anotadores não devem ver a saída da LLM antes de concluir a anotação.
- Divergências devem ser adjudicadas e registradas.
- Development pode orientar refinamentos; validation e holdout não podem ser usados para ajustar prompts.
