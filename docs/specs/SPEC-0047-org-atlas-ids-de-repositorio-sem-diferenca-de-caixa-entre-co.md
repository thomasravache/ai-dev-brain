---
id: SPEC-0047
title: "org-atlas: ids de repositório sem diferença de caixa entre coletores"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-11-02
parent:
depends_on: [SPEC-0034, SPEC-0035]
consumes_contract: []
touches: [skills/boson-atlas/assets/collectors/github.py, skills/boson-atlas/assets/collectors/argocd.py, skills/boson-atlas/tests/test_collector_github.py, skills/boson-atlas/tests/test_collector_argocd.py, skills/boson-atlas/tests/fixtures/github/**, skills/boson-atlas/tests/fixtures/argocd/**, skills/boson-atlas/references/collectors/github.md, skills/boson-atlas/references/collectors/argocd.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/references/collector-contract.md, skills/boson-atlas/references/curation.md, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/test_context.py, .claude-plugin/plugin.json]
adrs: [ADR-0011]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-13
---

# SPEC-0047 — org-atlas: ids de repositório sem diferença de caixa entre coletores

## 1. Problema
O coletor GitHub (SPEC-0034) gera `repository:<org>/<nome>` com a caixa do `full_name` da API; o coletor Argo CD (SPEC-0035) gera `sourced_from` → `repository:<owner>/<repo>` com a caixa escrita no `repoURL`. Quando as duas diferem (`Acme/API` × `acme/api`), a relação `sourced_from` aponta para um id que não existe: o cruzamento entre deployment e repositório se perde e o `lint` (SPEC-0039) só avisa `broken-ref`. Achado nas revisões G4 das SPEC-0034 e SPEC-0035.

## 2. Causa Raiz
Os nomes de organização e repositório do GitHub não diferenciam caixa, mas os ids do contrato `org-atlas/collector@1` são comparados como texto exato, e cada coletor preserva a caixa da sua fonte (`github.py`: `canonical_full_name`; `argocd.py`: `repository_ref`).

## 3. Mudança Proposta
- Os dois coletores emitem o id de repositório do GitHub em minúsculas (`repository:acme/api`), em entidades, relações e sinais; o `name` da entidade guarda a grafia da API.
- O `context` compara o escopo `repository:` das convenções sem diferença de caixa, para que convenções curadas antes da mudança (`scope: repository:Acme/API`) continuem no pacote; `curation.md` passa a dizer que o id vai em minúsculas e o CHANGELOG avisa que o primeiro `scan` depois do upgrade mostra a troca de ids uma vez (Emenda v2).
- **Não muda:** o formato do contrato (`repository:<owner>/<repo>`), os ids das demais entidades e o validador.

**Padrão seguido:** ids de time em minúsculas no `github.py` (correção do G4 da SPEC-0034).

**Rollback:** reverter o commit; snapshots antigos voltam a ter a caixa da fonte (o `diff` mostra a troca de ids uma vez).

**Outras ocorrências:** coletores futuros que citem repositórios do GitHub seguem a mesma regra (registrar em `collector-contract.md`).

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes atuais das SPEC-0034/0035 cobrem o comportamento e são ajustados.
- **UT-01** — Dado a resposta de um repositório com `full_name` `Acme/API`, quando o `github.py` mapeia, então o id é `repository:acme/api`, o `name` mantém `API`, e `builds`, `owns` e os sinais usam o mesmo id.
- **UT-02** — Dado `repoURL` `https://github.com/Acme/API.git`, quando o `argocd.py` mapeia a origem, então `sourced_from` aponta para `repository:acme/api`.
- **UT-03** — Dada uma convenção curada antes da mudança, com `scope: repository:Acme/API`, quando o `context` monta o pacote do repositório `acme/api`, então a convenção aparece; o escopo `repository:` é comparado sem diferença de caixa (Emenda v2).
- **IT-01** — O `scan` de um atlas com os dois coletores declarados sobre fixtures com caixas diferentes termina sem relação `sourced_from` para id inexistente.

## 5. Questões em Aberto
- [x] Minúsculas nos dois coletores (esta proposta) ou comparação sem diferença de caixa no cruzamento e no `lint` (SPEC-0036/0039), mantendo a grafia da fonte? — Minúsculas nos dois coletores: o id fica canônico na origem (como os ids de time), e o cruzamento e o `lint` continuam comparando texto exato; a grafia da API fica no `name` (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01, UT-02 e IT-01 com a tag `SPEC-0047:<ID>`, falhando pelo motivo certo; testes atuais das SPEC-0034/0035 ajustados à caixa nova
- [x] Green: `github.py` e `argocd.py` emitem `repository:<owner>/<repo>` em minúsculas (entidades, relações e sinais), `name` com a grafia da API; regra registrada em `collector-contract.md`; `ATLAS_VERSION`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [x] Red/Green da Emenda v2: UT-03 (escopo `repository:` sem diferença de caixa no `context`), `curation.md` e aviso de migração no CHANGELOG
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=6, skipped=1)) — c65629b | 2026-11-15 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — d4a6c5b | 2026-11-15 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 2701042 | 2026-11-15 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer independente: APPROVED (rodada 2; major do escopo de convenção resolvido) — 1f9f7d5 | 2026-11-15 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #30 em fec95b7 verde (run 43694044518 ci Python 3.9/3.15; run 43694044524 sdd/pr-check) — fec95b7 | 2026-11-15 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-15 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-15 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — f2ab859 | 2026-11-15 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- Os coletores GitHub e Argo CD emitem o id de repositório do GitHub em minúsculas (`repository:acme/api`) nas entidades, no `to` de `builds`, `owns` e `sourced_from` e no `repository` dos sinais; o `name` guarda a grafia da API. O cruzamento deployment → repositório não se perde mais quando as caixas diferem (`Acme/API` × `acme/Api`).
- O id do pipeline e os das demais entidades não mudam.
- O `context` compara o escopo `repository:` das convenções sem diferença de caixa, então convenções curadas antes (`scope: repository:Acme/API`) continuam no pacote (Emenda v2).
- Regra registrada em `collector-contract.md`, `collectors/github.md`, `collectors/argocd.md` e `curation.md`; `ATLAS_VERSION` e `version` do plugin 2026.11.5; CHANGELOG com aviso de upgrade (o primeiro `scan` mostra a troca de ids uma vez no `diff`).

### Como foi feito
- Testes em c65629b (UT-01, UT-02, IT-01, com fixtures `acme-mixed-case`) e e814e98 (UT-03); correções em fb86647 (`.lower()` em `map_repository`, `map_workflows`, `parse_codeowners`, sinais e `repository_ref`) e d4a6c5b (`casefold` em `_context_conventions`).
- O Architect ampliou o `touches` no PLAN (`collector-contract.md`, que a seção 3 manda atualizar, e `atlas.py` para a versão) e na Emenda v2 (`curation.md`, `test_context.py`).
- **Revisão G4:** rodada 1 REPROVADO (major: convenção com escopo em outra caixa sumia do `context`); rodada 2 APPROVED.

### Prova de Correção
- **Antes (c65629b):** 6 falhas por asserção, por exemplo `'Acme/API' != 'acme/api'` e, no IT-01, `['repository:acme/Api', 'repository:ACME/api'] != []` (`sourced_from` para repositório inexistente); e814e98: `'branch-prefix-feat-acme-backoffice-old-case' not found` no pacote do `context`.
- **Depois (d4a6c5b):** suíte completa verde (boson-atlas 358 testes, 1 skip antigo), também no Python 3.14 local e no 3.15 da CI.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | `github.py` com `Acme/API`: id `repository:acme/api`, `name` `API`, `builds`, `owns` e sinais com o mesmo id | PASS | `test_collector_github.py::MixedCaseRepositoryTest` — CI do PR #30 (run 43694044518, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | `argocd.py` com `repoURL` `Acme/API`: `sourced_from` para `repository:acme/api` | PASS | `test_collector_argocd.py::MixedCaseRepositoryRefTest` — CI do PR #30 (run 43694044518, Python 3.9 e 3.15) e suíte local no G5 |
| UT-03 | Convenção com `scope: repository:Acme/...` continua no pacote do `context` | PASS | `test_context.py::RepositoryScopeCaseCliTest` — CI do PR #30 (run 43694044518, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | `scan` com os dois coletores sobre caixas diferentes sem `sourced_from` para id inexistente | PASS | `test_collector_argocd.py::MixedCaseScanTest` — CI do PR #30 (run 43694044518, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — c65629b/e814e98 vermelhos, fb86647/d4a6c5b verdes
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — rodada 2
- [x] Padrão existente mantido — ids de time já em minúsculas no `github.py`
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — `collector-contract.md`, `collectors/github.md`, `collectors/argocd.md`, `curation.md`, CHANGELOG `[2026.11.5]`
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma: coletores futuros seguem a regra registrada em `collector-contract.md`

### Deploy
N/A — `ATLAS_VERSION` 2026.11.5, PR #30.

### Pendências
Nenhuma nova. Nits da revisão, sem spec: evidência e títulos das propostas de curadoria mostram o id em minúsculas; um coletor genérico que declare `repository:Acme/API` fica desalinhado (a regra está documentada).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-15 | O `context` compara o escopo `repository:` das convenções sem diferença de caixa; UT-03 novo; `curation.md` e aviso de migração no CHANGELOG; `touches` ganha `curation.md` e `test_context.py` | G4 (major): com os ids em minúsculas, uma convenção confirmada com `scope: repository:Acme/API` sumia em silêncio do pacote do `context` | nenhuma | thomas, 2026-11-15 (piloto automático com o recomendado) |
