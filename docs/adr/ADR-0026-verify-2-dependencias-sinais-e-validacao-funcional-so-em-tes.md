---
id: ADR-0026
title: "verify@2: dependências, sinais e validação funcional só em teste"
status: accepted
origin: decision
date: 2026-11-24
pillars: []
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: testes da SPEC-0102 (verify@2 sem escrita no atlas, verify@1 aceito, não verificado com motivo) e da SPEC-0103 (funcional só em tier test)
---

# ADR-0026 — verify@2: dependências, sinais e validação funcional só em teste

## Contexto e Problema
O `verify@1` (ADR-0024) olha a entrega, o runtime e os logs do workload. Com as probes de recursos (ADR-0025), dá para comparar também as dependências do serviço e os sinais delas, além de rodar a jornada principal no ambiente de teste. Três perguntas ficam abertas:
- como encaixar isso na foto e na comparação sem quebrar as fotos e os consumidores atuais;
- como escolher quais dependências olhar;
- como rodar validação funcional sem nunca tocar produção e sem ler comando do atlas.

## Direcionadores da Decisão
- **Comparar contra a foto de antes,** nunca contra um valor absoluto: as filas e os bancos são compartilhados.
- **Escopo pelo grafo:** só as dependências ligadas ao serviço no ambiente, ou as pedidas na chamada.
- **Veredito explícito:** "não verificado" com motivo, nunca `passou` sem prova.
- **Produção só passiva** (SPEC-0075): nada funcional fora de `tier: test`.
- **Compatibilidade:** uma foto `verify@1` continua aceita.

## Opções Consideradas
- **`verify@2`:** as verificações `dependencies`, `signals` e `functional` no mesmo `snapshot` e `compare`.
- **Um comando por tipo de dependência** (`verify queue`, `verify db`…), cada um com o seu veredito.
- **Validação funcional fora do `verify`,** só como instrução da gluon-spec.

## Resultado da Decisão
**Opção escolhida:** "`verify@2`". Mantém um veredito único e uma foto por tarefa, e a gluon-spec continua chamando dois comandos. Um comando por tipo espalharia o veredito. A validação funcional só como instrução não seria repetível, mas a execução dela fica atrás de um adaptador, como as probes.

Regras:
1. **Foto.**
   - O `snapshot` grava `contract: verify@2` com tudo o que o `verify@1` já gravava, mais `dependencies`, um mapa `kind:id → estado` por recurso.
   - O estado de cada recurso é só contagem, conjunto de nomes ou agregado numérico, nunca dado de linha nem mensagem:
     - fila: profundidade, em voo, idade da mais antiga e profundidade da DLQ;
     - tópico: o conjunto de assinaturas (destino e a impressão digital do filtro);
     - banco: as migrations aplicadas e os nomes das tabelas;
     - sinais: os agregados por métrica na janela;
     - permissão: `allowed` ou `denied` por ação.
2. **Escopo.**
   - Por padrão entram todos os recursos ligados ao deployment pelas regras do ADR-0025, até `--max-resources` (padrão 20; acima disso, os excedentes ficam "não verificado" com o motivo).
   - `--resource <kind:id>`, que pode ser repetido, restringe a lista.
   - A DLQ ligada só pelo atributo `dlq` de uma fila fica fora do escopo padrão. Ela entra quando é pedida com `--resource`, e a profundidade dela já vem no item da fila (`dlq_visible`).
   - Quem não declarou nenhum adaptador de recurso nesta máquina e não passou `--resource` fica como no `verify@1`: os checks `dependencies` e `signals` não aparecem e o veredito não muda.
   - Cada recurso usa a capacidade que o kind dele tem num adaptador declarado. Recurso sem adaptador ou sem acesso local fica "não verificado", com o motivo.
3. **Comparação.**
   - **`dependencies`** dá `failed` quando, contra a foto:
     - a DLQ ganhou mais mensagens que `--max-new-dlq` (padrão 0);
     - a idade da mais antiga passou de `--max-queue-age` (padrão 10m);
     - uma assinatura sumiu ou mudou de filtro;
     - uma migration esperada (`--expect-migration`) não está aplicada;
     - uma tabela sumiu;
     - uma permissão que a relação exige estava `allowed` na foto e ficou `denied`. Se já estava negada antes do deploy, a verificação fica "não verificado", com a ação na evidência. A relação diz a ação: `publishes` → publicar num tópico ou enviar numa fila, `consumes` → receber e apagar, `depends_on` de fila → enviar.
   - **`signals`** dá `failed` quando uma métrica de erro ou de latência piora acima de `--max-signal-increase` (padrão 0.5, ou seja 50%) contra a foto.
   - Cada verificação traz `resource` (o `kind:id`) além de `deployment`.
