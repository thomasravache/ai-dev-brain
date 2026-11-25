---
id: SPEC-0102
title: "boson-atlas: verify@2 — dependências e sinais na foto e na comparação"
tier: full
type: feature
user_facing: false
status: approved
created: 2026-11-24
parent: SPEC-0095
depends_on: [SPEC-0096]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/references/verify.md, skills/boson-atlas/references/probes.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, skills/boson-atlas/tests/test_verify.py, skills/boson-atlas/tests/test_verify_dependencies.py, skills/boson-atlas/tests/fixtures/fake-probes/scripted_resources.py, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0023, ADR-0024, ADR-0025, ADR-0026]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0102 — boson-atlas: verify@2 — dependências e sinais na foto e na comparação

> Origem: épico SPEC-0095. O `verify` (SPEC-0090) prova a entrega, o runtime e os logs do workload; esta spec acrescenta as dependências que o grafo liga ao serviço no ambiente e os sinais delas, pelas probes de recurso (SPEC-0096) e pelos adaptadores SPEC-0098 a SPEC-0101, seguindo o ADR-0026.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O `atlas.py verify` passa ao contrato `verify@2`:
- **`snapshot`** grava, além do que o `verify@1` já gravava, o bloco `dependencies`: o estado de cada recurso (`queue`, `topic`, `datastore`) ligado ao deployment do serviço no ambiente, só com contagens, conjuntos de nomes e agregados;
- **`compare`** ganha duas verificações por recurso, `dependencies` e `signals`, cada uma com o `resource` (`kind:id`), comparadas contra a foto e contra limites configuráveis.

O veredito, os exits, a regra de produção e o "nada no atlas" continuam os do `verify@1`. Uma foto `verify@1` continua aceita: as verificações novas ficam "não verificado" com o motivo "foto sem dependências".

## 2. Motivação & Escopo
**Motivação:** a entrega pode estar com a imagem certa e sem erro nos logs e, mesmo assim, quebrada nas dependências: a DLQ enchendo, a migration que não rodou, a assinatura do tópico que perdeu o filtro, o workload sem permissão na fila, a latência do banco subindo. Hoje isso fica fora do veredito do G6 (ADR-0026).

**Objetivos (dentro do escopo):**
- Foto `verify@2` com `dependencies`: um mapa `kind:id → estado`, por recurso, só com contagens, conjuntos e agregados (nunca dado de linha, corpo de mensagem nem amostra).
- Escopo pelo grafo: os recursos ligados ao deployment pelas regras do ADR-0025 (SPEC-0096), `--resource <kind:id>` repetível para restringir e `--max-resources` (padrão 20).
- `compare` com as verificações `dependencies` e `signals`, cada uma com `resource`, e as opções `--max-new-dlq`, `--max-queue-age`, `--expect-migration` (repetível) e `--max-signal-increase`.
- Regras de `ok`, `failed` e `not_verified` por tipo de recurso e por aspecto, com "não verificado" e motivo sempre que falta adaptador, acesso, foto ou item válido.
- Leitura dos itens de cada capacidade (`messaging`, `database`, `signals`, `permissions`) pelo contrato da regra 4a do ADR-0026, a fonte única que os adaptadores SPEC-0098 a SPEC-0101 cumprem.
- `validate_verify_snapshot` e `validate_verify_result` aceitando `verify@1` e `verify@2`.
- Ponto de extensão explícito para a verificação `functional` (SPEC-0103).

**Não-objetivos (fora do escopo):**
- A validação funcional e a verificação `functional`: SPEC-0103.
- Os adaptadores em si (SPEC-0098 a SPEC-0101) e o alvo de recurso no `probe` (SPEC-0096): esta spec só os consome.
- O G6 da gluon-spec e os limites por projeto no `sdd-config.yml`: SPEC-0105.
- Ações no ambiente (redrive da DLQ, rodar migration, mexer em política): seguem fora, como no `verify@1`.
- Consultas em paralelo entre recursos: as probes rodam uma depois da outra nesta versão.

## 3. Dependências
- **Implementações necessárias:** SPEC-0096 — o `probe --resource` (alvo de recurso, ligação pelo grafo, acesso local, `probe@2`, máscara e `resource` no `probes.log`) e a função única `linked_resources`, que lista os recursos ligados ao deployment no ambiente, com a relação de cada um. O escopo do `verify` vem só dela, e o `verify` chega aos adaptadores só pelo `run_probe`.
- **Contratos consumidos:** N/A — o contrato dos itens é a regra 4a do ADR-0026 (fonte única); os adaptadores SPEC-0098 (`messaging`), SPEC-0099 (`database`), SPEC-0100 (`signals`) e SPEC-0101 (`permissions`) o cumprem, cada um com o seu teste de contrato. Os testes desta spec usam um adaptador `probe@2` falso que fala esse contrato, sem depender da implementação deles.
- **Pré-requisitos externos:** N/A (sem nuvem, banco nem rede nos testes).

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Padrões de referência:
- `verify` da SPEC-0090 em `scripts/atlas.py` (`_verify_setup`, `_verify_targets`, `_verify_observe`, `cmd_verify_snapshot`, `cmd_verify_compare`, `verdict_of`, `verify_suggestion`, validadores e `write_exclusive`);
- `run_probe` (SPEC-0088), estendido pela SPEC-0096 com `--resource`, e `linked_resources` (SPEC-0096) para o escopo;
- testes de `tests/test_verify.py` e o adaptador falso com roteiro `tests/fixtures/fake-probes/scripted.py`.

**Decisão:**
- O `verify` continua um subcomando do `atlas.py`. A observação ganha um passo por recurso (`_verify_observe_resource`), que roda, pelo `run_probe`, as probes dos aspectos do kind (tabela da seção 6.1) e guarda só os campos da regra 4a do ADR-0026 (seção 6.2).
- As verificações novas são funções puras sobre (foto, estado atual, limites): `_dependencies_check` e `_signals_check`, como `_delivery_check` e `_runtime_check`.
- **Ponto de extensão:** a lista de verificações vira um registro único, `VERIFY_CHECKS = ("delivery", "runtime", "logs", "dependencies", "signals")`, com uma entrada por verificação (nível `deployment` ou `resource`, função de observação e função de comparação). A SPEC-0103 acrescenta `functional` (nível `deployment`, `resource: null`) a esse registro e aos validadores, sem mudar o nome do contrato nem as regras das outras verificações.

**Justificativa:** mantém um veredito único e uma foto por tarefa (ADR-0026), reaproveita todas as proteções das probes e deixa cada regra testável sem processo.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- Um comando por tipo de dependência (ADR-0026).
- O `verify` pedir ao adaptador de permissões as ações a simular: mudaria a entrada do `probe@2` (SPEC-0096). O adaptador devolve as ações abstratas do kind, e o `verify` escolhe as que a relação exige.
- Comparar o valor absoluto da fila e dos sinais: os recursos são compartilhados (ADR-0026).

