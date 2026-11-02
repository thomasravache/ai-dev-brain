---
id: SPEC-0037
title: "org-atlas: curadoria de convenções"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0036]
consumes_contract: []
contract_version: 2
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/curation.md, skills/org-atlas/assets/pages/convention.md, skills/org-atlas/assets/atlas-config.yml, skills/org-atlas/tests/test_curate.py, skills/org-atlas/tests/fixtures/curate/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0012]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0037 — org-atlas: curadoria de convenções

## 1. Visão Geral
Implementa a curadoria do ADR-0012. A partir dos sinais dos coletores (padrão de título de PR, prefixo de branch, forma de merge, template de PR), o `atlas.py` **propõe** convenções como `inferred`, com a evidência. Só um humano, pelo `curate confirm` ou `curate reject`, muda o status. Só convenção `confirmed` vale como regra para outras skills.

## 2. Motivação & Escopo
**Motivação:** inferir não é normatizar. Sem curadoria, a bagunça de metade dos PRs vira padrão e as outras skills passam a seguir isso (SPEC-0029, ADR-0012).

**Objetivos (dentro do escopo):**
- `curate propose`, que também roda no fim de todo `scan`: cria ou atualiza `conventions/<id>.md` com `status: inferred` quando um padrão domina (padrão: pelo menos 60% de pelo menos 20 itens; configurável em `curation`).
- `curate list [--status S] [--json]`, `curate confirm ID --by NOME --via VIA` e `curate reject ID --by NOME --via VIA [--reason TEXTO]`.
- Escopo da convenção: `organization` quando a maioria dos repositórios com sinal segue o mesmo padrão; senão, uma por `repository`.
- Evidência numa região gerada; texto do time no arquivo preservado.

**Não-objetivos (fora do escopo):**
- Convenções de código (estrutura de pastas, estilo): precisam de coletores que leiam código, fora do MVP.
- Aplicar a convenção em algum lugar: isso é das skills consumidoras (ex.: `gh-create-pr`, `sdd-management`).

## 3. Dependências
- **Implementações necessárias:** SPEC-0036 — as páginas geradas e as regras de região que os arquivos de convenção reaproveitam.
- **Contratos consumidos:** N/A.
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** segue as regiões geradas da SPEC-0036 e o padrão de "o script cria, o humano decide" do H1 da `sdd-management` (`set ... approved_by`), que aqui vira `confirmed_by` e `confirmed_via`.

**Decisão:** o id da convenção inclui o padrão dominante (ex.: `pr-title-conventional`, `merge-method-merge`). Se o padrão dominante muda, é outra convenção; uma convenção `rejected` nunca é proposta de novo com o mesmo id, mas a evidência dela continua atualizada.

**Justificativa:** id estável e ligado ao padrão resolve o "não propor de novo o que foi rejeitado" sem regra de limiar difícil de explicar.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** confirmação automática por limiar (ADR-0012, opção B).

**ADRs:** ADR-0010, ADR-0012.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `propose` com sinais de 300 repositórios em menos de 2 s.
- **Segurança:** nenhum comando além de `confirm`/`reject` grava `confirmed`/`rejected` (UT-04).
- **Privacidade e dados pessoais:** a evidência guarda contagens e a amostra já mascarada pelo `scan`; nenhum autor de PR.
- **Disponibilidade e resiliência:** sinal ausente para uma categoria → nenhuma proposta, sem erro.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comandos `curate`, chave `curation` e o formato dos arquivos de convenção (consumido pela SPEC-0038 e pela SPEC-0039).

