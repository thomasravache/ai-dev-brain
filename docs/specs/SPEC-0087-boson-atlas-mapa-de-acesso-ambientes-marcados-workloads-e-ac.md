---
id: SPEC-0087
title: "boson-atlas: mapa de acesso — ambientes marcados, workloads e acesso local por cluster"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-11-22
parent: SPEC-0075
depends_on: []
consumes_contract: []
contract_version: 3
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/collectors/argocd.py, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/assets/atlas-config.yml, skills/boson-atlas/references/**, skills/boson-atlas/tests/**, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/SKILL.md, mcp/tests/**, .claude-plugin/plugin.json]
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

**Esclarecimentos (Emenda v2):**
- **CH-01:** compara com a fixture `acme` sem `status.resources`. Antes de comparar, tira só os campos novos que já têm valor hoje (`namespace`, `access`) e as partes "; namespace …" e "; sem acesso local" do Markdown. `tier` e `workloads` não podem aparecer.
- **Testes antigos que mudam com o atributo novo:** o conjunto de atributos do deployment e o `expected-acme.json` (SPEC-0035), e o conjunto de chaves de `delivery.deployments` no CT-01 da SPEC-0086. Quem atualiza é o test-writer desta spec, no commit `test(...)` dela, antes do código.
- **`access`:** só aparece quando o deployment tem cluster no grafo. Sem cluster, a chave fica ausente.
- **`access.clusters`:** a chave é o nome do cluster como está no grafo, e pode ser uma URL do servidor (por exemplo `https://kubernetes.default.svc`). Basta ser um texto de 1 a 256 caracteres, sem quebra de linha.
- **Linhas do `doctor`:** seguem o formato das outras linhas (`<rótulo> — <detalhe>`). Os testes conferem só os pedaços do contrato. Um `access` inválido aparece como ERRO no `doctor`, com o exit de erro de sempre do `doctor` (1). O exit 2 vale para `config --json`, `build` e `lint`.
- **Markdown:** as partes novas vêm depois de `cluster`, `sync` e `health`, nesta ordem: `tier`, `namespace`, `workloads`, `sem acesso local`. Vários workloads vão juntos, separados por vírgula, dentro do mesmo trecho em crase.

**Esclarecimentos (Emenda v3):**
- **`tier` do deployment:**
  - é `production` quando algum dos seus ambientes é de produção;
  - é `test` só quando todos os ambientes são de teste;
  - fica ausente quando algum ambiente não tem marcação, mesmo que outro seja de produção (quem consome trata a ausência como produção, ADR-0023).
- **Leituras:**
  - `doctor` e `lint` leem as marcações da chave `environments`;
  - o `doctor` lê os ambientes e os clusters do `graph.json`;
  - `scan` e `build` não leem `access`, que é local. O exit 2 de um `access` inválido vale para `config`, `context` e `lint`.
- **Testes antigos que mudam com esta spec:** são as expectativas exatas que ganham as partes novas, na lista abaixo. Quem as atualiza é o test-writer, num commit `test(...)` antes do `feat(...)`.
  - `test_collector_argocd`: a lista de entidades de `map_application`;
  - `test_context_delivery`: UT-01, UT-03 e IT-01 (`namespace`, `access: false`, "; sem acesso local");
  - `mcp/tests/test_atlas_context_delivery.py` UT-05;
  - `test_lint`: a lista de regras e os casos "sem achado", que ganham o aviso `untiered-environment` quando o ambiente não tem marcação.
- **Golden do CH-01:** normaliza a `version` do pacote, como já faz com a pasta e a data.
- **`touches`:** ganha `skills/boson-atlas/SKILL.md` (lista de regras do `lint`) e `mcp/tests/**`.

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
- [x] Red: CH-01 (passa antes), UT-01 a UT-05, IT-01 e CT-01 com a tag `SPEC-0087:<ID>`, falhando pelo motivo certo; fixtures `image-link` e `acme` reaproveitadas, com nomes genéricos
- [x] Green: atributo `workloads` no coletor `argocd.py`; `environments` (com `tier`) e `access.clusters` na configuração; campos novos em `delivery.deployments` no `context`; avisos do `doctor`; regra `untiered-environment` no `lint`; `references/`, `ATLAS_VERSION`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 68f7863 | 2026-11-22 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=38, skipped=1)) — b442bcd | 2026-11-23 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 5828e49 | 2026-11-23 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — fa7a721 | 2026-11-23 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente (subagente, rodada 1): APPROVED — sem blocker/major; 1 minor (nome com quebra de linha final passa no HOST_RE, já existente) e 2 nits no Relatório de Entrega; o FAIL anterior foi só o veredito escrito sem a palavra APPROVED — 0f4bd97 | 2026-11-23 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — e5bbfe9 | 2026-11-23 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-23 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-23 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 070a48a | 2026-11-23 |

### Histórico de reprovações
- G4 FAIL 2026-11-23 — verify G1+G4: PASS; revisão: reviewer independente (subagente, rodada 1): APROVADO — sem blocker/major; 1 minor (nome com \n final passa no HOST_RE, já existente) e 2 nits registrados no Relatório de Entrega — fbf77b6
- G4 PASS 2026-11-23 — depois de 1 reprovação(ões)

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
- O atlas sabe quais ambientes são de teste e quais são de produção: a chave compartilhada `environments` marca o `tier`, e o `build` grava esse `tier` no ambiente. Um ambiente sem marcação conta como produção.
- O coletor `argocd` grava os `workloads` de cada deployment (Deployment, StatefulSet, DaemonSet e Rollout), tirados de `status.resources`.
- Cada máquina declara, na configuração local, o contexto do kubeconfig de cada cluster (`access.clusters`). O valor nunca sai em nenhuma saída nem arquivo.
- O `context` mostra em `delivery.deployments` o `tier`, o `namespace`, os `workloads` e se há acesso local. O `doctor` avisa dos ambientes sem marcação e dos clusters sem acesso, e o `lint` tem a regra `untiered-environment`.

### Como foi feito
- `assets/collectors/argocd.py`: `workloads_of`, com os kinds permitidos e a regra de nome simples.
- `scripts/atlas.py`:
  - `validate_environments` e `validate_access` seguem o padrão do `image_repositories` (SPEC-0082) e do `remotes` (SPEC-0080);
  - `with_tiers` grava o tier no `build`;
  - `access_view` troca o contexto por "definido";
  - `_deployment_tier` e `_access_fields` montam os campos do `context`;
  - o `doctor` ganhou as linhas novas, e o `lint` a regra `untiered-environment`;
  - o `dump_yaml` põe aspas nas chaves com ":", para uma URL de cluster sobreviver ao `init --join`.
- Emenda v2: perguntas do test-writer no G1. Emenda v3: relatório do implementer. Ela define o `tier` de um deployment com vários ambientes, as leituras do `doctor` e do `lint`, os testes antigos a atualizar e o `touches`.
- G4 aprovado na rodada 1. O primeiro registro do G4 saiu FAIL só porque o veredito foi escrito sem a palavra APPROVED.
- Versões: ATLAS_VERSION 2026.11.14, plugin 2026.11.27.

### Prova de Correção
N/A — type feature.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Sem as chaves novas, grafo, páginas, context, doctor e lint iguais aos de antes | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-01 | `environments` marca o `tier` dos ambientes; item inválido recusado com posição e motivo | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-02 | `workloads` só dos kinds permitidos, ordenado, com nome simples | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-03 | `access.clusters` local validado; o contexto nunca é impresso; chave em URL; vários atlas | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-04 | `delivery.deployments` com tier (regra da Emenda v3), namespace, workloads e access; Markdown na ordem | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |
| UT-05 | Avisos do `doctor` e regra `untiered-environment` no `lint` | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |
| IT-01 | `scan` + `build` + `context` com tudo ligado, sem o contexto local em nenhum arquivo ou saída | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |
| CT-01 | Snapshot com `workloads` aceito pelo `@1` atual e pela versão anterior | PASS | `test_access_map.py` — CI do PR #61 (run 45117677611, Python 3.9 e 3.15) e suíte local no G2/G5 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy (G6 N/A, mesmo critério da SPEC-0017). A entrega chega pelo plugin `fermion` 2026.11.27, depois do merge do PR #61.

### Pendências
Nenhuma spec nova. Achados do G4 que ficaram para o radar:
- minor: o `HOST_RE` aceita um nome com quebra de linha no fim (problema que já existia; o Kubernetes não gera nomes assim);
- nit: o `doctor` casa o `access` só pelo nome do cluster, e o `context` casa pelo nome ou pelo id;
- nit: o nome `_lint_image_repositories` ficou estreito.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0087`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-23 | Esclarecimentos (Emenda v2): CH-01 sem `status.resources`; testes antigos atualizados pelo test-writer; `access` só com cluster; chave de `access.clusters` pode ser URL; formato e exit do `doctor`; ordem das partes no Markdown | Perguntas do test-writer no G1 | SPEC-0088 | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 3 | 2026-11-23 | Esclarecimentos (Emenda v3): `tier` do deployment com vários ambientes; o que `doctor`, `lint`, `scan` e `build` leem; testes antigos a atualizar; versão normalizada no golden; `touches` com `SKILL.md` e `mcp/tests/**` | Relatório do implementer no G2 | SPEC-0088 | thomas, 2026-11-23 (piloto automático com o recomendado) |