**ADRs:** ADR-0010, ADR-0023, ADR-0024, ADR-0025 e ADR-0026 (aplicados; nenhum criado).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** por recurso, no máximo 4 probes (o kind define quais), em sequência, cada uma com o timeout e os limites do núcleo; até `--max-resources` recursos (padrão 20, máximo 50). Sem foto `verify@2`, nenhuma probe de recurso roda no `compare`.
- **Segurança:**
  - tudo só de leitura, pelas probes (verbos `queue`, `subscriptions`, `migrations`, `tables`, `metrics`, `simulate`, além dos do `verify@1`);
  - o alvo de recurso passa pelas regras da SPEC-0096 antes de qualquer probe; `--resource` fora do grafo dá exit 2;
  - o profile, o usuário, o nome do banco e o caminho do arquivo de senhas nunca aparecem na foto, na saída, nos motivos nem no `probes.log`;
  - verificado por UT-01, UT-08 e UT-10.
- **Privacidade e dados pessoais:** a foto guarda só os campos da regra 4a do ADR-0026 (seção 6.2), já mascarados pelo núcleo (ids de conta como `[REDACTED]`); campos extras dos itens são descartados (UT-01). A foto continua sendo arquivo da tarefa, apagado no fim (SPEC-0091).
- **Disponibilidade e resiliência:** probe recusada, com erro, com falha, cortada ou com item fora do contrato deixa o aspecto `not_verified`, com o motivo; nunca vira `ok` (UT-08). Login de nuvem expirado chega como o motivo fixo do adaptador ("renove o login da nuvem").
- **Acessibilidade (UI):** N/A — CLI sem interface gráfica.
- **Custo:** as APIs de métricas e de simulação são pagas por chamada em algumas nuvens; o limite de recursos, a janela limitada e uma única probe `metrics` por recurso seguram o custo (o adaptador da SPEC-0100 faz as consultas em lote).

## 6. Artefato A — Contrato
**Interface:** subcomandos `verify snapshot` e `verify compare`, o arquivo de foto `verify@2`, a saída `verify@2` e o contrato dos itens consumidos das capacidades.

```text
atlas.py verify snapshot --service <id> --env <ambiente> --out <arquivo>
    [--since 30m] [--resource <kind:id>]... [--max-resources 20] [--confirm-production] [--atlas X]
  tudo o que o verify@1 faz, mais, por recurso do escopo (seção 6.1): as probes dos aspectos do kind
  grava <arquivo> (mesmas regras de --out do verify@1: fora do atlas por identidade, temporário exclusivo, 0600):
    {"contract": "verify@2", "service", "environment", "taken_at", "deployments": {...como no verify@1...},
     "dependencies": {"<kind:id>": {<estado do recurso>}}, "not_verified": [...]}
  exits: 0 gravado · 2 argumento inválido ou recurso fora do grafo · 3 sem configuração · 4 recusado (probes
         desligadas, produção sem confirmação)

atlas.py verify compare --service <id> --env <ambiente> --expect-image <imagem>
    [--baseline <arquivo>] [--window 10m] [--max-new-errors 0] [--max-new-restarts 0]
    [--resource <kind:id>]... [--max-resources 20]
    [--max-new-dlq 0] [--max-queue-age 10m] [--expect-migration [<datastore>=]<migration>]...
    [--max-signal-increase 0.5]
    [--confirm-production] [--json] [--atlas X]
  verificações por deployment: delivery, runtime, logs (como no verify@1, com "resource": null)
  verificações por recurso do escopo: dependencies e signals (seção 6.3), com "resource": "<kind:id>"
  veredito: degradou se alguma failed; senão inconclusivo se alguma not_verified; senão passou
  saída --json: {"contract": "verify@2", "verdict", "checks", "suggestion"}
  exits: 0 passou · 1 degradou · 5 inconclusivo · 2 argumento inválido · 3 sem configuração · 4 recusado
  nada é gravado no atlas; cada probe entra no registro local (SPEC-0088, com "resource" da SPEC-0096)
```

