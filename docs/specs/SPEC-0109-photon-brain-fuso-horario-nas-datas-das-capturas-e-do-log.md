---
id: SPEC-0109
title: "photon-brain: fuso horário nas datas das capturas e do log"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-26
parent: SPEC-0093
depends_on: []
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/assets/brain-config.yml, skills/photon-brain/references/config.md, skills/photon-brain/references/connectors.md, skills/photon-brain/references/inbox.md, skills/photon-brain/SKILL.md, skills/photon-brain/CHANGELOG.md, skills/photon-brain/tests/test_timezone.py, skills/photon-brain/tests/test_timezone_cli.py, skills/photon-brain/tests/test_connector.py, .claude-plugin/plugin.json]
adrs: [ADR-0007, ADR-0027]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-26
---

# SPEC-0109 — photon-brain: fuso horário nas datas das capturas e do log

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O vault passa a ter um fuso: a chave opcional `timezone` do `brain-config.yml` (nome IANA, como `America/Sao_Paulo`). Com ela, as datas que o `brain.py` grava saem no fuso do usuário mesmo numa sessão na nuvem em UTC, e o `created` das capturas leva o deslocamento (`2026-11-26T09:15:02-03:00`). Sem a chave, vale o fuso da máquina, também com o deslocamento (ponto 4 da SPEC-0093).

## 2. Motivação & Escopo
**Motivação:** numa sessão na nuvem, a captura saiu em UTC e o `created` sem fuso; a nota parecia ter sido feita três horas depois. Quem lê o vault em outra máquina não sabe de que fuso veio a hora.

**Objetivos (dentro do escopo):**
- Chave `timezone` em `SHARED_KEYS`, opcional, com o nome IANA; o `doctor` mostra o fuso em uso e acusa nome inválido.
- O relógio do `brain.py` (`now()`, `today()` e o de `cmd_capture`) usa o fuso configurado, ou o da máquina sem a chave.
- `created` da captura em ISO 8601 com deslocamento; o nome do arquivo da captura usa a hora no mesmo fuso.
- `capture --print` aceita `--timezone NOME` para a sessão que não consegue ler a configuração; lida a configuração, vale a chave.
- `SKILL.md`, `references/config.md`, `references/connectors.md` e `references/inbox.md` explicam a chave e o formato.

**Não-objetivos (fora do escopo):**
- Mudar o formato do `created` das notas organizadas (continua `AAAA-MM-DD`, agora no fuso configurado) e o formato da linha do `log.md` (continua sem deslocamento, agora no fuso configurado).
- Reescrever datas de capturas antigas.
- Horário de verão por regra própria: vale a base de fusos do sistema.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** módulo `zoneinfo` da biblioteca padrão (Python 3.9+) e a base de fusos do sistema; sem ela (comum no Windows), o nome não é encontrado e o `brain.py` avisa (ver contrato).

## 4. Decisão Arquitetural
**Contexto:** a configuração compartilhada é lida por `read_config` e validada por `check_shared`; chaves fora de `SHARED_KEYS` geram AVISO no `doctor`. O relógio está em `now()`, `today()` e num `dt.datetime.now()` direto em `cmd_capture`; as funções puras de captura já recebem `clock=`.

**Decisão:** uma função `vault_clock(shared, override=None)` devolve um relógio com `tzinfo` (`zoneinfo.ZoneInfo(nome)` ou o fuso local da máquina por `astimezone()`); `now()`, `today()` e `cmd_capture` passam a usá-lo; `capture_note` grava `created` com `isoformat(timespec="seconds")` do datetime com fuso.

**Justificativa:** biblioteca padrão, sem rede (ADR-0007); a chave fica no vault porque a sessão na nuvem não tem a configuração local (ADR-0027).

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** fuso na configuração local (não existe na nuvem); sempre UTC com deslocamento `Z` (correto, mas a hora mostrada não é a do usuário, que foi a queixa).

**ADRs:** ADR-0007, ADR-0027.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — uma leitura do fuso por execução.
- **Segurança:** o nome do fuso é validado contra `^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$` antes de chegar ao `zoneinfo`, para não virar caminho de arquivo — UT-03.
- **Privacidade e dados pessoais:** o fuso indica a região do usuário; fica no vault dele, como o resto da configuração. N/A além disso.
- **Disponibilidade e resiliência:** fuso inválido ou ausente na máquina não derruba a leitura: os comandos que só leem seguem; os que gravam datas saem com 2 e a mensagem — UT-03.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A — local.

