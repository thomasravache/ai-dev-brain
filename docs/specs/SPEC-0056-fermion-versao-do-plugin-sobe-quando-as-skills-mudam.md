---
id: SPEC-0056
title: "fermion: versão do plugin sobe quando as skills mudam"
tier: lite
type: feature
user_facing: false
status: proposed
created: 2026-11-13
parent: SPEC-0031
depends_on: [SPEC-0053]
consumes_contract: []
touches: [tests/plugin/**, .github/workflows/ci.yml, README.md, AGENTS.md]
adrs: []
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0056 — fermion: versão do plugin sobe quando as skills mudam

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
O `.claude-plugin/plugin.json` fixa `version` (SPEC-0053). Com a versão explícita, o Claude Code usa a versão como chave do cache e para decidir se há atualização. Um commit novo na `main` que muda `skills/**` sem subir a versão não chega a quem roda `claude plugin update fermion@fermion-lab`. Achado M1 da revisão G4 da SPEC-0053, segundo a documentação de plugins; não foi testado na prática.

## 2. Causa Raiz
Nada liga a versão do plugin às mudanças das skills. Cada skill sobe a própria versão (`SDD_TOOL_VERSION`, `BRAIN_VERSION`, `ATLAS_VERSION`), mas o `plugin.json` fica igual.

## 3. Mudança Proposta
Checagem na CI e no `pr-check`: um PR que muda `skills/**` também muda `version` no `plugin.json` (`AAAA.MM.N` maior que o da base). README e AGENTS.md dizem quando subir. Avaliar `claude plugin tag` na pesquisa.

**Não muda:** o formato da versão nem as versões das skills.

**Padrão seguido:** testes em `tests/plugin/` (SPEC-0053) e passo da CI existente.

**Rollback:** reverter o commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — o teste novo cobre a regra.
- **UT-01** — Dado um diff que muda `skills/**` sem mudar a versão do `plugin.json`, quando a checagem roda, então acusa; com a versão maior, não acusa; sem mudança em `skills/**`, não exige nada.
- **IT-01** — Dado um repositório git temporário com dois commits, quando a checagem roda contra a base, então dá o mesmo resultado do UT-01.

## 5. Questões em Aberto
- [ ] A checagem fica na CI do repositório (script em `tests/plugin/`) ou vira regra do `pr-check` da `gluon-spec`? (thomas)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PENDING | | |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
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
