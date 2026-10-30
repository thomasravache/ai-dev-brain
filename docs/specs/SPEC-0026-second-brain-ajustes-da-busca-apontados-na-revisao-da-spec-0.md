---
id: SPEC-0026
title: "second-brain: ajustes da busca apontados nas revisões das SPEC-0018 e SPEC-0020"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0020]
consumes_contract: []
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/references/search.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0026 — second-brain: ajustes da busca apontados nas revisões das SPEC-0018 e SPEC-0020

## 1. Problema
A revisão G4 da SPEC-0018 aprovou a entrega e reproduziu à mão casos que a busca trata errado:
1. Um arquivo oculto como `.dot.md` aparece nos resultados. O Obsidian não indexa arquivos ocultos.
2. Um link digitado em NFC (`[[Ação]]`) não encontra um arquivo cujo nome está gravado em NFD, o que é comum no macOS e em alguns provedores de sincronização.
3. Uma cerca de 4 crases (````) é fechada por uma de 3, e o que vem depois dela é lido como texto (`#x` vira tag).
4. Termos de 1 caractere, como o `s` de `[[Ref#s]]`, contam na pontuação. Por causa disso, `log.md` aparece como "relacionada" a qualquer nota.
5. No `context` (SPEC-0020), o `index.md` liga as notas recentes. Por isso ele vira um atalho na expansão de vizinhos e traz como `link:2` notas sem relação real. A revisão da SPEC-0020 viu o mesmo com o MOC, que já foi corrigido lá.
6. `references/search.md` diz que só anexos fora do vault aparecem em `broken`, mas todo `![[anexo]]` aparece lá.

Há também dois problemas de manutenção do código: as marcas de acento estão no código como caracteres literais invisíveis, e `Note(**campos)` aceita nomes de campo desconhecidos sem avisar.

## 2. Causa Raiz
Em `skills/second-brain/scripts/brain.py`:
- `ignored_dir` filtra pastas ocultas, mas não arquivos ocultos;
- `_link_key` não normaliza Unicode;
- `FENCE_RE` não guarda o tamanho da cerca;
- a tokenização não tem tamanho mínimo de termo;
- `COMBINING_RE` usa caracteres literais;
- `Note.__init__` ignora chaves extras.

O texto errado sobre anexos está em `references/search.md`.

## 3. Mudança Proposta
- Arquivos `.md` ocultos (nome começando com `.`) são ignorados pela varredura.
- `_link_key` e as chaves de caminho passam por `unicodedata.normalize("NFC", …)`.
- Uma cerca só fecha com outra do mesmo caractere e com pelo menos o mesmo tamanho.
- Termos com menos de 2 caracteres são descartados na tokenização.
- `log.md` e `index.md` (`layout.log` e `layout.index`) ficam fora de `related` e nunca servem de caminho na expansão do `context`, mas continuam em `search`.
- `COMBINING_RE` vira um filtro com `unicodedata.combining`.
- `Note` recusa campos desconhecidos com `TypeError`.
- `references/search.md` diz que todo `![[anexo]]` aparece em `broken`. Distinguir anexo de nota quebrada fica para o `lint` (SPEC-0023).

NÃO muda: os pesos, os formatos JSON, as mensagens e os códigos de saída da SPEC-0018. A assinatura real `resolve_link(target, paths)`, fixada pelos testes da SPEC-0018, continua como está, e as specs seguintes a usam.

**Padrão seguido:** as funções de leitura e busca da SPEC-0018 no `brain.py` e os testes `test_search.py` e `test_search_cli.py`.

