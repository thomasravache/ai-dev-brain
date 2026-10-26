---
id: SPEC-0014
title: validate não sugere a política de H2 já declarada
tier: lite
type: fix
user_facing: false
status: in-progress
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
- [ ] Red: UT-01 com a tag `SPEC-0014:UT-01`, falhando pelo motivo certo
- [ ] Green: correção mínima, seguindo o padrão citado
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `SDD_TOOL_VERSION` 2026.10.12 e seção no CHANGELOG da skill (ADR-0005)
- [ ] Review (G4), integração (G5) e H2 (política auto-on-green)
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — ccf95e5 | 2026-10-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=2, skipped=1)) — c22b6bd | 2026-10-26 |
| G2 Green | PASS | MANUAL: CI do GitHub no PR #12 em 96d612f (run 40398202620): ruff check 'All checks passed!' e 159 testes OK em Python 3.9 e 3.15; local (macOS) 159 testes OK — só o lint não roda aqui (sem uv/ruff) | 2026-10-26 |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue

### Como foi feito

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Teste de regressão falhou antes e passa depois da correção
- [ ] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão existente mantido
- [ ] Disponível no ambiente-alvo via pipeline (G6)
- [ ] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [ ] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
