---
id: SPEC-0052
title: "second-brain: localizar o vault pelo conector em sessão sem configuração"
tier: lite
type: fix
user_facing: false
status: in-progress
created: 2026-11-02
parent:
depends_on: [SPEC-0044]
consumes_contract: []
touches: [skills/second-brain/SKILL.md, skills/second-brain/references/connectors.md, skills/second-brain/tests/test_connector_instructions.py, skills/second-brain/scripts/brain.py, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0013]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-02
---

# SPEC-0052 — second-brain: localizar o vault pelo conector em sessão sem configuração

## 1. Problema
Em sessão nova na nuvem ou no celular (claude.ai, app), o `brain.py config` sai com 3: a configuração local (`$BRAIN_CONFIG_HOME/config.yml`) fica na máquina e não acompanha a sessão. Com o conector do provedor disponível, o agente deveria entrar direto no modo só conector (SPEC-0044), mas o `SKILL.md` não diz **como achar o vault** pelo conector nem proíbe perguntar sobre configuração. Na prática o agente pede o caminho do vault, comenta que "a skill não está configurada" ou começa o onboarding, quando bastaria localizar o `brain-config.yml` pelo conector.

**Impacto:** cada captura ou consulta pelo celular começa com perguntas de configuração que a pessoa não sabe ou não precisa responder.

## 2. Causa Raiz
Só instruções; o `brain.py` está correto (exit 3 sem configuração local é o contrato do SPEC-0017).
- `skills/second-brain/SKILL.md`, "Antes de qualquer fluxo": a regra **Sem enxergar o vault** manda para o modo só conector, mas não diz que exit 3 numa sessão nova é o caso normal nem como achar o vault.
- "Modo só conector": a lista começa em **Capturar**; não há o passo de localizar o vault e o `layout`.
- "Regras", primeiro item: só cobre o caso configurado.
- `references/connectors.md`, "Quando usar": mesma lacuna (não diz como localizar o vault). `references/config.md` não contradiz: descreve as duas camadas e o `brain-config.yml` na raiz do vault, que é justamente o que o conector procura.

## 3. Mudança Proposta
Só texto de instrução, com o mínimo de mudança:
1. `SKILL.md`, "Antes de qualquer fluxo", depois da lista de casos: parágrafo **"Exit 3 numa sessão nova é normal"** — a configuração local não acompanha sessões na nuvem ou no celular; com conector, antes de pensar em onboarding, buscar `brain-config.yml` pelo conector; achou → a pasta dele é o vault, entrar direto no modo só conector sem perguntar nem comentar configuração; onboarding só se o conector não achar o arquivo ou se a pessoa pedir para configurar esta máquina; pedido fora do modo só conector → explicar o limite em uma frase.
2. `SKILL.md`, "Modo só conector", primeiro item: **Localizar o vault** — buscar `brain-config.yml` pelo conector; a pasta dele é a raiz do vault, e o arquivo traz o `layout` (como a inbox); não pedir o caminho nem comentar a falta de configuração.
3. `SKILL.md`, "Regras", primeiro item: **`brain.py config` antes de qualquer fluxo.** Configurado → direto ao pedido, sem perguntar configuração. Exit 3 com conector → localizar o vault pelo conector e seguir, sem perguntar configuração.
4. `references/connectors.md`, "Quando usar": uma frase com o mesmo passo de localizar o vault (alinhamento mínimo).
   Nos dois lugares (item 2 e item 4): mais de um `brain-config.yml` → usar o que tem `index.md` e `log.md` na mesma pasta; se ainda sobrar mais de um, uma única pergunta curta sobre qual vault usar.
5. Versão: `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007), conforme a Questão 1.

**Não muda:** o limite do modo só conector (só consulta e captura na inbox; qualquer outra escrita exige o computador com a pasta do vault, ADR-0013); o comportamento do `brain.py` (o exit 3 continua igual); o onboarding e o `init --join`.

**Padrão seguido:** `skills/second-brain/SKILL.md` seção "Modo só conector" e `references/connectors.md` (SPEC-0044); teste de instruções `tests/test_connector_instructions.py` (SPEC-0044:UT-03), que checa as regras linha a linha.

**Rollback:** `git revert` do commit; só texto e a versão.

**Outras ocorrências:** Nenhuma — `references/mobile-capture.md` só aponta para o modo só conector e não trata de configuração.

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0052:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — as regras atuais do modo só conector já são checadas pelo SPEC-0044:UT-03 e continuam valendo.
- **UT-01** — Dado o `SKILL.md`, quando lido, então "Antes de qualquer fluxo" diz que exit 3 numa sessão nova é normal e manda buscar o `brain-config.yml` pelo conector antes do onboarding, sem perguntar nem comentar configuração, com onboarding só se não achar ou se a pessoa pedir; "Modo só conector" começa com **Localizar o vault** (a pasta do `brain-config.yml` é a raiz; `layout` dá a inbox; não pedir o caminho; com mais de um `brain-config.yml`, o que tem `index.md` e `log.md` ao lado, e só então uma pergunta curta); e a primeira regra cobre "Exit 3 com conector". Falha hoje porque nenhum desses trechos existe.
- **UT-02** — Dado `references/connectors.md`, quando lido, então "Quando usar" traz o passo de localizar o vault pelo `brain-config.yml`; e o `SKILL.md` continua dizendo que qualquer outra escrita no modo só conector é recusada (o limite não mudou).
- Integração/E2E: N/A — só instruções do agente; o `brain.py` não muda (ADR-0002: a jornada da CLI fica coberta pelos testes existentes).

## 5. Questões em Aberto
- [x] O pedido diz "não altere o `brain.py`", mas o ADR-0007 exige `BRAIN_VERSION` e CHANGELOG em toda mudança de comportamento da skill, e o zip do claude.ai usa a versão para saber o que está instalado. Recomendado: mudar só a constante `BRAIN_VERSION` (nenhuma lógica) e acrescentar a seção no CHANGELOG. (thomas) — só a constante `BRAIN_VERSION` e a seção no CHANGELOG, sem lógica (thomas, 2026-11-02)
- [x] Se o conector achar mais de um `brain-config.yml` (outro vault, uma cópia de backup, uma pasta antiga), o que fazer? Recomendado: usar o que tem `index.md` e `log.md` na mesma pasta; se ainda houver mais de um, fazer **uma** pergunta curta sobre qual vault usar (exceção à regra de não perguntar). (thomas) — usar o que tem `index.md` e `log.md` ao lado; se ainda houver mais de um, uma pergunta curta sobre qual vault (thomas, 2026-11-02)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
**Fase 1: Instruções do modo só conector**
- [ ] Red: UT-01 e UT-02 com a tag `SPEC-0052:<ID>`, falhando pelo motivo certo
- [ ] Green: `SKILL.md` (Antes de qualquer fluxo, Modo só conector, Regras) e `references/connectors.md`
- [ ] `BRAIN_VERSION` (só a constante) e seção no `skills/second-brain/CHANGELOG.md`
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega e CHANGELOG (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 1b3f11b (árvore suja) | 2026-11-02 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue

### Como foi feito

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Teste de regressão falhou antes e passa depois da correção
- [ ] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão existente mantido
- [ ] Disponível no ambiente-alvo via pipeline (G6)
- [ ] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [ ] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
