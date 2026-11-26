---
id: SPEC-0095
title: "boson-atlas: verificação completa depois do deploy — dependências, sinais e funcional"
tier: epic
type: feature
status: implemented
created: 2026-11-24
depends_on: [SPEC-0075]
adrs: [ADR-0010, ADR-0011, ADR-0012, ADR-0023, ADR-0024, ADR-0025, ADR-0026]
external: []
approved_by: thomas
approved_at: 2026-11-24
---

# SPEC-0095 — boson-atlas: verificação completa depois do deploy — dependências, sinais e funcional (Épico)

> **Origem (thomas, 2026-11-24):** "vamos criar tudo que precisamos pra fechar essa funcionalidade". Continua o épico SPEC-0075, que entregou o mapa de acesso, o núcleo do probe, o adaptador Kubernetes, o `verify` e o G6 ativo. Ficaram para as ondas seguintes:
> - logs e métricas externos;
> - banco e mensageria;
> - simulação de IAM;
> - smoke e E2E em teste;
> - onboarding e métricas de uso;
> - coletores automáticos.
>
> O contexto da rotina real de verificação está no radar da SPEC-0075: os passos 1 a 6, a ordem revista e as garantias transversais. Este épico segue esse contexto.
>
> **O que a verificação cobre (thomas, 2026-11-24):** "de tudo que o atlas mapeou". O atlas real usado como referência mapeia:
> - bancos PostgreSQL gerenciados;
> - caches compatíveis com Redis (Valkey) gerenciados;
> - filas e tópicos, com assinaturas tópico → fila;
> - deployments num cluster Kubernetes, entregues pelo GitOps.
>
> As ferramentas citadas aqui (AWS CLI, `psql`) são as do primeiro uso real. Cada uma é um adaptador trocável pelo contrato, e o desenho fica agnóstico.
>
> **Acompanhar a pipe (thomas, 2026-11-24):** "o atlas tem que saber tudo da infra e, se tiver acesso, saber avaliar como uma funcionalidade ou correção está subindo, e auxiliar a gluon-spec quando um PR disparar uma pipe". Vira a SPEC-0106.
>
> **Ações de escrita** (rollback, restart, reprocessar DLQ): seguem no radar da SPEC-0075, fora deste épico (recomendação do Architect seguida no piloto automático, thomas, 2026-11-24).

## 1. Visão
Depois do merge, o agente prova, só lendo, que a entrega está saudável **e que as dependências dela também estão**:
- a migration aplicada no banco;
- a fila sem acúmulo e a DLQ sem mensagens novas;
- as assinaturas do tópico com os filtros;
- o workload com permissão no recurso;
- os sinais das dependências (erros, latência, saturação) dentro da linha de base;
- a jornada principal passando no ambiente de teste.

Tudo parte do que o atlas já mapeou e chega por adaptadores declarados nesta máquina, com as mesmas proteções das probes. O resultado é um veredito único no G6, com a evidência de cada verificação. Quando falta campo, acesso ou adaptador, a verificação aparece como "não verificado", com o motivo.

A pessoa configura o acesso por um onboarding em linguagem simples. As métricas de uso mostram o que ainda falta mapear.

## 2. Escopo
**Objetivos (dentro do escopo):**
- **Probes em recursos do grafo** (SPEC-0096, ADR-0025):
  - `probe --resource <kind:id>` mira um banco, cache, fila ou tópico ligado ao serviço no ambiente;
  - o acesso fica nesta máquina e nunca é impresso: o profile da nuvem por ambiente, e o usuário e o arquivo de senhas do banco, por referência;
  - o contrato passa a `probe@2`, compatível com os adaptadores `probe@1`.
- **Coletor `aws` oficial** (SPEC-0097): só metadados e só leitura. Traz bancos, caches, filas com a DLQ, tópicos e as assinaturas tópico → fila, no contrato `@1` dos coletores.
- **Adaptadores só de leitura:**
  - mensageria AWS (SPEC-0098): profundidade, idade da mensagem mais antiga, DLQ e assinaturas com filtros;
  - PostgreSQL (SPEC-0099): migrations aplicadas e tabelas;
  - CloudWatch (SPEC-0100): sinais das dependências na janela;
  - simulação de IAM (SPEC-0101): permissão do workload no recurso, levando a política do recurso.
- **`verify@2`** (SPEC-0102, ADR-0026): a foto e a comparação ganham `dependencies` e `signals`. Só entram as dependências que o grafo liga ao serviço, ou as indicadas na chamada.
- **Validação funcional só em teste** (SPEC-0103, ADR-0026): jornadas e suítes curadas por serviço no atlas, executadas só em ambiente `tier: test`.
- **Onboarding do acesso e métricas de uso** (SPEC-0104):
  - perguntas simples que viram a configuração local;
  - contagens do `probes.log` que sugerem o que falta mapear, sempre como proposta.
