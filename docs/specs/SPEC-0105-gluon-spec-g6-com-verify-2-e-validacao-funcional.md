---
id: SPEC-0105
title: "gluon-spec: G6 com verify@2, acompanhamento da entrega e validação funcional"
tier: full
type: feature
user_facing: false
status: approved
created: 2026-11-24
parent: SPEC-0095
depends_on: [SPEC-0102, SPEC-0103, SPEC-0106]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/gluon-spec/SKILL.md, skills/gluon-spec/references/gates.md, skills/gluon-spec/references/sdd-config.template.yml, skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/CHANGELOG.md, skills/gluon-spec/tests/test_delivery_verify2.py, .claude-plugin/plugin.json]
adrs: [ADR-0023, ADR-0024, ADR-0025, ADR-0026]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0105 — gluon-spec: G6 com verify@2, acompanhamento da entrega e validação funcional

> Origem: épico SPEC-0095. Fecha o épico do lado da gluon-spec: o G6 ativo da SPEC-0091 passa a usar o `verify@2` (dependências e sinais, SPEC-0102), o acompanhamento da entrega de um commit (`verify track`, SPEC-0106) e a validação funcional em teste (SPEC-0103).

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O G6 da gluon-spec, com `delivery_check.verify: true`, passa a:
- **acompanhar a entrega** do commit do merge com `atlas.py verify track` (SPEC-0106, saída `track@1`), no lugar de seguir à mão os passos 1 e 2 do roteiro (pipeline e imagem nova), e usar o `expected_image` que ele descobre no `--expect-image` do `compare`;
- **verificar as dependências do serviço** com o `verify@2` (SPEC-0102), pelo escopo padrão dele (os recursos ligados ao serviço no ambiente), com os limites de `delivery_check`; o diff só restringe a lista quando os ligados passam de `max_resources`;
- **rodar a validação funcional** (SPEC-0103) só com `delivery_check.functional: true` e só nos ambientes `tier: test`.

Produção continua só passiva, com a confirmação da pessoa a cada execução. Tudo vai para o Relatório de Entrega, inclusive quantas dependências foram verificadas e quantas não.

## 2. Motivação & Escopo
**Motivação:** com a SPEC-0091, o G6 prova a entrega, o runtime e os logs do workload. O épico deu ao `verify` as dependências, os sinais e a jornada em teste, e ao atlas o acompanhamento do commit pela pipeline e pelo GitOps. Sem esta spec, o agente não sabe quais recursos pedir, quais limites usar, quando ligar a validação funcional, nem como esperar a entrega sem seguir o roteiro à mão.

**Objetivos (dentro do escopo):**
- **Chaves novas em `delivery_check`** no template do `sdd-config.yml`, todas opcionais e comentadas:
  - `functional` (padrão `false`);
  - `max_new_dlq` (0), `max_queue_age` (`10m`), `max_signal_increase` (0.5) e `max_resources` (20), os limites do `verify@2`;
  - `track_max_minutes` (30), quanto tempo no máximo o `verify track` é repetido enquanto a entrega está em andamento.
- **`verify track` no G6:** substitui os passos 1 e 2 do roteiro quando disponível, repete enquanto a entrega está em andamento (`state` `running` ou `pending`, exit 6), mapeia o `state` e as etapas para o G6 e cai no roteiro manual quando o `track` não está disponível.
- **Dependências do serviço:** o G6 não passa `--resource` por padrão: vale o escopo padrão do `verify@2`, que são os recursos ligados ao serviço no ambiente e que fica vazio quando a máquina não tem adaptador de recurso (como no `verify@1`). Só quando as dependências `queue`, `topic` e `datastore` do serviço no pacote do `atlas.py context` passam de `max_resources`, o agente restringe com `--resource` aos recursos que o diff aponta. A mesma lista (ou nenhuma) e o mesmo `--max-resources` vão à foto e à comparação, e `--expect-migration <datastore>=<id>` vai para cada migration nova do diff.
- **Validação funcional:** `--functional` só com `delivery_check.functional: true` e só em ambiente `tier: test`. Nunca em produção, nem com confirmação.
- **Produção:** só passiva, com o "sim" da pessoa para cada execução de `snapshot`, `track` e `compare`, inclusive para cada repetição do `track` (ADR-0023: a confirmação vale para aquela consulta).
- **Relatório de Entrega:** por serviço e ambiente, o veredito, as etapas do `track`, as verificações e a contagem de dependências verificadas e não verificadas.
- **`SDD_TOOL_VERSION`** na próxima versão, com a seção datada no CHANGELOG, para o `whats-new` mostrar as chaves novas.

