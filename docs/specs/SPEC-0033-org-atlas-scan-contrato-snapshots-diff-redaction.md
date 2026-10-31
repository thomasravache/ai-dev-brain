---
id: SPEC-0033
title: "org-atlas: scan com contrato dos coletores, snapshots, diff e redaction"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0032]
consumes_contract: []
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/collector-contract.md, skills/org-atlas/references/redaction.md, skills/org-atlas/assets/atlas-config.yml, skills/org-atlas/tests/test_scan.py, skills/org-atlas/tests/fixtures/contract/**, skills/org-atlas/tests/fixtures/fake-collectors/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0011]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0033 — org-atlas: scan com contrato dos coletores, snapshots, diff e redaction

## 1. Visão Geral
Implementa o `atlas.py scan`: roda os coletores declarados no `atlas-config.yml`, valida a saída de cada um contra o contrato do ADR-0011, **mascara o que parecer segredo**, grava um snapshot normalizado por coletor e mostra o que mudou desde o scan anterior. Também define, em `references/collector-contract.md`, o contrato que qualquer coletor (das SPEC-0034 e SPEC-0035 ou escrito pela organização) segue.

## 2. Motivação & Escopo
**Motivação:** o atlas precisa de dados de provedores diferentes sem conhecê-los no código (ADR-0010). O contrato neutro e o `scan` são o ponto único por onde tudo entra, e por isso é aqui que ficam as proteções contra segredo e o diff que vira PR no modo repositório.

**Objetivos (dentro do escopo):**
- Chave `collectors` no `atlas-config.yml`: `id`, `category`, `command` (lista de argumentos, sem shell), `timeout`, `enabled`; marcadores `{skill}` e `{atlas}` no lugar de caminhos absolutos.
- `scan [--only id,...] [--json]`: executa, valida, mascara, normaliza, grava `snapshots/<id>.json` e `snapshots/_scan.json` (data do último scan de cada coletor, que é o `seen_at` dos fatos dele) e imprime o diff.
- Validador do contrato e redaction como funções do `atlas.py`, usadas também pelo `lint` (SPEC-0039).
- `references/collector-contract.md` (contrato, exemplos válidos e inválidos) e `references/redaction.md` (padrões e como acrescentar).

**Não-objetivos (fora do escopo):**
- Os coletores de provedor (SPEC-0034, SPEC-0035) e o cruzamento entre snapshots (SPEC-0036).
- Detecção de segredo por entropia: só padrões conhecidos e os da configuração; o `lint` reforça (SPEC-0039).

## 3. Dependências
- **Implementações necessárias:** SPEC-0032 — configuração e estrutura do atlas.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** a referência é o `run_processor` da `second-brain` (SPEC-0022, ADR-0009): comando declarado na configuração, executado sem shell, com timeout e saída capturada. No `atlas.py`, a função equivalente é `run_collector`, a única que pode chamar `subprocess` (ADR-0010, teste UT-05 da SPEC-0032).

**Decisão:** `run_collector` → `validate_collector_output` (ADR-0011) → `redact` → `normalize` → `diff_snapshots` → gravação. Um coletor que falha não para os outros: o snapshot anterior dele fica, a data em `_scan.json` não avança e o scan sai com 1.

**Justificativa:** um ponto único de entrada torna as proteções testáveis, e o snapshot normalizado deixa o diff estável para o PR do atlas.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** gravar `seen_at` em cada entidade (o arquivo mudaria a cada scan e o PR ficaria ruidoso); parar o scan no primeiro coletor com falha (uma fonte fora do ar travaria o atlas inteiro).

**ADRs:** ADR-0010, ADR-0011.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** validar, mascarar e gravar 10.000 entidades em menos de 5 s, sem contar o tempo dos coletores (fixture gerada na revisão).
- **Segurança:** comando sem shell; `timeout` por coletor (padrão 300 s); stderr do coletor mostrado só nas últimas 20 linhas, já mascarado; chaves de `attrs` proibidas descartadas e reportadas; caminho absoluto em `command` rejeitado.
- **Privacidade e dados pessoais:** nenhum valor que case com um padrão de segredo chega ao snapshot (IT-03); sinais limitados a contagens e amostra (ADR-0011).
- **Disponibilidade e resiliência:** falha, timeout ou JSON inválido de um coletor não impede os outros (IT-04).
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** chave `collectors`, comando `scan`, contrato dos coletores (ADR-0011) e arquivos em `snapshots/`.

```text
atlas-config.yml:
  collectors:
    - id: github                     # ^[a-z0-9-]+$, único
      category: code                 # ADR-0011
      command: ["python3", "{skill}/assets/collectors/github.py", "--org", "acme"]
      timeout: 300                   # segundos, padrão 300
      enabled: true
  redaction: {extra_patterns: ["<regex>", ...]}

Saída de um coletor (stdout, um objeto JSON) — ADR-0011:
  {"contract": "org-atlas/collector@1", "collector": "github", "category": "code",
   "collected_at": "2026-10-30T12:00:00Z",
   "entities":  [{"kind": "repository", "id": "acme/api", "name": "api", "attrs": {...}, "source": "github"}],
   "relations": [{"from": "pipeline:acme/api/ci", "to": "repository:acme/api", "type": "builds", "source": "github"}],
   "signals":   [{"type": "pr-titles", "repository": "acme/api", "total": 200, "pattern_counts": {...}, "sample": [...]}]}

Redaction (references/redaction.md): tokens com prefixos conhecidos (ex.: ghp_, gho_, github_pat_, xoxb-, AKIA),
  blocos "-----BEGIN ... PRIVATE KEY-----", JWT (eyJ...), credencial em URL (scheme://user:senha@host) e os
  extra_patterns → o trecho vira "[REDACTED]"; cada ocorrência conta no relatório (sem mostrar o valor)

atlas.py scan [--only id,...] [--json]
  para cada coletor habilitado: executa, valida, mascara, normaliza, grava snapshots/<id>.json
  snapshots/_scan.json: {"<id>": {"seen_at": "AAAA-MM-DD", "status": "ok|failed", "entities": N, "relations": M}}
  saída: por coletor "OK <id> — +A entidades, -R, ~C; +a relações, -r" e "N valor(es) mascarado(s)";
         sem mudança: "OK <id> — sem mudanças"
  coletor com exit ≠ 0, timeout, JSON inválido ou violação do contrato:
    "FALHA <id> — <motivo>"; snapshot anterior mantido; seen_at não avança; scan continua
  exit 0 sem falha, 1 com alguma falha, 2 com configuração inválida ou --only com id desconhecido
  violações do contrato (exemplos): contract ≠ org-atlas/collector@1 | kind ou type fora da lista |
    chave de entidade repetida | from/to fora do formato kind:id | attrs com valor que não é escalar
  chave de attrs proibida (password, secret, token, key, credential, private): descartada e reportada,
    sem falhar o coletor
  command com caminho absoluto: exit 2 "command não pode ter caminho absoluto — use {skill} ou {atlas}"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Saída válida | coletor segue o contrato | aceita | UT-01, CT-01 |
| Contrato violado | versão, tipo ou formato errado | "FALHA <id>" com o motivo | UT-02, CT-01 |
| Chave proibida | `attrs.password` | descartada e reportada | UT-03 |
| Segredo no valor | token, chave privada, JWT, URL com senha | "[REDACTED]" no snapshot, contagem no relatório | UT-04, IT-03 |
| Normalização | mesma saída em ordem diferente | arquivo idêntico byte a byte | UT-05 |
| Diff | entidades e relações novas, removidas e alteradas | relatório por coletor | UT-06, IT-02 |
| Caminho no comando | `command` com caminho absoluto | exit 2 | UT-07 |
| Primeiro scan | coletor falso válido | snapshot e `_scan.json` gravados | IT-01 |
| Falha de coletor | exit ≠ 0, timeout, JSON inválido | os outros seguem; anterior mantido; exit 1 | IT-04 |
| Id desconhecido | `--only nao-existe` | exit 2 | IT-05 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado uma saída que segue o contrato, quando `validate_collector_output` roda, então não há violação.
- **UT-02** — Dado saídas com contrato `@9`, `kind` desconhecido, `type` desconhecido, chave repetida e `from` sem `kind:`, quando são validadas, então cada uma gera a violação certa.
- **UT-03** — Dado uma entidade com `attrs.password`, quando é validada, então a chave é descartada e reportada, e o coletor não falha.
- **UT-04** — Dado valores com cada padrão de segredo e um `extra_pattern`, quando `redact` roda, então cada trecho vira `[REDACTED]` e a contagem bate.
- **UT-05** — Dado a mesma saída com entidades e relações em ordens diferentes, quando é normalizada, então o JSON gerado é idêntico.
- **UT-06** — Dado dois snapshots, quando `diff_snapshots` roda, então lista entidades e relações adicionadas, removidas e alteradas.
- **UT-07** — Dado um `command` com caminho absoluto, quando a configuração é validada, então falha; com `{skill}` e `{atlas}`, os marcadores são resolvidos.

### 7.3 Testes de Integração
- **IT-01** — `scan` pela CLI com um coletor falso (script em `tests/fixtures/fake-collectors/`) grava `snapshots/<id>.json` e `_scan.json`.
- **IT-02** — Um segundo `scan`, com o coletor falso devolvendo uma entidade nova e uma a menos, mostra só essas diferenças; um terceiro sem mudança mostra "sem mudanças".
- **IT-03** — Um coletor falso que planta um token e uma URL com senha em `attrs`: o snapshot só tem `[REDACTED]`, o relatório conta 2 e o valor não aparece na saída.
- **IT-04** — Com três coletores (um com exit 1, um que estoura o timeout e um com JSON inválido) e um válido: o válido é gravado, os outros mantêm o snapshot anterior e o `seen_at` antigo, e o scan sai com 1.
- **IT-05** — `scan --only nao-existe` sai com 2.

### 7.4 Testes de Contrato
- **CT-01** — Os exemplos válidos e inválidos de `references/collector-contract.md`, copiados em `tests/fixtures/contract/`, passam ou falham no validador com a mensagem documentada (contrato fornecido às SPEC-0034 e SPEC-0035).

### 7.5 Testes E2E
- N/A — ferramenta de linha de comando usada pelo agente; a jornada é provada pela SPEC-0038.

### 7.6 Outros
- Medição de desempenho da seção 5 na revisão.

**Dublês e dados de teste:** coletores falsos em Python (stdlib) que imprimem JSON fixo, falham, dormem além do timeout ou imprimem JSON inválido.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto, junto com a versão da skill.
- **Dados/schema:** `snapshots/` novo; contrato `org-atlas/collector@1`.
- **Compatibilidade:** contrato versionado (ADR-0011).
- **Observabilidade:** relatório do `scan` e `_scan.json`.
- **Rollback:** reverter o PR; snapshots são arquivos versionados no git do atlas.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e redaction**
- [ ] Red: UT-01, UT-02, UT-03, UT-04, CT-01 com a tag `SPEC-0033:<ID>`, falhando pelo motivo certo
- [ ] Green: `validate_collector_output`, `redact`, `references/collector-contract.md`, `references/redaction.md` e fixtures do contrato
- [ ] Refactor mantendo tudo verde

**Fase 2: Normalização e diff**
- [ ] Red: UT-05, UT-06, UT-07 com a tag `SPEC-0033:<ID>`, falhando pelo motivo certo
- [ ] Green: `normalize`, `diff_snapshots`, validação de `collectors` e marcadores `{skill}`/`{atlas}`
- [ ] Refactor mantendo tudo verde

**Fase 3: Comando scan**
- [ ] Red: IT-01, IT-02, IT-03, IT-04, IT-05 com a tag `SPEC-0033:<ID>`, falhando pelo motivo certo
- [ ] Green: `run_collector` (sem shell, timeout), `scan`, `snapshots/` e `_scan.json`; coletores falsos
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `ATLAS_VERSION` e seção no `skills/org-atlas/CHANGELOG.md` (ADR-0010)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: skill distribuída por cópia (como a second-brain)
- [ ] Relatório de Entrega, README e `skills/org-atlas/CHANGELOG.md` (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0033`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
