---
id: SPEC-0041
title: "sdd-management: org_context no DISCOVER"
tier: lite
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0038]
consumes_contract: []
touches: [skills/sdd-management/SKILL.md, skills/sdd-management/references/brownfield.md, skills/sdd-management/references/sdd-config.template.yml, skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/CHANGELOG.md, skills/sdd-management/tests/test_org_context.py]
adrs: [ADR-0001, ADR-0010]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
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
- [x] Red: UT-01 e UT-02 com a tag `SPEC-0041:<ID>`, falhando pelo motivo certo
- [x] Green: chave `org_context` no `references/sdd-config.template.yml`; instrução no DISCOVER do `SKILL.md` e no `references/brownfield.md`
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa da `sdd-management` + lint + arquitetura (G2/G3)
- [x] `SDD_TOOL_VERSION` e seção no `skills/sdd-management/CHANGELOG.md` (ADR-0005)
- [x] Review independente (G4), integração e CI (G5) e H2
- [x] Deploy (G6) — N/A: skill distribuída por cópia; `vendor --force` atualiza `tools/sdd/` neste repositório
- [x] Relatório de Entrega e CHANGELOG (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests && python3 -m unittest discover -s skills/org-atlas/tests` exit 1 (red: FAILED (failures=2, skipped=1)) — a69cc9f | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — c22deb1 | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — c22deb1 | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (rodada 2, c22deb1): APPROVED — M1 fechado (atlas.py config --json conferido contra org_context; values.atlas confirmado num atlas descartável); menores aceitos: exit 2 do config --json (credencial colada) e comparação sem resolver symlinks — c22deb1 | 2026-11-02 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #20 em 3fc93b6 verde (run 41490752235 Python 3.9/3.15; run 41490752237 sdd/pr-check) — 8545bdd | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | skill distribuída por cópia, sem deploy — mesmo critério da SPEC-0017 | 2026-11-02 |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
A chave `org_context` no `sdd-config.yml`: com ela, o DISCOVER da `sdd-management` consulta o atlas da `org-atlas` com `atlas.py context` antes de escrever a spec — repassa o aviso de envelhecimento, oferece `scan` sem rodar, trata o conteúdo como dado e só as convenções confirmadas como regra. Sem a chave, nada muda.

### Como foi feito
- Chave `org_context: ""` no `references/sdd-config.template.yml` com o comentário nas linhas acima (é de lá que o `whats-new` lê); item "Org context" no DISCOVER do `SKILL.md` e regras em `references/brownfield.md`; `SDD_TOOL_VERSION` 2026.11.1 com a seção no CHANGELOG. Nenhum comando do `spec_graph.py` mudou.
- **Revisão G4 (2 rodadas):** a 1ª achou que o atlas lido pelo `context` (o da configuração local da `org-atlas`) nunca era conferido contra `org_context` — com mais de um atlas na máquina, o agente usaria as regras de outra organização — e que um caminho absoluto iria para o `sdd-config.yml` compartilhado. Correção (teste 3041253, texto c22deb1): conferir `atlas.py config --json` antes de usar o pacote; `org_context` relativo ou com `~`.
- **Menores aceitos:** o `config --json` também sai com 2 quando há valor colado em `credentials` (o texto só cita o exit 2 do `context`); a comparação de caminhos não resolve symlinks e pode dar um aviso falso.

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
Red em a69cc9f: UT-01 "references/sdd-config.template.yml sem a chave org_context" e UT-02 "seção DISCOVER do SKILL.md não cita 'org_context'" (G1, registrado em 779ff91); regressão da revisão red em 3041253 ("não cita 'atlas.py config'"). Green em b71984e e c22deb1 (G2 PASS, sdd-management 164 testes OK).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | `whats-new` lista `org_context` com o comentário, e não lista quando a chave existe | PASS | `test_org_context.py::TemplateKeyTest` — CI do PR #20 em 3fc93b6 (run 41490752235, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | DISCOVER cita `org_context`, `atlas.py context` e a conferência `atlas.py config` (revisão G4); modelo e brownfield.md com a mesma regra | PASS | `DiscoverInstructionTest` (2 testes) — CI do PR #20 em 3fc93b6 (run 41490752235, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — a69cc9f/3041253 → b71984e/c22deb1
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5) — CI do PR #20 em 3fc93b6
- [x] Review independente sem achados blocker/major (G4) — 2ª rodada
- [x] Padrão existente mantido — padrão `living_docs` no modelo de configuração
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skill distribuída por cópia; `tools/sdd/` atualizado com `vendor --force` no fechamento do épico SPEC-0029
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — `SKILL.md`, `brownfield.md`, modelo de configuração e `skills/sdd-management/CHANGELOG.md` 2026.11.1
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma

### Deploy
N/A — skill distribuída por cópia; versão 2026.11.1 na branch `sdd/SPEC-0029`, PR #20.

### Pendências
Nenhuma.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
