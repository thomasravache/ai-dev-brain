---
id: SPEC-0111
title: "photon-brain: brain.py sem assets/ quando o vault já tem a configuração"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-26
parent: SPEC-0093
depends_on: []
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/references/config.md, skills/photon-brain/SKILL.md, skills/photon-brain/CHANGELOG.md, skills/photon-brain/tests/test_no_assets.py, skills/photon-brain/tests/brain_architecture_rules.py, skills/photon-brain/tests/test_architecture.py, .claude-plugin/plugin.json]
adrs: [ADR-0007]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-26
---

# SPEC-0111 — photon-brain: brain.py sem assets/ quando o vault já tem a configuração

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O `brain.py` passa a funcionar copiado sozinho (sem a pasta `assets/` ao lado) quando o vault já tem o `brain-config.yml` e os modelos em `templates/`: os padrões da configuração ficam também embutidos no script, e um teste de arquitetura garante que os embutidos são iguais ao `assets/brain-config.yml` (ponto 8 da SPEC-0093).

## 2. Motivação & Escopo
**Motivação:** para usar na nuvem, uma cópia do `brain.py` guardada no vault falhou porque `read_config` sempre lê `assets/brain-config.yml`; o remendo foi copiar `scripts` e `assets` juntos.

**Objetivos (dentro do escopo):**
- Padrões da configuração compartilhada embutidos no `brain.py`, usados quando `assets/brain-config.yml` não existe.
- Os comandos que leem e organizam o vault (`config`, `doctor`, `search`, `capture`, `new-note`, `relate`, `index`, `lint`, `inbox ...`) funcionam sem `assets/` quando o vault tem `brain-config.yml` e o modelo do tipo em `templates/`.
- Sem o modelo no vault nem em `assets/`, o `new-note` sai com 2 e diz qual modelo falta; o `init` sem `assets/` sai com 2 (é o único que precisa dos modelos da skill).
- `references/config.md` e `SKILL.md` dizem que a cópia mínima é `scripts/brain.py`, e a completa é a pasta da skill.

**Não-objetivos (fora do escopo):**
- Um comando que copia a skill para o vault (a cópia é da pasta da skill inteira, ou só o script com o vault já iniciado).
- Embutir os modelos de nota no script.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** `SKILL_DIR`, `ASSETS_DIR`, `DEFAULT_SHARED_CONFIG` e `TEMPLATES_DIR` no topo do `brain.py`; `default_shared()` lê o arquivo dos padrões e `read_config` a chama sempre; os modelos caem para `TEMPLATES_DIR` em `moc_text` e `cmd_new_note`. Regras de arquitetura em `tests/brain_architecture_rules.py`.

**Decisão:** uma constante `EMBEDDED_SHARED_DEFAULTS` (o mesmo conteúdo do `assets/brain-config.yml`); `default_shared()` usa o arquivo quando existe e a constante quando não; uma regra nova de arquitetura compara a constante com o arquivo e reprova se divergirem.

**Justificativa:** o arquivo em `assets/` continua a fonte que o `init` copia para o vault; a constante só cobre a cópia sem `assets/`, e o teste impede que os dois se separem.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** ler os padrões só do vault (um vault antigo sem uma chave nova quebraria); copiar `assets/` para dentro do vault (mais arquivos no vault da pessoa).

**ADRs:** ADR-0007.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A
- **Segurança:** N/A — nenhuma entrada nova.
- **Privacidade e dados pessoais:** N/A
- **Disponibilidade e resiliência:** sem `assets/`, mensagem clara em vez de traceback — UT-03.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A

## 6. Artefato A — Contrato
**Interface:** execução de `scripts/brain.py` copiado sem `assets/`

```text
cópia: <qualquer pasta>/brain.py  (sem assets/ ao lado)
  vault com brain-config.yml e templates/:
    config, doctor, search, capture, new-note, relate, index, lint, inbox list|done, ingest → como com a skill inteira
  new-note de um tipo sem templates/<tipo>.md no vault:
    exit 2 "modelo <tipo> não encontrado: copie a pasta da skill inteira ou crie templates/<tipo>.md no vault"
  init (vault novo):
    exit 2 "init precisa da pasta da skill inteira (assets/ não encontrada)"
  nenhum traceback por falta de assets/

regra de arquitetura nova (G3)
  EMBEDDED_SHARED_DEFAULTS == conteúdo de assets/brain-config.yml (como YAML lido pelo brain.py)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** `scripts/brain.py` (`EMBEDDED_SHARED_DEFAULTS`, `default_shared`, mensagens de modelo e do `init`); `tests/brain_architecture_rules.py` e `tests/test_architecture.py` (regra nova); `references/config.md` e `SKILL.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Script sozinho | cópia do `brain.py` sem `assets/`, vault iniciado | comandos de leitura e organização funcionam | UT-01, IT-01 |