**Argumentos novos (exit 2, antes de qualquer probe, sem citar valor sensível):**
- `--resource <kind:id>` — `kind` em `queue`, `topic` e `datastore` (`bucket` fica fora nesta versão, ADR-0026 4a) e `id` pela regra de nome simples do atlas; fora do formato, inclusive `bucket:<id>` → `--resource inválido — use <kind>:<id> com kind queue, topic ou datastore`. Repetível; repetido é contado uma vez. Recurso não ligado → `recurso <kind:id> não ligado a <serviço> em <ambiente>` (a mensagem da SPEC-0096).
- `--max-resources N` — o mesmo no `snapshot` e no `compare`: inteiro de 1 a 50 (padrão 20); fora → `--max-resources inválido — use um inteiro de 1 a 50`. Mais `--resource` distintos que `N` → `mais recursos em --resource que --max-resources`.
- `--max-new-dlq N` — inteiro ≥ 0 (padrão 0), mesmo formato de `--max-new-errors`.
- `--max-queue-age D` — duração no formato de `--window` (padrão `10m`, até `24h`).
- `--expect-migration [<datastore>=]<migration>` — repetível; aceita `<datastore>=<id>` (ex.: `orders-db=20261124_add_status`), com `<datastore>` pela regra de nome simples. `<migration>` casa `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. A forma sem `<datastore>=` só vale com exatamente um `datastore` no escopo; com zero ou mais de um → `--expect-migration <m> ambígua: use <datastore>=<migration>`. `<datastore>` fora do escopo → `recurso datastore:<id> fora do escopo do verify`.
- `--max-signal-increase X` — decimal `^\d+(\.\d+)?$`, de 0 a 100 (padrão `0.5`, ou seja 50%); fora → `--max-signal-increase inválido — use um decimal de 0 a 100 (0.5 = 50%)`.

**Ordem das checagens (a do `verify@1`, estendida):**
1. configuração (3);
2. probes desligadas (4);
3. argumentos (2), inclusive os novos acima e a `--baseline` (`verify@1` ou `verify@2` válida, do mesmo serviço e ambiente);
4. regras do alvo (2): os deployments e, pela SPEC-0096, cada recurso do escopo; produção sem confirmação (4) — para todos os alvos antes de qualquer probe. Com a produção recusada, nada roda e nada é registrado.

### 6.1 Escopo e aspectos
**Escopo:**
- Por padrão, todos os recursos `queue`, `topic` e `datastore` que `linked_resources` (SPEC-0096, regras do ADR-0025: aresta do deployment, `config_refs` resolvido, DLQ) devolve para algum deployment do serviço no ambiente, na ordem de `kind:id`. Um `bucket` ligado não entra (ADR-0026 4a). Um recurso ligado por mais de um deployment entra uma vez, atribuído ao primeiro deployment pelo id.
- Uma fila ligada **só** pelo atributo `dlq` de outra fila do escopo não entra por padrão (o estado dela já vem em `dlq_visible` da fila principal). Pedida em `--resource`, ela entra no papel de DLQ (`dlq_of: <kind:id da fila principal>`).
- `--resource` restringe o escopo à lista dada (cada uma validada pela SPEC-0096).
- Acima de `--max-resources`, os primeiros N pela ordem entram; os excedentes não têm probe e ficam `not_verified` nas duas verificações, com o motivo `acima de --max-resources (<N>)`.
- Sem nenhum recurso ligado, `dependencies` fica `{}` e não há verificações por recurso.
- **Sem adaptador de recurso nesta máquina:** se nenhum adaptador declarado em `probes.adapters` declara, no `--describe` `probe@2`, uma das capacidades de recurso (`messaging`, `database`, `signals`, `permissions`) e não há `--resource`, o escopo fica vazio: `dependencies` fica `{}` na foto, nenhuma probe de recurso roda e o `compare` não emite `dependencies` nem `signals` (o resultado fica como no `verify@1`, sem virar `inconclusivo`). Basta um adaptador de recurso declarado, ou um `--resource`, para o escopo valer, e então os recursos cujo kind não tem adaptador ficam `not_verified` com o motivo. A decisão usa só o `--describe` (que roda mesmo em produção sem confirmação) e entra no ADR-0026.

**Relações e ações exigidas** (para o aspecto `permissions`): a relação é o tipo da aresta que liga o recurso ao deployment (um `config_refs` resolvido conta como `depends_on`; a ligação só por `dlq` não tem relação):

| Relação | Kind | Ações exigidas |
|---|---|---|
| `publishes` | `topic` | `publish` |
| `publishes` | `queue` | `send` (enviar numa fila, ADR-0026 regra 3) |
| `consumes` | `queue` | `receive`, `delete` |
| `depends_on` | `queue` | `send` |
| qualquer outra | qualquer | nenhuma |

**Aspectos por kind** (capacidade e verbo de cada probe; "sem adaptador" = nenhum adaptador declarado cujo `--describe` `probe@2` declara a capacidade, o verbo e o kind em `targets`):

| Kind | `dependencies` | `signals` |
|---|---|---|
| `queue` | `queue` (`messaging queue`); `permissions` (`permissions simulate`, só se a relação exige ação) | `signals metrics` |
| `queue` com `dlq_of` | `queue` (`messaging queue`) | `signals metrics` |
| `topic` | `subscriptions` (`messaging subscriptions`); `permissions` (só se a relação exige ação) | `signals metrics` |
| `datastore` com `engine` `postgres` ou `aurora-postgresql` | `migrations` (`database migrations`); `tables` (`database tables`) | `signals metrics` |
| `datastore` com outro `engine` ou sem `engine` (caches, por exemplo) | nenhum | `signals metrics` |

Um recurso sem nenhum aspecto de `dependencies` (um datastore que não é PostgreSQL) não tem a verificação `dependencies`, só `signals`. O `engine` vem do atributo do nó no `graph.json`.

As probes pedem `limits.lines` = 2000 (o máximo) e `limits.since_seconds` = `--since` no `snapshot` e `--window` no `compare` (usado só por `metrics`).

### 6.2 Leitura dos itens (contrato da regra 4a do ADR-0026)
Os campos dos itens são os da tabela da regra 4a do ADR-0026, a fonte única; os adaptadores SPEC-0098 a SPEC-0101 a cumprem. Esta seção diz só como o `verify` os lê. O `verify` lê só esses campos de cada item da saída `probe@2` (`status: ok`); outros campos escalares podem vir e são descartados (nunca vão para a foto; `api_action` vai só para a evidência). Um item sem um campo obrigatório ou com o tipo errado deixa o aspecto `not_verified`, com o motivo `item fora do contrato de <capacidade> <verbo>: <campo>`. Inteiro = número inteiro, não booleano.

| Capacidade / verbo (alvo) | Itens | Campos e tipos que o `verify` confere |
|---|---|---|
| `messaging queue` (fila) | exatamente 1 | `visible` e `in_flight` (inteiros ≥ 0), `oldest_age_seconds` (inteiro ≥ 0 ou `null`), `dlq_visible` (inteiro ≥ 0, ou `null` sem DLQ) |
| `messaging subscriptions` (tópico) | 0 ou mais, um por assinatura | `destination` (texto não vazio: o `kind:id` do grafo ou o destino mascarado), `filter_fingerprint` (texto não vazio, ou `null` sem filtro) |
| `database migrations` (PostgreSQL) | 0 ou mais | `id` (texto não vazio), `success` (booleano ou `null`; só `false` deixa a migration como não aplicada) |
| `database tables` (PostgreSQL) | 0 ou mais | `name` (texto não vazio, `schema.tabela`) |
| `signals metrics` (banco, cache, fila, tópico) | 0 ou mais | `name` (texto não vazio), `stat` (`^(sum\|count\|avg\|min\|max\|p\d{1,2}(\.\d)?)$`), `value` (número finito ou `null`), `kind` (`error`, `latency`, `saturation` ou `traffic`) |
| `permissions simulate` (fila, tópico) | 0 ou mais | `action` (`publish`, `send`, `receive`, `delete`, `read` ou `write`), `api_action` (texto, só evidência), `decision` (`allowed` ou `denied`) |

- `messaging queue` com 0 ou mais de 1 item → `not_verified` (`resposta de messaging queue com <n> item(ns), esperado 1`).
- `signals metrics` com o mesmo `name|stat` repetido → `not_verified` (`métrica repetida: <name>|<stat>`).
- `permissions simulate` com a mesma `action` repetida e decisões diferentes → conta como `denied` (leitura conservadora).
- A impressão digital do filtro e o `destination` são responsabilidade do adaptador (SPEC-0098): o mesmo filtro dá sempre o mesmo texto, sem o conteúdo do filtro.
- Migration aplicada = item com `success` diferente de `false`; um item com `success: false` não conta como aplicada (vai em `not_applied` na evidência).
- Os textos chegam já mascarados pelo núcleo (ids de conta em ARNs e URLs como `[REDACTED]`); a comparação é feita sobre o texto mascarado, igual nas duas fases.

`references/verify.md` traz, para cada capacidade e verbo, um exemplo válido e um inválido em blocos `json verify-items <capacidade> <verbo> <valid|invalid>`, lidos pelo teste de contrato desta spec; os adaptadores testam a saída deles contra a mesma regra 4a.

### 6.3 Regras da comparação
Toda verificação nova tem `deployment` (o que liga o recurso), `resource` (`kind:id`), `check`, `status`, `evidence` e `reason`.

**Antes das regras (para as duas verificações de um recurso):**
- sem `--baseline` → `not_verified` (`sem foto de antes: dependências e sinais não se comparam`), sem probe de recurso;
- `--baseline` `verify@1` → `not_verified` (`foto sem dependências`), sem probe de recurso;
- recurso do escopo atual ausente de `dependencies` da foto → `not_verified` (`recurso fora da foto`);
- recurso da foto fora do escopo atual → ignorado (nenhuma verificação).

**`dependencies`** — avalia cada aspecto do kind; `failed` se algum aspecto falha; senão `not_verified` se algum aspecto não pôde ser verificado (sem adaptador, probe recusada, com erro, com falha, cortada, item fora do contrato, ou o aspecto ausente da foto quando a regra precisa dela); senão `ok`.

| Aspecto | `failed` quando | Precisa da foto? |
|---|---|---|
| `queue` (fila) | `dlq_visible` agora − `dlq_visible` da foto > `--max-new-dlq` (foto `null` e agora número: a foto conta como 0); ou `oldest_age_seconds` agora > `--max-queue-age` **e** na foto era `null` ou ≤ o limite (passou do limite depois do deploy) | sim |
| `queue` (fila com `dlq_of`) | `visible` agora − `visible` da foto > `--max-new-dlq` (a idade não conta) | sim |
| `subscriptions` | um `destination` da foto sumiu, ou o conjunto de `filter_fingerprint` de um `destination` mudou (assinatura nova não falha; vai na evidência) | sim |
| `migrations` | uma migration de `--expect-migration` para este datastore não está entre os `id` aplicados agora (`success` diferente de `false`) | não (a foto só dá a evidência das novas) |
| `tables` | um `name` da foto não está entre os de agora (tabela nova não falha) | sim |
| `permissions` | uma ação exigida pela relação estava `allowed` na foto e vem `denied` agora | sim |

- `dlq_visible` `null` agora com número na foto → aspecto `not_verified` (`DLQ sem leitura agora`); `null` nas duas → sem DLQ, só evidência.
- Idade já acima do limite na foto → não falha por idade; a evidência traz `age_above_limit_in_baseline: true`.
- Probe cortada (`truncated: true`) → aspecto `not_verified` (`probe de <verbo> cortada`), com uma exceção: em `migrations`, se todas as esperadas estão entre os itens recebidos, o aspecto é `ok` (achar é prova; não achar numa lista cortada não é).
- Ação exigida ausente dos itens de `simulate` agora → aspecto `not_verified` (`ação <a> não simulada`); ausente da foto → `not_verified` (`ação <a> fora da foto`).
- Ação exigida já `denied` na foto (e `denied` agora) → aspecto `not_verified` (`permissão já negada antes do deploy`), com a ação em `denied_in_baseline` na evidência: a verificação compara contra a foto. `denied` na foto e `allowed` agora → ok.

**`signals`** — compara cada métrica (`name|stat`) presente na foto e agora:
- `sum` e `count` são normalizados por minuto (`value / (janela em segundos / 60)`), porque a janela da foto (`--since`) e a de agora (`--window`) diferem; as outras estatísticas são comparadas como vêm.
- `kind: error` → piora quando, com a foto > 0, agora > foto × (1 + `--max-signal-increase`); com a foto 0 ou `null`, qualquer valor > 0 agora.
- `kind: latency` → piora quando, com a foto > 0, agora > foto × (1 + `--max-signal-increase`); com a foto 0 ou `null`, a métrica não é comparada (vai em `without_baseline`).
- `saturation` e `traffic` nunca falham; vão só na evidência.
- `value` `null` agora → a métrica não é comparada (`without_data`).
- Status: `failed` se alguma métrica de `error` ou `latency` piorou; senão `not_verified` se a probe não sustentou (recusada, erro, falha, cortada, item fora do contrato, sinais ausentes da foto) ou se nenhuma métrica de `error` ou `latency` foi comparada (`nenhuma métrica de erro ou latência comparável`); senão `ok`.

**Evidência** (objeto; chaves documentadas, presentes só para os aspectos do kind):
- `dependencies`: `relations` (lista), `dlq_of` (texto ou `null`), `queue` (`{"now": {...4 campos}, "baseline": {...}, "new_dlq": n, "max_new_dlq": n, "max_queue_age_seconds": n, "age_above_limit_in_baseline": bool}`), `subscriptions` (`{"missing": [...], "changed": [...], "new": [...]}`), `migrations` (`{"expected": [...], "missing": [...], "not_applied": [...], "new_since_baseline": n}`), `tables` (`{"missing": [...], "new": n}`), `permissions` (`{"required": {"<ação>": "allowed|denied|ausente"}, "api_actions": {"<ação>": "<api_action>"}, "denied_in_baseline": [...]}`), `not_verified` (`{"<aspecto>": "<motivo>"}`).
- `signals`: `window_seconds`, `baseline_window_seconds`, `max_signal_increase`, `worse` (`[{"metric": "<name>|<stat>", "kind", "baseline", "now"}]`, valores normalizados), `compared` (inteiro), `without_baseline`, `without_data`, `other` (as de `saturation` e `traffic`, com os dois valores).

**Sugestão:** a mesma do `verify@1` em `degradou` (texto fixo, sem comando). Nenhuma ação é sugerida na fila, no banco nem na política.

### 6.4 Foto `verify@2`
Chaves fechadas: `contract` (`verify@2`), `service`, `environment`, `taken_at`, `deployments` (como no `verify@1`), `dependencies` e `not_verified`.

- `dependencies`: mapa `"<kind:id>" → objeto` com as chaves fechadas `deployment` (texto), `relations` (lista de textos), `dlq_of` (texto ou `null`) e, só quando a probe sustentou o aspecto, `queue` (os 4 campos), `subscriptions` (lista de `{"destination", "filter_fingerprint"}`, ordenada), `migrations` (lista dos `id` aplicados, com `success` diferente de `false`, ordenada), `tables` (lista de textos, ordenada), `signals` (`{"window_seconds": n, "metrics": {"<name>|<stat>": {"kind", "value"}}}`) e `permissions` (`{"<ação>": "allowed" | "denied"}`).
- `not_verified`: os itens do `verify@1` (`deployment`, `check`, `reason`, com `check` em `delivery`, `runtime`, `logs`) e os de recurso, com as chaves fechadas `deployment`, `resource`, `check` (`dependencies` ou `signals`) e `reason` (o motivo começa pelo aspecto: `queue: probe recusada — nenhum adaptador para messaging`).
- Exemplo:

```json
{"contract": "verify@2", "service": "orders", "environment": "dev", "taken_at": "2026-11-24T09:00:00Z",
 "deployments": {"dev-orders": {"images": ["acme/orders:2.0.1"], "ready": 2, "desired": 2, "restarts": {"orders-6b7c-aaaa": 0},
                 "warnings": [], "error_signatures": {}}},
 "dependencies": {
   "queue:orders": {"deployment": "dev-orders", "relations": ["consumes"], "dlq_of": null,
                    "queue": {"visible": 3, "in_flight": 1, "oldest_age_seconds": 40, "dlq_visible": 0},
                    "signals": {"window_seconds": 1800, "metrics": {"ApproximateAgeOfOldestMessage|max": {"kind": "latency", "value": 40}}},
                    "permissions": {"receive": "allowed", "delete": "allowed"}},
   "datastore:orders-db": {"deployment": "dev-orders", "relations": ["depends_on"], "dlq_of": null,
                           "migrations": ["20261120_create_orders"], "tables": ["public.orders"]}},
 "not_verified": [{"deployment": "dev-orders", "resource": "datastore:orders-db", "check": "signals",
                   "reason": "signals: probe recusada — nenhum adaptador para signals"}]}
