---
id: SPEC-0086
title: "boson-atlas e gluon-spec: caminho de entrega no context e roteiro de verificação depois do merge"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-11-20
parent:
depends_on: []
consumes_contract: []
contract_version: 3
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/references/context.md, skills/boson-atlas/tests/**, skills/boson-atlas/CHANGELOG.md, skills/gluon-spec/SKILL.md, skills/gluon-spec/references/gates.md, skills/gluon-spec/references/brownfield.md, skills/gluon-spec/references/sdd-config.template.yml, skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/tests/**, skills/gluon-spec/CHANGELOG.md, mcp/tests/**, .claude-plugin/plugin.json]
adrs: [ADR-0022]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-20
---

# SPEC-0086 — boson-atlas e gluon-spec: caminho de entrega no context e roteiro de verificação depois do merge

> Origem: pedido do thomas em 2026-11-20, depois da SPEC-0082. Uma implementação da gluon-spec deve poder consultar o atlas para saber como verificar a entrega depois do merge de um PR, sempre de forma agnóstica e configurável.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O `context` da boson-atlas (CLI e tool MCP `atlas_context`) passa a entregar, por serviço, o **caminho de entrega** que o grafo já conhece desde a SPEC-0082:
- repositório do código e repositório de configuração;
- pipelines;
- imagens;
- deployments por ambiente, com cluster e o último estado visto.

A gluon-spec usa esse pacote no G6 para montar um **roteiro de verificação depois do merge**: o que acompanhar, onde e em quais ambientes. Os ambientes são configurados no `sdd-config.yml`.

## 2. Motivação & Escopo
**Motivação:** a SPEC-0082 pôs o caminho "do commit até o pod" na página do serviço, mas o `context` devolve só uma lista única de repositórios e os deployments com o ambiente. Quem consulta o atlas por máquina (outras skills, a tool MCP) não recebe a separação código/configuração, as pipelines, as imagens nem o cluster e o estado. A gluon-spec, depois do merge, redescobre esse caminho sozinha para saber o que verificar.

**Objetivos (dentro do escopo):**
- **`context --json`:** chave nova `delivery` em cada serviço que tem caminho de entrega, com:
  - repositórios de código e de configuração;
  - pipelines, cada uma com o seu repositório;
  - imagens;
  - deployments com ambientes, clusters, `sync_status`, `health_status` e imagens.
- **`context` em Markdown:** o mesmo dado num bloco "Entrega" dentro do serviço.
- **gluon-spec, G6:** com o atlas disponível e `delivery_check` ligado, o roteiro de verificação vem do `delivery` dos serviços da spec e fica registrado no Relatório de Entrega ("Deploy") e na evidência do G6.
- **Configuração:** chave `delivery_check` no `sdd-config.yml`:
  - `enabled` liga ou desliga a consulta;
  - `environments` diz quais ambientes, com os nomes do atlas, entram no roteiro.

**Não-objetivos (fora do escopo):**
- Rodar a verificação: consultar o cluster, ler logs ou chamar a CI. Fica com o agente e as ferramentas do projeto, e o mapa de acesso, observabilidade e validação é da SPEC-0075.
- Marcação de ambiente `test`/`production` no atlas (SPEC-0075). Aqui vale a regra que a gluon-spec já tem: produção só com a confirmação explícita da pessoa.
- Comando pronto vindo do atlas: o pacote traz só dados estruturados.
- Kind, relação ou coletor novo.

## 3. Dependências
- **Implementações necessárias:** N/A — SPEC-0082 (imagem, regra 4 e separação código/configuração) já está na main.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com os seguintes padrões de referência:
- **context:** `build_context`, `_service_entry` e `_service_lines` em `skills/boson-atlas/scripts/atlas.py`, com a regra de valores numa linha só e crase trocada por `'` (SPEC-0048) e o corte por `--max-chars`;
- **separação código/configuração:** `_code_edges` e `_flow_lines` (SPEC-0082), que já montam a região "Do commit até o pod" a partir do grafo;
- **gluon-spec:** o uso do `org_context` no DISCOVER (SPEC-0081, `references/brownfield.md`), cujas regras de escolha do atlas, exit 3 e aviso de envelhecimento o G6 reaproveita;
- **testes:** `skills/boson-atlas/tests/test_context.py`, `test_image_repositories.py` (fixtures `image-link`), os testes de texto da SKILL.md da SPEC-0081 e os testes da tool MCP em `mcp/tests/`.

**Decisão:**
- `delivery` é calculado no `context`, só de leitura, a partir do `graph.json`, com as mesmas regras da região "Do commit até o pod". Não há texto fixo de ferramenta.
- A chave é aditiva: as chaves de hoje (`repositories`, `deployments` e as outras) não mudam.
- A gluon-spec consulta no G6 com as mesmas regras de escolha do atlas do DISCOVER e monta o roteiro como dados. O agente transforma cada passo em comandos só de leitura das ferramentas do próprio projeto.

**Justificativa:** o dado já existe no grafo (SPEC-0082). Faltava entregá-lo a quem consulta, e uma chave aditiva não quebra nenhum consumidor. A configuração por projeto (`delivery_check`) deixa cada time escolher os ambientes sem acoplar a skill a um provedor.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **O agente ler a página `services/<id>.md`:** é texto livre, não estruturado, e mistura as notas do time.
- **Comando novo `atlas.py delivery`:** duplicaria a busca e o envelhecimento que o `context` já faz.
- **Comandos prontos no atlas:** o conteúdo do atlas é dado, não instrução (SPEC-0075, restrições).

**ADRs:** ADR-0022 (a separação código/configuração vem da regra 4).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `delivery` usa os índices que o `context` já monta. Num atlas de 1.000 serviços, o `context` não fica mais que 20% mais lento (medido no teste de desempenho do `context`, quando existir; senão, num grafo gerado no IT-01).
- **Segurança:**
  - Nenhum valor novo além do que o grafo já guarda.
  - Os valores saem numa linha só, com crase trocada (SPEC-0048).
  - Tag, host de registry e credencial continuam fora, porque o grafo não os tem (SPEC-0082).
  - O roteiro da gluon-spec é só de leitura e nunca põe segredo em comando.
- **Privacidade e dados pessoais:** N/A — só nomes de repositório, pipeline, imagem, ambiente e cluster.
- **Disponibilidade e resiliência:**
  - Sem caminho de entrega no grafo, o pacote fica igual ao de hoje (CH-01).
  - Sem atlas (exit 3) ou com o atlas velho, a gluon-spec avisa e segue com o `smoke_test` e o `deploy_*` do `sdd-config.yml`, sem bloquear o G6.
- **Acessibilidade (UI):** N/A — saída de CLI e Markdown.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** chave `delivery` do `context --json`, bloco "Entrega" do `context` em Markdown, chave `delivery_check` do `sdd-config.yml` e o passo de G6 da gluon-spec.

```text
context --json — cada item de "services" ganha, quando o serviço tem caminho de entrega:
  "delivery": {
    "code_repositories":   ["acme/api"],          # sourced_from com evidência image: (regra 4)
    "config_repositories": ["acme/iac"],          # os demais sourced_from, só quando há código; senão []
    "pipelines": [{"id": "acme/api/build", "name": "Build", "repository": "acme/api"}],
    "images": ["acme/api"],                       # as mesmas da região "Do commit até o pod"
    "deployments": [{"id": "dev-api", "environments": ["dev"], "clusters": ["cluster-dev"],
                     "sync_status": "Synced", "health_status": "Healthy", "images": ["acme/api"]}]
  }
  tem caminho de entrega = ao menos um deployment, uma pipeline ou um repositório de código
  listas em ordem alfabética (pipelines por id, deployments por id); chave de status ausente quando o atlas não tem
  pipelines = as que fazem "builds" de qualquer repositório sourced_from do serviço ou do próprio serviço
  sem caminho de entrega → sem a chave "delivery"; nenhuma chave existente muda

context (Markdown) — dentro do bloco do serviço, depois de "Deployments", só com "delivery":
  - Entrega:
    - Código: acme/api
    - Pipelines: Build (acme/api), Publish (acme/api)
    - Imagens: acme/api
    - Configuração (GitOps): acme/iac
    - dev: dev-api — cluster cluster-dev; sync Synced; health Healthy
  cada linha só quando tem valor; valores numa linha só, crase → ' (SPEC-0048); o bloco faz parte do item do
  serviço no corte de --max-chars (ordem do corte inalterada)

sdd-config.yml (gluon-spec) — chave opcional
  delivery_check:
    enabled: true          # false: o G6 não consulta o atlas
    environments: []       # nomes de ambiente do atlas que entram no roteiro; [] = todos os do serviço

gluon-spec, G6, depois do merge do PR
  com delivery_check.enabled diferente de false e o atlas disponível (mesmas regras do org_context no DISCOVER):
    roda: atlas.py context --json [--atlas <org_context>] "<serviços e termos da spec>"
    para cada serviço com "delivery", o "Roteiro de verificação" no Relatório de Entrega ("Deploy"), em ordem:
      1. pipelines do repositório do código a acompanhar no commit do merge
      2. repositório de configuração em que a imagem nova deve aparecer
      3. por ambiente de delivery_check.environments (ou todos): deployment, cluster e o estado esperado
         (sync e health), com o estado do atlas marcado como "último visto pelo atlas", nunca como atual
    a evidência do G6 cita o roteiro e o resultado de cada passo verificado
  regras: passos só de leitura; nenhum comando vem do atlas (o agente monta com as ferramentas do projeto);
    produção só com a confirmação explícita da pessoa (regra do G6); aviso de envelhecimento repassado;
    serviço sem "delivery" ou atlas indisponível → diz que o atlas não conhece o caminho e segue com
    smoke_test/test_e2e/deploy_* do sdd-config.yml; nunca bloqueia o G6 por falta de dado do atlas
```

**Esclarecimentos (Emenda v2):**
- `images` de cada deployment em `delivery` é o atributo `images` do próprio deployment, ordenado, ou `[]` sem o atributo. Não há filtro pelo repositório de código.
- Na linha `<ambiente>: <deployment>` do Markdown, cada parte (`cluster`, `sync`, `health`) só aparece quando o atlas tem o valor.
- O bloco "Entrega" vem depois da linha "Deployments" do mesmo serviço.
- `delivery_check` é uma chave de verdade no template (`enabled: true`, `environments: []`), com comentário, para o `whats-new` listá-la.

**Esclarecimentos (Emenda v3):**
- O `context` resolve as imagens com o mapa `image_repositories` do `atlas-config.yml` compartilhado, como o `build`. `delivery.images` fica igual às imagens da região "Do commit até o pod", inclusive quando o mapa aponta para um repositório ausente, caso em que não há fallback. Um mapa editado depois do último `build` só muda as arestas no próximo `build`.
- Uma pipeline que só faz `builds` do próprio serviço tem `repository: ""`, e no Markdown sai sem parênteses. Uma pipeline que faz build de vários repositórios usa o primeiro que é do serviço, e na falta dele o primeiro em ordem alfabética.
- No bloco "Entrega", cada valor vindo do atlas sai em código inline (crase), como na região da página, para um nome não imitar outra parte da linha.
- A SKILL.md (passo 7) traz só quando o roteiro roda e um ponteiro para o `gates.md` (G6), onde ficam as regras.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `skills/boson-atlas/scripts/atlas.py`: `delivery` no `_service_entry` e o bloco no `_service_lines`, reaproveitando `_code_edges` e a resolução de imagens da SPEC-0082.
- `skills/boson-atlas/references/context.md`: a chave e o bloco.
- `skills/gluon-spec/SKILL.md` (passo 7), `references/gates.md` (G6) e `references/brownfield.md` (o `org_context` também vale no G6).
- `skills/gluon-spec/references/sdd-config.template.yml`: `delivery_check` comentado.
- CHANGELOGs das duas skills, `SDD_TOOL_VERSION`, `ATLAS_VERSION`, `plugin.json` e testes.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Serviço com código e GitOps | regra 4 + `repoURL`, pipelines, deployments | `delivery` completo, separado, ordenado | UT-01 |
| Serviço sem repositório de código | só `repoURL` | `code_repositories` e `config_repositories` vazios; pipelines e deployments presentes | UT-02 |
| Sem caminho de entrega | serviço sem deployment, pipeline nem código | sem `delivery`; pacote igual ao de hoje | CH-01 |
| Markdown | serviço com `delivery`; valor com crase e quebra de linha | bloco "Entrega" na ordem, numa linha só, crase trocada | UT-03 |
| Corte | `--max-chars` pequeno | o bloco sai com o item do serviço; ordem do corte igual | UT-04 |
| Tool MCP | `atlas_context` | o JSON traz `delivery` como a CLI | UT-05 |
| gluon-spec | SKILL.md, gates.md, brownfield.md e o template | `delivery_check`, os três passos do roteiro, só leitura, produção com confirmação, fallback sem atlas | UT-06 |
| Ponta a ponta | `scan` + `build` + `context --json` | `delivery` correto, sem tag nem host de registry | IT-01 |
| Contrato | pacote de hoje | todas as chaves e tipos de antes continuam | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dado um atlas com serviços sem deployment, pipeline nem repositório de código, quando `context` roda em Markdown e em JSON, então a saída é igual à de hoje, byte a byte e sem a chave `delivery`. Para os serviços com caminho de entrega, as chaves de antes ficam iguais (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado o grafo das fixtures `image-link` (código `acme/api`, configuração `acme/iac`, pipelines Build e Publish de `acme/api`, deployments `dev-api` e `qa-api` com cluster e estado), quando `context --json "api"` roda, então `delivery` é exatamente o do contrato, com as listas em ordem.
- **UT-02** — Dado um serviço ligado só por `repoURL`, com pipeline e deployment, quando `context --json` roda, então:
  - `code_repositories` e `config_repositories` são `[]`;
  - `pipelines` e `deployments` estão presentes;
  - um deployment sem `sync_status` não tem a chave.
- **UT-03** — Dado um serviço com `delivery`, quando `context` roda em Markdown, então o bloco "Entrega" vem depois de "Deployments", com as linhas na ordem do contrato e só as que têm valor. Um nome de pipeline com crase e quebra de linha sai numa linha só, com `'`. Nenhum texto de ferramenta fixo (`argo`, `github`, `kubernetes`, `helm`) aparece fora dos dados.
- **UT-04** — Dado `--max-chars` que corta serviços, quando `context` roda, então o bloco "Entrega" nunca aparece sem o seu serviço, e a ordem de corte (serviços → regras → dependências → dicas) é a de hoje.
- **UT-05** — Dado o servidor MCP com um atlas de teste, quando `atlas_context` é chamado, então o JSON devolvido traz `delivery` igual ao da CLI.
- **UT-06** — Dados os arquivos da gluon-spec, então:
  - o `sdd-config.template.yml` traz `delivery_check` (`enabled`, `environments`) comentado;
  - a SKILL.md (passo 7) e o `gates.md` (G6) descrevem os três passos do roteiro, "último visto pelo atlas", só leitura, produção com confirmação e o caminho sem atlas;
  - o `brownfield.md` diz que as regras do `org_context` valem também no G6;
  - o `whats-new` lista `delivery_check` como chave nova.

### 7.3 Testes de Integração
- **IT-01** — Com as fixtures `image-link` (SPEC-0082), quando `scan`, `build` e `context --json "api"` rodam num atlas temporário, então o `delivery` de `service:api` traz o código, a configuração, as duas pipelines, a imagem e os dois deployments. Nenhuma saída contém tag nem host de registry.

### 7.4 Testes de Contrato
- **CT-01** — Dado o pacote de hoje (chaves e tipos documentados em `references/context.md`), quando o `context --json` novo roda nas fixtures `acme`, então todas as chaves de antes existem com os mesmos tipos, e `delivery`, quando existe, é um objeto com as cinco chaves do contrato.

### 7.5 Testes E2E
- N/A — sem jornada interativa: o IT-01 roda a CLI de ponta a ponta, e o UT-05 roda o servidor MCP por stdio.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- Fixtures `image-link` e `acme` existentes, só com nomes genéricos.
- `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários.
- Sem rede.

**Ambiente de execução:** local e CI (`python3 -m unittest discover` em `skills/boson-atlas/tests`, `skills/gluon-spec/tests` e `mcp/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin.
- **Dados/schema:** nenhum dado novo. `delivery` sai do `graph.json` existente, e `delivery_check` é opcional (sem a chave, vale `enabled: true` e todos os ambientes).
- **Compatibilidade:**
  - quem lê o pacote de hoje continua funcionando, porque a chave é aditiva;
  - um `sdd-config.yml` sem `delivery_check` não muda nada;
  - a versão anterior da skill ignora a chave.
- **Observabilidade:** o roteiro e o resultado de cada passo ficam na evidência do G6 e no Relatório de Entrega.
- **Rollback:** reverter o merge. Nenhum dado a desfazer.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Onde fica a configuração da verificação? — No `sdd-config.yml` do projeto (`delivery_check`), porque cada projeto escolhe os ambientes. O atlas continua só descrevendo a organização (recomendação do arquiteto; revisável no H1).
- [x] O `delivery` entra sempre no `context` ou atrás de uma opção? — Sempre que o serviço tem caminho de entrega: é aditivo e pequeno, e o `--max-chars` já controla o tamanho (recomendação do arquiteto; revisável no H1).
- [x] O estado do deployment no atlas vale como verificação? — Não. É "último visto pelo atlas", e o agente confirma ao vivo, só lendo, com as ferramentas do projeto (recomendação do arquiteto; revisável no H1).
- [x] Relação com a SPEC-0075? — Esta spec é o primeiro passo, com o que o grafo já tem. Acesso, logs, contas de teste e marcação de produção continuam na SPEC-0075 (recomendação do arquiteto; revisável no H1).

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
- [x] Red: CH-01 (passa antes), UT-01 a UT-06, IT-01 e CT-01 com a tag `SPEC-0086:<ID>`, falhando pelo motivo certo; fixtures `image-link` e `acme` reaproveitadas
- [x] Green: `delivery` no `_service_entry` e o bloco "Entrega" no `_service_lines` (`scripts/atlas.py`), `references/context.md`, `ATLAS_VERSION`; gluon-spec: SKILL.md (passo 7), `references/gates.md` (G6), `references/brownfield.md`, `delivery_check` no `sdd-config.template.yml`, `SDD_TOOL_VERSION`; CHANGELOGs das duas skills; `version` do `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 24b0cf1 | 2026-11-20 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=7, skipped=1)) — 7242318 | 2026-11-20 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 11ebfb4 | 2026-11-20 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 4bbc2f5 | 2026-11-20 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer (subagente independente), rodada 2: APPROVED, só um nit — 6a37a5d | 2026-11-20 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 4430687 | 2026-11-20 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-20 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-20 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — cfb1708 | 2026-11-20 |

### Histórico de reprovações
- G4 FAIL 2026-11-20 — major: delivery.images ignora image_repositories no context (lê graph.json sem o mapa) e diverge da região da página; minors: pipeline que só faz build do serviço sem teste; valores do bloco Entrega fora de crase — 0127e18
- G4 PASS 2026-11-20 — depois de 1 reprovação(ões)

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
- O `context` da boson-atlas (CLI e tool MCP `atlas_context`) entrega, em cada serviço com caminho de entrega, a chave `delivery`: repositórios de código e de configuração, pipelines com o repositório, imagens e deployments com ambientes, clusters, sync, health e imagens. Em Markdown, o mesmo dado vem no bloco "Entrega".
- A gluon-spec, no G6, monta depois do merge um roteiro de verificação com três passos, a partir do `delivery`:
  1. as pipelines do repositório do código;
  2. o repositório de configuração onde a imagem nova deve aparecer;
  3. o deployment, o cluster e o estado esperado em cada ambiente.

  O roteiro é só de leitura, marca o estado do atlas como "último visto pelo atlas" e exige confirmação para produção. Sem atlas, segue com `smoke_test`/`test_e2e`/`deploy_*` sem bloquear.
- `delivery_check` no `sdd-config.yml` liga ou desliga a consulta e escolhe os ambientes.

### Como foi feito
- `scripts/atlas.py`: `_delivery` e `_delivery_lines`. `_code_images`, `_service_pipelines` e `_deployment_images` saíram da SPEC-0082 para servir a página e o `context` com a mesma regra. O `context` resolve as imagens com o mapa `image_repositories` do arquivo compartilhado.
- gluon-spec: o passo 7 da SKILL.md diz quando o roteiro roda e aponta para o `gates.md` (G6), que traz os passos e as regras. O `brownfield.md` estende as regras do `org_context` ao G6, e o template ganhou a chave `delivery_check`.
- Emenda v2: esclarecimentos do G1. Emenda v3: achados da rodada 1 do G4. O principal foi o `delivery.images` divergir da página quando havia mapa de imagens; também entraram a crase nos valores e a SKILL.md mais enxuta.
- Versões: ATLAS_VERSION 2026.11.13, SDD_TOOL_VERSION 2026.11.9, plugin 2026.11.26.

### Prova de Correção
N/A — type feature.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Sem caminho de entrega, pacote igual ao de hoje; chaves de antes iguais | PASS | `test_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| UT-01 | `delivery` completo, separado e ordenado | PASS | `test_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| UT-02 | Sem repositório de código; status ausente; repositório da pipeline | PASS | `test_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| UT-03 | Bloco "Entrega" na ordem, em crase, numa linha só, sem texto de ferramenta | PASS | `test_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| UT-04 | Corte por `--max-chars` com o bloco dentro do serviço | PASS | `test_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| UT-05 | `atlas_context` devolve o mesmo `delivery` da CLI | PASS | `mcp/tests/test_atlas_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| UT-06 | `delivery_check`, roteiro do G6, só leitura, produção com confirmação, sem atlas não bloqueia | PASS | `skills/gluon-spec/tests/test_delivery_check.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| IT-01 | `scan` + `build` + `context` com e sem mapa de imagens, igual à página | PASS | `test_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |
| CT-01 | Chaves e tipos de antes mantidos; `delivery` com as cinco chaves | PASS | `test_context_delivery.py` — CI do PR #60 (run 44835594269, Python 3.9 e 3.15) e suíte local no G2 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4) — rodada 2
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado — sem desvio; ADR-0022
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — segurança (UT-03, IT-01), resiliência (CH-01, UT-06); desempenho: sem índice novo, reaproveita os do `context`
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — roteiro na evidência do G6; rollback = reverter o merge
- [x] Documentação raiz e CHANGELOG atualizados (G7) — `references/context.md`, `gates.md`, `brownfield.md`, template, CHANGELOGs das duas skills
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: o projeto não declara `living_docs`
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
N/A — ATLAS_VERSION 2026.11.13, SDD_TOOL_VERSION 2026.11.9, plugin 2026.11.26, PR #60.

### Pendências
A verificação ativa depois do deploy (acompanhar rollout e logs no ambiente) fica na SPEC-0075, já no radar. Nit sem spec: o rótulo do ambiente na linha do bloco "Entrega" fica fora da crase, como a linha "Deployments" de hoje.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0086`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 3 | 2026-11-20 | `context` usa o mapa `image_repositories` (imagens iguais às da página); pipeline só do serviço com `repository: ""`; valores do bloco "Entrega" em crase; SKILL.md enxuta | G4 rodada 1 (major): `delivery.images` divergia da região com o mapa; minors e nits | nenhuma | thomas, 2026-11-20 (piloto automático com o recomendado) |
| 2 | 2026-11-20 | Esclarece: `images` do deployment é o atributo dele (ou `[]`); partes da linha do ambiente só com valor; bloco depois de "Deployments"; `delivery_check` como chave real do template | G1 (test-writer): leituras literais a confirmar | nenhuma | thomas, 2026-11-20 (piloto automático com o recomendado) |
