---
id: SPEC-0090
title: "boson-atlas: verify — foto antes do merge, comparação depois do deploy e veredito"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-22
parent: SPEC-0075
depends_on: [SPEC-0088, SPEC-0089]
consumes_contract: []
contract_version: 5
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/references/verify.md, skills/boson-atlas/references/probes.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/tests/**, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0023, ADR-0024]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-23
---

# SPEC-0090 — boson-atlas: verify — foto antes do merge, comparação depois do deploy e veredito

> Origem: épico SPEC-0075. É a verificação ativa que thomas pediu em 2026-11-20: depois do PR, acompanhar o deploy e os logs no ambiente para saber se a entrega está funcionando.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Comando `atlas.py verify`, em duas fases, sobre as probes de runtime (SPEC-0088 e SPEC-0089):
- **`snapshot`**, antes do merge: grava uma foto do serviço num ambiente, num arquivo da tarefa, fora do atlas;
- **`compare`**, depois do deploy: compara o estado atual com a foto e com a imagem esperada.

O resultado é um veredito, `passou`, `degradou` ou `inconclusivo`, com a evidência de cada verificação.

## 2. Motivação & Escopo
**Motivação:** os testes provam o código, mas não o ambiente. Depois do merge, a pergunta é se a versão nova chegou, se o workload está de pé e se apareceram erros que não existiam. Responder isso à mão é lento, e o resultado muda conforme quem verifica (ADR-0024).

**Objetivos (dentro do escopo):**
- `atlas.py verify snapshot --service <id> --env <ambiente> --out <arquivo>` com o estado, os eventos e as assinaturas de erro dos logs da janela anterior.
- `atlas.py verify compare --service <id> --env <ambiente> --baseline <arquivo> --expect-image <imagem>` com três verificações:
  - **entrega:** a imagem esperada em todos os pods prontos e o rollout concluído;
  - **runtime:** restarts novos, pods não prontos e eventos de alerta novos;
  - **logs:** assinaturas de erro que não estavam na foto.
- Limites por opção: `--window`, `--max-new-errors`, `--max-new-restarts`. Os padrões são conservadores (10 min, 0, 0).
- Veredito e exit:
  - `passou` dá 0, `degradou` dá 1 e `inconclusivo` dá 5;
  - "não verificado" vem com o motivo quando falta acesso, adaptador ou foto;
  - em `degradou`, sai uma sugestão de rollback, sem executar nada.
- Produção segue a regra das probes: `--confirm-production`, só verificações passivas.

**Não-objetivos (fora do escopo):**
- Métricas (taxa de erro, latência), banco, mensageria e smoke: ficam para ondas seguintes, cada uma como mais uma verificação com o seu adaptador.
- Aguardar a CI e o GitOps: o G6 da gluon-spec faz isso pelo roteiro da SPEC-0086 (SPEC-0091).
- Qualquer ação no ambiente, inclusive rollback.

## 3. Dependências
- **Implementações necessárias:**
  - SPEC-0088 (núcleo do probe, resumo de logs, confirmação de produção);
  - SPEC-0089 (verbos `status`, `events` e `logs`), usada pelo IT-01 com o dublê de kubectl.
- **Contratos consumidos:** N/A (vêm com as implementações).
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **probe:** `atlas.py probe` (SPEC-0088), cujas funções internas o `verify` chama, sem um subprocesso por probe;
- **arquivo JSON com contrato:** `snapshots/_scan.json`;
- **exits e mensagens:** os do `atlas.py`;
- **testes:** os de `probe` e o dublê de kubectl da SPEC-0089.

**Decisão:** `verify` é um subcomando do `atlas.py`. Ele reaproveita a resolução do alvo, as recusas, a redaction e o registro do `probe`, e grava a foto só no caminho que recebe. Esse caminho não pode ficar dentro da pasta do atlas (ADR-0024).

**Justificativa:** uma comparação determinística em código é repetível e testável. Na conversa, o mesmo estado poderia dar vereditos diferentes.

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:**
- Só instruções na gluon-spec.
- Análise por métricas já agora: ainda não há adaptador (ADR-0024).

**ADRs:** ADR-0023, ADR-0024 (criado pelo épico SPEC-0075 e por esta spec).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `snapshot` e `compare` fazem 3 probes por deployment do ambiente (`status`, `events`, `logs --summary`) e respeitam o timeout e os limites do núcleo.
- **Segurança:**
  - tudo só de leitura, pelas probes;
  - a foto passa pela redaction e não guarda linhas de log, só assinaturas e amostras mascaradas;
  - `--out` dentro do atlas dá exit 2;
  - nenhuma sugestão vira execução.
- **Privacidade e dados pessoais:** a foto é um arquivo da tarefa; a skill que chama apaga o arquivo no fim (SPEC-0091).
- **Disponibilidade e resiliência:** uma probe que falha ou é recusada marca a verificação dela como "não verificado", com o motivo, e o veredito fica `inconclusivo`. Nunca vira `passou`.
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** subcomandos `verify snapshot` e `verify compare`, o arquivo de foto `verify@1` e o veredito.

```text
atlas.py verify snapshot --service <id> --env <ambiente> --out <arquivo>
    [--since 30m] [--confirm-production] [--atlas X]
  roda, por deployment do serviço no ambiente: probe runtime status, events e logs --summary (janela --since)
  grava <arquivo> (recusa caminho dentro da pasta do atlas → exit 2):
    {"contract": "verify@1", "service": "api", "environment": "dev", "taken_at": "<ISO UTC>",
     "deployments": {"dev-api": {"images": ["acme/api:1.4.1@sha256:…"], "ready": 3, "desired": 3,
                                 "restarts": {"<pod>": 0}, "warnings": ["BackOff|Pod/api-x"],
                                 "error_signatures": {"<assinatura>": 2}},
     "not_verified": [{"deployment": "dev-api", "check": "logs", "reason": "…"}]}
  exits: 0 gravado · 2 argumento inválido · 3 sem configuração · 4 recusado (regras do probe)

atlas.py verify compare --service <id> --env <ambiente> --expect-image <imagem>
    [--baseline <arquivo>] [--window 10m] [--max-new-errors 0] [--max-new-restarts 0]
    [--confirm-production] [--json] [--atlas X]
  <imagem>: caminho normalizado com ":<tag>" e/ou "@<digest>" (ex.: acme/api:1.4.2 ou acme/api@sha256:…)
  verificações por deployment:
    delivery  — ok se rollout_complete e todo pod pronto roda a imagem esperada (digest, se dado; senão tag)
    runtime   — ok se nenhum pod não pronto, soma de restarts novos (contra a foto; sem foto: restarts na janela)
                <= --max-new-restarts e nenhum warning novo (motivo|objeto sem o sufixo do pod, ausente na foto)
    logs      — ok se assinaturas de erro na janela --window ausentes da foto <= --max-new-errors;
                sem --baseline → não verificado ("sem foto de antes: erros novos e antigos não se separam")
  cada verificação: {"deployment", "check", "status": "ok" | "failed" | "not_verified", "evidence": {...},
                     "reason": "…"}
  veredito: degradou se alguma failed; senão inconclusivo se alguma not_verified; senão passou
  saída: Markdown ou --json {"contract": "verify@1", "verdict", "checks", "suggestion"}
  suggestion (só em degradou): texto fixo pedindo à pessoa para decidir o rollback, citando o repositório de
    configuração do delivery (SPEC-0086), nunca um comando
  exits: 0 passou · 1 degradou · 5 inconclusivo · 2 argumento inválido · 3 sem configuração · 4 recusado
  nada é gravado no atlas; cada probe entra no registro local (SPEC-0088)
```

**Esclarecimentos (Emenda v2):**
- **Probes que voltam cortadas ou vazias:**
  - o adaptador Kubernetes (Emenda v5 da SPEC-0089) pula os pods que não respondem e marca `truncated`;
  - quando a probe de `logs` volta com `truncated: true` e nenhum item, a verificação `logs` fica `not_verified`, com o motivo "nenhum pod respondeu", e nunca `ok`;
  - quando a probe de `status` volta com `found: false` para o workload, a verificação `runtime` fica `failed`.
- **Contexto da probe:** o `verify` chama o mesmo caminho do `probe` (mesmas proteções, registro e máscara da SPEC-0088); não roda adaptador por conta própria.

**Esclarecimentos (Emenda v3):**
- **CH-01 em duas partes**, como na SPEC-0088: uma guarda que passa antes (nada muda e o `probe` segue igual) e a recusa com exit 4 quando as probes estão desligadas.
- **Assinaturas de erro:** só as de nível `error` do `--summary`; `warn` e `info` não contam como erro novo.
- **Foto sem amostra:** a foto guarda só assinaturas e contagens, nenhuma linha de log, nem mascarada.
- **Chave dos avisos:** `reason|objeto`, com o nome do pod trocado pelo workload dono (sem o sufixo do pod). O mesmo motivo em outro pod do workload não é novo.
- **Restarts:** contados por pod, agora menos a foto. Um pod que não estava na foto conta desde 0.
- **Probe recusada, com erro ou com falha do adaptador:** a verificação dependente fica `not_verified` (exit 5). O exit 4 do comando todo vale só para probes desligadas e para produção sem confirmação. Em produção sem confirmação, nenhuma consulta roda (o `--describe` pode rodar).
- **`found: false`:** `runtime` fica `failed` e `delivery` não é `ok`.
- **Foto com `logs` em `not_verified`:** o `logs` daquele deployment também não pode dar `ok` na comparação.
- **Argumentos:** dão exit 2 antes de qualquer probe:
  - `--out` dentro do atlas, inclusive por `..`;
  - `--expect-image` sem tag nem digest;
  - `--baseline` ausente, inválido ou com outro contrato.
- **Janelas:** `--window` do `compare` (padrão 10m) e `--since` do `snapshot` (padrão 30m) viram o `since_seconds` da probe de logs.
- **Saída `--json`:**
  - chaves fechadas: `contract`, `verdict`, `checks` e `suggestion` (vazia fora de `degradou`);
  - cada verificação tem `deployment`, `check`, `status`, `evidence` e `reason`, este último obrigatório em `not_verified`;
  - a foto também tem chaves fechadas.
- **Validador:** `validate_verify_snapshot` e `validate_verify_result`, cada um devolvendo `list[str]`. Os exemplos do `references/verify.md` são blocos json com `"contract": "verify@1"`.
- **Sugestão sem comando:** nenhuma linha começa com `$`, e nenhuma cita `kubectl`, `argocd`, `helm` nem `git revert/push/reset/checkout`.

**Esclarecimentos (Emenda v4):**
- **Ordem das checagens:**
  1. configuração (3);
  2. probes desligadas (4);
  3. argumentos (2): `--out` resolvido com `..` e links, pasta pai existente, `--expect-image`, formatos de janela e limite, e `--baseline` de outro serviço ou ambiente;
  4. regras do alvo (2) e produção sem confirmação (4), para todos os alvos antes de qualquer probe.

  Com a produção recusada, nada roda e nada é registrado.
- **Probe recusada ou com falha:** a falha de cada probe marca como `not_verified` as verificações que dependem dela:
  - `status` → `delivery` e `runtime`;
  - `events` → `runtime`, salvo quando o `status` já deixou o `runtime` `failed`;
  - `logs` → `logs`.
- **`delivery` falha quando:**
  - o workload vem com `found: false` ou não vem;
  - o rollout não completou;
  - não há pod pronto;
  - um pod pronto não tem a imagem esperada (mesmo caminho, mais o digest quando há digest, senão a tag).
- **Avisos:** a chave é `reason|Kind/<workload dono>`, pelo mapa de pods do `status`, senão pelo maior prefixo de nome de workload.
- **Sem foto, ou com o `runtime` da foto `not_verified`:** todo restart e todo aviso contam (leitura conservadora).
- **`--max-new-errors`:** conta assinaturas novas distintas.
- **Saída:**
  - a foto é gravada de uma vez, com chaves ordenadas e `taken_at` em UTC;
  - o `--json` sempre traz as quatro chaves, com `suggestion` vazia fora de `degradou`.
- **Probes:** o caminho do `probe` virou `run_probe`, sem mudar o comportamento. O `verify` chega aos adaptadores só por ele.

**Esclarecimentos (Emenda v5):**
- **`--out` fora do atlas por identidade:**
  - a pasta pai e cada pasta acima dela são comparadas com a pasta do atlas pelo arquivo (mesmo `st_dev` e `st_ino`), não pelo texto do caminho;
  - assim nem a caixa diferente (macOS) nem um link para dentro do atlas passam.
- **Arquivo temporário:** a foto é gravada num temporário criado de forma exclusiva na pasta de destino (`mkstemp`), depois renomeado. Nunca segue um link existente.
- **Probes cortadas não dão `ok`:**
  - o `verify` pede as probes com o limite máximo de linhas;
  - se a probe de `status` volta com `truncated`, `delivery` e `runtime` ficam `not_verified` ("probe de status cortada");
  - se a de `events` volta cortada, `runtime` fica `not_verified`, salvo quando já está `failed`;
  - se a de `logs` volta cortada, com ou sem itens, `logs` fica `not_verified` ("probe de logs cortada"), porque um pod pode não ter respondido ou erros antigos da janela podem ter ficado de fora.
- **Imagem esperada:**
  - `--expect-image` passa pela mesma normalização do adaptador: tira o primeiro segmento quando ele tem `.` ou `:` ou é `localhost`, e põe o digest em minúsculas;
  - o `references/verify.md` avisa que o digest só casa quando o manifesto fixa o digest.
- **Baseline de outro serviço ou ambiente:** exit 2 sem rodar probe, agora com teste.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: os subcomandos, as verificações e o veredito.
- `references/verify.md` (nova): as fases, as verificações, os limites, os exits e um exemplo.
- `references/probes.md`: um ponteiro para o `verify`.
- `SKILL.md`: uma linha sobre o comando.
- CHANGELOG, `plugin.json` e testes.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Foto | estado, eventos e logs da janela | arquivo `verify@1` sem linhas de log, com redaction | UT-01 |
| Foto no atlas | `--out` dentro da pasta do atlas | exit 2, nada gravado | UT-01 |
| Entrega ok | imagem esperada em todos os pods prontos | `delivery` ok | UT-02 |
| Entrega falha | pod com a imagem antiga ou rollout incompleto | `delivery` failed com a evidência | UT-02 |
| Runtime | restarts novos, pod não pronto, warning novo | `runtime` failed; o que já estava na foto não conta | UT-03 |
| Logs | assinatura nova, antiga e sem foto | nova conta; antiga não; sem foto, não verificado | UT-04 |
| Veredito | combinações de ok, failed e not_verified | regra do contrato; exits 0, 1 e 5 | UT-05 |
| Nada no atlas e sem ação | qualquer execução | árvore do atlas igual; nenhuma chamada fora de get e logs | UT-06 |
| Ponta a ponta | snapshot → troca do estado do dublê → compare | `passou` num caso, `degradou` no outro | IT-01 |
| Contrato | arquivo de foto e saída JSON | validados contra `verify@1` | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dado o `atlas.py` de hoje com as probes da SPEC-0088, quando os comandos existentes rodam, então nada muda com o subcomando novo, e `verify` sem probes ligadas sai com 4 (guarda: os comandos de hoje passam antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado o dublê de kubectl com 3 pods prontos, 2 eventos Warning e logs com 2 assinaturas de erro, quando `verify snapshot` roda, então o arquivo tem as imagens, réplicas, restarts por pod, warnings e assinaturas com contagem, sem nenhuma linha de log inteira e com redaction. Com `--out` dentro da pasta do atlas, o resultado é exit 2 e nenhum arquivo é criado.
- **UT-02** — Com `--expect-image acme/api@sha256:new`:
  - todos os pods prontos rodando o digest novo e o rollout concluído dão `delivery` ok;
  - um pod com `sha256:old` dá failed, com o pod e a imagem na evidência;
  - `rollout_complete: false` dá failed.

  Com `--expect-image acme/api:1.4.2`, sem digest, a verificação é feita pela tag.
- **UT-03** — Dada uma foto com `restarts: {api-a: 2}` e warning `BackOff|Pod/api`, então:
  - o estado atual com `api-a: 2` e o mesmo warning dá `runtime` ok;
  - `api-a: 3` com `--max-new-restarts 0` dá failed;
  - um warning `FailedMount` novo dá failed;
  - um pod não pronto dá failed.
- **UT-04** — Dada uma foto com a assinatura `ERROR user <n> not found`, então:
  - logs atuais com essa assinatura e uma nova `ERROR timeout calling <s>` dão `logs` failed com `--max-new-errors 0`, e ok com `--max-new-errors 1`;
  - só a antiga dá ok;
  - sem `--baseline`, `logs` fica `not_verified` com o motivo do contrato.
- **UT-05** — Para as combinações de status das três verificações em dois deployments, o veredito segue a regra (`failed` > `not_verified` > `ok`) e os exits são 0, 1 e 5. Uma probe recusada ou com erro vira `not_verified` com o motivo, nunca `ok`. Em `degradou`, a sugestão cita o repositório de configuração e não contém nenhum comando.
- **UT-06** — Em todos os testes do `verify`, a árvore da pasta do atlas tem o mesmo hash antes e depois, e o registro de argv do dublê só tem `get` e `logs`. Em ambiente de produção, sem `--confirm-production`, a saída é exit 4 e nenhuma chamada é feita.

### 7.3 Testes de Integração
- **IT-01** — Num atlas temporário com o mapa de acesso, as probes ligadas, o adaptador `kubernetes` e o dublê de kubectl:
  1. `verify snapshot` roda com o estado "antes" (imagem 1.4.1);
  2. o dublê passa ao estado "depois";
  3. `verify compare --expect-image acme/api:1.4.2` roda.

  Com o estado "depois" saudável, a saída é `passou` (exit 0). Com o estado "depois" com um pod em CrashLoop e uma assinatura de erro nova, a saída é `degradou` (exit 1), com as evidências.

### 7.4 Testes de Contrato
- **CT-01** — Dado um arquivo de foto e uma saída `--json`, quando o validador `verify@1` roda, então as chaves e os tipos do contrato são aceitos e um arquivo com chave desconhecida ou versão diferente é recusado no `compare` (exit 2). `references/verify.md` traz os mesmos exemplos.

### 7.5 Testes E2E
- N/A — sem jornada interativa; IT-01 roda as duas fases como processo, de ponta a ponta, com o dublê.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- Dublê de kubectl da SPEC-0089 com estados "antes" e "depois" por arquivo.
- Atlas e configuração temporários.
- Só nomes `acme`.
- Sem cluster e sem rede.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. Só funciona com as probes ligadas.
- **Dados/schema:** arquivo de foto da tarefa (`verify@1`), fora do atlas.
- **Compatibilidade:** é aditivo.
- **Observabilidade:** o veredito, as evidências e o registro local das probes.
- **Rollback:** reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Os limites padrão? — Janela de 10 min, 0 assinaturas de erro novas e 0 restarts novos. São conservadores; o projeto ajusta no `sdd-config.yml` (SPEC-0091; recomendação do arquiteto, revisável no H1).
- [x] Sem foto de antes, os logs contam? — Não. Ficam `not_verified`, porque sem a linha de base erros antigos virariam falsos "novos" (ADR-0024; recomendação do arquiteto, revisável no H1).
- [x] `verify` aguarda o rollout terminar? — Não, nesta onda. O G6 chama o `compare` depois que o roteiro mostra a imagem nova no repositório de configuração. Se o rollout ainda não terminou, o resultado é `degradou` na entrega, e o G6 pode repetir depois da janela (SPEC-0091; recomendação do arquiteto, revisável no H1).

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
- [ ] Red: CH-01 (passa antes), UT-01 a UT-06, IT-01 e CT-01 com a tag `SPEC-0090:<ID>`, falhando pelo motivo certo; adaptadores falsos de probe (sem `kubectl` de verdade)
- [ ] Green: `verify snapshot` e `verify compare` no `atlas.py` (`verify@1`, foto fora do atlas, verificações delivery, runtime e logs, veredito e exits), `references/verify.md`, `references/probes.md`, `SKILL.md`, `ATLAS_VERSION`, CHANGELOG da boson-atlas e `version` do `plugin.json`
- [ ] Validar: suíte completa + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 9846c60 | 2026-11-22 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=52, skipped=1)) — 97b43c2 | 2026-11-23 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — e83e347 | 2026-11-23 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 9999d02 | 2026-11-23 |
| G4 Review | FAIL | reviewer independente (subagente, rodada 1): REJECTED — major: --out aceito dentro do atlas com outra caixa no macOS; status cortado ainda dá passou; minors: logs e eventos cortados, --expect-image sem normalização, baseline de outro serviço sem teste; nit: arquivo temporário seguindo link | 2026-11-23 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-23 — reviewer independente (subagente, rodada 1): REJECTED — major: --out aceito dentro do atlas com outra caixa no macOS; status cortado ainda dá passou; minors: logs e eventos cortados, --expect-image sem normalização, baseline de outro serviço sem teste; nit: arquivo temporário seguindo link — afa1d4d

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0090`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-23 | Esclarecimentos (Emenda v2): logs cortados e sem item são `not_verified`; workload não encontrado é `failed`; o `verify` usa o caminho do `probe` | Achados do G4 da SPEC-0089 e planejamento | — | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 3 | 2026-11-23 | Esclarecimentos (Emenda v3): CH-01 em duas partes; só assinaturas `error`; foto sem amostra; chave dos avisos; restarts por pod; recusas viram `not_verified`; argumentos e janelas; chaves fechadas; validadores; sugestão sem comando | Perguntas do test-writer no G1 | SPEC-0091 | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 4 | 2026-11-23 | Esclarecimentos (Emenda v4): ordem das checagens; dependências das probes; quando `delivery` falha; chave dos avisos; leitura sem foto; contagem de erros; formato da saída; `run_probe` | Relatório do implementer no G2 | SPEC-0091 | thomas, 2026-11-23 (piloto automático com o recomendado) |
| 5 | 2026-11-23 | Esclarecimentos (Emenda v5): `--out` comparado por identidade; temporário exclusivo; probes cortadas viram `not_verified`; `--expect-image` normalizada; teste da baseline de outro serviço | Achados da rodada 1 do G4 | SPEC-0091 | thomas, 2026-11-23 (piloto automático com o recomendado) |
