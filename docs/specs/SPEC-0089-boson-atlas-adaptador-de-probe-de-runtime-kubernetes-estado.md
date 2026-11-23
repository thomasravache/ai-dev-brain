---
id: SPEC-0089
title: "boson-atlas: adaptador de probe de runtime (Kubernetes: estado, eventos e logs)"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-22
parent: SPEC-0030
depends_on: [SPEC-0088]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/assets/probes/**, skills/boson-atlas/references/probes/**, skills/boson-atlas/tests/test_probe_kubernetes.py, skills/boson-atlas/tests/fixtures/kubernetes/**]
adrs: [ADR-0023]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0089 — boson-atlas: adaptador de probe de runtime (Kubernetes: estado, eventos e logs)

> Origem: épico SPEC-0030, adaptador de referência de runtime. É a primeira capacidade que a verificação da SPEC-0075 usa.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Adaptador `kubernetes` do contrato `probe@1` para a capacidade `runtime`. Ele usa o `kubectl` da máquina, só para leitura, com o contexto e o namespace que o atlas entrega, e responde três perguntas:
- **`status`:** o workload está de pé, com a imagem certa?
- **`events`:** que alertas apareceram?
- **`logs`:** o que os pods escreveram na janela?

## 2. Motivação & Escopo
**Motivação:** o núcleo do probe (SPEC-0088) não executa nada sozinho. A verificação depois do deploy precisa, primeiro, do estado do rollout e dos logs do workload.

**Objetivos (dentro do escopo):**
- **`assets/probes/kubernetes.py`:** só stdlib, Python 3.9 ou mais novo. Usa `--describe` e o protocolo `probe@1`.
- **`status`:** por workload, informa:
  - réplicas desejadas, atualizadas e prontas;
  - se o rollout está concluído;
  - por pod: fase, restarts, imagem (caminho, tag e digest, sem o host do registry) e motivo do último término.
- **`events`:** eventos `Warning` dos workloads e dos pods deles na janela, com motivo, objeto, contagem e último horário.
- **`logs`:** linhas dos pods dos workloads na janela (`--since`, `--tail`, com horário), todos os containers.
- **Lista fechada:**
  - subcomandos: `get` e `logs`;
  - recursos: `deployments`, `statefulsets`, `daemonsets`, `rollouts`, `replicasets`, `pods` e `events`.
  - O adaptador recusa qualquer outro antes de chamar o kubectl.

**Não-objetivos (fora do escopo):**
- `exec`, `describe`, `port-forward` e qualquer verbo de escrita.
- Ler `Secret` ou `ConfigMap`.
- Métricas (`top`) e fontes de log externas: ficam para adaptadores próprios.

## 3. Dependências
- **Implementações necessárias:** SPEC-0088, porque o IT-01 e o CT-01 usam o núcleo e o validador de `probe@1` reais.
- **Contratos consumidos:** N/A (o `probe@1` vem com a implementação da SPEC-0088).
- **Pré-requisitos externos:** `kubectl` no PATH da máquina que roda a probe. Nos testes ele é substituído por um dublê.

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **coletor `argocd`:** `assets/collectors/argocd.py`, que usa o `kubectl` com `-o json`, um dublê `tests/fixtures/argocd/fake_kubectl.py` e normaliza imagens com `normalize_image` (SPEC-0082);
- **contrato:** `probe@1` (SPEC-0088).

**Decisão:** é um script próprio em `assets/probes/`, no molde do coletor `argocd`. Ele monta cada chamada a partir dos campos do alvo e de uma lista fechada de subcomandos e recursos, e lê sempre com `-o json`, menos no `logs`.

**Justificativa:** repetir o padrão do coletor (dublê de kubectl, stdlib, JSON) deixa o adaptador testável sem cluster. A lista fechada é a segunda barreira, depois da credencial (ADR-0023).

**Desvio do padrão existente:** nenhum.

**Alternativas descartadas:** a biblioteca cliente do Kubernetes (dependência nova) e o `kubectl describe` (texto livre, difícil de validar).

**ADRs:** ADR-0023.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:**
  - no máximo um `get` por tipo de recurso e um `logs` por workload;
  - cada chamada com `--request-timeout` igual ao timeout menos uma folga;
  - `logs` limitado por `--tail` e `--since`.
- **Segurança:**
  - lista fechada de subcomandos e recursos;
  - o contexto vem só da entrada e nunca é impresso;
  - imagem sem o host do registry;
  - nenhuma leitura de `Secret`;
  - as mensagens de erro do kubectl saem resumidas ao motivo, como "Forbidden" ou "NotFound".
- **Privacidade e dados pessoais:** as linhas de log passam pela redaction do núcleo (SPEC-0088).
- **Disponibilidade e resiliência:**
  - `kubectl` ausente → `status: error`, "kubectl não encontrado";
  - sem permissão → `status: error` com o motivo;
  - workload inexistente → item com `found: false`.
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** a descrição e os três verbos do adaptador `kubernetes`.

```text
--describe → {"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "events", "logs"]}}

chamadas permitidas (sempre com --context <target.context> -n <target.namespace> e --request-timeout):
  kubectl get <recurso> [<nome>] -o json   recurso ∈ {deployments, statefulsets, daemonsets, rollouts,
                                                      replicasets, pods, events}
  kubectl logs <Kind>/<nome> --all-containers --timestamps --since=<s>s --tail=<n> --prefix
  qualquer outra → recusada antes de executar (status: error, "chamada não permitida")

status → items, um por workload e um por pod:
  {"kind": "workload", "workload": "Deployment/api", "found": true, "desired": 3, "updated": 3, "ready": 3,
   "available": 3, "rollout_complete": true}
  {"kind": "pod", "workload": "Deployment/api", "pod": "api-7f9c-abcd", "phase": "Running", "ready": true,
   "restarts": 0, "images": ["acme/api:1.4.2@sha256:…"], "last_termination": "OOMKilled" | ""}
  imagem: o caminho normalizado (regra da SPEC-0082), mais ":<tag>" e "@<digest>" quando existem, sem o host
  pods do workload: pelo seletor do workload (spec.selector.matchLabels)
  rollout_complete: updated == desired == ready == available e observedGeneration >= generation

events → itens {"reason", "object": "Pod/api-7f9c-abcd", "count", "last_ts", "message"} só type=Warning,
  só dos workloads e dos seus pods, last_ts dentro de since_seconds; message até 300 caracteres

logs → itens {"workload", "pod", "container", "ts", "line"}; linha sem o prefixo do kubectl; no máximo
  limits.lines itens no total (os mais recentes); excedente → truncated: true

erros → status: "error", items: [], message: "kubectl não encontrado" | "sem permissão (Forbidden)" |
  "contexto inexistente" | "chamada não permitida" | "timeout"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `assets/probes/kubernetes.py` (novo).
- `references/probes/kubernetes.md` (nova): os verbos, as chamadas, a permissão mínima sugerida (ClusterRole de leitura sem `secrets`) e um exemplo.
- `tests/test_probe_kubernetes.py` e `tests/fixtures/kubernetes/` (dublê de kubectl e respostas JSON).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Descrição | `--describe` | capacidades e verbos do contrato | CT-01 |
| Rollout concluído | deployment e pods prontos | `rollout_complete: true`, pods com imagem e restarts | UT-01 |
| Rollout em andamento ou falho | réplicas faltando, CrashLoop, OOMKilled | `rollout_complete: false`, restarts e último término | UT-01 |
| Eventos | Warning e Normal, dentro e fora da janela, de outros objetos | só Warning dos workloads e pods, na janela | UT-02 |
| Logs | vários pods e containers, mais linhas que o limite | itens com horário, os mais recentes, truncated | UT-03 |
| Erros | kubectl ausente, Forbidden, contexto inexistente, timeout | `status: error` com o motivo, sem o contexto | UT-04 |
| Lista fechada | pedido que levaria a `secrets`, `exec` ou `delete` | recusado antes de chamar o kubectl | UT-05 |
| Ponta a ponta | `atlas.py probe` com o adaptador e o dublê | saída validada pelo núcleo | IT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — adaptador novo, sem comportamento anterior. O CH-01 do núcleo (SPEC-0088) cobre o resto.

### 7.2 Testes Unitários
- **UT-01** — Com o dublê de kubectl devolvendo:
  - um Deployment `api` com 3 réplicas prontas e 3 pods com `ghcr.io/acme/api:1.4.2@sha256:abc`;
  - um Deployment `worker` com 1 de 2 prontas, um pod em CrashLoop com 4 restarts e o último término `OOMKilled`,

  quando `status` roda, então `api` tem `rollout_complete: true` e as imagens `acme/api:1.4.2@sha256:abc`, sem `ghcr.io`. `worker` tem `rollout_complete: false`, e o pod dele tem `restarts: 4` e `last_termination: OOMKilled`.
- **UT-02** — Com eventos Warning e Normal, dentro e fora da janela, de pods do workload e de outro workload, quando `events` roda, então saem só os Warning dos pods do workload dentro da janela, com a mensagem cortada em 300 caracteres.
- **UT-03** — Com dois pods e dois containers e 300 linhas, quando `logs` roda com `lines: 100`, então saem as 100 mais recentes, com `workload`, `pod`, `container`, `ts` e `line`, e `truncated: true`.
- **UT-04** — Com o kubectl ausente, Forbidden, contexto inexistente ou acima do timeout, quando qualquer verbo roda, então `status: error` vem com a mensagem do contrato. O nome do contexto não aparece na saída.
- **UT-05** — O dublê registra cada argv recebido. Em todos os testes, todo argv começa com `get` ou `logs`, com um recurso da lista. Uma entrada que levaria a `secrets` (workload `Secret/x`) ou a um verbo fora da lista é recusada sem nenhuma chamada.

### 7.3 Testes de Integração
- **IT-01** — Com o núcleo (SPEC-0088), um atlas temporário com o mapa de acesso (SPEC-0087) e o dublê de kubectl no PATH, quando `atlas.py probe runtime status --service api --env dev --json` roda como processo, então a saída validada pelo núcleo traz os itens do UT-01 e o registro local tem a linha da probe.

### 7.4 Testes de Contrato
- **CT-01** — `--describe` e as saídas de `status`, `events`, `logs` e de erro, quando passam pelo validador `probe@1` do núcleo, são aceitos.

### 7.5 Testes E2E
- N/A — sem jornada interativa; o IT-01 roda o comando de ponta a ponta com o dublê.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- `tests/fixtures/kubernetes/fake_kubectl.py`: responde por argv, registra as chamadas e não aceita nada fora da lista.
- Respostas JSON só com nomes `acme`.
- Sem cluster e sem rede.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. Só roda com as probes ligadas na máquina.
- **Dados/schema:** nenhum.
- **Compatibilidade:** é aditivo.
- **Observabilidade:** o registro local do núcleo.
- **Rollback:** tirar o adaptador de `probes.adapters` ou reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Usar `kubectl describe`? — Não. Ele é texto livre; `get -o json` dá o mesmo dado estruturado (recomendação do arquiteto; revisável no H1).
- [x] Mostrar o digest da imagem? — Sim, só na saída da probe, sem o host. Ele é o que prova a versão quando a tag é reaproveitada, e não vai para o atlas (ADR-0024; recomendação do arquiteto, revisável no H1).

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 68f7863 (árvore suja) | 2026-11-22 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0089`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