**Não-objetivos (fora do escopo):**
- **Mudar o `atlas.py`:** os comandos são os das SPEC-0102, SPEC-0103 e SPEC-0106.
- **Rollback ou qualquer ação** no ambiente: continua com a pessoa.
- **Validação funcional fora de `tier: test`** por qualquer caminho.
- **O `spec_graph.py` ler subchaves de `delivery_check`:** o `whats-new` continua lendo só as chaves de primeiro nível; as novas aparecem no comentário da chave.
- **Configurar o acesso local:** é o `access setup` (SPEC-0104), que o G6 só cita quando a verificação não roda por falta de acesso.

## 3. Dependências
- **Implementações necessárias:**
  - SPEC-0102: as opções do `verify@2` (`--resource` e `--max-resources` no `snapshot` e no `compare`; `--max-new-dlq`, `--max-queue-age`, `--expect-migration [<datastore>=]<migration>` e `--max-signal-increase` no `compare`), conferidas pelo CT-01 contra o `--help` real; o G6 usa sempre a forma `<datastore>=<migration>`;
  - SPEC-0103: `--functional` e `--journey` no `verify compare` e a regra de `tier: test`;
  - SPEC-0106: `atlas.py verify track --service <id> --env <ambiente> --commit <sha de 40 hexadecimais> [--expect-image] [--confirm-production] [--json]`, a saída `track@1` (`state`, `current_stage`, `expected_image`, `expected_image_source`, `stages` com `pipeline`, `image`, `gitops` e `rollout`), os status `pending`, `running`, `ok`, `failed` e `not_verified` e os exits 0 (ok), 1 (failed), 5 (not_verified), 6 (running ou pending), 2, 3 e 4.
- **Contratos consumidos:** N/A (os três chegam com as implementações).
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **G6 ativo:** a subseção "Active verification (SPEC-0091)" de `references/gates.md`, com a foto no H2 e o roteiro da SPEC-0086 como base;
- **chaves de `delivery_check`:** o template e o comentário lido pelo `whats-new` (SPEC-0091, Emenda v2 e v3);
- **testes de instrução:** `skills/gluon-spec/tests/test_delivery_verify.py` e `test_delivery_check.py`, que leem os `.md` e o template e guardam fatos estáveis, não frases; o CT confere as opções contra o `--help` do `atlas.py` da boson-atlas.

**Decisão:**
- A subseção do G6 cresce no mesmo lugar, com três passos novos: acompanhar (`track`), escolher as dependências e rodar a funcional. O passo do veredito não muda.
- As regras ficam no `gates.md`. A SKILL.md só ganha uma oração na frase de `delivery_check.verify` do passo 7, apontando para lá.
- O `verify track` substitui os passos 1 e 2 do roteiro "quando disponível". O texto continua dizendo que o `compare` roda depois dos passos 1 e 2, agora acompanhados pelo `track`. O roteiro manual continua como reserva.

**Justificativa:** o comando determinístico faz o trabalho e a skill só orquestra e registra, como na SPEC-0091. Usar o escopo padrão do `verify@2` e restringir pelo diff só acima do limite segue a ordem revista da SPEC-0075 ("dependências só as que o diff ou o grafo indicam") e mantém a foto pequena (ADR-0026, consequência "ruim").

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- **Sempre restringir com `--resource` aos recursos do diff:** com `--resource`, o escopo vale mesmo sem adaptador de recurso, e uma máquina sem adaptador teria o veredito sempre `inconclusivo`. O escopo padrão mantém o comportamento do `verify@1` nesse caso (decisão do Architect).
- **Funcional ligada por padrão:** exige suíte e configuração local na máquina; sem elas o G6 ficaria sempre `inconclusivo`.
- **`--functional` em todos os ambientes, deixando o `verify` marcar `not_verified` fora de teste:** tornaria o veredito de produção sempre `inconclusivo`. O G6 só passa a opção onde ela pode rodar.
- **`verify track` obrigatório:** um atlas sem pipeline mapeada não teria o G6 ativo. O roteiro manual fica como reserva.