- **Acompanhar a entrega de um commit** (SPEC-0106): quando o PR dispara a pipeline, o atlas segue o caminho do `delivery` (SPEC-0086). A sequência é: run da CI do commit → imagem → Application do GitOps → rollout. Cada etapa sai com o estado e a evidência, e o `verify track` diz se a entrega ainda está a caminho, chegou ou falhou. Tudo só de leitura, sem re-rodar nem sincronizar nada.
- **G6 da gluon-spec com `verify@2` e o acompanhamento da entrega** (SPEC-0105).

**Não-objetivos (fora do escopo):**
- **Ações de escrita** (rollback, restart, redrive, escala, flags): seguem no radar da SPEC-0075.
- **Traces e métricas de aplicação** (Prometheus, APM): o atlas não mapeia essas fontes. As métricas do serviço continuam vindo de restarts e logs (SPEC-0090).
- **Logs de aplicação fora do cluster** (Loki, CloudWatch Logs de função): o atlas de referência roda as aplicações no Kubernetes, e o adaptador de lá já lê esses logs. Uma fonte nova entra como adaptador da capacidade `logs`.
- **Contas de nuvem, fornecedores e ciclo de vida no modelo:** SPEC-0084.
- **Coletor de infraestrutura como código:** SPEC-0083.
- **DORA e registro no board:** ficam para depois.

## 3. Arquitetura Alvo
**Contexto:** projeto existente. O épico estende a arquitetura da SPEC-0075 sem trocá-la, então não é `type: migration`. Ela tem três partes:
- o atlas guarda o mapa;
- o `atlas.py probe` roda adaptadores externos por um contrato JSON, com verbos permitidos, confirmação de produção e redaction (ADR-0023);
- o `atlas.py verify` compara uma foto com o estado depois do deploy (ADR-0024).

As extensões ficam registradas em dois ADRs:
- **ADR-0025:** os alvos novos e o `probe@2`;
- **ADR-0026:** o `verify@2` e a validação funcional.

```
 atlas (mapa)                          máquina (acesso)                 adaptadores (como)
 ───────────                          ────────────────                 ──────────────────
 graph.json: service ─depends_on/      access.clusters  (SPEC-0087)    kubernetes    probe@1 (runtime)
   publishes/consumes→ datastore,      access.cloud.<amb>.profile      aws-messaging probe@2 (messaging)
   queue, topic; topic ─publishes→     access.databases.<id>           postgres      probe@2 (database)
   queue; deployment ─runs_in→ amb.    probes.adapters.<id>            cloudwatch    probe@2 (signals)
 service.attrs.journeys (curadas)                                       iam           probe@2 (permissions)
        │                                     │                               ▲
        └──────────► atlas.py probe --resource kind:id ───────────────────────┘
                              │
                     atlas.py verify snapshot|compare  (verify@2: delivery, runtime, logs,
                              │                          dependencies, signals, functional)
                     gluon-spec G6 (SPEC-0105) ──► Relatório de Entrega
```

**Decisões (ADRs):**
- **ADR-0025:**
  - o alvo de uma probe pode ser um recurso do grafo ligado ao deployment do serviço no ambiente;
  - o acesso local à nuvem e ao banco é só por referência e nunca é impresso;
  - o contrato passa a `probe@2`, e o `probe@1` segue aceito para alvo de deployment.
- **ADR-0026:**
  - o `verify@2` acrescenta `dependencies` e `signals` à foto e à comparação, e continua lendo fotos `verify@1`;
  - a validação funcional roda só em `tier: test`, a partir de jornadas curadas (ADR-0012), nunca de um comando lido do atlas.
- **Seguem valendo:**
  - ADR-0010: credencial só por nome;
  - ADR-0011: contrato `@1` dos coletores, com atributos novos como listas de escalares;
  - ADR-0012: curadoria;
  - ADR-0023: probes;
  - ADR-0024: verify.

**Regras de arquitetura a garantir (G3):** os testes de arquitetura da boson-atlas continuam valendo e ganham estas regras.
- **Alvo:** nenhum adaptador recebe um recurso que o grafo não liga ao deployment do serviço no ambiente (SPEC-0096).
- **Acesso que não aparece:** o profile da nuvem, o usuário do banco e o caminho do arquivo de senhas nunca saem em `config`, `context`, `doctor`, `probe`, `verify` nem no `probes.log` (SPEC-0096).
- **Só leitura:**
  - cada adaptador novo declara só verbos de leitura e monta a chamada como lista de argumentos, sem shell (SPEC-0098 a 0101, SPEC-0103 e SPEC-0106);
  - o adaptador de banco abre a sessão só de leitura e só roda as consultas fixas dele (SPEC-0099).
