---
id: SPEC-0027
title: "second-brain: ajustes do lint, da busca e da exportação"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0023, SPEC-0024, SPEC-0026]
consumes_contract: []
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/maintenance.md, skills/second-brain/references/providers.md, skills/second-brain/references/config.md, skills/second-brain/references/notebooklm.md, skills/second-brain/references/search.md, skills/second-brain/references/query-flow.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0008]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0027 — second-brain: ajustes do lint, da busca e da exportação

## 1. Problema
A revisão G4 da SPEC-0023 aprovou o `lint` e apontou seis pontos.

1. (Separado para a SPEC-0028, a pedido do usuário em 2026-10-30.) A conferência dos padrões de conflito com cópias reais de cada provedor.
2. Um padrão escrito pelo usuário com backtracking catastrófico, como `(?P<base>(a+)+)b\.md$`, trava o `lint` e o `doctor`. Como o `brain-config.yml` é sincronizado, trava todas as máquinas.
3. Os padrões genéricos diferenciam maiúsculas: `Plano Conflict.md` não é detectado.
4. O `SKILL.md` sugere `index` para resolver uma nota órfã, mas isso não adianta para uma nota sem contexto.
5. Um caminho fora da pasta `files` (`../../x`, `/etc/hosts`) aparece como "não existe na pasta files".
6. `--only ""` mostra a mensagem "regra desconhecida:  —", com o nome da regra vazio.

A revisão G4 da SPEC-0024 (exportação para o NotebookLM) aprovou e apontou mais quatro pontos:

7. Se a escrita falha no meio, os arquivos já gravados ficam em `--out`. A pasta fica não vazia e bloqueia uma nova tentativa, com a mensagem "já existe", que confunde.
8. Duas notas cujos títulos só diferem na normalização Unicode (NFC e NFD) geram o mesmo nome de arquivo no APFS, e a exportação falha com um pacote parcial.
9. `flatten_links` reescreve wikilinks dentro de código (`` `[[x]]` `` vira `` `x` ``), o que altera exemplos de código.
10. Só o MOC exportado é bloqueado. Um MOC de outro contexto serve de caminho, e `export-notebooklm index` exporta quase o vault inteiro.

A revisão G4 da SPEC-0026 (ajustes da busca) aprovou e apontou mais quatro pontos:

11. O `lint` ainda lê arquivos `.md` ocultos, que a varredura da busca já ignora.
12. A exclusão de `index.md` e `log.md` compara o caminho exato, então não funciona quando muda a caixa (`Index.md`) ou a forma Unicode.
13. Dentro de um bloco ```, uma linha como "```python" fecha o bloco, mas o CommonMark não aceita texto depois de uma cerca de fechamento.
14. Em `references/search.md` há uma linha longa fora da quebra do arquivo, e o `references/query-flow.md` não diz que o `context` não expande pelo `index.md` nem pelo `log.md`.

## 2. Causa Raiz
Em `skills/second-brain/scripts/brain.py`:
- `GENERIC_CONFLICT_PATTERNS` não tem `(?i)`;
- `compile_conflict_patterns` aceita qualquer regex, sem limite;
- a mensagem de `check_missing_file` não diferencia "fora da pasta files" de "não existe";
- a validação de `--only` não trata uma lista vazia.

O texto da sugestão de órfã está no `SKILL.md`.

