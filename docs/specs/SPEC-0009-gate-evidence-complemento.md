---
id: SPEC-0009
title: gate --run grava o complemento de --evidence
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-10-14
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, CHANGELOG.md]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0009 — gate --run grava o complemento de --evidence

## 1. Problema
A ajuda de `gate` diz que `--evidence` é "texto de evidência (com --manual) ou complemento", mas com `--run` o texto é descartado. Em 2026-10-14 a nota de bypass do G5 sumiu dos registros e foi preciso regravar com `--manual`.

## 2. Causa Raiz
O caminho `--run` de `cmd_gate` monta a evidência só com as partes geradas pela execução; o argumento `evidence` não é passado para esse caminho.

## 3. Mudança Proposta
Com `--run`, `--evidence "<texto>"` entra no fim da evidência gerada como `nota: <texto>`, antes do SHA. Não muda: `--manual`, `--na`, `--fail`, `--by`, nem o PASS/FAIL (a nota nunca altera o resultado).

**Padrão seguido:** montagem de `parts` em `gate_run` (cada parte separada por "; ").

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — os outros caminhos de `gate` já usam o texto.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `test_run_generates_evidence_and_manual_is_flagged` fixa o caminho `--run` e continua passando.
- **UT-01** — Dado uma spec com G0 pendente, quando roda `gate SPEC-0001 G0 --run --evidence "bypass até amanhã"`, então a linha do G0 tem a evidência gerada, `nota: bypass até amanhã` e o SHA, e o status é o mesmo que sem a nota.
- Integração/E2E: N/A — UT-01 roda o comando pela CLI num repositório temporário.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
- [x] Red: UT-01 com a tag `SPEC-0009:UT-01`, falhando pelo motivo certo
- [x] Green: correção mínima, seguindo o padrão citado
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `SDD_TOOL_VERSION` e CHANGELOG (ADR-0005)
- [x] Review (G4), integração (G5, bypass local enquanto a CI estiver bloqueada) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 59a1d33 | 2026-10-14 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=1, skipped=1)) — fbce02b | 2026-10-14 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 1388b43 | 2026-10-14 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 1388b43 | 2026-10-14 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (modo solo) — 0 blocker/major; minor (pendência, fora do escopo): test_spec_graph.py não isola o registro do usuário (SDD_CONFIG_HOME/HOME) desde a SPEC-0003; um projects.json inválido na máquina quebraria a suíte antiga — 1388b43 | 2026-10-14 |
| G5 Integração & CI | PASS | test exit 0 (OK (skipped=1)); arch_test exit 0 (OK); nota: CI do GitHub verde no PR #3 em ee02ae2: ci 3.9 e 3.15 (run 38677000910) e sdd/pr-check (run 38677000897) — substitui o bypass local — 138ad48 | 2026-10-15 |
| H2 Integração aprovada | PASS | aprovado por thomas — autorizou os merges em 2026-10-15 ('pode ir seguindo com os merges quando tudo passar'), com G5 verde na CI do GitHub | 2026-10-15 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): a skill vale na main pelo link simbólico | 2026-10-15 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — daa4847 | 2026-10-15 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-14 | G1 | decisão | Onda aguarda o H2 das specs abertas (SPEC-0001, 0003–0006), adiado: merges ficam para depois e o GitHub Actions está bloqueado (IMP-02) | waves/next: arquivos em comum com specs em andamento | thomas | thomas autorizou em 2026-10-14 continuar todas as implementações antes dos merges ('precisamos continuar todas as implementações'); base: sdd/SPEC-0002, que já contém as specs anteriores | 2026-10-14 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
`gate --run --evidence` grava o texto como `nota:` na evidência, como a ajuda descreve.

### Como foi feito
O texto de `--evidence` é anexado à evidência gerada pelo `--run`, antes do SHA.

### Prova de Correção
Red: commit fbce02b — `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (FAILED (failures=1, skipped=1)), registrado no G1. Green: commit 1388b43 — suíte exit 0 (OK) no G2, e verde na CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Dado uma spec com G0 pendente, quando roda `gate SPEC-0001 G0 --run --evidence "bypass até amanhã"`, então a linha do G0 tem a evidência… | PASS | `test_spec_graph.py::test_run_keeps_the_evidence_note` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — modo solo (projeto de um mantenedor); merge aprovado por thomas (H2)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: pilar entrega dispensado; vale na `main` pelo link simbólico
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado): passa a valer na `main` com o merge do PR #3, pelo link simbólico `~/.claude/skills/sdd-management`. Versão da ferramenta 2026.10.8. Rollback: revert do merge.

### Pendências
Nenhuma. A cópia `tools/sdd` é atualizada em PR próprio depois do merge (ADR-0005).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