- **Atlas intocado:** o `verify@2` nunca grava no atlas (SPEC-0102).
- **Nada funcional em produção:** a validação funcional recusa ambiente que não seja `tier: test`, mesmo com `--confirm-production` (SPEC-0103).

## 4. Decomposição
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0096 | probe@2 — recursos do grafo como alvo e acesso local à nuvem e ao banco | full | feature | M | — | — |
| SPEC-0097 | coletor aws oficial — bancos, caches, filas, tópicos e assinaturas | full | feature | M | — | — |
| SPEC-0098 | adaptador de mensageria aws — filas, DLQ e assinaturas | full | feature | M | SPEC-0096 | — |
| SPEC-0099 | adaptador postgres só de leitura — migrations e tabelas | full | feature | M | SPEC-0096 | — |
| SPEC-0100 | adaptador cloudwatch — sinais das dependências | full | feature | M | SPEC-0096 | — |
| SPEC-0101 | adaptador de simulação de IAM — permissão do workload no recurso | full | feature | M | SPEC-0096 | — |
| SPEC-0102 | verify@2 — dependências e sinais na foto e na comparação | full | feature | M | SPEC-0096 | — |
| SPEC-0103 | validação funcional em teste — jornadas e suítes curadas | full | feature | M | SPEC-0102, SPEC-0104 | — |
| SPEC-0104 | onboarding do acesso e métricas de uso das probes | full | feature | M | SPEC-0096 | — |
| SPEC-0106 | acompanhar a entrega de um commit — pipeline, imagem, GitOps e rollout | full | feature | M | SPEC-0096 | — |
| SPEC-0105 | gluon-spec: G6 com verify@2, acompanhamento da entrega e validação funcional | full | feature | S | SPEC-0102, SPEC-0103, SPEC-0106 | — |

Os adaptadores dependem do núcleo implementado, porque o IT deles roda o `atlas.py` real com o `probe@2`. Todas as filhas da boson-atlas tocam o CHANGELOG, o `SKILL.md` e o `plugin.json`, então a ordem real de execução sai do `waves`, pelos `touches`.

## 5. Estratégia de Entrega
- **Ambientes:** as skills chegam pelo plugin `fermion`, sem deploy, mesmo critério da SPEC-0017. Cada filha sobe a versão do plugin (SPEC-0056).
- **Entrega por onda:**
  1. SPEC-0096 e SPEC-0097;
  2. os adaptadores, um PR para cada;
  3. SPEC-0102, SPEC-0104 e SPEC-0106;
  4. SPEC-0103;
  5. SPEC-0105.

  Cada onda já serve sozinha: um adaptador funciona no `probe` antes do `verify@2` existir.
- **Feature flags:**
  - `probes.enabled` (desligada por padrão) e `delivery_check.verify` continuam controlando tudo;
  - um adaptador novo só roda depois de declarado em `probes.adapters`, com os verbos liberados;
  - a validação funcional ganha a chave própria `delivery_check.functional`, desligada por padrão (SPEC-0105).
- **Rollback:** voltar a versão do plugin. A configuração local nova é opcional: sem ela tudo fica como na SPEC-0075, e as verificações novas aparecem como "não verificado", com o motivo.
- **Métricas de sucesso pós-release:**
  - nas verificações reais do G6, quantas dependências foram verificadas contra quantas ficaram sem verificar;
  - as recusas por falta de acesso ou de adaptador, contadas pelo `probes stats` (SPEC-0104).

## 6. Riscos & Mitigações
- **Credencial com escrita usada por engano:**
  - o adaptador de banco abre a sessão com `default_transaction_read_only` e só roda consultas fixas;
  - os outros só chamam APIs de leitura (`get`, `list`, `describe`, `simulate`), numa lista fechada e testada;
  - o onboarding e o `doctor` recomendam um papel só de leitura.
- **Vazamento de ids de conta e hosts:**
  - ARNs, URLs de fila e hosts de banco passam pela redaction das probes;
  - os ids de conta saem mascarados;
  - o profile e o caminho do arquivo de senhas entram na máscara literal (ADR-0025).
