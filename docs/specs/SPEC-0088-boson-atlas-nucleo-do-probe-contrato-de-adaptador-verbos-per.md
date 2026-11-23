---
id: SPEC-0088
title: "boson-atlas: núcleo do probe — contrato de adaptador, verbos permitidos, ambientes e registro local"
tier: full
type: feature
user_facing: false
status: approved
created: 2026-11-22
parent: SPEC-0030
depends_on: []
consumes_contract: [SPEC-0087@1]
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/references/probes.md, skills/boson-atlas/references/config.md, skills/boson-atlas/SKILL.md, skills/boson-atlas/tests/**, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0011, ADR-0023]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-23
---

# SPEC-0088 — boson-atlas: núcleo do probe — contrato de adaptador, verbos permitidos, ambientes e registro local

> Origem: épico SPEC-0030, primeira filha. Thomas decidiu em 2026-11-22 que a verificação da SPEC-0075 usa as probes.

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Comando `atlas.py probe`, desligado por padrão, que roda uma consulta **só de leitura** na infraestrutura real por meio de um adaptador externo declarado (contrato `probe@1`).

O atlas monta o alvo a partir do grafo e do mapa de acesso (SPEC-0087). Antes de executar, o núcleo verifica três coisas:
- o verbo está na lista permitida;
- o ambiente é de teste, ou houve confirmação de produção;
- a máquina tem acesso ao cluster.

Depois de executar, o núcleo valida e limita a saída, mascara segredos e registra a consulta localmente, sem o resultado.

## 2. Motivação & Escopo
**Motivação:** a verificação depois do deploy (SPEC-0090) e a investigação (SPEC-0030) precisam consultar o cluster e os logs com as mesmas proteções. Sem um núcleo, cada uso montaria comandos à mão, sem lista de verbos e sem redaction garantida.

**Objetivos (dentro do escopo):**
- `atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente>`, com as opções `--since`, `--lines`, `--summary`, `--confirm-production` e `--json`.
- Chave local `probes` no `config.yml`, com `enabled`, adaptadores (comando, verbos, timeout, credenciais por nome) e limites.
- Contrato `probe@1`:
  - a descrição do adaptador (`--describe`);
  - a entrada em JSON pelo stdin;
  - a saída em JSON, que o núcleo valida.
- Recusas com exit 4: probes desligadas, verbo fora da lista, produção sem confirmação, cluster sem acesso local.
- Redaction com as regras do atlas, limite de linhas e resumo de logs por assinatura (`--summary`).
- Registro local em JSON Lines na pasta da configuração da máquina, sem o resultado.
- `doctor` com as linhas das probes: ligadas ou desligadas, e cada adaptador encontrado ou não.

**Não-objetivos (fora do escopo):**
- Adaptadores concretos: runtime é a SPEC-0089; SQL, nuvem e observabilidade ficam para ondas seguintes.
- Verbos de escrita, em qualquer forma.
- Tool MCP de probe e política no servidor (SPEC-0031).
- Gravar qualquer resultado no atlas.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** SPEC-0087@1. São usados o `tier` do ambiente, o `namespace` e os `workloads` do deployment, e `access.clusters` da configuração local.
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente, com estes padrões de referência:
- **processo externo declarado com contrato JSON:** os coletores (`run_collector`, `collector_environment` e a validação do `collector@1` em `scripts/atlas.py`, `references/collector-contract.md`);
- **redaction:** `references/redaction.md`;
- **chave local só com nomes:** `credentials` (ADR-0010);
- **testes:** os coletores falsos de `tests/fixtures/fake-collectors/`.

**Decisão:** `probe` é um subcomando do `atlas.py` que roda adaptadores como processos externos, igual aos coletores. Ele tem contrato próprio e versionado (`probe@1`) e segue o ADR-0023.

**Justificativa:**
- Reaproveita o modelo dos coletores, que já tem execução isolada, credenciais por nome, timeout e validação.
- Deixa as proteções num lugar só, testável.

**Desvio do padrão existente:** nenhum. É um contrato novo no mesmo molde do `collector@1`.

**Alternativas descartadas:** o agente rodar as CLIs direto, e um servidor MCP já agora (ADR-0023).

**ADRs:** ADR-0023 (criado pelo épico SPEC-0030 e por esta spec), ADR-0010, ADR-0011.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** timeout por adaptador (padrão 60 s, máximo 300 s). A saída é limitada a `--lines` (padrão 200, máximo 2.000) e a 1 MB lido do adaptador.
- **Segurança:**
  - lista de verbos e confirmação de produção (ADR-0023);
  - o adaptador recebe só as credenciais declaradas nele, por nome;
  - redaction em todo texto da saída;
  - a mensagem de erro do adaptador também passa pela redaction;
  - nada é gravado no atlas.
- **Privacidade e dados pessoais:** os padrões de redaction do atlas valem para as linhas de log (e-mail, token, documento). O registro local não guarda resultado.
- **Disponibilidade e resiliência:**
  - adaptador ausente, saída inválida ou timeout → exit 1 com o motivo, sem saída parcial;
  - sem a chave `probes` → exit 4 "probes desligadas".
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** subcomando `probe`, chave local `probes`, contrato `probe@1` e registro local.

```text
config.yml (local; na forma com vários atlas, dentro da entrada do atlas)
  probes:
    enabled: false                     # padrão; true liga
    limits: {lines: 200, since: 30m}   # padrões; máximo lines 2000, since 24h
    adapters:
      kubernetes:                      # id do adaptador; sem command = o adaptador que vem com a skill
        command: ["python3", "/caminho/adaptador.py"]   # opcional
        verbs: [status, events, logs]  # liberados por esta máquina (interseção com os do adaptador)
        timeout: 60
        credentials: [NOME_DA_ENV]     # só nomes (ADR-0010)
  inválido → exit 2: "probes: <campo> inválido — <motivo>" (sem o valor)

atlas.py probe <capacidade> <verbo> --service <id> --env <ambiente>
    [--since 30m] [--lines N] [--summary] [--confirm-production] [--json] [--atlas X]
  1. sem probes.enabled: true → exit 4 "probes desligadas nesta máquina (probes.enabled)"
  2. alvo: deployments de service:<id> que runs_in environment:<ambiente>; nenhum → exit 2
  3. adaptador: o primeiro em adapters que declara <capacidade>; nenhum → exit 4 "nenhum adaptador para <capacidade>"
  4. verbo fora de (verbos do --describe ∩ verbs da configuração) → exit 4 "verbo <v> não permitido"
  5. tier do ambiente diferente de "test" (inclui sem tier) e sem --confirm-production → exit 4
     "ambiente <a> é de produção ou sem marcação: confirme com a pessoa e use --confirm-production"
  6. cluster do deployment sem access.clusters → exit 4 "sem acesso local ao cluster <c> (access.clusters)"
  7. roda o adaptador com a entrada abaixo no stdin, as credenciais declaradas e o timeout
  8. valida a saída, aplica redaction e limites e imprime (Markdown ou --json); registra
  exit: 0 ok · 1 erro do adaptador ou saída inválida · 2 argumento ou configuração inválida
        · 3 sem configuração · 4 recusado

probe@1 — descrição: <command> --describe  →
  {"contract": "probe@1", "adapter": "kubernetes", "capabilities": {"runtime": ["status", "events", "logs"]}}
probe@1 — entrada (stdin):
  {"contract": "probe@1", "capability": "runtime", "verb": "logs",
   "target": {"service": "api", "environment": "dev", "deployment": "dev-api", "clusters": ["cluster-dev"],
              "context": "<access.clusters.<c>.context>", "namespace": "api", "workloads": ["Deployment/api"]},
   "limits": {"lines": 200, "since_seconds": 1800}}
probe@1 — saída (stdout):
  {"contract": "probe@1", "adapter": "kubernetes", "capability": "runtime", "verb": "logs",
   "status": "ok" | "error", "items": [{<chave>: escalar | lista de escalares}], "truncated": false,
   "message": "texto curto"}
  chaves fechadas; items com no máximo `lines` itens (excedente → truncated: true); texto passa pela redaction

--summary (só para verbos que devolvem linhas de log: itens com "line")
  assinatura = linha com números, hexadecimais de 8 ou mais, UUIDs, e-mails e textos entre aspas trocados
  por marcadores; nível = error | warn | info | other pela palavra na linha
  itens: {"signature", "level", "count", "first_ts", "last_ts", "sample"} por (nível, assinatura), ordenados
  por nível e contagem

registro local: <pasta da configuração>/probes.log, uma linha JSON por probe:
  {"at", "atlas", "service", "environment", "capability", "verb", "adapter", "status", "exit",
   "confirmed_production": bool}   — nunca items, message nem o contexto
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: o subcomando, a validação de `probes`, o contrato e o resumo.
- `references/probes.md` (nova): contrato, configuração, exits e como escrever um adaptador.
- `references/config.md`: a chave `probes`.
- `SKILL.md`: uma linha sobre o comando e as regras de uso (confirmar produção com a pessoa).
- CHANGELOG, `plugin.json` e testes.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Sem probes | sem a chave ou `enabled: false` | exit 4; nenhum adaptador roda | CH-01 |
| Configuração | campos válidos e inválidos | aceito; inválido → exit 2 sem o valor | UT-01 |
| Verbo | fora da interseção | exit 4, adaptador não roda | UT-02 |
| Produção | tier production ou sem tier | exit 4 sem `--confirm-production`; roda com ela | UT-03 |
| Acesso | cluster sem `access.clusters` | exit 4 | UT-03 |
| Saída | segredo, excesso de itens, chave desconhecida, JSON inválido, timeout | mascarado; truncado; erro sem saída parcial | UT-04 |
| Registro | qualquer probe | uma linha local sem resultado; nada no atlas | UT-05 |
| Resumo | linhas de log com números e ids variando | assinaturas agrupadas e contadas | UT-06 |
| Ponta a ponta | adaptador falso real como processo | saída, registro e exits certos | IT-01 |
| Contrato | `--describe`, entrada e saída | validados contra `probe@1` | CT-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dada uma configuração sem a chave `probes` (ou com `enabled: false`), quando qualquer comando de hoje roda, então nada muda. `probe` sai com 4, "probes desligadas", sem executar nenhum processo (guarda: os comandos de hoje passam antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado `probes` com adaptador, verbos, timeout e credenciais válidos, então `config --json` mostra a configuração sem valores de credencial. Os casos inválidos dão exit 2 com `probes: <campo> inválido — <motivo>`, sem o valor:
  - timeout fora de 1..300;
  - `lines` fora de 1..2000;
  - verbo com espaço;
  - credencial com valor.
- **UT-02** — Dado um adaptador que declara `runtime: [status, logs]` e uma configuração que libera `[status]`, quando `probe runtime logs` roda, então sai com 4, "verbo logs não permitido", e o adaptador não roda (registro de processos do dublê vazio). O mesmo vale para `probe runtime delete`.
- **UT-03** — Para um ambiente `tier: production`, e também para um ambiente sem tier, `probe` sem `--confirm-production` sai com 4 e a mensagem do contrato, e com a opção roda e registra `confirmed_production: true`. Num ambiente `tier: test`, roda sem a opção. Um cluster sem `access.clusters` sai com 4.
- **UT-04** — Dado um adaptador que devolve:
  - uma linha com `token=ghp_...` e um e-mail;
  - 500 itens com `--lines 50`;
  - uma chave fora do contrato;
  - JSON inválido;
  - ou demora mais que o timeout,

  então o token e o e-mail saem mascarados e a saída fica com 50 itens e `truncated: true`. Chave desconhecida, JSON inválido e timeout dão exit 1 com o motivo, sem nenhum item impresso. O `message` de erro também é mascarado.
- **UT-05** — Depois de probes com sucesso, com erro e recusadas, o `probes.log` local tem uma linha por probe com as chaves do contrato e sem `items`, `message` nem o contexto. Nenhum arquivo da pasta do atlas muda (hash da árvore antes e depois).
- **UT-06** — Dadas as linhas `ERROR user 123 not found`, `ERROR user 456 not found`, `WARN retry 3 of 5` e `ERROR id 5f2b...-uuid failed`, quando `--summary` roda, então há duas assinaturas de erro (`ERROR user <n> not found` × 2 e a do UUID) e uma de aviso, com contagem, primeiro e último horário.

### 7.3 Testes de Integração
- **IT-01** — Com um adaptador falso de verdade (script Python em `tests/fixtures/fake-probes/`) e um atlas temporário com o mapa de acesso, quando `atlas.py probe runtime status --service api --env dev --json` roda como processo, então a saída segue o contrato, o registro tem uma linha e as credenciais declaradas chegam ao adaptador só pelos nomes configurados.

### 7.4 Testes de Contrato
- **CT-01** — Dados exemplos de `--describe`, entrada e saída de `probe@1` (válidos e inválidos), quando o validador do núcleo roda, então os válidos passam e cada inválido é recusado com o motivo. `references/probes.md` traz os mesmos exemplos (o teste os lê do documento).

### 7.5 Testes E2E
- N/A — sem jornada interativa. IT-01 roda a CLI como processo, e a jornada de verificação é da SPEC-0090.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- Adaptadores falsos em `tests/fixtures/fake-probes/` (ok, erro, lento, saída inválida, eco das credenciais por nome).
- Configuração e atlas temporários.
- Sem rede e sem cluster.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin. A funcionalidade vem desligada (`probes.enabled: false`).
- **Dados/schema:** chave local nova e um arquivo de registro local. Nada no atlas.
- **Compatibilidade:** é aditiva. A versão anterior não tem o subcomando e ignora a chave local.
- **Observabilidade:** o registro local e as linhas do `doctor`.
- **Rollback:** `probes.enabled: false` ou reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Onde fica a configuração das probes? — No `config.yml` local, junto das credenciais por nome, porque é a máquina que tem o acesso (ADR-0023; recomendação do arquiteto, revisável no H1).
- [x] Ambiente sem marcação pode receber probe sem confirmação? — Não. Conta como produção (ADR-0023; recomendação do arquiteto, revisável no H1).
- [x] O resumo de logs fica no núcleo ou no adaptador? — No núcleo, para valer igual em qualquer adaptador de logs e ser usado pelo `verify` (recomendação do arquiteto; revisável no H1).

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — c2bbfa3 | 2026-11-22 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0088`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
