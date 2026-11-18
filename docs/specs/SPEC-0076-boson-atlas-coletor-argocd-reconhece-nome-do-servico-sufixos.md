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
2. **Sufixos de `config_refs`.** Em .NET as chaves terminam em `Endpoint`, `Url`, `Uri` ou `Host`, sem `_` (ex.: `BM.Account__RouterEndpoint`, `ServiceUrl`). O padrão (`_HOST,_URL,_DSN,_ADDR,_QUEUE,_TOPIC,_BUCKET`) descarta essas chaves: no uso real saíram 73 referências com o padrão e 301 com os sufixos ajustados. O `--ref-suffixes` já existe e é configurável no `command` do `atlas-config.yml`, mas o padrão e a documentação não cobrem esse estilo de nome.
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
- **Não muda:**
  - o contrato `boson-atlas/collector@1` (ADR-0011): mesmas entidades, atributos e formato `KEY=host`;
  - a regra de inferência do `build`, que continua dando `depends_on` e não adivinha `publishes`/`consumes` (doc da SPEC-0035);
  - os ambientes, o cluster e o `sourced_from`;
  - os demais formatos de valor.

**Padrão seguido:** as funções puras de `assets/collectors/argocd.py` (`host_of`, `_ref`, `service_and_environment`) e seus testes em `tests/test_collector_argocd.py`, com fixtures em `tests/fixtures/argocd/` (SPEC-0035, SPEC-0047).

**Rollback:** reverter o commit. O `scan` seguinte volta aos serviços com o nome da Application, e o `diff` mostra a troca uma vez.

**Outras ocorrências:** nenhuma nos coletores atuais (`github` e `generic` não extraem `config_refs`). `publishes`/`consumes` a partir de filas e tópicos é inferência nova do `build` e fica para uma spec própria, se for priorizada.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes da SPEC-0035/0047 em `test_collector_argocd.py` cobrem o comportamento atual e continuam passando sem mudança, exceto pelos sufixos padrão, que crescem.
- **UT-01** — Dada uma Application sem o rótulo de serviço e com `nameOverride: account` em `helm.valuesObject`, quando o coletor mapeia, então o serviço é `service:account`; o mesmo vale para uma linha sem indentação `nameOverride: account` em `helm.values` e para o parâmetro `nameOverride` em `helm.parameters`.
- **UT-02** — Dada uma Application com o rótulo de serviço e com `nameOverride`, quando o coletor mapeia, então vale o rótulo; e dado `nameOverride` indentado (fora da raiz), vazio, com template do Helm (chaves duplas) ou `${NAME}` ou com espaço, então vale o nome da Application.
- **UT-03** — Dados os sufixos padrão e as chaves `BM.Account__RouterEndpoint=http://account`, `ServiceUrl=https://pay.interno/x`, `CallbackUri=https://cb.interno` e `Db_Host=db.interno`, quando o coletor extrai `config_refs`, então as quatro saem (`...=account`, `...=pay.interno`, `...=cb.interno`, `...=db.interno`), e `LOG_LEVEL`, `DB_PASSWORD` e `API_TOKEN` continuam fora.
- **UT-04** — Dadas `ORDERS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/orders`, o formato antigo `https://us-east-1.queue.amazonaws.com/123456789012/billing.fifo`, `EVENTS_TOPIC=arn:aws:sns:us-east-1:123456789012:orders-events` e `DLQ_QUEUE=arn:aws:sqs:sa-east-1:123456789012:orders-dlq`, quando o coletor extrai `config_refs`, então saem `orders`, `billing.fifo`, `orders-events` e `orders-dlq`.
- **UT-05** — Dados valores de SQS e SNS com `@` em qualquer posição, com nome fora de `HOST_RE`, com caminho extra (`.../conta/fila/x`) ou com ARN de outro serviço (`arn:aws:s3:::bucket`, `arn:aws:iam::123456789012:role/x`), quando o coletor extrai, então não sai referência nenhuma, e o id da conta (`123456789012`) não aparece em lugar nenhum da saída do coletor.
- **IT-01** — Dado um `--input` gravado (fixture) com duas Applications sem rótulo (`dev-account` com `nameOverride: account`, e `dev-router` com `BM.Router__AccountEndpoint=http://account` e `ORDERS_QUEUE_URL` do SQS), mais um coletor `generic` que emite `queue:orders`, quando `scan` e `build` rodam num atlas temporário, então o grafo tem `service:account` (e não `service:dev-account`), a aresta inferida `service:dev-router` → `depends_on` → `service:account` e o `depends_on` para `queue:orders`, sem o id da conta nos snapshots.

## 5. Questões em Aberto
- [x] Uma spec ou três? — Uma: os três achados estão no mesmo arquivo (`argocd.py`), com a mesma doc e os mesmos testes, tamanho S, sem dependência entre eles (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-17: "beleza, segue no piloto automático até o merge"; revisável no H1)
- [x] Algum item muda o contrato do coletor (ADR-0011)? — Não: mesmas entidades, atributos e formato `KEY=host`; muda só quais chaves e valores viram referência e de onde vem o nome do serviço (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] Os sufixos devem ser configuráveis no `atlas-config.yml`? — Já são, pelo `--ref-suffixes` no `command` do coletor; a correção é ampliar o padrão (superconjunto, sem `_`) e documentar o exemplo, sem chave nova de configuração (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] O `nameOverride` deve vir por padrão ou atrás de uma opção nova? — Por padrão, depois do rótulo: é o nome que o próprio chart dá ao serviço, e atlas sem o rótulo hoje já têm um serviço por Application; o CHANGELOG avisa que o primeiro `scan` depois do upgrade mostra a troca dos ids de serviço uma vez, como na SPEC-0047 (recomendação do arquiteto, piloto automático; revisável no H1)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01 a UT-05 e IT-01 com a tag `SPEC-0076:<ID>`, falhando pelo motivo certo; fixture do IT-01 em `tests/fixtures/argocd/`
- [ ] Green: `nameOverride` na ordem do nome do serviço, sufixos padrão novos e SQS/SNS em `host_of`, em `assets/collectors/argocd.py`; `references/collectors/argocd.md` (ordem do nome, sufixos com exemplo de `atlas-config.yml`, tabela de valores com SQS/SNS); CHANGELOG da boson-atlas com o aviso da troca de ids de serviço; `ATLAS_VERSION` (só a constante, em `scripts/atlas.py`) e `version` do `plugin.json`
- [ ] Validar: suíte completa + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 80676c7 | 2026-11-18 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=44, skipped=1)) — 8c75a49 | 2026-11-18 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 0108986 | 2026-11-18 |
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
| 2 | 2026-11-18 | Esclarece a ordem do `nameOverride` (parâmetros > valuesObject > values em cada origem; inválido segue para o próximo lugar e a próxima origem) e que URL do SQS sem a conta não dá referência; testes do UT-01 e do UT-05 cobrem os dois casos | G1 (test-writer): três ambiguidades da Mudança Proposta | nenhuma | thomas, 2026-11-18 (piloto automático com o recomendado) |