- **Custo e limite das APIs de métricas:** janela limitada, número máximo de recursos por `verify` e consultas em lote (SPEC-0100, SPEC-0102).
- **Falso negativo da simulação de IAM sem a política do recurso:** o adaptador sempre inclui a política do recurso quando ela existe. Quando não consegue lê-la, a verificação fica "não verificado" (SPEC-0101).
- **Recurso compartilhado entre serviços:** a fila pode receber mensagens de outros serviços. Por isso a comparação é contra a foto de antes, com limites configuráveis, e nunca contra um valor absoluto (ADR-0026).
- **Login expirado (SSO):** o adaptador devolve erro com o texto fixo "renove o login da nuvem", e a verificação fica "não verificado". A skill nunca faz o login.

## 7. Critérios de Aceite do Épico
- [x] Uma probe de recurso só roda para um recurso ligado ao serviço no ambiente, usando o acesso local, e nunca imprime o profile, o usuário nem o caminho do arquivo de senhas — SPEC-0096:IT-01
- [x] O coletor `aws` gera, a partir de respostas gravadas da AWS CLI, um snapshot `@1` válido com bancos, caches, filas com DLQ, tópicos e assinaturas tópico → fila — SPEC-0097:IT-01
- [x] O adaptador de mensageria responde o contrato `probe@2` só com verbos de leitura, contra uma AWS CLI falsa que registra as chamadas — SPEC-0098:IT-01
- [x] O adaptador PostgreSQL lê migrations e tabelas numa sessão só de leitura — SPEC-0099:IT-01
- [x] O adaptador CloudWatch traz os sinais de um recurso na janela pedida — SPEC-0100:IT-01
- [x] O adaptador de IAM simula a permissão do workload levando a política do recurso — SPEC-0101:IT-01
- [x] O `verify compare` dá `degradou` quando a DLQ de uma fila ligada ao serviço ganha mensagens depois do deploy, e `passou` quando as dependências seguem a foto — SPEC-0102:IT-01
- [x] A validação funcional roda a jornada curada só em `tier: test` e recusa produção — SPEC-0103:IT-01
- [x] O onboarding grava o acesso local a partir das respostas, e o `doctor` sugere o que falta mapear a partir das recusas do `probes.log` — SPEC-0104:IT-01
- [x] O `verify track` segue um commit da pipeline até o rollout e diz em que etapa a entrega está, só lendo — SPEC-0106:IT-01
- [x] O G6 da gluon-spec descreve o `verify@2` e a validação funcional, com a confirmação de produção e a validação funcional só em teste — SPEC-0105:IT-01

## 8. Questões em Aberto
- [x] Quais fontes a verificação deve ler? — "de tudo que o atlas mapeou": bancos PostgreSQL, caches Valkey, filas e tópicos com assinaturas, além do cluster que já existe (thomas, 2026-11-24)
- [x] As ações de escrita entram? — Não. Ficam no radar da SPEC-0075 (recomendação seguida no piloto automático, thomas, 2026-11-24)
- [x] Logs fora do cluster (Loki, CloudWatch Logs) entram? — Não nesta onda. O atlas de referência não mapeia essas fontes, e os logs das aplicações já vêm do Kubernetes. Entram como adaptador da capacidade `logs` quando forem mapeadas (Architect, 2026-11-24, no piloto automático)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico. -->