## 3. Mudança Proposta
- O padrão genérico de "conflict" passa a ignorar maiúsculas.
- Padrões com quantificador aninhado (`(…+)+`, `(…*)*` e variações) são recusados com achado `config`. Cada padrão também tem limite de tamanho. `config.md` e `providers.md` avisam sobre isso.
- `missing-file` mostra o detalhe "fora da pasta files" quando é o caso, e `maintenance.md` diz isso.
- `--only` vazio sai com 2 e a mensagem "nenhuma regra em --only".
- O `SKILL.md` diz que o `index` só resolve órfãs que têm contexto; nas demais, usar `relate` ou uma nota nova.
- A exportação grava numa pasta temporária ao lado de `--out` e move tudo no final. Se falhar, nada fica em `--out`.
- Os nomes exportados são comparados com `unicodedata.normalize("NFC", …).casefold()`.
- `flatten_links` não mexe em código, nem em cercas nem em código inline.
- Na exportação, todos os MOCs (`layout.mocs`) ficam bloqueados como caminho, e `index.md` e `log.md` são recusados como MOC, com exit 2.
- O `lint` ignora `.md` ocultos como notas, com o mesmo filtro da varredura.
- `generated_paths` e as comparações de caminho de layout passam a usar `_link_key` (caixa e NFC).
- Uma cerca de fechamento só aceita espaços depois da marca.
- `search.md` tem a linha longa quebrada, e `query-flow.md` diz que o `context` não expande pelo `index.md` nem pelo `log.md`.

NÃO muda: as regras, as severidades, os formatos e os códigos de saída da SPEC-0023, nem o formato do pacote da SPEC-0024.

**Padrão seguido:** as funções `check_*`, `compile_conflict_patterns` e os testes `test_lint*.py` da SPEC-0023; `export_*`, `flatten_links` e `test_notebooklm*.py` da SPEC-0024.

**Rollback:** `git revert` do commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes da SPEC-0023 fixam o comportamento que não muda.
- **UT-01** — Dado o padrão `(?P<base>(a+)+)b\.md$`, quando `compile_conflict_patterns` roda, então ele é recusado como achado `config` sem tentar casar nenhum nome; e dado `Plano Conflict.md` ao lado de `Plano.md`, quando `check_conflict_copy` roda com os padrões genéricos, então a cópia é detectada.
- **UT-02** — Dado uma nota com `files: [../../x.pdf]`, quando `check_missing_file` roda, então o detalhe diz "fora da pasta files".
- **UT-03** — Dado o texto `` `[[codigo]]` e [[Nota]] ``, quando `flatten_links` roda, então devolve `` `[[codigo]]` e Nota ``; e dado dois títulos "Séries" em NFC e NFD, quando `export_name` roda, então gera nomes diferentes.
- **IT-02** — Dado uma falha simulada na escrita do terceiro arquivo, quando roda `export-notebooklm`, então `--out` continua vazio; e dado `export-notebooklm index`, então sai com 2; e dado uma nota citada que liga ao MOC de outro contexto, então as notas alcançadas só por esse MOC não entram.
- **UT-04** — Dado um bloco ``` com uma linha "```python" dentro e `#x` depois, quando `parse_note` roda, então `#x` não é tag; e dado `layout.index: index.md` com o arquivo `Index.md`, quando `generated_paths` é usado em `related`, então `Index.md` fica de fora.
- **IT-03** — Dado um vault com `.oculta.md` sem links, quando roda `lint`, então nenhum achado cita `.oculta.md`; e dado `references/query-flow.md`, quando lido, então diz que o `context` não expande pelo `index.md` nem pelo `log.md`.
- **IT-01** — Dado `--only ""`, quando roda `lint`, então sai com 2 e mostra "nenhuma regra em --only"; e dado um `brain-config.yml` com o padrão catastrófico e uma nota de 40 caracteres, quando roda `lint` e `doctor`, então os dois terminam em menos de 3 s com o achado `config`.