**Rollback:** `git revert` do commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes da SPEC-0018 já fixam o comportamento que não muda.
- **UT-01** — Dado o arquivo `.dot.md`, um link `[[Ação]]` (NFC) para `Ação.md` gravado em NFD, uma cerca ```` com ``` dentro e `#x` depois, e o texto `[[Ref#s]]`, quando `scan_vault`, `resolve_link` e `parse_note` rodam, então `.dot.md` não aparece, o link resolve, `#x` não é tag e `s` não é termo.
- **UT-02** — Dado um `Note` criado com um campo desconhecido, quando é instanciado, então lança `TypeError`.
- **IT-01** — Dado um vault criado pelo `init` com notas e com o `log.md` cheio de linhas de log, quando roda `related --note <nota>`, então `log.md` e `index.md` não aparecem, e `search` ainda encontra o `log.md` pelo termo `init`.
- **IT-02** — Dado um vault em que o `index.md` lista as notas recentes, quando roda `context <termo> --hops 2 --json`, então nenhuma nota aparece como `link:N` alcançada só pelo `index.md` ou pelo `log.md`.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01, UT-02, IT-01 e IT-02 com a tag `SPEC-0026:<ID>`, falhando pelo motivo certo
- [x] Green: arquivos ocultos, NFC, cercas, termos curtos, `log.md`/`index.md` fora de `related` e da expansão do `context`, `unicodedata.combining`, `Note` estrito, texto de `search.md`
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
| G0 Spec | PASS | validate: 0 erro(s) — e26c5a4 | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=11)) — 9d2f379 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 116fed3 | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 116fed3 | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (116fed3; 4 minor encaminhados para a SPEC-0027) — 116fed3 | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 423ad9d | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — f143a82 | 2026-10-30 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
A busca passa a ignorar arquivos ocultos. Ela resolve links com acento mesmo quando o nome do arquivo está gravado em outra forma Unicode (NFD, comum no macOS), trata direito cercas de código de 4 crases ou de tils e descarta termos de 1 caractere. Por fim, deixa `log.md` e `index.md` fora das relacionadas e da expansão do `context`; eles continuam encontráveis pelo `search`.

### Como foi feito
`brain.py` (versão 2026.10.10) mudou em `walk_notes` (ignora ocultos), `_link_key` (normalização NFC), `FENCE_RE` e `prose` (a cerca fecha com o mesmo caractere e tamanho mínimo), `tokenize` (`MIN_TERM = 2`), `fold` (agora usa `unicodedata.combining`), `Note` (recusa campos extras) e `generated_paths`. Esta última é usada por `related`, `build_context` e `export_notes`. `references/search.md` documenta as regras e diz que todo `![[anexo]]` aparece em `broken`. A revisão G4 aprovou com 4 minor, encaminhados para a SPEC-0027.

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
Red 9d2f379: os testes UT-01, UT-02, IT-01 e IT-02 tinham 11 falhas, contando os subtestes, registradas no G1. Green 743c8b0 e 116fed3: todos passam e a suíte completa passa (G2, G5 e CI do PR #15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Ocultos fora da varredura, links NFC/NFD, cercas de código, termos curtos e texto do search.md | PASS | `test_search_review.py::HiddenAndUnicodeScanTest.test_hidden_md_files_are_not_scanned; test_search_review.py::HiddenAndUnicodeScanTest.test_nfc_link_resolves_to_a_file_name_stored_in_nfd; test_search_review.py::ParseFixesTest.test_link_and_path_keys_are_compared_in_nfc; test_search_review.py::ParseFixesTest.test_a_fence_closes_only_with_the_same_char_and_at_least_the_same_length; test_search_review.py::ParseFixesTest.test_terms_shorter_than_two_characters_do_not_count; test_search_review.py::SearchDocTest.test_search_md_says_every_attachment_embed_is_broken_in_links` — CI do PR #15 em 423ad9d (run 41101566278, Python 3.9 e 3.15; pr-check no run 41101569025) e suíte local (G5) |
| UT-02 | Note recusa campos desconhecidos | PASS | `test_search_review.py::StrictNoteTest.test_note_rejects_unknown_fields` — CI do PR #15 em 423ad9d (run 41101566278, Python 3.9 e 3.15; pr-check no run 41101569025) e suíte local (G5) |
| IT-01 | log.md e index.md fora de related e ainda achados pelo search | PASS | `test_search_review.py::RelatedLayoutFilesCliTest.test_related_never_lists_log_or_index_but_search_still_finds_them` — CI do PR #15 em 423ad9d (run 41101566278, Python 3.9 e 3.15; pr-check no run 41101569025) e suíte local (G5) |
| IT-02 | context nunca expande pelo index.md ou pelo log.md | PASS | `test_search_review.py::ContextLayoutFilesCliTest.test_context_never_expands_through_index_or_log` — CI do PR #15 em 423ad9d (run 41101566278, Python 3.9 e 3.15; pr-check no run 41101569025) e suíte local (G5) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6)
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #15. Versão da skill: 2026.10.10. Rollback: revert do merge.

### Pendências
SPEC-0027 recebe os minor da revisão: o `lint` ainda lê `.md` ocultos; a exclusão de `index.md` e `log.md` compara o caminho exato, sem considerar maiúsculas nem a forma Unicode; uma cerca de fechamento com texto depois ("```python"); uma linha longa no `search.md`; e uma linha no `query-flow.md` dizendo que o `context` não expande pelo `index.md` nem pelo `log.md`.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