### O que foi entregue
- **SPEC-0096 (PR #75, boson-atlas 2026.11.19, plugin 2026.11.34):** contrato `probe@2` com alvo de recurso, `linked_resources`, acesso local por capacidade (cluster, nuvem, banco, URLs) e as chaves novas do `probes.log` (ADR-0025).
- **SPEC-0097 (PR #76, boson-atlas 2026.11.20, plugin 2026.11.35):** coletor `aws` só de leitura (RDS/Aurora, ElastiCache, SQS com DLQ, SNS e assinaturas), sem id de conta no atlas.
- **SPEC-0098 (PR #77, 2026.11.21 / 2026.11.36):** adaptador `aws-messaging` — fila, DLQ e assinaturas.
- **SPEC-0099 (PR #78, 2026.11.22 / 2026.11.37):** adaptador `postgres` — migrations e tabelas numa sessão só de leitura.
- **SPEC-0100 (PR #80, 2026.11.23 / 2026.11.38):** adaptador `cloudwatch` — sinais de erro, latência, saturação e tráfego.
- **SPEC-0101 (PR #81, 2026.11.24 / 2026.11.39):** adaptador `iam` — simulação da permissão do workload com a política do recurso.
- **SPEC-0102 (PR #82, 2026.11.25 / 2026.11.40):** `verify@2` — dependências e sinais na foto e na comparação (ADR-0026).
- **SPEC-0104 (PR #83, 2026.11.26 / 2026.11.41):** `access setup` (onboarding do acesso local), `reason` no `probes.log`, `probes stats` e as sugestões no `doctor`.
- **SPEC-0106 (PR #84, 2026.11.27 / 2026.11.42):** `verify track` e os adaptadores `github-actions` e `argocd`; máscara do id de conta no host ECR e em ARN maiúsculo.
- **SPEC-0103 (PR #85, 2026.11.28 / 2026.11.43):** validação funcional só em `tier: test`, com jornadas curadas e o adaptador `suite`.
- **SPEC-0105 (PR #86, gluon-spec 2026.11.11, plugin 2026.11.44):** o G6 da gluon-spec com `verify track`, `verify@2`, validação funcional e seis chaves novas no `delivery_check`.
- **ADR-0025** (probes de dependências) e **ADR-0026** (`verify@2`).

### Como
- Ondas: a SPEC-0096 e a SPEC-0097 primeiro; depois os adaptadores (0098 a 0101) e o `verify@2` (0102); o onboarding (0104) e o `track` (0106); a validação funcional (0103), que dependia da 0102 e da 0104; e o G6 (0105) por último. Test-writer e implementer de specs diferentes rodaram em paralelo; os merges seguiram a ordem das versões do plugin.
- Cada filha passou por test-writer, implementer e reviewer independentes, com red antes de green no G1.
- **Emendas:** v2 na 0099 (limite de chamadas de `migrations`), 0100 (`PartialData` só na última página), 0103 e 0104 (testes antigos nos `touches`), 0105 (testes da SPEC-0091) e 0106 (máscara do ECR); v3 na 0105 (migration esperada só no escopo da foto).
- **G4 reprovado uma vez** na SPEC-0100 (a regra da Emenda v2 sem teste que a provasse) e na SPEC-0105 (`--expect-migration` quebrava o fallback `verify@1`); a segunda rodada aprovou as duas.
- **G5 da SPEC-0101** falhou uma vez por um teste instável sob carga; a nova rodada passou. O fechamento dela (G5 a G7) ficou fora do merge do PR #81 e foi recuperado neste fechamento.
- Distribuição pelo plugin, sem deploy (G6 N/A em todas as filhas).

### Critérios de aceite
| Critério | Prova | Resultado |
|---|---|---|
| Probe de recurso só para recurso ligado, com acesso local, sem imprimir profile, usuário ou passfile | SPEC-0096:IT-01 (CI do PR #75) | PASS |
| Coletor `aws` gera snapshot `@1` válido de respostas gravadas | SPEC-0097:IT-01 (CI do PR #76) | PASS |
| Mensageria responde `probe@2` só com verbos de leitura | SPEC-0098:IT-01 (CI do PR #77) | PASS |
| PostgreSQL lê migrations e tabelas numa sessão só de leitura | SPEC-0099:IT-01 (CI do PR #78) | PASS |
| CloudWatch traz os sinais do recurso na janela | SPEC-0100:IT-01 (CI do PR #80) | PASS |
| IAM simula a permissão do workload com a política do recurso | SPEC-0101:IT-01 (CI do PR #81) | PASS |
| `verify compare` dá `degradou` com DLQ nova e `passou` com as dependências como na foto | SPEC-0102:IT-01 (CI do PR #82) | PASS |
| Validação funcional só em `tier: test`, recusando produção | SPEC-0103:IT-01 (CI do PR #85) | PASS |
| Onboarding grava o acesso local e o `doctor` sugere o que falta | SPEC-0104:IT-01 (CI do PR #83) | PASS |
| `verify track` segue o commit até o rollout, só lendo | SPEC-0106:IT-01 (CI do PR #84) | PASS |
| G6 da gluon-spec descreve `verify@2`, `track` e a validação funcional, com produção protegida | SPEC-0105:IT-01 (CI do PR #86) | PASS |

### Métricas pós-release
A acompanhar no uso real: quantas entregas passam pelo `verify track` até `ok`, quantos `compare` saem com dependências verificadas em vez de não verificadas, e as recusas por falta de acesso no `probes stats`. Nenhuma medida existe ainda, porque a versão acabou de sair.

### Pendências
- Os minors de G4 de cada filha estão nas Pendências dos relatórios delas (radar do épico); nenhum bloqueia. Os que mais pesam no uso: o `track` sem `--expect-image` fica em exit 6 quando a pipeline não é verificável (o `track_max_minutes` da SPEC-0105 limita), o datastore de migration não ligado ao serviço e a regex de conta do `iam`.
- A cópia em `tools/sdd/` deste repositório foi atualizada para 2026.11.11 neste fechamento.
- As ações de escrita continuam no radar da SPEC-0075.

## 12. Emendas
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
