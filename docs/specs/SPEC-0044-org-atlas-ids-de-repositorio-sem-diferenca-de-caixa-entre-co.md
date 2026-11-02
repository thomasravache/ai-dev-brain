---
id: SPEC-0044
title: "org-atlas: ids de repositório sem diferença de caixa entre coletores"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-11-02
parent: SPEC-0029
depends_on: [SPEC-0034, SPEC-0035]
consumes_contract: []
touches: [skills/org-atlas/assets/collectors/github.py, skills/org-atlas/assets/collectors/argocd.py, skills/org-atlas/tests/test_collector_github.py, skills/org-atlas/tests/test_collector_argocd.py, skills/org-atlas/tests/fixtures/github/**, skills/org-atlas/tests/fixtures/argocd/**, skills/org-atlas/references/collectors/github.md, skills/org-atlas/references/collectors/argocd.md, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0011]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0044 — org-atlas: ids de repositório sem diferença de caixa entre coletores

## 1. Problema
O coletor GitHub (SPEC-0034) gera `repository:<org>/<nome>` com a caixa do `full_name` da API; o coletor Argo CD (SPEC-0035) gera `sourced_from` → `repository:<owner>/<repo>` com a caixa escrita no `repoURL`. Quando as duas diferem (`Acme/API` × `acme/api`), a relação `sourced_from` aponta para um id que não existe: o cruzamento entre deployment e repositório se perde e o `lint` (SPEC-0039) só avisa `broken-ref`. Achado nas revisões G4 das SPEC-0034 e SPEC-0035.

## 2. Causa Raiz
Os nomes de organização e repositório do GitHub não diferenciam caixa, mas os ids do contrato `org-atlas/collector@1` são comparados como texto exato, e cada coletor preserva a caixa da sua fonte (`github.py`: `canonical_full_name`; `argocd.py`: `repository_ref`).

## 3. Mudança Proposta
- Os dois coletores emitem o id de repositório do GitHub em minúsculas (`repository:acme/api`), em entidades, relações e sinais; o `name` da entidade guarda a grafia da API.
- **Não muda:** o formato do contrato (`repository:<owner>/<repo>`), os ids das demais entidades e o validador.

**Padrão seguido:** ids de time em minúsculas no `github.py` (correção do G4 da SPEC-0034).

**Rollback:** reverter o commit; snapshots antigos voltam a ter a caixa da fonte (o `diff` mostra a troca de ids uma vez).

**Outras ocorrências:** coletores futuros que citem repositórios do GitHub seguem a mesma regra (registrar em `collector-contract.md`).

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes atuais das SPEC-0034/0035 cobrem o comportamento e são ajustados.
- **UT-01** — Dado a resposta de um repositório com `full_name` `Acme/API`, quando o `github.py` mapeia, então o id é `repository:acme/api`, o `name` mantém `API`, e `builds`, `owns` e os sinais usam o mesmo id.
- **UT-02** — Dado `repoURL` `https://github.com/Acme/API.git`, quando o `argocd.py` mapeia a origem, então `sourced_from` aponta para `repository:acme/api`.
- **IT-01** — O `scan` de um atlas com os dois coletores declarados sobre fixtures com caixas diferentes termina sem relação `sourced_from` para id inexistente.

## 5. Questões em Aberto
- [ ] Minúsculas nos dois coletores (esta proposta) ou comparação sem diferença de caixa no cruzamento e no `lint` (SPEC-0036/0039), mantendo a grafia da fonte? (thomas)

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
