---
id: SPEC-0087
title: "boson-atlas: mapa de acesso — ambientes marcados, workloads e acesso local por cluster"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-22
parent: SPEC-0075
depends_on: []
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/collectors/argocd.py, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/assets/atlas-config.yml, skills/boson-atlas/references/**, skills/boson-atlas/tests/**, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0011, ADR-0023]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-23
---

# SPEC-0087 — boson-atlas: mapa de acesso — ambientes marcados, workloads e acesso local por cluster

> Origem: épico SPEC-0075, primeira onda (decisão de thomas em 2026-11-22: "Entrega + runtime + logs", com a verificação usando as probes da SPEC-0030).

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O atlas passa a saber o que falta para consultar um deployment de verdade:
- **ambiente:** se é de teste ou de produção;
- **workload:** quais workloads rodam o serviço;
- **acesso da máquina:** como esta máquina chega a cada cluster, só pelo nome do contexto e nunca com credencial.

Com isso, as probes (SPEC-0088) e a verificação (SPEC-0090) montam o alvo sem perguntar nem adivinhar.

## 2. Motivação & Escopo
**Motivação:** para verificar um deploy, o agente hoje redescobre sozinho:
- o contexto do kubectl;
- o namespace e o workload;
- se o ambiente é de produção.

O grafo já tem o cluster (`runs_in`) e o namespace do deployment, mas não tem o workload nem a marcação do ambiente. Também não sabe como cada máquina chega ao cluster. O nome do contexto varia por máquina e é local.

**Objetivos (dentro do escopo):**
- **`environments`:** chave compartilhada nova no `atlas-config.yml`, com a marcação `tier: test | production` por ambiente. O `build` grava o `tier` no nó `environment`.
- **`workloads`:** atributo novo do `deployment` no coletor `argocd`, vindo de `status.resources` (ex.: `Deployment/api`).
- **`access.clusters`:** chave local nova no `config.yml` da máquina. Leva o nome do contexto de cada cluster, só o nome.
- **`context`:** o `delivery.deployments` (SPEC-0086) passa a trazer `tier`, `namespace`, `workloads` e `access` (se esta máquina tem acesso configurado ao cluster).
- **`lint` e `doctor`:** avisam de ambiente sem marcação e de cluster sem acesso local.

**Não-objetivos (fora do escopo):**
- Executar qualquer consulta (SPEC-0088 a SPEC-0090).
- Fontes de log externas (Loki, CloudWatch), dashboards, URLs públicas e contas de teste: ondas seguintes do épico.
- Profile e região de nuvem: só quando houver um adaptador de nuvem.
- Kind ou relação nova no contrato (ADR-0022).

## 3. Dependências
- **Implementações necessárias:** N/A — SPEC-0086 (`delivery` no `context`) já está na main.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **chave compartilhada com validação por posição e motivo:** `remotes:` (SPEC-0080) e `image_repositories` (SPEC-0082);
- **atributo de deployment:** `images` (SPEC-0082) e `config_refs` (SPEC-0076);
- **chave local só com nomes:** `credentials` (ADR-0010) e a forma com vários atlas (SPEC-0079);
- **`delivery` no `context`:** SPEC-0086;
- **testes:** `test_config.py`, `test_collector_argocd.py`, `test_context_delivery.py` e `test_lint.py`.

**Decisão:**
- **Marcação dos ambientes:** fica no arquivo compartilhado, porque é um fato da organização.
- **Acesso:** fica no arquivo local, porque o contexto é da máquina, e é por atlas na forma com vários atlas.
- **Workloads:** são um atributo, que o contrato `@1` já aceita como lista de escalares.
- **Ambiente sem marcação:** conta como produção para quem consome (ADR-0023).

**Justificativa:** separar o que é da organização do que é da máquina evita que o nome de um contexto local vá para o repositório do atlas. Um atributo e uma chave aditiva não quebram máquinas na versão anterior.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **Contexto do kubectl no arquivo compartilhado:** o nome muda por máquina e pode trazer o id da conta.
- **Kind `workload`:** quebraria a leitura na versão anterior (ADR-0022).
- **Inferir produção pelo nome do ambiente (`prod`):** frágil e não agnóstico.

**ADRs:** ADR-0010, ADR-0011, ADR-0023.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — leitura de configuração e um atributo por deployment.
- **Segurança:**
  - O valor do contexto nunca sai em `doctor`, `lint`, `config --json` nem no `context`. Só sai se ele existe.
  - O `lint` `secret-leak` vale para a chave nova.
  - Item inválido é recusado só com a posição e o motivo.
- **Privacidade e dados pessoais:** N/A — nomes de ambiente, cluster e workload.
- **Disponibilidade e resiliência:** sem as chaves novas, tudo fica igual (CH-01).
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** chave `environments` (compartilhada), chave `access` (local), atributo `workloads` do `deployment`, atributo `tier` do `environment` e campos novos de `delivery.deployments` no `context`.

```text
atlas-config.yml (compartilhado) — chave opcional
  environments:
    dev:  {tier: test}
    prod: {tier: production}
  chave = nome do ambiente como está no grafo (regra de nome simples do atlas); tier ∈ {test, production}
  inválido → exit 2 em config --json, build e lint: "environments: item N inválido — <motivo>" (sem o item)

build
  environment cujo nome está em environments → attrs.tier = valor; ambiente ausente do mapa → sem tier

config.yml (local, da máquina; na forma com vários atlas, dentro da entrada do atlas) — chave opcional
  access:
    clusters:
      cluster-dev: {context: <nome do contexto do kubeconfig>}
  chave = nome do cluster no grafo; context = texto de 1 a 256 caracteres, sem quebra de linha
  inválido → exit 2: "access.clusters: item N inválido — <motivo>" (sem o item); o valor nunca é impresso

coletor argocd — atributo novo do deployment (lista de escalares, ordenada)
  workloads: ["Deployment/api", "Rollout/api-canary"]
  de status.resources[] com kind ∈ {Deployment, StatefulSet, DaemonSet, Rollout}; nome pela regra de nome
  simples; nenhum válido → sem o atributo

context --json — cada item de delivery.deployments ganha, quando há:
  "tier": "test" | "production"      (do environment; ausente sem marcação)
  "namespace": "api"                  (attrs.namespace do deployment)
  "workloads": ["Deployment/api"]
  "access": true | false              (há access.clusters.<cluster> nesta máquina para algum cluster do deployment)
context Markdown — a linha do ambiente ganha "; tier `test`", "; namespace `api`", "; workloads `Deployment/api`"
  e "; sem acesso local" quando access é false (cada parte só com valor)

doctor
  ambiente sem tier → AVISO "ambientes sem marcação: dev, qa (conta como produção)"
  cluster do grafo sem access local → AVISO "acesso <cluster>: sem contexto local" (OK: "contexto definido", sem valor)
lint
  regra nova "untiered-environment" (aviso): um achado por ambiente sem tier
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/collectors/argocd.py`: o atributo `workloads`.
- `scripts/atlas.py`: as chaves `environments` (`SHARED_KEYS`) e `access` (`LOCAL_KEYS`), as validações, o `tier` no `build`, os campos no `context`, o `doctor` e a regra de `lint`.
- `assets/atlas-config.yml`: o exemplo comentado.
- `references/`: `config.md`, `collectors/argocd.md`, `collector-contract.md`, `context.md` e `graph.md`.
- CHANGELOG, `plugin.json` e testes.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Sem chaves novas | atlas e fixtures de hoje | grafo, páginas, context, doctor e lint iguais (menos os avisos novos documentados) | CH-01 |
| `environments` válido | `dev: test`, `prod: production` | `tier` no nó `environment` | UT-01 |
| `environments` inválido | tier desconhecido, nome fora da regra | exit 2 com posição e motivo, sem o item | UT-01 |
| `workloads` | `status.resources` com Deployment, Service, Secret, Rollout | só os kinds permitidos, ordenados | UT-02 |
| `access` local | contexto definido, inválido, com quebra de linha | aceito sem imprimir o valor; inválido → exit 2 sem o item | UT-03 |
| Vários atlas | `access` em cada entrada | cada atlas usa o seu | UT-03 |
| Context | deployment com tier, namespace, workloads e acesso | campos no JSON e na linha do Markdown | UT-04 |
| Avisos | ambiente sem tier, cluster sem acesso | AVISO no doctor; achado no lint | UT-05 |
| Ponta a ponta | scan + build + context com as chaves | campos certos; nenhum contexto local em saída nenhuma | IT-01 |
| Contrato | snapshot com `workloads` | aceito pelo `@1` e pela versão anterior | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dadas as fixtures de hoje (`acme`, `image-link`) sem `environments`, `access` nem `status.resources`, quando `scan`, `build` e `context` rodam, então `graph.json`, páginas e pacote são iguais aos de hoje. As únicas diferenças no `doctor` e no `lint` são os avisos novos documentados (guarda: o grafo e o pacote passam antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado `environments: {dev: {tier: test}, prod: {tier: production}}`, quando o `build` roda, então `environment:dev` tem `tier: test` e `environment:prod` tem `tier: production`. Com `tier: staging`, um nome com espaço ou um valor que não é mapa, o resultado é exit 2 com `environments: item N inválido — <motivo>` em `config --json`, `build` e `lint`, sem o texto do item.
- **UT-02** — Dado `status.resources` com `Deployment/api`, `Service/api`, `Secret/api-db`, `Rollout/api-canary` e um nome inválido, quando o coletor mapeia, então `workloads` é `["Deployment/api", "Rollout/api-canary"]`. Sem nenhum, não há atributo.
- **UT-03** — Dado o `config.yml` local com `access.clusters.cluster-dev.context: dev-ctx-SEGREDO-NAO`, quando `config --json`, `doctor` e `lint` rodam, então:
  - o contexto conta como definido;
  - `dev-ctx-SEGREDO-NAO` não aparece em nenhuma saída;
  - contexto vazio, com quebra de linha ou com mais de 256 caracteres dá exit 2 com `access.clusters: item N inválido — <motivo>`;
  - na forma com vários atlas, cada entrada usa o seu `access`.
- **UT-04** — Dado um deployment com tier, namespace, workloads e acesso local, quando `context --json` roda, então `delivery.deployments[]` traz `tier`, `namespace`, `workloads` e `access: true`. A linha do Markdown traz as partes novas em crase. Sem acesso, vem `access: false` e "sem acesso local". Sem tier, não há a chave `tier`.
- **UT-05** — Dados ambientes sem tier e um cluster sem acesso, quando `doctor` e `lint` rodam, então o `doctor` mostra os dois AVISOS e o `lint` mostra um achado `untiered-environment` por ambiente. Nenhum deles muda o exit de ERRO.

### 7.3 Testes de Integração
- **IT-01** — Com as fixtures `image-link`, mais `status.resources`, `environments` e `access` num atlas e numa configuração temporários, quando `scan`, `build` e `context --json "api"` rodam, então os deployments trazem os campos novos certos. Nenhum snapshot, página, `graph.json` ou saída contém o nome do contexto local.

### 7.4 Testes de Contrato
- **CT-01** — Dado um snapshot do `argocd` com `workloads`, quando o validador `@1` roda (e a validação que ignora atributos desconhecidos), então o snapshot é aceito. Sem o atributo, o grafo é o de hoje.

### 7.5 Testes E2E
- N/A — sem jornada interativa; IT-01 roda a CLI de ponta a ponta.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- Fixtures `image-link` e `acme` com nomes genéricos.
- `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários.
- Sem rede e sem kubectl real.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/boson-atlas/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin.
- **Dados/schema:** aditivo. O primeiro `scan` grava `workloads`, e o primeiro `build` com `environments` grava o `tier`.
- **Compatibilidade:**
  - a versão anterior ignora `workloads` e `tier`;
  - `environments` no arquivo compartilhado é acusado pelo `lint` da versão anterior, e o CHANGELOG avisa para atualizar as máquinas antes de declarar a chave (mesmo cuidado da SPEC-0082);
  - `access` é local e não afeta outras máquinas.
- **Observabilidade:** os avisos do `doctor` e o achado do `lint`.
- **Rollback:** reverter o merge e tirar as chaves novas.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Onde fica o contexto do cluster? — Na configuração local da máquina (`access.clusters`), só pelo nome, porque ele muda por máquina e pode trazer o id da conta (recomendação do arquiteto; revisável no H1).
- [x] Ambiente sem marcação vale como quê? — Como produção para quem consome (probes e verificação). É o lado conservador (recomendação do arquiteto; revisável no H1).
- [x] Profile e região de nuvem entram agora? — Não. Entram com o primeiro adaptador de nuvem, porque nada desta onda os usa (recomendação do arquiteto; revisável no H1).

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
- [ ] Red: CH-01 (passa antes), UT-01 a UT-05, IT-01 e CT-01 com a tag `SPEC-0087:<ID>`, falhando pelo motivo certo; fixtures `image-link` e `acme` reaproveitadas, com nomes genéricos
- [ ] Green: atributo `workloads` no coletor `argocd.py`; `environments` (com `tier`) e `access.clusters` na configuração; campos novos em `delivery.deployments` no `context`; avisos do `doctor`; regra `untiered-environment` no `lint`; `references/`, `ATLAS_VERSION`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [ ] Validar: suíte completa + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 68f7863 | 2026-11-22 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Todos os testes do plano passando e listados na Verificação
- [ ] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [ ] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [ ] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [ ] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [ ] Observabilidade e rollback prontos conforme o Plano de Rollout
- [ ] Documentação raiz e CHANGELOG atualizados (G7)
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0087`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
