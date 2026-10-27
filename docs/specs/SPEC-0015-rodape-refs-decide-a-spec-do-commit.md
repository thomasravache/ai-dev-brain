---
id: SPEC-0015
title: Rodapé Refs decide a spec do commit
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-10-27
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/CHANGELOG.md]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-10-27
---

# SPEC-0015 — Rodapé Refs decide a spec do commit

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
O `verify` (G1/G4) e o `pr-check` atribuem um commit a uma spec sempre que o ID dela aparece no assunto ou no corpo da mensagem. Um commit de outra spec que cita a primeira como contexto (ex.: "Consome o contrato SPEC-0005@1.") entra na lista da SPEC-0005: os arquivos dele aparecem como "fora de touches" e ele conta na ordem red/green da spec errada.

- Reproduzir: spec A e spec B; commit de B com `Refs: B` e o corpo citando A; `verify A --base main`.
- Esperado: o commit pertence só a B.
- Impacto: falso FAIL no G1/G4 de quem consome contrato de outra spec. Contornado no Subsolo com uma cópia corrigida de `tools/sdd` (commits 5a96ee1 e 7ecb778 de lá), que a próxima `vendor --force` apagaria sem este fix.

## 2. Causa Raiz
`spec_commits` (`spec_graph.py`) filtra os commits com `\bSPEC-NNNN\b` sobre assunto + corpo, sem distinguir o rodapé `Refs:` (que declara a spec do commit, por convenção do próprio hook `commit-msg`) das menções de contexto.

## 3. Mudança Proposta
- Nova função `commit_spec_refs(subject, body)`: com rodapé `Refs:` que cite spec, só ele conta; sem rodapé (ou com `Refs:` sem spec, ex.: `Refs: #12`), vale qualquer menção no assunto ou no corpo, como hoje.
- `spec_commits` usa essa função no modo normal. Não muda: o modo privado (commits ligados pela branch), o hook `commit-msg`, o `pr-check` além do que herda de `spec_commits`.
- `SDD_TOOL_VERSION` 2026.10.13 e seção no CHANGELOG da skill.

**Padrão seguido:** `SPEC_REF_RE` e o parsing de mensagens já existentes em `spec_graph.py`; testes em `GitChecksTest` de `test_spec_graph.py`.

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — `spec_commits` é o único ponto que liga commit a spec no modo normal.

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0015:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — os testes de `GitChecksTest` fixam a atribuição por menção e continuam passando.
- **UT-01** — Dado a spec A com red e green (`Refs: A`) e um commit da spec B com `Refs: B` cujo corpo cita A, quando roda `verify A --base main`, então sai 0 e sem "fora de touches"; `commit_spec_refs` devolve A para "cita A" sem rodapé e para `[A]` no assunto com `Refs: #12`.
- Integração/E2E: N/A — UT-01 roda o `verify` pela CLI num repositório git temporário (padrão de `GitChecksTest`).

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
- [x] Red: UT-01 com a tag `SPEC-0015:UT-01`, falhando pelo motivo certo
- [x] Green: correção mínima, seguindo o padrão citado
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `SDD_TOOL_VERSION` 2026.10.13 e seção no CHANGELOG da skill (ADR-0005)
- [x] Review (G4), integração (G5) e H2 (política auto-on-green)
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-27 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=2, skipped=1)) — 06190c1 | 2026-10-27 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 40ad050 | 2026-10-27 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — f924585 | 2026-10-27 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (Reviewer independente) — 0 blocker/major; 3 minor aceitos: REFS_TRAILER_RE não aceita espaço antes de 'Refs' nem de ':' (o pr-check aceita); constante longe das outras do topo; qualquer linha 'Refs:' do corpo conta, não só o bloco final de trailers — 1039cea | 2026-10-27 |
| G5 Integração & CI | PASS | test exit 0 (OK (skipped=1)); arch_test exit 0 (OK) — b5d77a6 | 2026-10-27 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-27 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): a skill vale na main pelo link simbólico | 2026-10-27 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 704e957 (árvore suja) | 2026-10-27 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
O `verify` (G1/G4) e o `pr-check` passam a atribuir um commit só às specs do rodapé `Refs:` quando ele cita alguma. Um commit de outra spec que menciona a primeira no corpo (ex.: "Consome o contrato SPEC-0005@1.") deixa de entrar nela, com falso "fora de touches" e ordem red/green errada. Sem rodapé com spec (ou com `Refs: #12`), vale qualquer menção no assunto ou no corpo, como antes; o modo privado não muda.

### Como foi feito
Nova função `commit_spec_refs(subject, body)` em `spec_graph.py`, usada por `spec_commits` no modo normal, seguindo `SPEC_REF_RE` e o parsing de mensagens existente. `SDD_TOOL_VERSION` 2026.10.13 e seção no CHANGELOG da skill (ADR-0005). Minors aceitos na revisão: `REFS_TRAILER_RE` não aceita espaço antes de `Refs` nem de `:` (o regex do corpo do PR no `pr-check` aceita); a constante fica longe das outras do topo; qualquer linha `Refs:` do corpo conta, não só o bloco final de trailers.

### Prova de Correção
Red: commit 06190c1 — `python3 -m unittest discover -s skills/sdd-management/tests` exit 1, com UT-01 vendo `[G4] FAIL arquivos alterados fora de touches: src/b/b.py` (registrado no G1; a segunda falha é o mesmo teste herdado por `PrTitleTest`). Green: commit 32aa65a — suíte OK local (G2 em 40ad050, G5 em b5d77a6) e na CI do PR #14 em 704e957 (run 40581017025, Python 3.9 e 3.15; sdd run 40581017142).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Commit de outra spec com `Refs:` próprio e corpo citando a spec não entra no `verify` dela; sem rodapé com spec, a menção continua valendo | PASS | `test_spec_graph.py::GitChecksTest.test_refs_trailer_decides_commit_owner_over_body_mentions` — CI do PR #14 em 704e957 (run 40581017025) e suíte local (G5) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: pilar entrega dispensado; vale na `main` pelo link simbólico
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado): passa a valer na `main` com o merge do PR #14; as cópias instaladas da skill são sincronizadas depois. Versão da ferramenta 2026.10.13. Rollback: revert do merge.

### Pendências
- Minors do G4 (espaços no regex do rodapé, posição da constante), candidatos a uma spec lite futura.
- Fora desta spec: o `whats-new` rodado da cópia `tools/sdd` de um projeto procura o CHANGELOG em `tools/CHANGELOG.md` e mostra "CHANGELOG da skill não encontrado" — candidato a spec lite.
- A cópia `tools/sdd` deste repositório é atualizada em PR próprio depois do merge (ADR-0005).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
