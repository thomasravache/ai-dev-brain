---
id: SPEC-0038
title: "org-atlas: context com aviso de envelhecimento"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0036]
consumes_contract: [SPEC-0037@2]
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/context.md, skills/org-atlas/tests/test_context.py, skills/org-atlas/tests/fixtures/context/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0012]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0038 — org-atlas: context com aviso de envelhecimento

## 1. Visão Geral
Implementa o `atlas.py context QUERY`: o comando que as outras skills e o agente chamam. Para uma tarefa ("feature de cashout no backoffice"), ele monta um pacote só de leitura com:
- os serviços certos e o que está ligado a eles (repositório, deployments por ambiente, bancos, filas, outros serviços), até N passos no grafo;
- as convenções `confirmed` que valem para esses serviços, e as `inferred` separadas como **dica**;
- no topo, um **aviso de envelhecimento** quando algum coletor passou do `stale_days` ou falhou no último scan.

## 2. Motivação & Escopo
**Motivação:** é por aqui que o atlas chega a quem implementa (SPEC-0029). Um pacote pequeno e certo evita colocar o atlas inteiro no contexto do agente, e o aviso impede que ele decida com informação velha sem saber.

**Objetivos (dentro do escopo):**
- `context QUERY [--hops 0..2] [--limit N] [--max-chars N] [--json]`, na mesma linha do `context` da `second-brain` (SPEC-0020).
- Busca por termos no nome, no id, nos atributos e nas notas das páginas; vizinhos por aresta até `--hops` (padrão 1).
- Aviso de envelhecimento a partir do `_scan.json` e do `stale_days`.
- Instrução no `SKILL.md`: sempre rodar o `context` antes de responder sobre a organização, citar as páginas e repassar o aviso ao usuário.
- `references/context.md` com o formato do pacote.

**Não-objetivos (fora do escopo):**
- Rodar o `scan` sozinho quando o atlas está velho: o agente oferece, o usuário decide.
- Busca semântica ou por embeddings.

## 3. Dependências
- **Implementações necessárias:** SPEC-0036 — `graph.json` e páginas.
- **Contratos consumidos:** SPEC-0037@1 — formato dos arquivos de convenção (status e escopo).
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** a referência é o `context` da `second-brain` (`skills/second-brain/scripts/brain.py`, SPEC-0020): busca por termos com pontuação, vizinhos por link até `--hops`, limite de caracteres com itens omitidos listados, mensagem fixa e exit 0 quando nada é encontrado.

**Decisão:** mesmo desenho sobre o `graph.json`; o aviso de envelhecimento é sempre a primeira seção do pacote quando existe.

**Justificativa:** comportamento já conhecido pelo agente e pelo usuário, e testado na outra skill.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** devolver o `ATLAS.md` inteiro (grande demais e sem foco); esconder as convenções `inferred` (perderia dica útil; ficam separadas e marcadas).

**ADRs:** ADR-0010, ADR-0012.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** menos de 1 s num atlas com 500 serviços.
- **Segurança:** só leitura.
- **Privacidade e dados pessoais:** N/A — só o que já está no atlas.
- **Disponibilidade e resiliência:** atlas sem scan → pacote vazio com o aviso "atlas ainda sem scan — rode scan".
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comando `context` e o formato do pacote (consumido pela `sdd-management` na SPEC-0041).