**ADRs:** ADR-0023 (probes e confirmação de produção), ADR-0024 (verify), ADR-0025 (recursos do grafo), ADR-0026 (`verify@2` e funcional só em teste).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - o `track` é repetido a cada `window_minutes`, até `track_max_minutes`;
  - o `compare` é limitado por `max_resources`; acima dele, pela lista de recursos que o diff aponta.
- **Segurança:**
  - valem as regras dos ADR-0023 e ADR-0026: só leitura, produção confirmada a cada execução e nenhum comando vindo do atlas;
  - a funcional nunca recebe `--confirm-production` e nunca roda fora de `tier: test`;
  - os recursos vêm do pacote do `context` (dados do atlas) e do diff, nunca de texto livre do atlas tratado como instrução.
- **Privacidade e dados pessoais:** a foto continua temporária, apagada no fim e fora de commit. O Relatório leva só o resumo das verificações, sem dado de linha.
- **Disponibilidade e resiliência:**
  - `track` indisponível ou sem resposta → roteiro manual;
  - `track` em andamento depois de `track_max_minutes` → "entrega não acompanhada até o fim: <etapa>" e o roteiro manual;
  - recurso sem adaptador ou sem acesso → `not_verified`, registrado com a sugestão de `access setup` (SPEC-0104), sem bloquear o G6 por falta de configuração.
- **Acessibilidade (UI):** N/A — instruções da skill.
- **Custo:** N/A — as consultas de métricas são limitadas pelo `verify@2`.

## 6. Artefato A — Contrato
**Interface:** chaves novas de `delivery_check`, os passos novos da subseção "Active verification" do G6 e o registro no Relatório de Entrega.