## 6. Artefato A — Contrato
**Interface:** chave `timezone`; `created` da captura; `capture --print --timezone`

```text
brain-config.yml (compartilhada)
  timezone: America/Sao_Paulo      # opcional; nome IANA; sem a chave, o fuso da máquina

created da captura:  AAAA-MM-DDTHH:MM:SS±HH:MM   (ex: 2026-11-26T09:15:02-03:00; UTC sai +00:00)
nome da captura:     AAAA-MM-DD-HHMMSS-<slug>    (data e hora no mesmo fuso do created)
created das notas:   AAAA-MM-DD                  (data no fuso do vault)
linha do log.md:     formato de hoje, hora no fuso do vault

brain.py capture --print ... [--timezone NOME]
  configuração legível com timezone: vale a chave (--timezone é ignorado, com aviso no stderr se diferir)
  sem configuração legível: --timezone NOME; sem ele, o fuso da máquina

doctor
  OK   "fuso: America/Sao_Paulo"  |  OK "fuso: o da máquina (-03:00)" sem a chave
  ERRO "timezone inválido: use um nome como America/Sao_Paulo"            (nome fora da regra)
  ERRO "fuso <nome> não encontrado nesta máquina (instale a base de fusos)" (zoneinfo não acha)

comandos que gravam datas (capture, new-note, relate, append, index, inbox done, ...)
  com timezone inválido ou não encontrado: exit 2 com a mesma mensagem do doctor, nada gravado
```

