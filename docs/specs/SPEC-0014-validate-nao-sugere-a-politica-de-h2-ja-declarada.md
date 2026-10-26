---
id: SPEC-0014
title: validate não sugere a política de H2 já declarada
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-10-26
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/CHANGELOG.md]
adrs: []
external: []
size: S
approved_by: thomas
approved_at: 2026-10-26
---

# SPEC-0014 — validate não sugere a política de H2 já declarada

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Com `h2_policy: auto-on-green` declarada e aprovada no `sdd-config`, o `validate` continua avisando "H2 com o mesmo texto em N specs … declare h2_policy: auto-on-green no sdd-config.yml" por causa das specs antigas, que registraram a mesma autorização permanente antes da política existir. O aviso manda fazer o que já foi feito e não some nunca (neste repositório: 9 specs desde 2026-10-15).

## 2. Causa Raiz
`validate_config` (`spec_graph.py:1503`) agrupa os textos de H2 e emite a sugestão sem olhar se a política já está declarada; só as evidências que começam com "política auto-on-green" ficam de fora.

## 3. Mudança Proposta
Com `h2_policy: auto-on-green` válida (com `h2_policy_approved_by` e `h2_policy_approved_at`), a sugestão de declarar a política não é emitida. Não muda: o aviso continua com `per-wave` (ou sem a chave); os erros de política inválida ou sem aprovação registrada; o registro do H2 pela política.

**Padrão seguido:** checagens de `h2_policy` no mesmo trecho de `validate_config` e os testes de `H2PolicyTest` em `test_spec_graph.py`.

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — a sugestão de política só existe para o H2.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `test_repeated_h2_text_suggests_policy` fixa o aviso sem política e continua passando.
- **UT-01** — Dado três specs com o mesmo texto de H2 e `h2_policy: auto-on-green` com `h2_policy_approved_by` e `h2_policy_approved_at`, quando roda `validate`, então a saída não tem "declare h2_policy: auto-on-green".
- Integração/E2E: N/A — UT-01 roda o `validate` pela CLI num repositório temporário (padrão de `H2PolicyTest`).

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
- [x] Red: UT-01 com a tag `SPEC-0014:UT-01`, falhando pelo motivo certo
- [x] Green: correção mínima, seguindo o padrão citado
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `SDD_TOOL_VERSION` 2026.10.12 e seção no CHANGELOG da skill (ADR-0005)
- [x] Review (G4), integração (G5) e H2 (política auto-on-green)
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — ccf95e5 | 2026-10-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=2, skipped=1)) — c22b6bd | 2026-10-26 |
| G2 Green | PASS | MANUAL: CI do GitHub no PR #12 em 96d612f (run 40398202620): ruff check 'All checks passed!' e 159 testes OK em Python 3.9 e 3.15; local (macOS) 159 testes OK — só o lint não roda aqui (sem uv/ruff) | 2026-10-26 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 1fbdaa0 | 2026-10-26 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (Reviewer independente) — 0 blocker/major; 2 minor aceitos: falta teste de H2 repetido com auto-on-green sem aprovação (já gera ERROR), e o teste de tempo do leak-check (SPEC-0004:IT-10) oscila sob carga (fora desta spec) — ed05463 | 2026-10-26 |
| G5 Integração & CI | PASS | test exit 0 (OK (skipped=1)); arch_test exit 0 (OK); nota: CI do GitHub verde no PR #12 em 83698b3: ci 3.9 e 3.15 (run 40399136640) e sdd/pr-check (run 40399136609); a reprovação anterior foi o teste de tempo SPEC-0004:IT-10 sob carga (load ~14) — 79cc2fc | 2026-10-26 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-26 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): a skill vale na main pelo link simbólico | 2026-10-26 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 9ba962b | 2026-10-26 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
Com `h2_policy: auto-on-green` declarada e aprovada, o `validate` deixa de sugerir declarar a política por causa de specs antigas que repetem a mesma autorização de H2. Sem a política, o aviso continua.

### Como foi feito
Em `validate_config` (`spec_graph.py`), a condição da política aprovada virou `policy_approved` e a sugestão só é emitida quando a política não está declarada e aprovada; os erros de política inválida ou sem aprovação não mudaram. `SDD_TOOL_VERSION` 2026.10.12 e seção no CHANGELOG da skill (ADR-0005). Minors aceitos na revisão: falta teste de H2 repetido com `auto-on-green` sem aprovação (esse caso já gera ERROR) e o teste de tempo do leak-check (SPEC-0004:IT-10), que oscila sob carga.

### Prova de Correção
Red: commit c22b6bd — `python3 -m unittest discover -s skills/sdd-management/tests` exit 1, com UT-01 vendo a sugestão mesmo com a política declarada (registrado no G1). Green: commit b746e4c — suíte OK local (G5 em 79cc2fc) e na CI do PR #12 em 83698b3 (run 40399136640, Python 3.9 e 3.15); `validate` deste repositório sem o aviso das 9 specs.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Três specs com o mesmo H2 e a política declarada e aprovada não geram a sugestão | PASS | `test_spec_graph.py::H2PolicyTest.test_repeated_h2_text_does_not_suggest_declared_policy` — CI do PR #12 em 83698b3 (run 40399136640) e suíte local (G5) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: pilar entrega dispensado; vale na `main` pelo link simbólico
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado): passa a valer na `main` com o merge do PR #12; as cópias instaladas da skill são sincronizadas depois. Versão da ferramenta 2026.10.12. Rollback: revert do merge.

### Pendências
Nenhuma. A cópia `tools/sdd` é atualizada em PR próprio depois do merge (ADR-0005).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