```

### 6.5 Saída `verify@2` e validadores
- `--json`: chaves fechadas `contract` (`verify@2`), `verdict`, `checks` e `suggestion`; cada verificação com as chaves fechadas `deployment`, `resource` (`null` em `delivery`, `runtime` e `logs`; `kind:id` em `dependencies` e `signals`), `check`, `status`, `evidence` e `reason` (obrigatório e não vazio em `not_verified`). Quem conhece só o `verify@1` continua achando `verdict`, `checks` e `suggestion`.
- Markdown: a tabela ganha a coluna "recurso" (vazia nas verificações de deployment).
- `validate_verify_snapshot(data)` aceita `verify@1` (as chaves do `verify@1`, sem `dependencies`) e `verify@2` (as chaves acima, `dependencies` obrigatório, podendo ser `{}`); qualquer outro `contract` é recusado.
- `validate_verify_result(data)` aceita `verify@1` (verificações sem `resource`) e `verify@2` (com `resource` em toda verificação, `kind:id` válido em `dependencies` e `signals`, `null` nas outras). O `compare` só imprime `verify@2`.
- Ponto de extensão: o conjunto fechado de `check` vem de `VERIFY_CHECKS`; a SPEC-0103 acrescenta `functional`.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: `VERIFY_CONTRACT` `verify@2` (e o `verify@1` aceito na leitura), o registro `VERIFY_CHECKS`, o escopo de recursos, `_verify_observe_resource`, `_dependencies_check`, `_signals_check`, os argumentos novos, os validadores e o `ATLAS_VERSION`.
- `references/verify.md`: o escopo, os aspectos, o contrato dos itens com os blocos `verify-items`, as regras, as opções, os exemplos `verify@2` e a compatibilidade com o `verify@1`.
- `references/probes.md`: um ponteiro para o contrato dos itens em `references/verify.md`, para quem escreve um adaptador.
- `SKILL.md`: a linha do `verify` com as opções novas.
- `tests/test_verify.py`: os testes da SPEC-0090 passam a aceitar a foto e a saída `verify@2` (pelas mesmas regras), sem mudar o que verificam.
- `tests/test_verify_dependencies.py` e o adaptador falso `tests/fixtures/fake-probes/scripted_resources.py` (`probe@2`, roteiro por `kind:id` e verbo, registro de chamadas).
- CHANGELOG e `plugin.json`.

### 6.6 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Foto com dependências | fila, tópico e banco PostgreSQL ligados, adaptador falso com itens válidos e campos extras | `verify@2` com `dependencies` só com os campos da regra 4a do ADR-0026, ordenados e mascarados; sem campos extras | UT-01, CT-01 |
| Escopo padrão | recursos de `linked_resources` por aresta e por `config_refs`; DLQ ligada só por `dlq`; `bucket` ligado | todos entram, menos a DLQ e o `bucket`; um recurso de dois deployments entra uma vez | UT-02 |
| Datastore que não é PostgreSQL | cache `engine: valkey` ligado | só `signals`, sem `dependencies` e sem probe `database` | UT-02 |
| `--resource` | lista restrita; DLQ pedida | só os pedidos; a DLQ no papel `dlq_of` | UT-02 |
| `--resource` inválido | fora do formato, `bucket:<id>`, ou não ligado ao deployment do ambiente | exit 2 com a mensagem do contrato, nenhuma probe roda | UT-02 |
| Limite de recursos | mais ligados que `--max-resources`, no `snapshot` e no `compare` | os primeiros N verificados; os excedentes `not_verified` "acima de --max-resources" | UT-02 |
| Limite inválido | `--max-resources` 0 ou 51; mais `--resource` que o limite | exit 2, nenhuma probe | UT-02 |
| DLQ ganhou mensagens | `dlq_visible` 0 → 2 com `--max-new-dlq` 0 | `dependencies` failed com `new_dlq` na evidência; com `--max-new-dlq 2`, ok | UT-03, IT-01 |
| Idade da fila | passou do limite depois do deploy; já estava acima na foto | failed no primeiro; não falha no segundo, com `age_above_limit_in_baseline` | UT-03 |
| DLQ sem leitura | `dlq_visible` número na foto e `null` agora | aspecto `not_verified` "DLQ sem leitura agora" | UT-03 |
| DLQ pedida | fila com `dlq_of`, `visible` cresceu acima do limite | failed; a idade não conta | UT-03 |
| Limites da fila inválidos | `--max-new-dlq` negativo, `--max-queue-age` fora do formato | exit 2 | UT-03 |
| Assinaturas | uma sumiu; filtro mudou; uma nova; lista cortada | failed, failed, ok com a nova na evidência, `not_verified` | UT-04 |
| Migration esperada | aplicada; não aplicada; com `success: false`; lista cortada com ela; cortada sem ela; forma `<datastore>=<id>` | ok; failed; failed com ela em `not_applied`; ok; `not_verified`; aceita | UT-05 |
| `--expect-migration` inválida | formato, ambígua, datastore fora do escopo | exit 2 com a mensagem do contrato | UT-05 |
| Tabelas | uma tabela da foto sumiu; uma nova; lista cortada | failed; ok; `not_verified` | UT-05 |
| Permissão | relação `consumes` com `delete` `allowed` na foto e `denied` agora; `publishes` numa fila com `send` `denied` agora; já `denied` na foto; tudo permitido; ação não simulada | failed; failed; `not_verified` "permissão já negada antes do deploy" com a ação na evidência; ok; `not_verified` "ação <a> não simulada" | UT-06 |
| Sinais | erro sobe acima de 50%; no limite; de 0 para >0; latência sem base; saturação e tráfego | failed; ok; failed; não comparada; nunca falham | UT-07 |
| Janelas diferentes | `sum` com 30m na foto e 10m agora | comparação por minuto | UT-07 |
| Nada comparável | só `traffic`, ou só latência sem base | `signals` `not_verified` | UT-07 |
| `--max-signal-increase` inválido | negativo, texto, acima de 100 | exit 2 | UT-07 |
| Sem adaptador ou sem acesso | nenhum adaptador `probe@2` para a capacidade; só adaptador `probe@1`; sem acesso local | aspecto `not_verified` com o motivo, sem o valor do acesso; nunca ok | UT-08 |
| Probe com erro, falha, cortada ou item fora do contrato | `status: error` ("renove o login da nuvem"), exit do adaptador, `truncated`, campo faltando | `not_verified` com o motivo; nunca ok | UT-08, CT-02 |
| Recurso fora da foto | recurso ligado agora que não está na foto | `not_verified` "recurso fora da foto" | UT-08 |
| Nenhum adaptador de recurso | nenhum adaptador declara `messaging`, `database`, `signals` nem `permissions`, sem `--resource`, com recursos ligados | foto com `dependencies` `{}`; `compare` sem `dependencies` nem `signals`, veredito como no `verify@1`; nenhuma probe de recurso | UT-11 |
| Um adaptador de recurso ou `--resource` | só um adaptador de `messaging` declarado; ou nenhum e um `--resource` | escopo vale; os aspectos sem adaptador ficam `not_verified` com o motivo | UT-11 |
| Foto `verify@1` | `--baseline` `verify@1` | `delivery`, `runtime` e `logs` como hoje; `dependencies` e `signals` `not_verified` "foto sem dependências"; nenhuma probe de recurso | UT-09, CH-01 |
| Sem foto | sem `--baseline` | `dependencies` e `signals` `not_verified` "sem foto de antes"; nenhuma probe de recurso | UT-09 |
| Veredito e exits | combinações das cinco verificações | regra do `verify@1`; exits 0, 1 e 5; sugestão sem comando | UT-10 |
| Atlas intocado, só leitura, produção | qualquer execução; produção sem confirmação | hash do atlas igual; só verbos de leitura no registro; exit 4 sem nenhuma execução | UT-10 |
| Ponta a ponta | snapshot → troca do roteiro → compare, com `atlas.py` de verdade | `passou` com as dependências seguindo a foto; `degradou` com a DLQ crescendo | IT-01 |
| Contrato da foto e da saída | exemplos `verify@1` e `verify@2`, válidos e inválidos | validadores aceitam os dois contratos e recusam chave desconhecida, `resource` faltando e versão diferente | CT-01 |
| Contrato dos itens | blocos `verify-items` de `references/verify.md` | os válidos sustentam o aspecto; os inválidos dão `not_verified` com o campo no motivo | CT-02 |
| Comportamento de hoje | serviço sem recursos ligados, foto `verify@1` | as mesmas verificações, status, veredito e exit de hoje | CH-01 |

## 7. Artefato B — Plano de Testes (TDD)
<!-- Todo teste tem um ID e é escrito ANTES da implementação (Red). No código, cada teste carrega a tag `SPEC-0102:<ID>` — o G1 (`spec_graph.py verify`) verifica. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem testes: "N/A — motivo" SEM ID. Teste que protege comportamento existente e passa antes da mudança: marque `(guarda: passa antes da mudança)`. Estratégia completa: references/testing.md da skill. -->

### 7.1 Testes de Caracterização
- **CH-01** — Dado um atlas com o serviço `api` sem nenhum recurso ligado e uma foto `verify@1` do `snapshot` de hoje, quando `verify compare` roda nos estados "saudável" e "CrashLoop" do adaptador falso, então as verificações (`deployment`, `check`, `status`), o veredito e o exit são os de hoje (`passou`/0 e `degradou`/1), e `verify snapshot` grava os mesmos `deployments` e `not_verified` de hoje (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado o adaptador falso `probe@2` com `queue:orders` (`visible` 3, `in_flight` 1, `oldest_age_seconds` 40, `dlq_visible` 0, mais um campo extra `sample_body`), `topic:orders-events` (duas assinaturas com `destination` mascarado contendo o id de conta 123456789012) e `datastore:orders-db` (`engine: postgres`, migrations e tabelas `schema.tabela`), quando `verify snapshot` roda, então a foto é `verify@2` válida, com `dependencies` só com os campos da regra 4a do ADR-0026, listas ordenadas, o id de conta como `[REDACTED]`, sem `sample_body`, e sem o profile, o usuário, o nome do banco nem o caminho do arquivo de senhas em nenhum lugar do arquivo.
- **UT-02** — Dado um grafo com `queue:orders` (aresta `consumes`), `datastore:orders-db` (`engine: postgres`, por `config_refs`), `datastore:orders-cache` (`engine: valkey`), `bucket:orders-files` (aresta `writes`), `queue:orders-dlq` (só pelo `dlq` de `orders`) e `topic:orders-events` ligado por dois deployments, quando `verify snapshot` roda:
  - sem `--resource`, entram os quatro recursos que não são a DLQ nem o `bucket`, cada um uma vez, na ordem de `linked_resources`; `datastore:orders-cache` só com `signals`, sem nenhuma probe `database`;
  - com `--resource queue:orders-dlq`, só ela entra, com `dlq_of: queue:orders`;
  - com `--resource queue:outra` (não ligada), `--resource fila:orders` ou `--resource bucket:orders-files`, exit 2 com a mensagem do contrato e nenhuma linha `run` no registro do adaptador;
  - com `--max-resources 2`, os recursos além dos dois primeiros ficam em `not_verified` "acima de --max-resources (2)" sem probe, e o `compare` com o mesmo `--max-resources 2` dá o mesmo corte;
  - com `--max-resources 0`, `51` ou três `--resource` e `--max-resources 2`, exit 2, tanto no `snapshot` quanto no `compare`.
- **UT-03** — Dada uma foto com `queue:orders` (`dlq_visible` 0, `oldest_age_seconds` 40), quando `verify compare` roda:
  - `dlq_visible` 2 agora com `--max-new-dlq 0` dá `dependencies` failed com `new_dlq: 2`; com `--max-new-dlq 2`, ok;
  - `oldest_age_seconds` 900 agora com `--max-queue-age 10m` dá failed; com a foto já em 700, não falha e a evidência traz `age_above_limit_in_baseline: true`;
  - `dlq_visible` `null` agora dá `not_verified` "DLQ sem leitura agora";
  - com `--resource queue:orders-dlq` (papel `dlq_of`), `visible` 0 → 3 dá failed e uma idade alta não conta;
  - `--max-new-dlq -1` ou `--max-queue-age 2x` dá exit 2.
- **UT-04** — Dada uma foto com `topic:orders-events` e as assinaturas `{destination A, fp1}` e `{destination B, null}`, quando `verify compare` roda, então: A sumida dá failed com A em `missing`; A com `fp2` dá failed com A em `changed`; as duas iguais mais uma C nova dá ok com C em `new`; a probe cortada dá `not_verified` "probe de subscriptions cortada".
- **UT-05** — Dada uma foto com `datastore:orders-db` (`engine: postgres`, migrations `[m1]`, tabelas `[public.orders, public.items]`), quando `verify compare` roda:
  - `--expect-migration m2` com `m2` aplicada (`success: true`) dá ok com `new_since_baseline: 1`; sem `m2`, failed com `m2` em `missing`; com `m2` e `success: false`, failed com `m2` em `missing` e em `not_applied`; com `success: null`, ok;
  - `--expect-migration orders-db=m2` é aceita e dá o mesmo resultado que a forma curta;
  - lista cortada com `m2` dá ok; cortada sem `m2`, `not_verified`;
  - `public.items` sumida dá failed; uma tabela nova dá ok; tabelas cortadas dão `not_verified`;
  - `--expect-migration "m 2"`, `--expect-migration m2` com dois datastores no escopo e `--expect-migration outro-db=m2` (fora do escopo) dão exit 2 com as mensagens do contrato, sem probe.
- **UT-06** — Dada uma foto com `queue:orders` (relação `consumes`, `receive` e `delete` `allowed`) e `topic:orders-events` (relação `publishes`, `publish` `allowed`), quando `verify compare` roda, então: `delete` `denied` agora dá `dependencies` failed, com `delete` em `required`; tudo `allowed` dá ok; `simulate` sem a ação `receive` agora dá `not_verified` "ação receive não simulada"; `publish` `denied` no tópico dá failed. Com uma foto de `queue:orders-out` com relação `publishes` (`send` `allowed`), a ação exigida é `send`: `send` `denied` agora dá failed, e `send` `allowed` agora dá ok. Com uma foto em que `delete` já estava `denied`, `delete` `denied` agora dá `not_verified` "permissão já negada antes do deploy", com `delete` em `denied_in_baseline` (nunca failed nem ok), e `delete` `allowed` agora dá ok.
- **UT-07** — Dada uma foto com `signals` de `queue:orders` na janela de 1800 s (`Errors|sum` 30, `Latency|p95` 200, `Depth|max` 10 `saturation`, `Sent|sum` 900 `traffic`), quando `verify compare` roda com `--window 10m`:
  - `Errors|sum` 16 agora (1,6/min contra 1,0/min, +60%) dá `signals` failed com a métrica em `worse`; 15 (+50%) dá ok;
  - `Latency|p95` 301 dá failed; 300 dá ok;
  - erro de 0 na foto para 1 agora dá failed;
  - latência `null` na foto não é comparada (`without_baseline`);
  - `Depth` e `Sent` muito maiores nunca falham e vão em `other`;
  - só métricas `traffic` dá `not_verified` "nenhuma métrica de erro ou latência comparável";
  - `--max-signal-increase -0.1`, `abc` ou `101` dá exit 2.
- **UT-08** — Dada uma foto `verify@2` válida, quando `verify compare` roda com, para um recurso: nenhum adaptador `probe@2` para `messaging`; só um adaptador `probe@1`; o acesso local à nuvem ausente (exit 4 da probe); `status: error` com "renove o login da nuvem"; o adaptador saindo com 3; `truncated: true`; um item sem `dlq_visible`; ou o recurso ausente da foto — então o aspecto ou a verificação fica `not_verified`, com o motivo do contrato (sem nenhum valor de acesso local no motivo, na saída nem no `probes.log`), nunca `ok`, e o veredito é `inconclusivo` (exit 5) quando nada mais falhou.
- **UT-09** — Dada uma foto `verify@1` (o exemplo de hoje do `references/verify.md`), quando `verify compare` roda com recursos ligados e um adaptador de recurso declarado, então `delivery`, `runtime` e `logs` saem como no `verify@1`, `dependencies` e `signals` de cada recurso ficam `not_verified` "foto sem dependências", a saída é `verify@2` válida e o registro do adaptador falso não tem nenhuma probe de recurso. Sem `--baseline`, o motivo é "sem foto de antes: dependências e sinais não se comparam", também sem probe de recurso.
- **UT-10** — Para combinações de `ok`, `failed` e `not_verified` das cinco verificações em dois recursos, o veredito segue `failed` > `not_verified` > `ok`, com exits 0, 1 e 5, e a sugestão só em `degradou`, sem comando. Em todos os testes desta suíte: a árvore do atlas tem o mesmo hash antes e depois; o registro do adaptador falso só tem os verbos `status`, `events`, `logs`, `queue`, `subscriptions`, `migrations`, `tables`, `metrics` e `simulate`; em ambiente de produção sem `--confirm-production`, `snapshot` e `compare` saem com 4 sem nenhuma linha `run` no registro e sem nada no `probes.log`; com a confirmação, cada probe de recurso entra no `probes.log` com `resource`.
- **UT-11** — Dado um grafo com `queue:orders` e `datastore:orders-db` ligados e a configuração só com o adaptador `runtime` (`scripted.py`), sem `--resource`, quando `verify snapshot` e `verify compare` rodam, então a foto tem `dependencies` `{}`, o `compare` só emite `delivery`, `runtime` e `logs`, o veredito e o exit são os mesmos do caso sem recursos (`passou`/0 no estado saudável) e o registro não tem nenhuma probe `run` de recurso. Com um adaptador `probe@2` declarando só `messaging`, a fila tem `dependencies` verificada e `signals` e `permissions` ficam `not_verified` com o motivo, e o datastore fica `not_verified` nas duas (veredito `inconclusivo`, exit 5). Sem adaptador de recurso mas com `--resource queue:orders`, a fila entra e fica `not_verified` com o motivo.

### 7.3 Testes de Integração
- **IT-01** — Num atlas temporário com um serviço `orders` em `dev` (`tier: test`), a fila `queue:orders` (relação `consumes`, `dlq` `orders-dlq`), as probes ligadas, o acesso local à nuvem definido e dois adaptadores declarados no `config.yml` temporário (o `scripted.py` para `runtime` e o `scripted_resources.py` `probe@2` para `messaging`, `signals` e `permissions`), com o `atlas.py` de verdade como processo:
  1. `verify snapshot --out <tmp>/foto.json` roda com o roteiro "antes" (`dlq_visible` 0);
  2. o roteiro passa ao estado "depois";
  3. `verify compare --baseline <tmp>/foto.json --expect-image acme/orders:2.0.2 --json` roda.

  Com o "depois" seguindo a foto (`dlq_visible` 0, mesmas permissões `allowed`, sinais iguais), a saída é `passou` (exit 0). Com `dlq_visible` 4 no "depois", a saída é `degradou` (exit 1), com `dependencies` de `queue:orders` `failed` e `new_dlq: 4` na evidência. Nenhum `aws`, `psql` nem `kubectl` de verdade roda.

### 7.4 Testes de Contrato
- **CT-01** — Dados os blocos de exemplo de `references/verify.md` (`json` com `"contract": "verify@1"` e `"contract": "verify@2"`, e os marcados `verify@2 snapshot invalid` e `verify@2 result invalid`), quando `validate_verify_snapshot` e `validate_verify_result` rodam, então os válidos dos dois contratos são aceitos, e uma chave desconhecida, `resource` faltando numa verificação `verify@2`, `resource` com `kind` inválido, `dependencies` ausente numa foto `verify@2` e `contract: verify@3` são recusados; o exemplo de foto `verify@2` é aceito pelo `compare` como `--baseline`, e uma `--baseline` inválida sai com 2.
- **CT-02** — Dados os blocos `json verify-items <capacidade> <verbo> <valid|invalid>` de `references/verify.md`, que seguem a regra 4a do ADR-0026 (um válido e um inválido para `messaging queue`, `messaging subscriptions`, `database migrations`, `database tables`, `signals metrics` e `permissions simulate`), quando o adaptador falso devolve cada um como os itens de uma saída `probe@2`, então os válidos sustentam o aspecto (a foto guarda exatamente os campos do contrato) e os inválidos deixam o aspecto `not_verified` com o nome do campo no motivo. Um item `subscriptions` com `endpoint` no lugar de `destination` e um item `migrations` sem `success` estão entre os inválidos.

### 7.5 Testes E2E
- N/A — CLI sem jornada de usuário interativa; o IT-01 roda as duas fases como processo, de ponta a ponta, com os adaptadores falsos.

### 7.6 Outros
- N/A — a segurança (só leitura, acesso que não aparece, atlas intocado) está coberta pelos testes unitários acima, e o G3 continua com os testes de arquitetura da boson-atlas.

**Dublês e dados de teste:**
- `tests/fixtures/fake-probes/scripted_resources.py`: adaptador `probe@2` falso com roteiro por `target.resource` (`kind:id`) e verbo, `--describe` configurável (capacidades, verbos, `targets` e `access`), respostas `items`/`truncated`, `error` ou `exit`, e o registro de cada chamada (modo, argv e entrada), no padrão do `scripted.py`.
- O `scripted.py` de hoje para a capacidade `runtime`.
- Atlas, `graph.json` e configuração temporários (HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME em pastas temporárias, `helpers.Sandbox`); acesso local com valores falsos que os testes procuram nas saídas.
- Só nomes genéricos (`acme`, `orders`, `orders-dlq`, `orders-db`, `orders-events`, `dev`, `prod`); 123456789012 só como id de conta que precisa sair mascarado.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15), sem rede, sem nuvem, sem banco e sem cluster.

## 8. Plano de Rollout
- **Estratégia:** deploy direto, pela versão do plugin. Continua atrás de `probes.enabled` e de `delivery_check.verify`; sem adaptadores de recurso declarados, as verificações novas aparecem como `not_verified` com o motivo.
- **Dados/schema:** a foto da tarefa passa a `verify@2`, fora do atlas; nenhuma mudança no atlas nem no `graph.json`.
- **Compatibilidade:**
  - o `compare` aceita a foto `verify@1` (as novas ficam "foto sem dependências");
  - a saída passa a `verify@2`, mantendo `verdict`, `checks` e `suggestion`, o exit e as regras de veredito;
  - quem não declarou nenhum adaptador de recurso (e não passa `--resource`) não vê `dependencies` nem `signals`: o resultado fica como no `verify@1`, sem virar `inconclusivo`;
  - depois de declarar um adaptador de recurso, os recursos ligados cujo kind não tem adaptador ficam `not_verified` com o motivo (ADR-0026: não verificado nunca vira `passou`); `--resource` restringe o escopo, e a SPEC-0105 trata isso no G6;
  - os adaptadores `probe@1` continuam valendo para o `runtime`.
- **Observabilidade:** o veredito, as evidências por recurso e o `probes.log` com `resource` em cada probe (SPEC-0096), que a SPEC-0104 usa para as métricas de uso.
- **Rollback:** voltar a versão do plugin. Uma foto `verify@2` tirada antes do rollback é recusada pelo `compare` antigo (exit 2): basta tirar a foto de novo.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] A idade da mensagem mais antiga é comparada contra a foto ou como valor absoluto? — Contra a foto: falha só quando passa do `--max-queue-age` depois do deploy; se já estava acima na foto, não falha e a evidência avisa (`age_above_limit_in_baseline`). Segue o direcionador "comparar contra a foto" do ADR-0026, já que a fila é compartilhada (Architect, 2026-11-24, recomendado)
- [x] Uma permissão já negada na foto falha a comparação? — Não: só falha quando a ação exigida estava `allowed` na foto e está `denied` agora. Já negada na foto fica `not_verified` "permissão já negada antes do deploy", com a ação na evidência, porque a verificação compara contra a foto (Architect, 2026-11-24, ajuste do Architect)
- [x] Quem não configurou adaptador de recurso passa a ver `inconclusivo`? — Não: sem nenhum adaptador declarando `messaging`, `database`, `signals` ou `permissions` e sem `--resource`, `dependencies` e `signals` não aparecem e o resultado fica como no `verify@1`. Com um adaptador de recurso ou um `--resource`, o escopo vale e o que falta fica `not_verified` (Architect, 2026-11-24, ajuste do Architect; registrado no ADR-0026)
- [x] Como o `verify` diz ao adaptador de permissões quais ações simular? — Não diz: o adaptador devolve as ações abstratas do kind (`publish`, `send`, `receive`, `delete`, `read`, `write`), e o `verify` escolhe as exigidas pela relação. A entrada do `probe@2` (SPEC-0096) não muda (Architect, 2026-11-24, recomendado)
- [x] Os valores de `kind` das métricas ficam em português? — Não: `error`, `latency`, `saturation` e `traffic`, como os outros identificadores de contrato (`ok`, `failed`, `error`, `warn`); os rótulos em português ficam só no Markdown (Architect, 2026-11-24, recomendado)
- [x] Como comparar sinais de janelas diferentes (`--since` 30m na foto, `--window` 10m agora)? — `sum` e `count` são normalizados por minuto; médias, percentis, mínimo e máximo são comparados como vêm (Architect, 2026-11-24, recomendado)
- [x] A DLQ entra como recurso próprio no escopo padrão? — Não: o estado dela vem em `dlq_visible` da fila principal. Pedida em `--resource`, entra no papel `dlq_of`, avaliada só pelo crescimento (Architect, 2026-11-24, recomendado)
- [x] Um recurso novo do PR, que não estava na foto, é verificado? — Fica `not_verified` "recurso fora da foto": a comparação é sempre contra a foto (ADR-0026). Tirar a foto depois do `build` com o recurso já mapeado resolve (Architect, 2026-11-24, recomendado)
- [x] Sem foto, ou com foto `verify@1`, as probes de recurso rodam? — Não: as duas verificações ficam `not_verified` sem nenhuma probe, o que poupa custo e mantém o resultado determinístico (Architect, 2026-11-24, recomendado)
- [x] A que datastore se aplica `--expect-migration` sem prefixo? — Ao único `datastore` do escopo; com zero ou mais de um, exit 2 pedindo `<datastore>=<migration>` (Architect, 2026-11-24, recomendado)
- [x] Qual o máximo de `--max-resources`? — 50, com padrão 20 (ADR-0026), para segurar o tempo e o custo das APIs (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 0: Caracterização**
- [ ] CH-01 escrito(s) com a tag `SPEC-0102:<ID>`, passando no código atual, commitado(s) antes de qualquer mudança

**Fase 1: Contrato e implementação**
- [ ] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, UT-07, UT-08, UT-09, UT-10, UT-11, IT-01, CT-01, CT-02 com a tag `SPEC-0102:<ID>`, falhando pelo motivo certo
- [ ] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [ ] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — e297cb0 | 2026-11-24 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0102`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
