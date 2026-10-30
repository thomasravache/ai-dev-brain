---
id: SPEC-0041
title: "sdd-management: org_context no DISCOVER"
tier: lite
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0038]
consumes_contract: []
touches: [skills/sdd-management/SKILL.md, skills/sdd-management/references/brownfield.md, skills/sdd-management/references/sdd-config.template.yml, skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/CHANGELOG.md, skills/sdd-management/tests/test_org_context.py]
adrs: [ADR-0001, ADR-0010]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0041 — sdd-management: org_context no DISCOVER

## 1. Problema
Hoje o DISCOVER da `sdd-management` só enxerga o repositório atual. Quando a organização tem um atlas (SPEC-0029), o agente ainda precisa adivinhar quais outros serviços, bancos e filas a mudança toca e quais convenções da organização valem. O esperado: com um atlas configurado, o DISCOVER usa o `atlas.py context` automaticamente; sem ele, nada muda.

## 2. Causa Raiz
Melhoria, não defeito. O `sdd-config.yml` não tem onde dizer que existe um atlas, e o `SKILL.md` e o `references/brownfield.md` não mandam consultá-lo. Pelo ADR-0001, o `spec_graph.py` só executa `git` e os comandos declarados no `sdd-config`, então a integração fica nas instruções do agente e numa chave opcional, sem o script chamar o atlas.

## 3. Mudança Proposta
- Chave opcional no `references/sdd-config.template.yml`, comentada:
  `org_context: ""   # caminho do atlas da org-atlas; com ele, o DISCOVER roda "atlas.py context" (SPEC-0029)`.
- `SKILL.md`, passo DISCOVER: "com `org_context`, rode `python3 <atlas-skill-dir>/scripts/atlas.py context "<tarefa>"`, cite o pacote na Decisão Arquitetural e repasse o aviso de envelhecimento; convenções `confirmed` valem como regra, as `inferred` são só dica".
- `references/brownfield.md`, passo 1 da adoção e seção 2: o atlas como fonte das dependências entre serviços e das convenções da organização.
- `SDD_TOOL_VERSION` e `CHANGELOG.md` da skill (ADR-0005); o `whats-new` mostra a chave nova sozinho, porque lê as chaves do modelo.
- **Não muda:** nenhum comando do `spec_graph.py`, nem o comportamento sem a chave.

**Padrão seguido:** chaves opcionais já documentadas no modelo (ex.: `living_docs`, SPEC-0011) e a detecção de chaves novas do `whats-new` (SPEC-0013, `skills/sdd-management/tests/test_whats_new.py`).

**Rollback:** reverter o commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `whats-new` e o modelo de configuração já têm cobertura (SPEC-0013).
- **UT-01** — Dado um projeto cujo `sdd-config.yml` não tem `org_context`, quando `whats-new` roda com o modelo novo, então a chave aparece entre as novas, com o comentário.
- **UT-02** — Dado o `SKILL.md` da skill, quando a seção DISCOVER é lida, então cita `org_context` e `atlas.py context` (guarda contra a instrução sumir).
- Integração/E2E: N/A — a mudança é de instrução do agente e de modelo de configuração; nenhum comando do script muda.

## 5. Questões em Aberto
- [x] Integração por import ou por CLI? — Por CLI e arquivo, sem import (ADR-0007, ADR-0010) (thomas, 2026-10-30)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
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