```text
sdd-config.yml
  delivery_check:
    enabled: true            # SPEC-0086
    environments: []         # SPEC-0086
    verify: false            # SPEC-0091
    window_minutes: 10       # SPEC-0091; também o intervalo entre as tentativas do verify track
    max_new_errors: 0        # SPEC-0091
    max_new_restarts: 0      # SPEC-0091
    functional: false        # true: --functional nos ambientes tier: test (SPEC-0103); nunca em produção
    max_new_dlq: 0           # mensagens novas toleradas na DLQ (--max-new-dlq)
    max_queue_age: 10m       # idade máxima da mensagem mais antiga (--max-queue-age)
    max_signal_increase: 0.5 # piora tolerada de erro ou latência contra a foto, 0.5 = 50% (--max-signal-increase)
    max_resources: 20        # recursos no máximo por verify (--max-resources)
    track_max_minutes: 30    # tempo máximo acompanhando a entrega com verify track antes de cair no roteiro manual

G6, com delivery_check.verify true e o atlas disponível (regras do org_context), por serviço e ambiente:
  0. escopo das dependências (antes da foto), alinhado à SPEC-0102 §6.1:
     por padrão, sem --resource: o verify@2 usa os recursos ligados ao serviço no ambiente (queue, topic,
       datastore), até max_resources; sem adaptador de recurso declarado nesta máquina o escopo fica vazio e o
       verify fica como o verify@1 (sem dependencies nem signals); o Relatório diz "dependências: sem adaptador
       de recurso nesta máquina" — não é inconclusivo
     só quando as dependências queue, topic e datastore do serviço no pacote atlas.py context --json passam de
       max_resources: --resource para cada recurso cujo id ou nome aparece no diff da spec (configuração,
       código de fila ou tópico, migration); nenhum no diff → sem --resource (os excedentes ficam not_verified,
       SPEC-0102)
     migration nova no diff → --expect-migration <datastore>=<id da migration>
     recurso do escopo sem adaptador ou sem acesso local → not_verified e veredito inconclusivo (exit 5); o G6
       registra como inconclusivo, a pessoa decide (a regra de sempre), com a sugestão "rode atlas.py access
       setup" (sem acesso) ou "declare o adaptador" (sem adaptador), SPEC-0104
     a mesma lista de --resource (ou nenhuma) e o mesmo --max-resources vão ao snapshot e ao compare
  1. snapshot (no H2, antes do merge — como na SPEC-0091):
     atlas.py verify snapshot --service <s> --env <a> --out <foto> [--resource <kind:id>]...
       --max-resources <max_resources> [--atlas <org_context>]
  2. acompanhar a entrega (passos 1 e 2 do roteiro):
     atlas.py verify track --service <s> --env <a> --commit <sha completo do merge, 40 hexadecimais> --json
       [--atlas <org_context>]
     pelo state da saída track@1 (e o exit):
       ok (0) → expected_image vira o --expect-image do compare
       running ou pending (6) → espera window_minutes e repete, até track_max_minutes; passou do limite →
         "entrega não acompanhada até o fim: <current_stage>" e segue o roteiro manual
       failed (1) → G6 FAIL com a etapa (stage, deployment, reason e evidence); a pessoa decide
       not_verified (5), exit 2, 3 ou 4, ou subcomando ausente (boson-atlas antiga) → passos 1 e 2 à mão, como no
         roteiro da SPEC-0086 (a imagem vem do repositório de configuração ou da pipeline); a etapa not_verified e
         o reason vão para o Relatório
  3. compare (depois do passo 2 e de window_minutes):
     atlas.py verify compare --service <s> --env <a> --expect-image <imagem> --baseline <foto>
       --window <window_minutes>m --max-new-errors <n> --max-new-restarts <n>
       [--resource <kind:id>]... --max-resources <max_resources> [--expect-migration <datastore>=<id>]...
       --max-new-dlq <max_new_dlq> --max-queue-age <max_queue_age> --max-signal-increase <max_signal_increase>
       [--functional]                       # só com functional: true E tier do ambiente test
       --json [--atlas <org_context>]
     tier: o do deployment no pacote do context (test | production | ausente = produção, ADR-0023)
  4. veredito → G6: como na SPEC-0091 (passou 0 → PASS; degradou 1 → FAIL e a pessoa decide o rollback;
     inconclusivo 5 → a pessoa decide e a decisão é registrada; 4/3/2 → "não executada" com o motivo)
     verificações de dependência not_verified por falta de acesso ou adaptador → registradas com o motivo e a
     sugestão "rode atlas.py access setup" ou "declare o adaptador" (SPEC-0104); nunca bloqueiam por si
  produção (tier production ou sem tier):
    snapshot, track e compare só com o "sim" da pessoa para aquela execução, passando --confirm-production;
    cada repetição do track (exit 6) é uma execução nova e pede um "sim" novo: um "sim" nunca cobre a próxima
    repetição, nem do mesmo commit e ambiente (ADR-0023); sem o "sim", o G6 para de acompanhar e registra
    "entrega não acompanhada até o fim: sem confirmação de produção"
    só passiva; nunca --functional, nem com confirmação
  Relatório de Entrega ("Deploy"), uma linha por serviço e ambiente:
    veredito; imagem esperada e a origem (track: expected_image_source; ou roteiro manual); state e etapas do
    track; verificações ok/failed/not_verified com motivo; "dependências: N verificadas, M não verificadas" (ou
    "sem adaptador de recurso nesta máquina"); jornadas funcionais com o resultado (só em tier test)
  a foto é apagada no fim da tarefa; nunca entra em commit
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `skills/gluon-spec/references/gates.md`: os passos 0, 2 e 3 novos da subseção "Active verification (SPEC-0091)" e as regras de produção e da funcional, com a menção a SPEC-0105.
- `skills/gluon-spec/references/sdd-config.template.yml`: as seis chaves novas e o comentário de `delivery_check`.
- `skills/gluon-spec/SKILL.md`: uma oração no passo 7.
- `skills/gluon-spec/scripts/spec_graph.py`: só o `SDD_TOOL_VERSION`.
- CHANGELOG da gluon-spec (seção datada) e `plugin.json`.
- `skills/gluon-spec/tests/test_delivery_verify2.py` (novo): os testes desta spec, no estilo de `test_delivery_verify.py`, que fica como está.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Template | `delivery_check` | `functional`, `max_new_dlq`, `max_queue_age`, `max_signal_increase`, `max_resources` e `track_max_minutes` com os padrões e comentário; o comentário da chave cita as novas | UT-01 |
| `whats-new` | projeto na versão anterior | mostra a seção nova com as chaves | IT-02 |
| Critério do épico | G6 do `gates.md` e o `atlas.py` real | descreve o `verify@2` com opções que existem, a funcional só em `tier: test` e a confirmação de produção por execução | IT-01 |
| Acompanhar | gates.md G6 | `verify track` com `--commit` de 40 hexadecimais; `state` `ok` → `expected_image` no `--expect-image` | UT-02 |
| Em andamento | `running` ou `pending` (exit 6) | repete a cada janela até `track_max_minutes`; depois, roteiro manual | UT-02 |
| Etapa falhou | `state` `failed` (exit 1) | G6 FAIL com a etapa; a pessoa decide | UT-02 |
| Track indisponível | `not_verified` (exit 5), exits 2/3/4 ou sem o subcomando | passos 1 e 2 à mão, como na SPEC-0086 | UT-02 |
| Escopo padrão | ligados até `max_resources` | sem `--resource`; mesmo `--max-resources` na foto e na comparação; `--expect-migration <datastore>=<id>` da migration do diff | UT-03 |
| Acima do limite | ligados acima de `max_resources` | `--resource` só para os recursos do diff, a mesma lista na foto e na comparação | UT-03 |
| Sem adaptador de recurso | nenhum adaptador de recurso declarado (escopo padrão) | verify como o `verify@1`; Relatório "sem adaptador de recurso nesta máquina", não inconclusivo | UT-03 |
| Sem acesso a um recurso | adaptador declarado, recurso sem acesso local ou sem adaptador | `not_verified`, veredito `inconclusivo`; a pessoa decide, com a sugestão de `access setup` ou de declarar o adaptador | UT-03 |
| Limites | chaves de `delivery_check` | viram as opções do `compare` | UT-03 |
| Funcional | `functional: true` e ambiente `tier: test` | `--functional` no `compare`; resultado das jornadas no Relatório | UT-04 |
| Funcional fora de teste | produção, sem `tier` ou `functional: false` | sem `--functional`, nem com confirmação | UT-04 |
| Produção | qualquer passo em produção | confirmação por execução, inclusive a cada repetição do `track`; só passiva | UT-05 |
| Relatório | depois do veredito | linha por serviço e ambiente com etapas, verificações e "N verificadas, M não verificadas" | UT-05 |
| Sem acesso | dependência `not_verified` por acesso ou adaptador | registrada com a sugestão de `access setup`, sem bloquear | UT-05 |
| SKILL.md | passo 7 | uma oração e o ponteiro para gates.md | UT-06 |
| O que já valia | foto no H2, veredito, foto temporária, roteiro da SPEC-0086 | continua presente | CH-01 |
| Contrato | opções, exits e etapas citados | existem no `atlas.py verify` e nas referências da boson-atlas | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dados o `gates.md`, a SKILL.md e o template de hoje, então continuam presentes: o roteiro do G6 com o estado "último visto pelo atlas" e o fallback para `smoke_test` e `test_e2e`; a foto no H2, antes do merge, inclusive com `auto-on-green`; o `compare` depois dos passos 1 e 2 do roteiro; o mapeamento passou → PASS, degradou → FAIL com o rollback decidido pela pessoa e inconclusivo → a pessoa decide; a confirmação de produção por execução; a foto temporária apagada no fim; e as quatro chaves `verify`, `window_minutes`, `max_new_errors` e `max_new_restarts` do template. Sem `verify`, nenhuma instrução nova é exigida (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — O `sdd-config.template.yml` tem, em `delivery_check`, `functional: false`, `max_new_dlq: 0`, `max_queue_age: 10m`, `max_signal_increase: 0.5`, `max_resources: 20` e `track_max_minutes: 30`, cada uma com comentário, e o comentário de `delivery_check` cita `functional` e o `verify track`. As quatro chaves da SPEC-0091 continuam.
- **UT-02** — O G6 do `gates.md` descreve:
  - o `verify track` com `--service`, `--env`, `--commit` (o sha completo do merge) e `--json`, como os passos 1 e 2 do roteiro, e o `expected_image` da saída `track@1` indo para o `--expect-image` quando o `state` é `ok` (exit 0);
  - `running` ou `pending` (exit 6) repetidos a cada `window_minutes` até `track_max_minutes`, e o roteiro manual depois disso, com o `current_stage`;
  - `failed` (exit 1) como G6 FAIL, com a etapa e a pessoa decidindo;
  - o roteiro manual quando o `track` não está disponível (`not_verified` com exit 5, exits 2, 3 ou 4, ou sem o subcomando).
- **UT-03** — O G6 do `gates.md` descreve:
  - o escopo padrão do `verify@2`, sem `--resource`, com o mesmo `--max-resources` no `snapshot` e no `compare`;
  - `--resource` só quando as dependências do serviço no pacote do `context` passam de `max_resources`, e então só para os recursos que o diff aponta, a mesma lista nos dois comandos;
  - `--expect-migration <datastore>=<id>` para cada migration nova do diff, sempre com o datastore;
  - sem nenhum adaptador de recurso declarado, o escopo vazio e o `verify` como o `verify@1` e "dependências: sem adaptador de recurso nesta máquina" no Relatório, sem tratar como inconclusivo; com adaptador declarado e um recurso sem acesso local ou sem adaptador, o recurso `not_verified` e o veredito `inconclusivo`, registrado como tal (a pessoa decide) com a sugestão de `access setup` ou de declarar o adaptador;
  - as candidatas só `queue`, `topic` e `datastore` (sem `bucket`);
  - as opções `--max-new-dlq`, `--max-queue-age` e `--max-signal-increase` vindas das chaves de `delivery_check`.
- **UT-04** — O G6 do `gates.md` diz que `--functional` só vai com `delivery_check.functional: true` e só em ambiente `tier: test` (pelo `tier` do deployment no pacote do `context`); que em produção, ou sem `tier`, nunca vai, nem com `--confirm-production`; e que o resultado das jornadas entra no Relatório de Entrega.
- **UT-05** — O G6 do `gates.md` descreve:
  - a confirmação de produção para cada execução de `snapshot`, `track` e `compare`, inclusive para cada repetição do `track`, sem um "sim" cobrir a repetição seguinte, e a verificação só passiva;
  - a linha do Relatório de Entrega com o veredito, a origem da imagem (`track` ou roteiro), as etapas, as verificações e "dependências: N verificadas, M não verificadas";
  - a dependência `not_verified` por falta de acesso ou adaptador registrada com a sugestão de `access setup` ou de declarar o adaptador, sem bloquear o G6.
- **UT-06** — O passo 7 da SKILL.md cita `verify track`, as dependências e `delivery_check.functional` numa só oração, junto da frase de `delivery_check.verify`, e aponta para `references/gates.md` (G6). As regras detalhadas não são repetidas na SKILL.md.

### 7.3 Testes de Integração
- **IT-01** — Dados o `gates.md`, o template e a SKILL.md da skill e o `atlas.py` da boson-atlas do mesmo repositório, quando o teste lê a subseção do G6 e roda `atlas.py verify snapshot --help`, `verify compare --help` e `verify track --help` como processos, então o G6 descreve o `verify@2` (as opções de dependências e sinais que cita existem no `--help` real), a validação funcional (`--functional` só com `delivery_check.functional: true` e só em ambiente `tier: test`, nunca em produção, nem com `--confirm-production`) e a confirmação de produção a cada execução de `snapshot`, `track` e `compare`. É o critério do épico para esta spec.
- **IT-02** — Dado um projeto temporário com `tools/sdd` na versão anterior e um `sdd-config.yml` com o `delivery_check` da SPEC-0091, quando o `spec_graph.py whats-new` da skill roda como processo, então mostra a seção datada da versão nova com o G6 do `verify@2`, o `verify track` e a validação funcional, e o comentário de `delivery_check` com as chaves novas.

### 7.4 Testes de Contrato
- **CT-01** — Toda opção de `atlas.py verify snapshot`, `verify track` e `verify compare` citada no G6 do `gates.md` existe no `--help` real do `atlas.py` da boson-atlas. Os exits citados (0, 1, 2, 3, 4, 5 e 6), o contrato `track@1`, as chaves `state`, `current_stage` e `expected_image`, os status (`pending`, `running`, `ok`, `failed`, `not_verified`) e as etapas (`pipeline`, `image`, `gitops`, `rollout`) são os de `skills/boson-atlas/references/verify.md`.

### 7.5 Testes E2E
- N/A — sem jornada interativa própria; a skill só orquestra comandos testados de ponta a ponta nas SPEC-0102, SPEC-0103 e SPEC-0106.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** os arquivos da skill, o `atlas.py` da boson-atlas do mesmo repositório (só o `--help`) e um projeto temporário para o `whats-new`.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/gluon-spec/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. Tudo segue atrás de `delivery_check.verify: true`, e a funcional atrás de `delivery_check.functional: true` (padrão `false`).
- **Dados/schema:** chaves opcionais novas no `sdd-config.yml`; sem elas valem os padrões.
- **Compatibilidade:**
  - um projeto sem as chaves fica como na SPEC-0091, mais o `track` quando disponível (CH-01);
  - com uma boson-atlas sem `verify track` ou sem as opções do `verify@2`, o G6 cai no roteiro manual ou recebe exit 2 do `compare`, corrige os argumentos uma vez e registra "não executada" se repetir, como já está na SPEC-0091.
- **Observabilidade:** a linha do Relatório de Entrega com as etapas, o veredito e a contagem de dependências verificadas e não verificadas, a métrica de sucesso do épico.
- **Rollback:** voltar a versão do plugin; as chaves novas ficam sem efeito.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Precisa subir o `SDD_TOOL_VERSION`? — Sim, para a próxima versão, só o número, com a seção datada no CHANGELOG: sem isso o `whats-new` não mostra as chaves novas a quem já tem `delivery_check` (o mesmo motivo da Emenda v3 da SPEC-0091) (Architect, 2026-11-24, recomendado)
- [x] Como o G6 escolhe as dependências? — Pelo escopo padrão do `verify@2` (os recursos ligados ao serviço no ambiente), sem `--resource`. Só acima de `max_resources` restringe com `--resource` aos recursos que o diff aponta, para manter o comportamento do `verify@1` numa máquina sem adaptador de recurso (decisão do Architect, 2026-11-24; ADR-0026, regra 2)
- [x] `--functional` vai para todos os ambientes? — Não: só para os `tier: test`, porque fora deles a verificação ficaria `not_verified` e o veredito de produção, sempre `inconclusivo` (Architect, 2026-11-24, recomendado)
- [x] Quanto tempo acompanhar a entrega? — `track_max_minutes` (padrão 30), repetindo a cada `window_minutes`; depois, o roteiro manual. O padrão é do Architect e o projeto ajusta (Architect, 2026-11-24, recomendado)
- [x] Os nomes do `verify track` são os da SPEC-0106? — Sim: `track@1`, `state`, `current_stage`, `expected_image`, as etapas e os exits 0, 1, 5 e 6. O CT-01 confere contra o `--help` e o `verify.md` reais; se a SPEC-0106 mudar um nome, o teste falha e a mudança vira emenda (Architect, 2026-11-24, recomendado)
- [x] Em produção, um "sim" cobre as repetições do `track`? — Não: cada repetição é uma consulta nova e pede um "sim" novo, porque o ADR-0023 liga a confirmação àquela consulta. É o mais seguro; o custo é perguntar de novo a cada janela (Architect, 2026-11-24, recomendado)
- [x] E quando a máquina não tem adaptador nem acesso a recursos? — Sem adaptador de recurso declarado, o escopo padrão fica vazio e o `verify` fica como o `verify@1` e não é inconclusivo. Com adaptador declarado e um recurso sem acesso local, o recurso fica `not_verified` e o veredito `inconclusivo`; o G6 registra assim, a pessoa decide e a sugestão é `access setup` (SPEC-0102 §6.1, ADR-0026, regra 2) (Architect, 2026-11-24, recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 0: Caracterização**
- [ ] CH-01 escrito(s) com a tag `SPEC-0105:<ID>`, passando no código atual, commitado(s) antes de qualquer mudança

**Fase 1: Contrato e implementação**
- [ ] Red: UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01, IT-02, CT-01 com a tag `SPEC-0105:<ID>`, falhando pelo motivo certo
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0105`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