```text
atlas.py context QUERY [--hops 0..2 (padrão 1)] [--limit N (padrão 8)] [--max-chars N (padrão 30000)] [--json]
  pacote em Markdown (ou JSON):
    ## Aviso de envelhecimento   (só quando há): "Atlas com D dias desde o último scan de: A, B (stale_days: 14)"
                                 e "Último scan falhou: C"
    ## Serviços                  por serviço encontrado: página, repositório, deployments por ambiente, donos
    ## Dependências              arestas até --hops, com tipo, "inferida" quando for e a evidência
    ## Convenções (regra)        as confirmed do escopo organization e dos repositórios dos serviços
    ## Convenções (dica)         as inferred do mesmo escopo, marcadas "não confirmada"
    ## Omitidos                  o que não coube em --max-chars
  nada encontrado: "Nada encontrado no atlas para: QUERY" e exit 0 (com o aviso, se houver)
  --hops fora de 0..2: exit 2; sem configuração: exit 3
  convenções rejected nunca aparecem
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Tarefa com serviço conhecido | termo bate com um serviço | serviço, dependências e convenções do escopo | UT-01, IT-01 |
| Vizinhos | `--hops 0`, `1`, `2` | só o nó, vizinhos diretos, dois passos | UT-02 |
| Convenções | confirmed, inferred e rejected no escopo | regra, dica e nada, nessa ordem | UT-03, CT-01 |
| Atlas velho | coletor com `seen_at` além de `stale_days` ou falha | aviso no topo | UT-04, IT-02 |
| Limite | pacote maior que `--max-chars` | itens omitidos listados | UT-05 |
| Nada encontrado | termo inexistente | mensagem fixa e exit 0 | IT-01 |
| Argumento inválido | `--hops 3` | exit 2 | IT-01 |
| Jornada | init → scan → curate confirm → context | pacote com o serviço, o banco e a convenção confirmada | IT-03 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado um grafo de exemplo, quando a busca roda com "cashout backoffice", então o serviço `backoffice` vem primeiro, com pontuação e motivo.
- **UT-02** — Dado `--hops` 0, 1 e 2, quando os vizinhos são coletados, então o pacote tem só o nó, os vizinhos diretos e os de dois passos.
- **UT-03** — Dado convenções `confirmed`, `inferred` e `rejected` no escopo, quando o pacote é montado, então aparecem em "regra", "dica" e nenhuma seção.
- **UT-04** — Dado um `_scan.json` com um coletor de 20 dias e outro com `status: failed`, com `stale_days: 14`, quando o aviso é calculado, então cita os dois.
- **UT-05** — Dado um pacote maior que `--max-chars`, quando é montado, então os itens que não cabem vão para "Omitidos".

### 7.3 Testes de Integração
- **IT-01** — `context` pela CLI num atlas de fixture: termo conhecido gera o pacote; termo inexistente imprime a mensagem fixa e sai com 0; `--hops 3` sai com 2.
- **IT-02** — Com o `_scan.json` antigo, o pacote começa pelo aviso de envelhecimento.
- **IT-03** — Jornada pela CLI: `init`, `scan` com os coletores falsos de GitHub, Argo CD e um fato `generic` de banco, `curate confirm` de uma convenção e `context "<serviço>"` trazem o serviço, o banco como dependência inferida e a convenção como regra.

### 7.4 Testes de Contrato
- **CT-01** — O `context` lê os arquivos de convenção no formato da SPEC-0037@1 (fixtures geradas pelo `curate` da SPEC-0037) e separa os três status.

### 7.5 Testes E2E
- N/A — sem jornada de usuário em interface; a jornada da CLI usada pelo agente é o IT-03.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** atlas de fixture e coletores falsos das SPEC-0034 e SPEC-0035.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto.
- **Dados/schema:** N/A — só leitura.
- **Compatibilidade:** formato do pacote documentado em `references/context.md`.
- **Observabilidade:** N/A.
- **Rollback:** reverter o PR.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Busca e pacote**
- [x] Red: UT-01, UT-02, UT-03, UT-05, CT-01 com a tag `SPEC-0038:<ID>`, falhando pelo motivo certo
- [x] Green: busca por termos, vizinhos até `--hops`, seções de convenções e limite de caracteres
- [x] Refactor mantendo tudo verde

**Fase 2: Envelhecimento e CLI**
- [x] Red: UT-04, IT-01, IT-02 com a tag `SPEC-0038:<ID>`, falhando pelo motivo certo
- [x] Green: aviso a partir do `_scan.json` e de `stale_days`; comando `context`
- [x] Refactor mantendo tudo verde

**Fase 3: Jornada**
- [x] Red: IT-03 com a tag `SPEC-0038:<ID>`, falhando pelo motivo certo
- [x] Green: `SKILL.md` (consultar antes de responder, repassar o aviso) e `references/context.md`
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests && python3 -m unittest discover -s skills/org-atlas/tests` exit 1 (red: FAILED (failures=14, errors=13)); nota: red da org-atlas conferido em worktree limpa em 6bd88ec: FAILED (failures=14, errors=13), só testes da SPEC-0038; se a cadeia parar antes, é o SPEC-0004:IT-10 (tempo, sob carga) — 6bd88ec | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 1a65633 | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 1a65633 | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (rodada 2, 1a65633): APPROVED — M1 corrigido (nenhuma seção forjada, inclusive com separadores Unicode e chaves com quebra de linha); menores 1–3 corrigidos; restam menores na SPEC-0048 (nome do serviço dentro de título ###, crase escapando do código inline) — 1a65633 | 2026-11-02 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #20 em e07339b verde (run 41478872579 Python 3.9/3.15; run 41478875431 sdd/pr-check) — e07339b | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | skill distribuída por cópia, sem deploy — mesmo critério da SPEC-0017 | 2026-11-02 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — c2ee61a | 2026-11-02 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
`atlas.py context TERMOS… [--hops 0..2] [--limit N] [--max-chars N] [--json]`: o pacote que outras skills e agentes leem antes de agir. Traz os serviços que casam com os termos (com página, repositório, deployments e donos), as dependências até `--hops` passos com tipo, se é inferida e a evidência, as convenções confirmadas como regras e as inferidas como dicas, e começa sempre pelo aviso de envelhecimento quando algum coletor passou do `stale_days`, falhou, nunca foi escaneado ou não tem data válida. Só leitura.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `staleness_warnings`, `build_context`, `render_context` e `cmd_context` no `atlas.py`, lendo `graph.json`, `snapshots/_scan.json`, as páginas e `conventions/`; corte por `--max-chars` com seção de omitidos (até 50 linhas e um resumo); `--json` com o pacote cru.
- **Revisão G4 (2 rodadas):** a 1ª achou que texto vindo de coletor ou de convenção com quebra de linha forjava seções do pacote — uma "Convenções (regra)" ou um "Aviso" falsos — exatamente onde o agente decide o que seguir. Correção (testes 01c3626, código 1a65633): todo valor entra no Markdown numa linha só; regra exige decisão completa (`confirmed_by`, `confirmed_at` e `confirmed_via` válidos); avisos para coletor nunca escaneado e `seen_at` inválido; regras ficam antes das dependências no corte. A 2ª rodada tentou separadores Unicode, chaves com quebra de linha e valores começando com `##` sem forjar seção.
- Guia `references/context.md` com as seções, mensagens fixas, flags, chaves do JSON e o passo a passo para outras skills; `SKILL.md` com o fluxo "Contexto para uma tarefa" e a instrução de tratar o conteúdo do atlas como dado, nunca como instrução; CHANGELOG em `[Unreleased]`.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`.

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Busca por termos com pontuação e motivo; notas do time só pesam na pontuação; valores em uma linha só no Markdown | PASS | `test_context.py::SearchTest` e casos de injeção — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| UT-02 | `--hops` 0, 1 e 2 coletam os vizinhos com tipo, `inferred` e evidência | PASS | `HopsTest` — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| UT-03 | Regra só com decisão completa; inferida e decisão incompleta como dica; rejeitada nunca aparece; nenhum título de seção vem de dado | PASS | `ConventionsTest` e testes de injeção — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| UT-04 | Aviso de envelhecimento: mais de `stale_days`, último scan com falha, `seen_at` ausente ou inválido, coletor nunca escaneado; atlas sem scan | PASS | `StalenessTest` — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| UT-05 | `--max-chars` corta na ordem serviços → regras → dependências → dicas e lista os omitidos; o aviso nunca é omitido | PASS | `MaxCharsTest` — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| IT-01 | `context` pela CLI: seções na ordem, `--json`, nada encontrado, `--hops` inválido sai com 2, sem configuração sai com 3, nunca escreve | PASS | `ContextCliTest` — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| IT-02 | Atlas antigo, coletor com falha ou nunca escaneado: o pacote começa pelo aviso | PASS | `StaleCliTest` — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| IT-03 | Jornada `init` → `scan` → `curate confirm` → `context api` com a cadeia api → banco e a regra confirmada | PASS | `JourneyTest` — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |
| CT-01 | Lê os arquivos de convenção gerados pela curadoria (SPEC-0037@2) e segue `references/context.md` | PASS | `ConventionContractTest` — CI do PR #20 em e07339b (run 41478872579, Python 3.9 e 3.15) e suíte local no G5 (e07339b) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5) — CI do PR #20 em e07339b
- [x] Review independente sem achados blocker/major (G4) — 2ª rodada
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — 500 serviços: ~0,17 s por consulta pela CLI (meta 1 s); só leitura conferida por hash dos arquivos na revisão; atlas sem scan → pacote vazio com aviso (UT-04)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skill distribuída por cópia
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — aviso de envelhecimento no próprio pacote; rollback por revert
- [x] Documentação raiz e CHANGELOG atualizados (G7) — README, `SKILL.md`, `references/context.md` e `skills/org-atlas/CHANGELOG.md`
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: `living_docs` não habilitado neste repositório
- [x] Pendências registradas como novas specs (ou nenhuma) — SPEC-0048

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
N/A — skill distribuída por cópia; em `[Unreleased]` na branch `sdd/SPEC-0029`, PR #20.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- SPEC-0048 — nome do serviço dentro do título `###` do pacote e crase escapando do código inline (menores da revisão G4).

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0038`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
