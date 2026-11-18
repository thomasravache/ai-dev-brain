---
id: SPEC-0076
title: "boson-atlas: coletor argocd reconhece nome do serviço, sufixos .NET, filas e tópicos"
tier: lite
type: fix
user_facing: false
status: approved
created: 2026-11-17
parent:
depends_on: []
consumes_contract: []
touches: [skills/boson-atlas/assets/collectors/argocd.py, skills/boson-atlas/tests/test_collector_argocd.py, skills/boson-atlas/tests/fixtures/argocd/**, skills/boson-atlas/references/collectors/argocd.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/scripts/atlas.py, .claude-plugin/plugin.json]
adrs: [ADR-0011]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-18
---

# SPEC-0076 — boson-atlas: coletor argocd reconhece nome do serviço, sufixos .NET, filas e tópicos

> Origem: radar de 2026-11-17 (uso real do coletor argocd via kubectl, com GitOps num repositório de IaC); detalhada em 2026-11-18.

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Três achados de um uso real do coletor `argocd` (SPEC-0035) fazem o atlas perder relações:

1. **Nome do serviço.** Sem o rótulo `app.kubernetes.io/part-of`, cada Application vira um serviço (`dev-account`, `qa-account`…). A regra 3 do `build` (host igual ao nome de um serviço → `depends_on`) nunca casa com `http://account`, porque não existe `service:account`. Os charts Helm já declaram o nome no `nameOverride` dos values, mas o coletor não lê esse valor.
2. **Sufixos de `config_refs`.** Em .NET as chaves terminam em `Endpoint`, `Url`, `Uri` ou `Host`, sem `_` (ex.: `Acme.Account__RouterEndpoint`, `ServiceUrl`). O padrão (`_HOST,_URL,_DSN,_ADDR,_QUEUE,_TOPIC,_BUCKET`) descarta essas chaves: no uso real saíram 73 referências com o padrão e 301 com os sufixos ajustados. O `--ref-suffixes` já existe e é configurável no `command` do `atlas-config.yml`, mas o padrão e a documentação não cobrem esse estilo de nome.
3. **Filas e tópicos da AWS.** Na URL de fila do SQS (`https://sqs.us-east-1.amazonaws.com/123456789012/orders`), o nome da fila fica no caminho. O coletor guarda só o host `sqs.us-east-1.amazonaws.com`, que é igual para todas as filas da região. O ARN do SNS (`arn:aws:sns:us-east-1:123456789012:orders-events`) não dá referência nenhuma. A regra 2 do `build` perde as filas e os tópicos.

Impacto: grafo com serviços duplicados por ambiente e sem as dependências de serviço, fila e tópico.

## 2. Causa Raiz
- `service_and_environment` em `assets/collectors/argocd.py` usa só o rótulo `--service-label` e, sem ele, o `metadata.name` da Application. Não consulta os values do Helm.
- `DEFAULT_REF_SUFFIXES` exige o `_` (`_HOST`, `_URL`). Como `_matches` compara pelo fim da chave, `RouterEndpoint` e `ServiceUrl` não casam.
- `host_of` segue uma regra genérica: tira o esquema, fica com a autoridade e descarta o caminho. Isso é certo para bancos e caches, mas a URL de fila do SQS guarda o recurso no caminho. O ARN (`arn:...:...`) falha no `_strip_port` porque o que vem depois de `:` não é porta.

## 3. Mudança Proposta
- **Nome do serviço:** a ordem passa a ser:
  1. rótulo `--service-label`;
  2. `nameOverride` dos values do Helm, na primeira origem (`spec.source`, depois `spec.sources`) que o declare, só na raiz: em `helm.valuesObject`, numa linha sem indentação de `helm.values`, ou no parâmetro `nameOverride` de `helm.parameters`;
  3. nome da Application.

  O valor só vale se for um nome simples (mesma regra de `HOST_RE`). Template, vazio ou texto com espaço passa para o próximo item da ordem.
  Dentro de uma origem vale a precedência do Argo CD e do Helm: `helm.parameters`, depois `helm.valuesObject`, depois `helm.values`. Um `nameOverride` inválido é ignorado e a busca segue para o próximo lugar e para a próxima origem; o nome da Application só vale quando nenhuma origem tem um válido (Emenda v2).
- **Sufixos padrão:** `HOST,URL,URI,ENDPOINT,DSN,ADDR,_QUEUE,_TOPIC,_BUCKET`, um superconjunto do padrão atual (`HOST` cobre `_HOST`, `URL` cobre `_URL`). A comparação continua sem diferença de caixa e só pelo fim da chave. O `--ref-suffixes` continua substituindo a lista inteira, e a doc ganha um exemplo de `atlas-config.yml` com sufixos próprios (ex.: `redis`).
- **SQS e SNS:** antes da regra genérica, `host_of` reconhece:
  - URL de fila do SQS (`https://sqs.<região>.amazonaws.com/<conta>/<fila>` e o formato antigo `https://<região>.queue.amazonaws.com/<conta>/<fila>`) → o nome da fila;
  - ARN `arn:<partição>:sqs|sns:<região>:<conta>:<nome>` → o nome.

  Uma URL de fila do SQS sem o segmento da conta (`https://sqs.<região>.amazonaws.com/<fila>`) não dá referência: o host regional nunca sai sozinho (Emenda v2).
  O id da conta, a região e o resto da URL nunca saem. Um valor com `@` em qualquer lugar, ou um nome fora de `HOST_RE`, não dá referência (mesma regra de privacidade de hoje). A referência fica `ORDERS_QUEUE_URL=orders` (ou `orders.fifo`), e a regra 2 do `build` casa com uma `queue`/`topic` de mesmo nome emitida por outro coletor.
- **Endurecimento de valores (Emenda v3):** os sufixos mais amplos tornam mais chaves elegíveis, por isso:
  - `host_of` e o `nameOverride` recusam os literais YAML de nulo e booleano (`null`, `~`, `true`, `false`, em qualquer caixa). Um `nameOverride: null` cai no próximo item da ordem.
  - Um valor cuja autoridade contenha `=`, `;` ou `,`, com ou sem esquema, não dá referência. Isso cobre strings de conexão como `Server=db;Password=p@ss` e `sqlserver://db;password=p@ss`, de onde hoje sai o pedaço depois do último `@`, que pode ser parte da senha (Emenda v4: com esquema também).
  - Os booleanos do YAML 1.1 que o Helm aceita (`yes`, `no`, `on`, `off`, `y`, `n`, em qualquer caixa) são recusados junto com `null`, `~`, `true` e `false` (Emenda v4).
  - As URLs de fila do SQS nos formatos FIPS (`sqs-fips.<região>.amazonaws.com`) e de VPC endpoint (`*.sqs.<região>.vpce.amazonaws.com`) seguem a mesma regra da URL padrão: sai só o nome da fila, ou nada.
  - Nenhum host de VPC endpoint (`*.vpce.amazonaws.com`) sai inteiro: se for de SQS (com ou sem prefixo antes de `sqs.`), sai o nome da fila pela regra acima; de qualquer outro serviço, nada (Emenda v4).
- **Não muda:**
  - o contrato `boson-atlas/collector@1` (ADR-0011): mesmas entidades, atributos e formato `KEY=host`;
  - a regra de inferência do `build`, que continua dando `depends_on` e não adivinha `publishes`/`consumes` (doc da SPEC-0035);
  - os ambientes, o cluster e o `sourced_from`;
  - os demais formatos de valor, fora o endurecimento acima.

**Padrão seguido:** as funções puras de `assets/collectors/argocd.py` (`host_of`, `_ref`, `service_and_environment`) e seus testes em `tests/test_collector_argocd.py`, com fixtures em `tests/fixtures/argocd/` (SPEC-0035, SPEC-0047).

**Rollback:** reverter o commit. O `scan` seguinte volta aos serviços com o nome da Application, e o `diff` mostra a troca uma vez.

**Outras ocorrências:** nenhuma nos coletores atuais (`github` e `generic` não extraem `config_refs`). `publishes`/`consumes` a partir de filas e tópicos é inferência nova do `build` e fica para uma spec própria, se for priorizada.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes da SPEC-0035/0047 em `test_collector_argocd.py` cobrem o comportamento atual e continuam passando sem mudança, exceto pelos sufixos padrão, que crescem.
- **UT-01** — Dada uma Application sem o rótulo de serviço e com `nameOverride: account` em `helm.valuesObject`, quando o coletor mapeia, então o serviço é `service:account`; o mesmo vale para uma linha sem indentação `nameOverride: account` em `helm.values` e para o parâmetro `nameOverride` em `helm.parameters`.
- **UT-02** — Dada uma Application com o rótulo de serviço e com `nameOverride`, quando o coletor mapeia, então vale o rótulo; e dado `nameOverride` indentado (fora da raiz), vazio, com template do Helm (chaves duplas) ou `${NAME}` ou com espaço, então vale o nome da Application.
- **UT-03** — Dados os sufixos padrão e as chaves `Acme.Account__RouterEndpoint=http://account`, `ServiceUrl=https://pay.interno/x`, `CallbackUri=https://cb.interno` e `Db_Host=db.interno`, quando o coletor extrai `config_refs`, então as quatro saem (`...=account`, `...=pay.interno`, `...=cb.interno`, `...=db.interno`), e `LOG_LEVEL`, `DB_PASSWORD` e `API_TOKEN` continuam fora.
- **UT-04** — Dadas `ORDERS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/orders`, o formato antigo `https://us-east-1.queue.amazonaws.com/123456789012/billing.fifo`, `EVENTS_TOPIC=arn:aws:sns:us-east-1:123456789012:orders-events` e `DLQ_QUEUE=arn:aws:sqs:sa-east-1:123456789012:orders-dlq`, quando o coletor extrai `config_refs`, então saem `orders`, `billing.fifo`, `orders-events` e `orders-dlq`.
- **UT-05** — Dados valores de SQS e SNS com `@` em qualquer posição, com nome fora de `HOST_RE`, com caminho extra (`.../conta/fila/x`) ou com ARN de outro serviço (`arn:aws:s3:::bucket`, `arn:aws:iam::123456789012:role/x`), quando o coletor extrai, então não sai referência nenhuma, e o id da conta (`123456789012`) não aparece em lugar nenhum da saída do coletor.
- **UT-06** — Dados `nameOverride` igual a `null`, `~`, `true` ou `False` (em `helm.values`, `helm.parameters` e `helm.valuesObject`), valores `true`/`false`/`null` em chaves com sufixo (`ENABLE_CURL=true`, `VerifyHost=false`), as strings de conexão `ReplicaDsn=Server=db;Password=abc@xyz` e `Db_Host=Host=db;Password=p@ss`, e as URLs `https://sqs-fips.us-east-1.amazonaws.com/123456789012/orders` e `https://vpce-1.sqs.us-east-1.vpce.amazonaws.com/123456789012/orders`, quando o coletor mapeia, então o serviço cai no próximo item da ordem, as chaves booleanas e as strings de conexão não dão referência (nem `xyz`, nem `ss`), e as duas URLs do SQS dão `orders` sem região, id de VPC endpoint nem conta. Emenda v4: `sqlserver://db;user=sa;password=p@ss`, `tcp://h;Password=a@b` e `redis://cache,password=p@ss` não dão referência; `nameOverride: yes` e `VerifyHost=no` (e `on`, `off`, `y`, `n`) são recusados; `https://sqs.us-east-1.vpce.amazonaws.com/123456789012/orders` dá `orders`, e `https://vpce-1.sns.us-east-1.vpce.amazonaws.com/x` não dá referência.
- **IT-01** — Dado um `--input` gravado (fixture) com duas Applications sem rótulo (`dev-account` com `nameOverride: account`, e `dev-router` com `Acme.Router__AccountEndpoint=http://account` e `ORDERS_QUEUE_URL` do SQS), mais um coletor `generic` que emite `queue:orders`, quando `scan` e `build` rodam num atlas temporário, então o grafo tem `service:account` (e não `service:dev-account`), a aresta inferida `service:dev-router` → `depends_on` → `service:account` e o `depends_on` para `queue:orders`, sem o id da conta nos snapshots.

## 5. Questões em Aberto
- [x] Uma spec ou três? — Uma: os três achados estão no mesmo arquivo (`argocd.py`), com a mesma doc e os mesmos testes, tamanho S, sem dependência entre eles (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-17: "beleza, segue no piloto automático até o merge"; revisável no H1)
- [x] Algum item muda o contrato do coletor (ADR-0011)? — Não: mesmas entidades, atributos e formato `KEY=host`; muda só quais chaves e valores viram referência e de onde vem o nome do serviço (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] Os sufixos devem ser configuráveis no `atlas-config.yml`? — Já são, pelo `--ref-suffixes` no `command` do coletor; a correção é ampliar o padrão (superconjunto, sem `_`) e documentar o exemplo, sem chave nova de configuração (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] O `nameOverride` deve vir por padrão ou atrás de uma opção nova? — Por padrão, depois do rótulo: é o nome que o próprio chart dá ao serviço, e atlas sem o rótulo hoje já têm um serviço por Application; o CHANGELOG avisa que o primeiro `scan` depois do upgrade mostra a troca dos ids de serviço uma vez, como na SPEC-0047 (recomendação do arquiteto, piloto automático; revisável no H1)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 a UT-05 e IT-01 com a tag `SPEC-0076:<ID>`, falhando pelo motivo certo; fixture do IT-01 em `tests/fixtures/argocd/`
- [x] Green: `nameOverride` na ordem do nome do serviço, sufixos padrão novos e SQS/SNS em `host_of`, em `assets/collectors/argocd.py`; `references/collectors/argocd.md` (ordem do nome, sufixos com exemplo de `atlas-config.yml`, tabela de valores com SQS/SNS); CHANGELOG da boson-atlas com o aviso da troca de ids de serviço; `ATLAS_VERSION` (só a constante, em `scripts/atlas.py`) e `version` do `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 80676c7 | 2026-11-18 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=44, skipped=1)) — 8c75a49 | 2026-11-18 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 13daf77 | 2026-11-18 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — f0d5123 | 2026-11-18 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer (subagente), rodada 3: APPROVED — 0 blocker, 0 major, 0 minor — 1fc66ea | 2026-11-18 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 7816492 | 2026-11-18 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-18 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-18 |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-18 — rodada 2: CHANGES_REQUESTED — 1 major (string de conexão com esquema deixa sair parte da senha), 2 minors (booleanos YAML 1.1, formas de VPC endpoint) — c2497c1
- G4 PASS 2026-11-18 — depois de 1 reprovação(ões)

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
- **Nome do serviço:** o coletor `argocd` usa o rótulo `--service-label`, depois o `nameOverride` dos values do Helm (`helm.parameters` > `helm.valuesObject` > `helm.values`, só na raiz, origem por origem) e só então o nome da Application. Applications sem o rótulo (`dev-account`, `qa-account`) passam a apontar para `service:account`, e a regra 3 do `build` casa com `http://account`.
- **Sufixos padrão:** `HOST,URL,URI,ENDPOINT,DSN,ADDR,_QUEUE,_TOPIC,_BUCKET`, que inclui tudo do padrão anterior e cobre chaves .NET (`Acme.Account__RouterEndpoint`, `ServiceUrl`, `CallbackUri`). A doc mostra como trocar a lista no `atlas-config.yml` com `--ref-suffixes`.
- **SQS e SNS:** a URL de fila do SQS (padrão, formato antigo, FIPS e VPC endpoint) e os ARNs de `sqs`/`sns` dão só o nome da fila ou do tópico. Conta, região e id de VPC endpoint nunca saem.
- **Endurecimento (Emendas v3 e v4):**
  - nulo e booleanos do YAML (inclusive `yes`/`no`/`on`/`off`) são recusados no `nameOverride` e nos valores;
  - uma autoridade com `=`, `;` ou `,` não dá referência, com ou sem esquema, o que fecha o vazamento de parte de senha em strings de conexão que já existia antes desta spec;
  - nenhum host de VPC endpoint sai inteiro.
- `references/collectors/argocd.md`, o CHANGELOG `[2026.11.9]` (com o aviso de troca dos ids de serviço no primeiro `scan`), `ATLAS_VERSION` 2026.11.9 e o plugin em 2026.11.21.

### Como foi feito
- **Testes:**
  - 734a16d: UT-01 a UT-05 e IT-01, com as fixtures `name-override*.json`;
  - 8c75a49: Emenda v2;
  - 25e3be3: Emenda v3 (UT-06);
  - 5853118: Emenda v4.
- **Implementação:**
  - 0108986: `name_override`, os sufixos e o SQS/SNS em `host_of`;
  - ac9e088: Emenda v3;
  - 13daf77: Emenda v4.

  Tudo em `assets/collectors/argocd.py`, com funções puras e sem dependências.
- O Architect incluiu a constante `ATLAS_VERSION` (`scripts/atlas.py`) no `touches` durante o PLAN.
- **Emendas:**
  - v2: precedência do `nameOverride` e SQS sem conta (dúvidas do test-writer);
  - v3: endurecimento e troca do prefixo dos exemplos por `Acme.`;
  - v4: string de conexão com esquema, YAML 1.1 e VPC endpoint.
- **Revisão G4:**
  - rodada 1: APPROVED com 5 minors, que viraram a Emenda v3;
  - rodada 2: CHANGES_REQUESTED (major: `sqlserver://db;password=p@ss` ainda dava `ss`);
  - rodada 3: APPROVED sem achados.

### Prova de Correção
- **Antes (734a16d/8c75a49):** 44 falhas, todas por asserção, por exemplo `'dev-account' != 'account'`, `sqs.us-east-1.amazonaws.com` no lugar de `orders` e `None` para os ARNs. No IT-01, `service:account` não existia no grafo. Antes de 25e3be3 e 5853118: `service:null`, `ReplicaDsn=xyz` e `ReplicaDsn=ss`.
- **Depois (13daf77):** suíte completa verde, com boson-atlas em 436 testes (1 skip antigo) no Python 3.14 e no 3.9 local, e na CI.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | `nameOverride` em valuesObject, values e parameters vira o serviço; precedência e origem seguinte (Emenda v2) | PASS | `test_collector_argocd.py::NameOverrideTest` — CI do PR #54 (run 44340775616, Python 3.9 e 3.15) e suíte local no G2 |
| UT-02 | Rótulo vence; `nameOverride` inválido cai no nome da Application | PASS | `test_collector_argocd.py::NameOverrideTest` — CI do PR #54 (run 44340775616) e suíte local no G2 |
| UT-03 | Sufixos padrão novos pegam as chaves .NET e deixam `LOG_LEVEL`, `DB_PASSWORD` e `API_TOKEN` fora | PASS | `test_collector_argocd.py::DotnetSuffixesTest` — CI do PR #54 (run 44340775616) e suíte local no G2 |
| UT-04 | URL do SQS e ARNs de SQS/SNS dão o nome da fila ou do tópico | PASS | `test_collector_argocd.py::AwsQueueTopicTest` — CI do PR #54 (run 44340775616) e suíte local no G2 |
| UT-05 | Valores inseguros ou de outro serviço não dão referência; o id da conta nunca sai | PASS | `test_collector_argocd.py::AwsQueueTopicTest`, `AwsAccountNeverLeavesTest` — CI do PR #54 (run 44340775616) e suíte local no G2 |
| UT-06 | Nulo e booleanos, strings de conexão com e sem esquema, SQS FIPS/VPC endpoint (Emendas v3 e v4) | PASS | `test_collector_argocd.py::HardenedValuesTest`, `HardenedValuesV4Test` — CI do PR #54 (run 44340775616) e suíte local no G2 |
| IT-01 | `scan` + `build` com `service:account`, `depends_on` para `service:account` e `queue:orders`, sem o id da conta nos snapshots | PASS | `test_collector_argocd.py::NameOverrideScanTest` — CI do PR #54 (run 44340775616) e suíte local no G2 |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção — 734a16d, 8c75a49, 25e3be3 e 5853118 em vermelho; 0108986, ac9e088 e 13daf77 em verde
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4) — rodada 3
- [x] Padrão existente mantido — funções puras de `argocd.py` e testes no estilo da SPEC-0035/0047
- [x] Disponível no ambiente-alvo via pipeline (G6) — N/A: skills distribuídas por cópia e pelo plugin
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7) — `collectors/argocd.md` e CHANGELOG `[2026.11.9]`
- [x] Outras ocorrências registradas como novas specs (ou nenhuma) — nenhuma nos coletores atuais; `publishes`/`consumes` fica como possível spec futura

### Deploy
N/A — `ATLAS_VERSION` 2026.11.9, plugin 2026.11.21, PR #54.

### Pendências
Nenhuma nova. Inferir `publishes`/`consumes` a partir de filas e tópicos fica como possível spec futura, se for priorizado (seção 3).

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 4 | 2026-11-18 | A recusa por `=`, `;` ou `,` na autoridade vale também com esquema; booleanos YAML 1.1 recusados; nenhum host de VPC endpoint sai inteiro; UT-06 ampliado | G4 rodada 2 (major): `sqlserver://db;password=p@ss` ainda dava `ss`; minors: `nameOverride: yes` virava serviço e outras formas de VPC endpoint deixavam sair região e id | nenhuma | thomas, 2026-11-18 (piloto automático com o recomendado) |
| 3 | 2026-11-18 | Endurece os valores: nulo e booleano recusados no `nameOverride` e em `host_of`; string de conexão sem esquema com `=` ou `;` não dá referência; SQS FIPS e VPC endpoint como a URL padrão; exemplos trocam o prefixo das chaves por `Acme.`; UT-06 novo | G4 (minors 1 a 5): `nameOverride: null` juntava as Applications em `service:null`; a string de conexão vazava parte da senha, e os sufixos novos ampliam esse vazamento; o host regional do SQS saía nos formatos FIPS/VPC; o prefixo dos exemplos vinha de um uso real | nenhuma | thomas, 2026-11-18 (piloto automático com o recomendado) |
| 2 | 2026-11-18 | Esclarece a ordem do `nameOverride` (parâmetros > valuesObject > values em cada origem; inválido segue para o próximo lugar e a próxima origem) e que URL do SQS sem a conta não dá referência; testes do UT-01 e do UT-05 cobrem os dois casos | G1 (test-writer): três ambiguidades da Mudança Proposta | nenhuma | thomas, 2026-11-18 (piloto automático com o recomendado) |