## 5. Questões em Aberto
- [x] A conferência com cópias reais de cada provedor fica aqui? — Não: vai para a SPEC-0028, separada, para esta spec seguir já (thomas, 2026-10-30)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 a UT-04 e IT-01 a IT-03 com a tag `SPEC-0027:<ID>`, falhando pelo motivo certo
- [x] Green: ajustes do lint, da busca e da exportação da seção 3
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy (G6) — N/A: pilar entrega dispensado
- [x] Relatório de Entrega e CHANGELOG (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 38e7d71 | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=33)) — 1b06b2a | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — e8e1624 | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — e8e1624 | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (e8e1624; 8 achados da 1ª rodada corrigidos; 1 minor: janela de corrida do os.replace não documentada) — e8e1624 | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 11849fb | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 8d6efbb | 2026-10-30 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
Ajustes de robustez em três áreas.
- **lint:** padrões de conflito que travariam a execução são recusados, "conflict" vale com qualquer maiúscula, a mensagem diz quando o caminho está fora da pasta `files`, `--only` vazio é tratado, `.md` ocultos são ignorados e a dica de nota órfã ficou correta.
- **busca:** a cerca de código fecha certo, e `index.md` e `log.md` são reconhecidos mesmo com outra caixa ou outra forma Unicode.
- **exportação:** grava numa pasta temporária, e uma falha ou um Ctrl-C não deixa pacote parcial. Também preserva código, compara nomes com normalização, bloqueia todos os MOCs e recusa `--out` dentro do vault mesmo digitado com outra caixa.

### Como foi feito
`brain.py` (versão 2026.10.11) ganhou:
- `nested_quantifier` e `_repeats_group` (checagem de melhor esforço, documentada com o exemplo não detectado `(a|aa)+`), além do limite de 500 caracteres por padrão;
- `fenced_lines` e `CLOSING_FENCE_RE`;
- `INLINE_CODE_RE` para sequências de crases de qualquer tamanho;
- `export_key`, `export_staging` e `write_export`, com limpeza em qualquer exceção;
- `inside_on_disk`, com `samefile` nos ancestrais, usado na exportação, no `process --out` e no `files` do `init`/`doctor`;
- `hidden_note`, compartilhado entre a varredura e o lint;
- `generated_paths` e `moc_notes` comparando com `_link_key`.