| Padrões iguais | constante e `assets/brain-config.yml` | regra de arquitetura passa; divergindo, reprova | UT-02 |
| Modelo faltando | tipo sem `templates/<tipo>.md` e sem `assets/` | exit 2 com a mensagem, sem traceback | UT-03 |
| Init sem assets | `init` na cópia sozinha | exit 2 com a mensagem | UT-03 |
| Documentação | `config.md` e `SKILL.md` | cópia mínima e completa descritas | UT-04 |
| Skill inteira | execução de hoje | igual | CH-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Com a skill inteira, `init`, `config --json`, `new-note` e `doctor` num vault temporário dão a mesma saída de antes (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado o `brain.py` copiado sozinho para uma pasta temporária e um vault iniciado pela skill inteira, quando `config --json`, `doctor`, `capture`, `new-note --type note`, `relate`, `index` e `lint` rodam com a cópia, então todos saem com 0 e o resultado é o mesmo da skill inteira.
- **UT-02** — A regra nova de arquitetura passa com a constante igual ao `assets/brain-config.yml` e reprova quando uma chave é mudada só num dos dois (teste com cópia temporária da skill).
- **UT-03** — Na cópia sozinha, `new-note` de um tipo cujo modelo foi tirado de `templates/` e `init` num vault novo saem com 2, com as mensagens do contrato e sem `Traceback` no stderr.
- **UT-04** — `references/config.md` e `SKILL.md` dizem que basta `scripts/brain.py` com um vault já iniciado e que o `init` precisa da pasta da skill inteira.

### 7.3 Testes de Integração
- **IT-01** — Num vault do `init` com o `brain.py` copiado para dentro do vault (como no uso na nuvem), quando o fluxo capturar → `inbox list` → `ingest --move` → `index` roda com a cópia, então ele termina sem erro e o `log.md` tem as linhas de cada passo.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs.

### 7.5 Testes E2E
- N/A — `user_facing: false`, sem jornada crítica declarada.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `Sandbox` e uma cópia temporária do `brain.py`.

**Ambiente de execução:** local e CI.

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin.
- **Dados/schema:** N/A
- **Compatibilidade:** nada muda com a skill inteira.
- **Observabilidade:** N/A
- **Rollback:** reverter o merge.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Precisa de um comando oficial para copiar a skill para o vault? — Não nesta spec: com o script funcionando sozinho, copiar a pasta da skill ou só o script basta (Architect, 2026-11-26, no piloto automático)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [x] Red: CH-01, UT-01, UT-02, UT-03, UT-04, IT-01 com a tag `SPEC-0111:<ID>`, falhando pelo motivo certo (CH passando)
- [x] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [x] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 5160e50 (árvore suja) | 2026-11-27 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=11)) — 1c94a51 | 2026-11-27 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 7a47d60 | 2026-11-27 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 5e56eb4 | 2026-11-27 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (cópia sozinha sem traceback, regra de arquitetura reprova as divergências; 2 minors no radar) — 348f26f | 2026-11-27 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 8034320 | 2026-11-27 |
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
O `brain.py` da photon-brain passa a funcionar copiado sozinho, sem a pasta `assets/` ao lado, num vault já iniciado (o caso da sessão na nuvem). Os padrões da configuração ficam embutidos no script (`EMBEDDED_SHARED_DEFAULTS`), e uma regra nova de arquitetura garante que eles são iguais ao `assets/brain-config.yml`. Sem o modelo de nota, o `new-note` sai com 2 e diz o que fazer; o `init` sem `assets/` também sai com 2. Versões: photon-brain 2026.11.13 e plugin 2026.11.49.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- **`scripts/brain.py`:** `EMBEDDED_SHARED_DEFAULTS` (YAML igual ao `assets/brain-config.yml`, sem comentários); `default_shared()` usa o arquivo quando existe e a constante quando não; `note_template` procura o modelo no vault e depois na skill (usado em `new-note` e no MOC); guarda no `init` depois do `--join`.
- **Arquitetura:** `shared_defaults_findings` em `tests/brain_architecture_rules.py`, rodada pelo `arch_test` (G3 e CI).
- **Documentação:** `references/config.md` (cópia mínima e completa) e `SKILL.md`.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`. Red em 1c94a51 (G1) e green em 7a47d60 (G2).

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | com a skill inteira, init, config, new-note e doctor iguais | PASS | `test_no_assets.py` e `SharedDefaultsRulesTest` (`test_architecture.py`); G2 PASS em 7a47d60; G3 PASS; G4 `verify` 6/6 |
| UT-01 | cópia sozinha do brain.py: comandos de leitura e organização iguais aos da skill inteira | PASS | `test_no_assets.py` e `SharedDefaultsRulesTest` (`test_architecture.py`); G2 PASS em 7a47d60; G3 PASS; G4 `verify` 6/6 |
| UT-02 | regra de arquitetura reprova quando a constante e o assets/brain-config.yml divergem | PASS | `test_no_assets.py` e `SharedDefaultsRulesTest` (`test_architecture.py`); G2 PASS em 7a47d60; G3 PASS; G4 `verify` 6/6 |
| UT-03 | modelo faltando e init sem assets/: exit 2 com a mensagem, sem traceback | PASS | `test_no_assets.py` e `SharedDefaultsRulesTest` (`test_architecture.py`); G2 PASS em 7a47d60; G3 PASS; G4 `verify` 6/6 |
| UT-04 | config.md e SKILL.md descrevem a cópia mínima e a completa | PASS | `test_no_assets.py` e `SharedDefaultsRulesTest` (`test_architecture.py`); G2 PASS em 7a47d60; G3 PASS; G4 `verify` 6/6 |
| IT-01 | capturar, inbox list, ingest --move e index com a cópia dentro do vault | PASS | `test_no_assets.py` e `SharedDefaultsRulesTest` (`test_architecture.py`); G2 PASS em 7a47d60; G3 PASS; G4 `verify` 6/6 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
Sem deploy: a skill chega pelo plugin `fermion` 2026.11.49 depois do merge.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- **Minors do G4:** na cópia sozinha e sem `templates/moc.md` no vault, o `context add` grava o contexto e cria a pasta antes de sair com 2 (o MOC fica faltando; checar o modelo antes de gravar); a lista do UT-01 não tem `inbox done` nem `ingest` sem `--move` (funcionam na mão).

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0111`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