**Esclarecimentos (Emenda v2):**
- Os testes da SPEC-0044 em `tests/test_connector.py` (`PrintMatchesCaptureTest`, `PrintWithoutConfigTest`) fixam o `created` da captura sem deslocamento; com este contrato eles passam a aceitar o `created` com `±HH:MM`, sem mudar o resto do que conferem. O arquivo entra em `touches` só para esse ajuste.

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** `scripts/brain.py` (`SHARED_KEYS`, `check_shared`, `vault_clock`, `now`, `today`, `cmd_capture`, `capture_config`, `doctor`); `assets/brain-config.yml` (a chave comentada); referências e `SKILL.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Fuso configurado | `timezone: America/Sao_Paulo`, máquina em UTC | `created` com `-03:00` e hora local do usuário; nome da captura na mesma hora | UT-01, IT-01 |
| Sem a chave | máquina em `TZ=America/Sao_Paulo` | `created` com `-03:00` | UT-02 |
| Máquina em UTC sem a chave | `TZ=UTC` | `created` com `+00:00` | UT-02 |
| Fuso inválido | nome fora da regra ou inexistente | `doctor` ERRO; comandos que gravam saem com 2 sem gravar; leitura segue | UT-03 |
| Conector sem config | `capture --print --timezone X` sem config legível | `created` no fuso X | UT-04 |
| Conector com config | config com `timezone` e `--timezone` diferente | vale a chave, aviso no stderr | UT-04 |
| Datas das notas e log | `timezone` configurado, máquina em UTC | `created` das notas e hora do log no fuso do vault | UT-05 |
| Chave conhecida | `timezone` no `brain-config.yml` | sem AVISO de chave desconhecida | UT-06 |
| Documentação | `config.md`, `connectors.md`, `inbox.md`, `SKILL.md` | chave e formato descritos | UT-07 |
| Sem a chave, hoje | vault sem `timezone` | captura igual à de hoje, só com o deslocamento | CH-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Dado um vault sem `timezone`, quando `capture` roda, então o nome do arquivo, o corpo e o `type` da captura são os de hoje; só o `created` muda, ganhando o deslocamento (o teste de antes da mudança fixa nome, corpo e `type`, e passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado `vault_clock` com `America/Sao_Paulo` e um instante fixo `2026-11-26T12:15:02Z`, então `capture_note` grava `created: 2026-11-26T09:15:02-03:00` e `capture_name` começa com `2026-11-26-091502-`.
- **UT-02** — Sem a chave, com `TZ=America/Sao_Paulo` no ambiente, o `created` termina em `-03:00`; com `TZ=UTC`, em `+00:00`.
- **UT-03** — Com `timezone` `../etc/passwd`, `Not/A/Zone/Too/Deep` ou `Mars/Olympus`, o `doctor` mostra o ERRO certo, `capture` e `new-note` saem com 2 sem criar arquivo, e `search` e `config` seguem funcionando.
- **UT-04** — Sem configuração legível, `capture --print --timezone America/Sao_Paulo` grava `-03:00`; com a configuração em `Europe/Lisbon` e `--timezone America/Sao_Paulo`, vale `Europe/Lisbon` e o stderr avisa da diferença.
- **UT-05** — Com `timezone: America/Sao_Paulo` e `TZ=UTC`, perto da meia-noite UTC (instante fixo `2026-11-27T01:30:00Z`), o `created` de uma nota nova é `2026-11-26` e a hora da linha do log é `22:30`.
- **UT-06** — `timezone` está em `SHARED_KEYS`: um `brain-config.yml` com a chave não gera AVISO de chave desconhecida no `doctor`.
- **UT-07** — `references/config.md` descreve `timezone` (nome IANA, opcional, padrão o fuso da máquina); `references/connectors.md` e `references/inbox.md` mostram o `created` com deslocamento e o `--timezone` do `capture --print`; o `SKILL.md` cita a chave no fluxo de captura.

### 7.3 Testes de Integração
- **IT-01** — Num vault do `init` com `timezone: America/Sao_Paulo` e o processo em `TZ=UTC`, quando `capture`, `inbox list` e `ingest --move` rodam, então a captura tem `created` com `-03:00`, a idade do `inbox list` é calculada certo e a nota criada tem a data do fuso do vault.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs.

### 7.5 Testes E2E
- N/A — CLI de uso do agente; `user_facing: false` e sem jornada crítica declarada.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `Sandbox` com `TZ` no ambiente do processo; instantes fixos só pelo parâmetro `clock=` das funções puras (`vault_clock`, `capture_note`, `capture_name`, `today`/`now` com relógio injetado), como os testes de hoje fazem — sem variável de ambiente de teste no `brain.py`. Os testes de CLI conferem o deslocamento e a coerência entre o nome do arquivo e o `created`, não a hora exata.

**Ambiente de execução:** local e CI (Linux e macOS, com a base de fusos do sistema).

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin.
- **Dados/schema:** a chave é opcional; vaults sem ela seguem com o fuso da máquina.
- **Compatibilidade:** o `created` da captura ganha o deslocamento; quem lê a captura (o próprio `brain.py`, ao processar a inbox) aceita os dois formatos, com e sem deslocamento.
- **Observabilidade:** a linha "fuso" do `doctor`.
- **Rollback:** reverter o merge; capturas com deslocamento continuam ISO 8601 válido.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] O formato da linha do `log.md` muda? — Não: continua igual, com a hora no fuso do vault, para não quebrar quem lê o log (Architect, 2026-11-26, no piloto automático)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [ ] Red: CH-01, UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, UT-07, IT-01 com a tag `SPEC-0109:<ID>`, falhando pelo motivo certo (CH passando)
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
| G0 Spec | PASS | validate: 0 erro(s) — 08e07c7 (árvore suja) | 2026-11-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=18)) — bb8a880 | 2026-11-26 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — a217e1d | 2026-11-26 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — b7e30eb | 2026-11-26 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED na segunda rodada (backup no fuso do vault resolvido, minors resolvidos) — 530cb37 | 2026-11-26 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-26 — CHANGES_REQUESTED: cmd_backup não usa o relógio do vault — linha do log.md no fuso da máquina e, com timezone inválido, grava e sai com 0 em vez de 2 (contrato: comandos que gravam datas) — 4392048
- G4 PASS 2026-11-26 — depois de 1 reprovação(ões)

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0109`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-26 | `tests/test_connector.py` em `touches` para os testes da SPEC-0044 aceitarem o `created` com deslocamento | G2 da SPEC-0109: testes antigos fixavam o formato sem fuso (TEST_DEFECT) | nenhuma | thomas, 2026-11-26 (piloto automático com o recomendado) |