Os padrões de conflito conferidos com cópias reais foram separados na SPEC-0028, a pedido do usuário. A 1ª revisão G4 pediu mudanças: 1 major (`(a+){20}` passava e travava o lint) e 7 minor. Os testes de regressão vieram antes da correção (red 290fef7; fix fdd1a87 e e8e1624), e a 2ª revisão aprovou com 1 minor aceito: a janela de corrida entre a checagem e o `os.replace` na mudança arquivo a arquivo para um `--out` existente não está documentada; só importa se outro programa escrever em `--out` durante a exportação.

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
Red 1b06b2a: os testes do plano tinham 33 falhas, contando os subtestes, registradas no G1. Red 290fef7: as regressões da revisão, com 16 falhas. Green a566fea, 26138b3, fdd1a87 e e8e1624: todos passam e a suíte completa passa (G2, G5 e CI do PR #15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Padrões com quantificador aninhado ou repetição contada recusados; conflict sem diferenciar maiúsculas | PASS | `test_lint_review.py::ConflictPatternsReviewTest.test_nested_quantifiers_and_too_long_patterns_are_refused_without_matching; test_lint_review.py::ConflictPatternsReviewTest.test_safe_patterns_are_still_accepted; test_lint_review.py::ConflictPatternsReviewTest.test_generic_conflict_pattern_ignores_case; test_spec0027_review.py::RepeatedGroupPatternTest.test_a_group_with_a_repeat_inside_followed_by_a_count_is_refused; test_spec0027_review.py::RepeatedGroupPatternTest.test_a_counted_group_without_a_repeat_inside_is_still_accepted; test_spec0027_review.py::PatternDocsTest.test_docs_say_the_check_is_best_effort_and_advise_simple_patterns` — CI do PR #15 em 11849fb (run 41110986589, Python 3.9 e 3.15) e suíte local (G5) |
| UT-02 | Detalhe "fora da pasta files" | PASS | `test_lint_review.py::MissingFileReviewTest.test_a_path_outside_the_files_folder_says_so` — CI do PR #15 em 11849fb (run 41110986589, Python 3.9 e 3.15) e suíte local (G5) |
| UT-03 | flatten_links preserva código; nomes exportados comparados com NFC e casefold | PASS | `test_notebooklm_review.py::FlattenLinksReviewTest.test_flatten_links_keeps_code_untouched; test_notebooklm_review.py::ExportNameReviewTest.test_names_that_differ_only_in_unicode_form_or_case_folding_do_not_collide; test_spec0027_review.py::FlattenInlineCodeTest.test_inline_code_with_backtick_runs_of_any_length_is_kept` — CI do PR #15 em 11849fb (run 41110986589, Python 3.9 e 3.15) e suíte local (G5) |
| IT-02 | Exportação sem pacote parcial (falha ou Ctrl-C); index/log recusados como MOC; MOCs bloqueados; --out com outra caixa recusado | PASS | `test_notebooklm_review.py::ExportReviewCliTest.test_a_failure_while_writing_leaves_out_empty_and_a_retry_works; test_notebooklm_review.py::ExportReviewCliTest.test_index_and_log_are_refused_as_moc; test_notebooklm_review.py::ExportReviewCliTest.test_the_moc_of_another_context_is_never_walked_through; test_spec0027_review.py::ExportSafetyReviewTest.test_an_interruption_while_writing_leaves_no_staging_folder; test_spec0027_review.py::ExportSafetyReviewTest.test_out_inside_the_vault_with_another_case_is_refused` — CI do PR #15 em 11849fb (run 41110986589, Python 3.9 e 3.15) e suíte local (G5) |
| UT-04 | Cerca de fechamento só com espaços; index/log reconhecidos por caixa e NFC | PASS | `test_search_layout_review.py::ClosingFenceTest.test_a_closing_fence_accepts_only_spaces_after_the_mark; test_search_layout_review.py::LayoutFilesKeyTest.test_related_excludes_index_and_log_regardless_of_case_and_unicode_form; test_search_layout_review.py::LayoutFilesKeyTest.test_context_never_walks_through_index_or_log_regardless_of_case_and_unicode_form` — CI do PR #15 em 11849fb (run 41110986589, Python 3.9 e 3.15) e suíte local (G5) |
| IT-03 | lint ignora .md ocultos; dica de órfã alinhada; docs de search, query-flow e maintenance | PASS | `test_lint_review.py::LintReviewCliTest.test_hidden_md_files_are_not_lint_notes; test_lint_review.py::OrphanHintTest.test_skill_md_says_index_only_helps_orphans_with_a_context; test_search_layout_review.py::ReferencesReviewTest.test_search_md_text_lines_follow_the_file_wrap; test_search_layout_review.py::ReferencesReviewTest.test_query_flow_says_context_does_not_expand_through_index_or_log; test_spec0027_review.py::OrphanContextTest.test_orphan_suggestion_mentions_the_context; test_spec0027_review.py::OrphanContextTest.test_maintenance_orphan_row_matches_skill_md` — CI do PR #15 em 11849fb (run 41110986589, Python 3.9 e 3.15) e suíte local (G5) |
| IT-01 | --only vazio; lint e doctor com padrão catastrófico abaixo de 3 s | PASS | `test_lint_review.py::LintReviewCliTest.test_empty_only_exits_2_with_the_message; test_lint_review.py::LintReviewCliTest.test_lint_refuses_the_catastrophic_pattern_in_under_3_seconds; test_lint_review.py::LintReviewCliTest.test_doctor_refuses_the_catastrophic_pattern_in_under_3_seconds; test_spec0027_review.py::RepeatedGroupCliTest.test_lint_refuses_the_counted_nested_pattern_in_under_3_seconds; test_spec0027_review.py::RepeatedGroupCliTest.test_doctor_refuses_the_counted_nested_pattern_in_under_3_seconds` — CI do PR #15 em 11849fb (run 41110986589, Python 3.9 e 3.15) e suíte local (G5) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6)
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #15. Versão da skill: 2026.10.11. Rollback: revert do merge.

### Pendências
SPEC-0028 (avulsa): padrões de conflito conferidos com cópias reais de cada provedor, que dependem das cópias do usuário. Minor aceito: a janela de corrida do `os.replace` na exportação para um `--out` existente.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
