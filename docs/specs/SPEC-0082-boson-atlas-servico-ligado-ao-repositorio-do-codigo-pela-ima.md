---
id: SPEC-0082
title: "boson-atlas: serviço ligado ao repositório do código pela imagem e caminho de entrega no build"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-19
parent:
depends_on: []
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/collectors/argocd.py, skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/assets/atlas-config.yml, skills/boson-atlas/references/collectors/argocd.md, skills/boson-atlas/references/graph.md, skills/boson-atlas/references/config.md, skills/boson-atlas/references/collector-contract.md, skills/boson-atlas/tests/**, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0011, ADR-0022]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0082 — boson-atlas: serviço ligado ao repositório do código pela imagem e caminho de entrega no build

> Origem: radar de 2026-11-19 (uso real com GitOps: a Application aponta para o repositório de IaC e o código mora em outro repositório); detalhada em 2026-11-20.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O atlas passa a ligar cada serviço ao repositório do **código**, além do repositório de configuração do GitOps, pela imagem que o deployment roda. Com essa ligação, a página do serviço mostra as pipelines e os donos do repositório do código. Ela também ganha a seção "Do commit até o pod", montada só a partir do grafo. Applications nomeadas por ambiente (`dev-x`, `qa-x`) passam a cair no mesmo serviço por um padrão de nome configurável.

## 2. Motivação & Escopo
**Motivação:** no uso real com GitOps, o atlas ligava o serviço ao repositório de IaC. O `sourced_from` da Application é o `repoURL` dela, e esse é o repositório de configuração. Por isso as pipelines do repositório do código não apareciam ("Pipelines: nenhum"), e o agente teve de explorar os repositórios para explicar o caminho do commit até o pod. Sem `nameOverride` nos values (SPEC-0076), cada ambiente também virava um serviço separado.

**Objetivos (dentro do escopo):**
- **Coletor `argocd`, imagens:** novo atributo `images` no `deployment`, com a lista de imagens sem registry, tag nem digest. Vem de `status.summary.images` e, como reserva, da chave `image.repository` dos values do Helm.
- **Coletor `argocd`, nome do serviço:** opção `--service-pattern REGEX`, que tira o nome do serviço do nome da Application (grupo `service`). Entra na ordem depois do rótulo e do `nameOverride`.
- **`build`, regra 4:** uma imagem de um deployment que corresponde a um repositório conhecido dá `service sourced_from repository`, inferido, com a imagem como evidência.
- **Mapa explícito:** chave opcional `image_repositories` no `atlas-config.yml` compartilhado, para os casos em que o caminho da imagem não diz o repositório.
- **Página do serviço:** região gerada "Do commit até o pod" (repositório do código → pipelines → imagem → repositório de configuração → deployments por ambiente, com cluster e estado), e os repositórios separados em "Código" e "Configuração (GitOps)".

**Não-objetivos (fora do escopo):**
- Ler packages ou registries (API do GitHub Packages, ECR) e o conteúdo dos workflows. A ligação vem só do que os coletores já veem mais o mapa explícito.
- Kind ou relação nova no contrato (ADR-0022).
- Tag ou digest como dado: são dados de execução.
- Coletor de IaC (SPEC-0083), contas (SPEC-0084) e notas descobertas pelo agente (SPEC-0085).

## 3. Dependências
- **Implementações necessárias:** N/A — SPEC-0076 (`nameOverride`) já está na main.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com os seguintes padrões de referência:
- **coletor:** as funções puras de `assets/collectors/argocd.py` (`extract_config_refs`, `name_override`, `service_and_environment`, `map_application`) e as opções `--service-label`/`--ref-suffixes`;
- **build:** `infer_relations` em `scripts/atlas.py` (regras 1 a 3, só igualdade de texto, evidência por aresta) e `_service_regions`, que já busca as pipelines pelos repositórios `sourced_from` do serviço;
- **testes:** `tests/test_collector_argocd.py`, `tests/test_build.py` e o teste de coleta conjunta `MixedCaseScanTest`.

**Decisão:**
- `images` é um atributo do `deployment`: uma lista de escalares, que o contrato `@1` já aceita.
- A regra 4 roda no `build` depois da regra 1, com o casamento descrito no contrato.
- O mapa `image_repositories` fica no arquivo compartilhado, porque vale para a organização.
- A página separa os repositórios pela origem da aresta: a regra 1 vem de `repoURL` e é "Configuração"; a regra 4 vem de imagem e é "Código".

**Justificativa:**
- O `build` rejeita o snapshot inteiro quando encontra um kind ou relação desconhecido (`read_snapshots` revalida o contrato). Um kind novo faria máquinas na versão anterior perderem todos os dados do coletor.
- Um atributo e uma regra de inferência não mudam o contrato, e a versão anterior só ignora o atributo.
- A página já soma as pipelines e os donos dos repositórios `sourced_from`, então a regra 4 sozinha já traz as pipelines do código.

**Desvio do padrão existente:** nenhum. Uma regra de inferência nova e um atributo seguem o padrão das regras 1 a 3 e de `config_refs` (ADR-0022).

**Alternativas descartadas:**
- **Kind `image` e relação `publishes_image`:** quebra a leitura em máquinas na versão anterior.
- **Ler a API de packages:** precisa de permissão extra e não cobre outros registries.
- **Ler o conteúdo dos workflows:** é frágil e específico de ferramenta.

**ADRs:** ADR-0022 (criado por esta spec), ADR-0011.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** a regra 4 é linear no número de deployments e imagens, com um índice de repositórios por nome. A meta de 1.000 Applications em menos de 10 s no coletor continua valendo (fixture gerada).
- **Segurança:** o host do registry nunca sai, porque pode conter id de conta (ex.: `<conta>.dkr.ecr.<região>.amazonaws.com`). Também nunca saem tag, digest, credenciais na URL da imagem nem valores do Helm além de `image.repository`. Uma imagem que não passa a regra de nome é descartada.
- **Privacidade e dados pessoais:** N/A — só nomes de imagem e de repositório.
- **Disponibilidade e resiliência:** snapshot sem `images` (coletor antigo) dá o mesmo grafo de hoje (CH-01). Um `image_repositories` inválido dá exit 2 com a chave e a posição, sem o valor (mesma regra da SPEC-0080).
- **Acessibilidade (UI):** N/A — páginas Markdown.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** atributo `images` do `deployment` (coletor `argocd`), opção `--service-pattern`, regra 4 do `build`, chave `image_repositories` do `atlas-config.yml` e regiões da página do serviço.

```text
Coletor argocd — atributo novo do deployment (contrato collector@1, lista de escalares)
  images: ["acme/api", "acme/worker"]       # ordenada, sem repetição
  fontes, nesta ordem, juntando tudo: status.summary.images; parâmetro ou chave de values "image.repository"
  normalização de cada imagem:
    tira o esquema (oci://, docker://), tag (":1.4.2"), digest ("@sha256:...") e o host do registry
    (primeiro segmento com "." ou ":" ou igual a "localhost"); "docker.io/library/x" → "library/x"
    minúsculas; o resto precisa casar ^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$, senão é descartada
    credencial na URL ("user:pass@host/...") → descartada inteira

Coletor argocd — nome do serviço
  --service-pattern REGEX   (opcional; regex Python com o grupo nomeado "service")
  ordem: --service-label → nameOverride (SPEC-0076) → --service-pattern sobre metadata.name → metadata.name
  o grupo "service" precisa passar a mesma regra de nome simples do nameOverride, senão cai no próximo item
  regex inválida ou sem o grupo "service" → exit 2: "--service-pattern inválido: <motivo>"

atlas-config.yml (compartilhado) — chave opcional
  image_repositories:
    "acme/legacy-api": "acme/api-v1"        # caminho normalizado da imagem → <dono>/<repositório>
  cada chave e valor seguem a regra de nome acima (valor com exatamente uma "/"); senão exit 2:
    "image_repositories: item N inválido — <motivo>" (sem citar o item)

Build — regra 4 (inferida, depois da regra 1)
  para cada deployment D com deploys → service:S e cada imagem I de D.attrs.images:
    1. I em image_repositories → repository:<valor>, se esse repositório existe no grafo
    2. senão, I = "<dono>/<nome>" e repository:<dono>/<nome> existe → esse
    3. senão, o último segmento de I é o nome de exatamente um repositório do grafo → esse
    4. senão (nenhum ou mais de um) → nada
  gera S sourced_from repository (inferred: true, evidence: "image:<I>"); igual a uma aresta declarada ou
  repetida → não duplica (regras de hoje)

Página do serviço (services/<id>.md, regiões do atlas)
  "Repositórios": separados em "Código" (arestas com evidência image:) e "Configuração (GitOps)" (demais);
    sem nenhuma image:, a lista fica como hoje
  "Pipelines" e "Donos": como hoje (somam todos os repositórios sourced_from)
  região nova "Do commit até o pod", só quando há repositório de Código:
    repositório do código → pipelines dele → imagem(ns) → repositório de configuração → um item por
    deployment com ambiente, cluster, sync_status e health_status; sem nenhum texto de ferramenta fixo
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/collectors/argocd.py`: as imagens e o `--service-pattern`.
- `scripts/atlas.py`: a regra 4, `image_repositories` (validação e `SHARED_KEYS`), as regiões da página e `ATLAS_VERSION`.
- `assets/atlas-config.yml`: o exemplo comentado.
- `references/collectors/argocd.md`, `references/graph.md`, `references/config.md` e `references/collector-contract.md`: o atributo `images`.
- Testes, fixtures, CHANGELOG e `plugin.json`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Imagens do deployment | `status.summary.images` e `image.repository` com host, tag, digest | `images` normalizada, ordenada, sem host, tag nem digest | UT-01 |
| Imagem insegura ou inválida | credencial na URL, caracteres fora da regra, host com id de conta | descartada; nenhum pedaço sai | UT-02 |
| Nome por padrão | `--service-pattern '^(dev\|qa)-(?P<service>.+)$'` sem rótulo nem `nameOverride` | `dev-api` e `qa-api` → `service:api` | UT-03 |
| Padrão inválido | regex quebrada, sem grupo `service`, grupo que não casa ou inválido | exit 2, ou cai no nome da Application | UT-03 |
| Regra 4 por dono/nome | imagem `acme/api` e `repository:acme/api` | `service sourced_from repository:acme/api`, evidência `image:acme/api` | UT-04 |
| Regra 4 por nome único | `team-x/api` e um só repositório `api` | liga a ele; dois `api` → nada | UT-05 |
| Mapa explícito | `image_repositories` | vence a convenção; item inválido → exit 2 sem o item | UT-06 |
| Página do serviço | serviço com repositório de código e de GitOps | "Código"/"Configuração", pipelines do código, região "Do commit até o pod" | UT-07, IT-01 |
| Compatibilidade | snapshot sem `images`; serviço sem imagem que case | grafo e páginas iguais a hoje | CH-01 |
| Contrato | snapshot com `images` | aceito pelo validador `@1` e pela versão anterior (atributo ignorado) | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dadas as fixtures atuais de `argocd` e `github` (`acme`), quando `scan` e `build` rodam, então o `graph.json` e as páginas são iguais aos de hoje, sem região nova e sem aresta nova (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dados `status.summary.images` com `ghcr.io/acme/api:1.4.2`, `ghcr.io/acme/api@sha256:abc`, `docker.io/library/redis:7` e o parâmetro Helm `image.repository=registry.interno:5000/acme/worker`, quando o coletor mapeia, então `images` é `["acme/api", "acme/worker", "library/redis"]`.
- **UT-02** — Dadas imagens `user:tok@ghcr.io/acme/api`, `123456789012.dkr.ecr.us-east-1.amazonaws.com/api` (ECR), `ghcr.io/Acme/API` e `ghcr.io/acme/a b`, quando o coletor mapeia, então:
  - a primeira e a última são descartadas;
  - a do ECR vira `api`;
  - `ghcr.io/Acme/API` vira `acme/api`;
  - `tok`, `123456789012` e `amazonaws` não aparecem em nenhuma saída do coletor.
- **UT-03** — Dado `--service-pattern '^(?:dev|qa)-(?P<service>.+)$'`, quando as Applications `dev-api`, `qa-api` e `prod-api` (sem rótulo nem `nameOverride`) são mapeadas, então dão `service:api`, `service:api` e `service:prod-api`. O rótulo e o `nameOverride` continuam vencendo. Uma regex inválida ou sem o grupo `service` dá exit 2, e um grupo que capture texto inválido cai no nome da Application.
- **UT-04** — Dados `deployment:dev-api` (`images: [acme/api]`, `deploys service:api`, `sourced_from repository:acme/iac`) e `repository:acme/api`, quando o `build` infere, então há `service:api sourced_from repository:acme/api` com `inferred: true` e `evidence: "image:acme/api"`, além da aresta da regra 1 para `acme/iac`.
- **UT-05** — Dada a imagem `team-x/api`, quando existe um único repositório de nome `api` (`acme/api`), então a regra 4 liga a ele. Com dois (`acme/api` e `globex/api`), ou com nenhum, não há aresta.
- **UT-06** — Dado `image_repositories: {"acme/legacy-api": "acme/api-v1"}`, quando o `build` infere, então liga a `repository:acme/api-v1` mesmo que exista `acme/legacy-api`. Um item inválido (valor sem `/`, maiúsculas, esquema, `@`) dá exit 2 com `item N inválido` e o motivo, sem nenhum texto do item, em `config --json`, `build` e `lint`.
- **UT-07** — Dado um serviço com aresta de imagem e aresta de `repoURL`, quando a página é gerada, então:
  - "Repositórios" mostra "Código: acme/api" e "Configuração (GitOps): acme/iac";
  - "Pipelines" inclui as pipelines de `acme/api`;
  - a região "Do commit até o pod" lista, na ordem, repositório do código, pipelines, imagem, repositório de configuração e um item por deployment, com ambiente, cluster e estado.

  Sem aresta de imagem, a região não aparece.

### 7.3 Testes de Integração
- **IT-01** — Com fixtures novas de `github` (repositórios `acme/api` e `acme/iac`, pipelines de `acme/api`) e de `argocd` (Applications `dev-api` e `qa-api` com `repoURL` do `acme/iac`, `status.summary.images` com `ghcr.io/acme/api:<tag>` e `--service-pattern`), quando `scan` e `build` rodam num atlas temporário, então:
  - há um só `service:api` com dois deployments;
  - a página do serviço mostra as pipelines de `acme/api` e a região "Do commit até o pod";
  - nenhum snapshot nem página contém tag ou host de registry.

### 7.4 Testes de Contrato
- **CT-01** — Dado um snapshot do `argocd` com `images` nos deployments, quando o validador do contrato `@1` roda nesta versão e na lógica da versão anterior (validação sem conhecer o atributo), então o snapshot é aceito nas duas. Com o atributo removido, o grafo é igual ao de hoje.

### 7.5 Testes E2E
- N/A — a mudança é de dados e páginas geradas, sem jornada interativa; IT-01 roda `scan` e `build` como processo, de ponta a ponta.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- Fixtures em `tests/fixtures/argocd/` e `tests/fixtures/github/`, só com nomes genéricos (`acme`).
- `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários.
- Sem rede.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/boson-atlas/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin.
- **Dados/schema:** `images` e a regra 4 são aditivos.
  - O primeiro `scan` depois do upgrade acrescenta arestas `sourced_from` inferidas e a região nova.
  - Com `--service-pattern`, os ids de serviço por ambiente se juntam (o `diff` mostra a troca uma vez, como na SPEC-0076).
- **Compatibilidade:**
  - a versão anterior lê os snapshots novos e ignora `images`;
  - `image_repositories` no arquivo compartilhado é acusado pelo `lint` da versão anterior (chave desconhecida), e o CHANGELOG avisa para atualizar as máquinas antes de declarar a chave (mesmo cuidado da SPEC-0080).
- **Observabilidade:** a evidência `image:<I>` em cada aresta inferida e a seção "Do commit até o pod" na página.
- **Rollback:** reverter o merge e tirar `image_repositories` do `atlas-config.yml`. Os snapshots com `images` continuam válidos.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Kind `image` e relação nova, ou atributo e regra de inferência? — Atributo `images` e regra 4. O `build` descarta o snapshot inteiro diante de um kind ou relação desconhecido, e máquinas na versão anterior perderiam todos os dados do coletor (ADR-0022). A recomendação do arquiteto foi aceita no piloto automático autorizado por thomas em 2026-11-17 ("beleza, segue no piloto automático até o merge"); revisável no H1.
- [x] O host do registry entra? — Não. Ele pode conter id de conta (ECR), e o casamento com o repositório só precisa do caminho (recomendação do arquiteto, piloto automático; revisável no H1).
- [x] Como casar imagem e repositório sem convenção fixa? — Nesta ordem:
  1. mapa explícito;
  2. `<dono>/<nome>` igual;
  3. último segmento igual ao nome de um único repositório;
  4. senão, nada, para não ligar errado (recomendação do arquiteto, piloto automático; revisável no H1).
- [x] Onde fica o mapa explícito? — `image_repositories` no `atlas-config.yml` compartilhado, porque vale para a organização e chega às máquinas pelo `init --join` (recomendação do arquiteto, piloto automático; revisável no H1).
- [x] Nome do serviço por ambiente: padrão no coletor ou no `build`? — No coletor (`--service-pattern`), junto do rótulo e do `nameOverride`, para o id do serviço já sair certo no snapshot (recomendação do arquiteto, piloto automático; revisável no H1).

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — b289b44 | 2026-11-20 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0082`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