4. **Funcional.**
   - A capacidade `functional` só roda em ambiente `tier: test`. Em qualquer outro, mesmo com `--confirm-production`, sai com 4 e fica "não verificado" no `compare`.
   - O atlas guarda só as jornadas curadas por serviço (atributo `journeys`, lista de ids confirmados pela curadoria, ADR-0012).
   - O adaptador declarado nesta máquina recebe os ids e o ambiente, e roda a suíte pelo comando da configuração local, nunca por texto do atlas.
   - A conta de teste vai só por referência.
4a. **Itens que o `verify@2` lê.** É o contrato entre os adaptadores e o `verify`. Cada adaptador o cumpre e tem um teste de contrato contra ele.

   | Capacidade e verbo | Alvo | Campos de cada item |
   |---|---|---|
   | `messaging queue` | fila | exatamente 1 item: `visible`, `in_flight`, `oldest_age_seconds` (pode ser `null`), `dlq_visible` (`null` sem DLQ) |
   | `messaging subscriptions` | tópico | um item por assinatura: `destination` (`kind:id` do grafo ou o destino mascarado), `filter_fingerprint` (`null` sem filtro) |
   | `database migrations` | banco PostgreSQL | `id`, `success` (`false` = falhou ou ficou pela metade, e não conta como aplicada) |
   | `database tables` | banco PostgreSQL | `name` (`schema.tabela`) |
   | `signals metrics` | banco, cache, fila, tópico | `name`, `stat` (`sum`, `count`, `avg`, `min`, `max` ou `p<n>`), `value` (pode ser `null`), `kind` (`error`, `latency`, `saturation` ou `traffic`) |
   | `permissions simulate` | fila, tópico | `action` (`publish`, `send`, `receive`, `delete`, `read` ou `write`), `api_action` (o nome da API, só como evidência), `decision` (`allowed` ou `denied`; um *deny* implícito conta como `denied`) |

   Dois limites de escopo:
   - O aspecto `database` só vale para banco PostgreSQL (`engine` `postgres` ou `aurora-postgresql`). Os outros datastores, como os caches, ficam só com `signals`.
   - `bucket` fica fora do escopo nesta versão.
5. **Compatibilidade.**
   - O `compare` aceita uma foto `verify@1`: as verificações novas ficam "não verificado" com o motivo "foto sem dependências".
   - Quem lê o resultado e conhece só `verify@1` continua achando `verdict`, `checks` e `suggestion`.
   - O exit e as regras de veredito do ADR-0024 não mudam.
6. **Nada no atlas** e nenhuma ação no ambiente: valem as regras do ADR-0024.

### Consequências
- **Boa:** o G6 passa a provar as dependências que o PR toca, com o mesmo veredito.
- **Boa:** a jornada em teste vira evidência no Relatório de Entrega, sem risco para produção.
- **Ruim:** a foto fica maior e a verificação mais lenta, o que pede o limite de recursos e as consultas em lote.
- **Ruim:** os limites padrão podem gerar falso `degradou` em filas muito movimentadas; são configuráveis por projeto (SPEC-0105).

### Confirmação (G3)
Os testes da SPEC-0102 falham:
- se o `verify@2` gravar no atlas;
- se um recurso sem adaptador ou sem acesso virar `ok`;
- se uma foto `verify@1` for recusada.

Os testes da SPEC-0103 falham se a capacidade `functional` rodar em ambiente que não seja `tier: test`.

## Prós e Contras das Opções
| Critério (peso) | verify@2 | Um comando por tipo | Funcional só instrução |
|---|---|---|---|
| Veredito único (alto) | sim | não | parcial |
| Repetível e testável (alto) | sim | sim | não |
| Compatível com verify@1 (médio) | sim | sim | sim |
| Esforço (baixo) | médio | médio | baixo |

## Mais Informações
- ADR-0024, ADR-0025, SPEC-0090 e SPEC-0075 (ordem revista: dependências só as que o diff ou o grafo indicam; funcional só em teste).