```text
atlas-config.yml:
  curation: {min_share: 0.6, min_total: 20, min_repos: 3}   (min_repos: v2)

conventions/<id>.md (contrato v1, references/curation.md):
  ---
  id: pr-title-conventional
  title: "Títulos de PR em Conventional Commits"
  kind: pr-title | branch-prefix | merge-method | pr-template
  scope: organization | repository:<org>/<nome>
  status: inferred | confirmed | rejected
  proposed_at: AAAA-MM-DD
  confirmed_by:            # preenchido só por confirm/reject
  confirmed_at:
  confirmed_via:           # "PR #n" | "local"
  reason:                  # só em reject, opcional
  ---
  <!-- atlas:begin evidence --> total, quantos seguem, porcentagem, repositórios, amostra <!-- atlas:end evidence -->
  ## Notas  (texto do time, nunca reescrito)

padrão dominante por kind (v2):
  pr-title       itens = PRs da amostra; padrão = conventional | ticket_key | other (pattern_counts)
  branch-prefix  itens = branches da amostra; padrão = cada chave de counts ("feat/"…); id branch-prefix-<prefixo sem />
  → domina quando padrão/total ≥ min_share e total ≥ min_total; escopo organization quando mais da metade
    dos repositórios com o sinal tem o mesmo padrão dominante, senão uma convenção por repositório
  merge-method   itens = repositórios com o sinal; padrão = o único método permitido (merge | squash | rebase);
                 repositório com mais de um método não conta para nenhum padrão; id merge-method-<método>
  pr-template    itens = repositórios com o sinal; padrão = pr_template true; id pr-template-present
  → domina quando repositórios com o padrão / repositórios com o sinal ≥ min_share e repositórios com o
    sinal ≥ min_repos; escopo sempre organization (sinal sim/não de um repositório só não vira convenção)

atlas.py curate propose [--json]      (também roda no fim do scan)
  imprime "N nova(s), M atualizada(s), K esperando decisão"
atlas.py curate list [--status inferred|confirmed|rejected] [--json]
atlas.py curate confirm ID --by NOME --via "PR #n"|local
atlas.py curate reject  ID --by NOME --via "PR #n"|local [--reason TEXTO]
  sem --by ou --via: exit 2 "confirm exige --by e --via"
  id inexistente: exit 2 "convenção não encontrada: ID"
  --via fora do formato: exit 2 "--via aceita 'PR #<n>' ou 'local'"
  convenção já confirmada ou rejeitada: exit 2 "convenção já está <status>"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Padrão dominante | ≥ 60% de ≥ 20 itens | convenção `inferred` com evidência | UT-01, IT-01 |
| Padrão por kind | branch-prefix por branches; merge-method e pr-template por repositório, com `min_repos` | convenção do kind certo, escopo organization para sim/não | UT-05, UT-06 |
| Sem padrão | abaixo do limiar ou poucos itens | nenhuma proposta | UT-01 |
| Escopo | maioria dos repositórios com o mesmo padrão | `scope: organization`; senão por repositório | UT-02 |
| Confirmar | `confirm` com `--by` e `--via` | `status: confirmed` com quem, quando e por onde | IT-02, CT-01 |
| Confirmar sem dados | sem `--by` ou `--via`, `--via` inválido | exit 2 | UT-03 |
| Só humano confirma | `propose` e `scan` | nunca gravam `confirmed` nem `rejected` | UT-04, IT-02 |
| Rejeitada | `reject` e um novo scan | não volta a ser proposta; evidência atualizada | IT-03 |
| Texto do time | notas fora da região | preservadas | IT-04 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado sinais com 70% de títulos em Conventional Commits em 50 PRs, e outros com 40% ou com 10 PRs, quando as propostas são calculadas, então só o primeiro vira convenção.
- **UT-02** — Dado sinais de 5 repositórios, 4 com o mesmo padrão, quando o escopo é decidido, então a convenção é `organization`; com 2 de 5, uma por repositório.
- **UT-03** — Dado `confirm` sem `--by`, sem `--via` ou com `--via` inválido, quando os argumentos são validados, então sai com 2 e a mensagem do contrato.
- **UT-05** — Dado `branch-prefixes` com 70% de `feat/` em 50 branches num repositório e 40% em outro, quando as propostas são calculadas, então só o primeiro vira `branch-prefix-feat` (v2).
- **UT-06** — Dado `merge-methods` de 5 repositórios, 4 só com squash e 1 com merge e squash, e `pr-template` presente em 2 de 5, quando as propostas são calculadas, então há `merge-method-squash` (organization) e nenhuma de template; com 2 repositórios só (abaixo de `min_repos`), nenhuma (v2).
- **UT-04** — Dado o código do `atlas.py`, quando se procura quem grava `status: confirmed` ou `rejected`, então só as funções de `confirm` e `reject` gravam.

### 7.3 Testes de Integração
- **IT-01** — `scan` pela CLI com coletor falso devolvendo sinais de PR cria `conventions/pr-title-conventional.md` com `status: inferred` e a evidência.
- **IT-02** — `curate confirm pr-title-conventional --by thomas --via "PR #3"` grava `confirmed`, `confirmed_by`, `confirmed_at` e `confirmed_via`; um novo `scan` mantém `confirmed`.
- **IT-03** — Depois de `curate reject`, um novo `scan` com os mesmos sinais não cria outra proposta com o mesmo id e atualiza só a evidência.
- **IT-04** — Uma nota escrita na convenção continua igual depois de um novo `scan`.

### 7.4 Testes de Contrato
- **CT-01** — Os arquivos de convenção gerados nos testes seguem o formato de `references/curation.md` (chaves, valores permitidos, região `evidence`), contrato consumido pela SPEC-0038 e pela SPEC-0039.

### 7.5 Testes E2E
- N/A — comando usado pelo agente; a jornada é provada pela SPEC-0038.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** fixtures de sinais e coletor falso.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto.
- **Dados/schema:** `conventions/` com contrato v1.
- **Compatibilidade:** N/A — formato novo.
- **Observabilidade:** resumo do `curate propose` no fim do scan.
- **Rollback:** reverter o PR; convenções são arquivos versionados no git do atlas.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Quem confirma uma convenção — quem aprova o PR do atlas (modo repositório) ou quem roda o `curate` (modo local) (thomas, 2026-10-30)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Propostas**
- [x] Red: UT-01, UT-02, UT-05, UT-06, CT-01, IT-01 com a tag `SPEC-0037:<ID>`, falhando pelo motivo certo
- [x] Green: cálculo das propostas com `curation.min_share`/`min_total`, escopo e `conventions/<id>.md` com a região `evidence`; `curate propose` no fim do `scan`
- [x] Refactor mantendo tudo verde

**Fase 2: Decisão humana**
- [x] Red: UT-03, UT-04, IT-02, IT-03, IT-04 com a tag `SPEC-0037:<ID>`, falhando pelo motivo certo
- [x] Green: `curate list`, `confirm` e `reject`; `references/curation.md` e `SKILL.md`
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Seção em `[Unreleased]` do `skills/org-atlas/CHANGELOG.md`; o `ATLAS_VERSION` sobe no fim do épico, no mesmo PR #20

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: skill distribuída por cópia (como a second-brain)
- [x] Relatório de Entrega, README e `skills/org-atlas/CHANGELOG.md` (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests && python3 -m unittest discover -s skills/org-atlas/tests` exit 1 (red: FAILED (failures=27, errors=15)); nota: red da org-atlas conferido em worktree limpa em 8eb233b: FAILED (failures=27, errors=15), só testes da SPEC-0037; se a cadeia parar antes, é o SPEC-0004:IT-10 (tempo, sob carga) — 8eb233b | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — a120ff4 | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — a120ff4 | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (rodada 1, a120ff4): APPROVED — garantia do ADR-0012 resistiu a injeção por argumentos e por sinais; regras por kind conforme a v2; menores: nome de repositório com marcador de região faz o arquivo crescer, rejeição vale só para o mesmo escopo, ids de convenção podem colidir, empate alfabético, --via aceita dígitos não ASCII — a120ff4 | 2026-11-02 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #20 em 1ab24d1 verde (run 41471531830 Python 3.9/3.15; run 41471536190 sdd/pr-check) — 1ab24d1 | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | skill distribuída por cópia, sem deploy — mesmo critério da SPEC-0017 | 2026-11-02 |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-02 | G1 | spec | A spec lista 4 kinds (pr-title, branch-prefix, merge-method, pr-template), mas só define 'padrão dominante' (≥60% de ≥20 itens) para títulos de PR; para branch-prefix não diz qual é o item, e merge-method/pr-template são sim/não por repositório, onde '60% de 20 itens' não se aplica | Test-writer cobriu só pr-title (a4be65e, 1932c68); Architect leu a spec e o exemplo merge-method-merge da seção 4 | thomas | Emenda v2 (aprovada por thomas em 2026-11-02): padrão dominante definido para cada kind, com min_repos para merge-method e pr-template | 2026-11-02 |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
Curadoria de convenções da `org-atlas` (ADR-0012): no fim de cada `scan` (ou com `curate propose`), os sinais dos coletores viram propostas `conventions/<id>.md` com `status: inferred` e uma região de evidência quando um padrão domina — títulos de PR, prefixos de branch, método de merge permitido e template de PR, com escopo da organização ou do repositório. Só uma pessoa decide, com `curate confirm` ou `curate reject` (`--by` e `--via "PR #n"|local`); uma convenção rejeitada nunca volta com o mesmo id e o texto do time nunca é reescrito. `curate list` mostra o estado.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `propose_conventions`, `cmd_curate` e `_write_decision` no `atlas.py`; o `propose` roda depois do `build` no `scan` e entra no `scan --json` como `curation`; template `assets/pages/convention.md`; `curation` com padrões em `assets/atlas-config.yml` e validado no `config`/`doctor`.
- **Emenda v2** (IMP-01, aprovada por thomas): a v1 só definia o padrão dominante para títulos de PR; a v2 define a regra de cada kind e a chave `min_repos` (padrão 3) para os sinais sim/não por repositório. UT-05 e UT-06 novos; SPEC-0038 e SPEC-0039 passaram a consumir `SPEC-0037@2`.
- **Garantia do ADR-0012:** só `_write_decision`, chamada por `confirm` e `reject`, grava a decisão (UT-04, verificação estática); valores de `--by`, `--via` e `--reason` sempre entre aspas no YAML; ids validados contra caminho. A revisão tentou injeção pelos argumentos e pelos sinais dos coletores sem sucesso.
- Guia `references/curation.md`; `SKILL.md` com os comandos `curate` e o fluxo "o agente propõe, a pessoa decide"; CHANGELOG em `[Unreleased]` (com a correção das entradas das SPEC-0034/0035 que tinham ido para "Changed" na 2026.11.1).

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`.

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Padrão dominante de títulos de PR: ≥ 60% de ≥ 20 itens, limites inclusivos, limites da configuração | PASS | `test_curate.py::ProposeTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| UT-02 | Escopo organization com maioria dos repositórios; senão uma convenção por repositório | PASS | `ScopeTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| UT-03 | `confirm`/`reject` sem `--by`/`--via`, `--via` inválido ou id inexistente saem com 2 sem tocar o arquivo | PASS | `DecisionArgumentsTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| UT-04 | Só as funções de confirm/reject gravam `confirmed`/`rejected` (verificação estática do `atlas.py`) | PASS | `OnlyHumansDecideTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| UT-05 | Prefixos de branch dominantes viram `branch-prefix-<prefixo>` (v2) | PASS | `BranchPrefixTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| UT-06 | `merge-method` e `pr-template` por repositório, com `min_repos` e escopo organization (v2) | PASS | `RepositoryKindsTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| IT-01 | `scan` cria `conventions/<id>.md` inferida com evidência; mesmos sinais não mudam o arquivo; `curate propose` sozinho; kinds da v2 pelo `scan` | PASS | `ProposeCliTest`, `KindsCliTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| IT-02 | `curate confirm` grava a decisão, que sobrevive a novos `scan`; decidir de novo sai com 2; `list --status` | PASS | `ConfirmTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| IT-03 | Depois de `reject`, o mesmo id nunca volta; só a evidência é atualizada | PASS | `RejectTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| IT-04 | Nota do time na convenção sobrevive a novos `scan` e a `confirm` | PASS | `TeamTextTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |
| CT-01 | Arquivos de convenção seguem `references/curation.md` (chaves, valores, região `evidence`, `## Notas`) | PASS | `ConventionContractTest` — CI do PR #20 em 1ab24d1 (run 41471531830, Python 3.9 e 3.15) e suíte local no G5 (1ab24d1) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5) — CI do PR #20 em 1ab24d1
- [x] Review independente sem achados blocker/major (G4) — 1ª rodada
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — 300 repositórios: 18 ms em processo, 0,57 s pela CLI a frio, 0,17 s a quente (meta 2 s); UT-04 para a segurança; sem sinal, nenhuma proposta (UT-01)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skill distribuída por cópia
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — linha `Convenções: …` e `curation` no `scan --json`; rollback por revert
- [x] Documentação raiz e CHANGELOG atualizados (G7) — README, `SKILL.md`, `references/curation.md` e `skills/org-atlas/CHANGELOG.md`
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: `living_docs` não habilitado neste repositório
- [x] Pendências registradas como novas specs (ou nenhuma) — SPEC-0048

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
N/A — skill distribuída por cópia; em `[Unreleased]` na branch `sdd/SPEC-0029`, PR #20.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- SPEC-0048 — endurecimento da curadoria (marcador de região em nome de repositório, colisão de ids, `--via` com dígitos não ASCII) e alcance da rejeição entre escopos (questão para o thomas).

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0037`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-02 | Regra de padrão dominante para cada `kind`: branch-prefix por branches (como pr-title); merge-method e pr-template por repositório, com `curation.min_repos` (padrão 3) e escopo sempre `organization`; UT-05 e UT-06 novos | IMP-01: a v1 só definia o domínio para títulos de PR, e sinais sim/não por repositório não cabem em "60% de 20 itens" | SPEC-0038 e SPEC-0039 (formato do arquivo de convenção inalterado; só a chave nova `min_repos`) | thomas, 2026-11-02 |
