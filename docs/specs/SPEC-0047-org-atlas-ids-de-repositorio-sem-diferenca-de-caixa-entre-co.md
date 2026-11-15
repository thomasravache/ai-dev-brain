---
id: SPEC-0047
title: "org-atlas: ids de repositório sem diferença de caixa entre coletores"
tier: lite
type: fix
user_facing: false
status: in-progress
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
- [ ] Red: UT-01, UT-02 e IT-01 com a tag `SPEC-0047:<ID>`, falhando pelo motivo certo; testes atuais das SPEC-0034/0035 ajustados à caixa nova
- [ ] Green: `github.py` e `argocd.py` emitem `repository:<owner>/<repo>` em minúsculas (entidades, relações e sinais), `name` com a grafia da API; regra registrada em `collector-contract.md`; `ATLAS_VERSION`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [ ] Red/Green da Emenda v2: UT-03 (escopo `repository:` sem diferença de caixa no `context`), `curation.md` e aviso de migração no CHANGELOG
- [ ] Validar: suíte completa + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c5417ad (árvore suja) | 2026-11-13 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=6, skipped=1)) — c65629b | 2026-11-15 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — d4a6c5b | 2026-11-15 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 9b5087b | 2026-11-15 |
| G4 Review | FAIL | verify G1+G4: PASS; revisão: Reviewer independente: REPROVADO — major: convenção com scope repository:<Maiúsculas> some do context depois dos ids em minúsculas — 205812e | 2026-11-15 |
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
| 2 | 2026-11-15 | O `context` compara o escopo `repository:` das convenções sem diferença de caixa; UT-03 novo; `curation.md` e aviso de migração no CHANGELOG; `touches` ganha `curation.md` e `test_context.py` | G4 (major): com os ids em minúsculas, uma convenção confirmada com `scope: repository:Acme/API` sumia em silêncio do pacote do `context` | nenhuma | thomas, 2026-11-15 (piloto automático com o recomendado) |
