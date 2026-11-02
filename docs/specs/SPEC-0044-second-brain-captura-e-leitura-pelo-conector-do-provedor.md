---
id: SPEC-0044
title: "second-brain: captura e leitura pelo conector do provedor"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-02
parent:
depends_on: [SPEC-0021]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/connectors.md, skills/second-brain/references/mobile-capture.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0013, ADR-0008, ADR-0007, ADR-0002]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-02
---

# SPEC-0044 — second-brain: captura e leitura pelo conector do provedor

## 1. Visão Geral
O segundo cérebro passa a aceitar um segundo caminho de acesso: o **conector do provedor** que a ferramenta do agente tiver (por exemplo, o conector do Google Drive no app do Claude). O conector serve quando o agente não enxerga a pasta do vault: no celular, no navegador ou numa máquina sem a pasta montada.

Com ele, o agente pode fazer duas coisas:
- **Capturar:** gravar uma nota nova na `inbox/`. Só criar arquivo novo, nunca editar nem apagar.
- **Consultar:** ler notas, só para leitura, e responder citando as notas e avisando que a busca foi parcial.

Organizar continua sendo trabalho do computador com a pasta. O processamento da inbox, o índice, as relações e o `lint` seguem pelo `brain.py`, como hoje.

## 2. Motivação & Escopo
**Motivação:** o ADR-0008 escolheu a pasta sincronizada e deixou o acesso por API "para uma spec própria", que nunca foi criada. Na prática, a dependência da pasta montada apareceu em dois momentos:
- o macOS bloqueou o acesso desta sessão à pasta do Google Drive (TCC), e o vault teve de ir para `~/second-brain`;
- a captura pelo celular depende do app do provedor permitir enviar arquivos para a pasta.

Um conector resolve a captura e a consulta rápida de qualquer lugar sem mudar o `brain.py` para usar rede.

**Objetivos (dentro do escopo):**
- `brain.py capture TEXTO --print`: monta, sem escrever nada e sem exigir configuração, o caminho (relativo ao vault) e o conteúdo da nota de captura. São exatamente os mesmos que o `capture` gravaria, para o agente enviar pelo conector.
- Modo **"só conector"** no `SKILL.md`, para quando o `brain.py config` não enxerga o vault ou não há shell:
  - capturar → `capture --print` (ou, sem shell, o formato documentado) e enviar o arquivo para `inbox/` pelo conector;
  - consultar → buscar e ler pelo conector, citar `[[nota]]`, avisar que a busca é parcial e sem os vizinhos por link;
  - qualquer outra escrita → recusar e pedir para fazer no computador com a pasta.
- `references/connectors.md`: o que o modo faz, as regras, como identificar o conector de cada provedor e o conector do Google Drive conferido no diretório de conectores do Claude, com a data da conferência.
- `references/mobile-capture.md`: o conector como mais um canal de captura.

**Não-objetivos (fora do escopo):**
- `brain.py` chamando API de provedor ou usando rede. Continua proibido pelo ADR-0007 e pelo ADR-0008.
- Processar a inbox, gerar o índice, ligar notas ou rodar o `lint` pelo conector. Tudo isso segue pela pasta.
- Configurar ou autenticar o conector. Isso é do usuário, na ferramenta dele.
- Tarefa agendada na nuvem processando a inbox, que fica para uma spec futura.

## 3. Dependências
- **Implementações necessárias:** SPEC-0021 — `capture`, `capture_name` e o formato da nota de captura, `inbox list` e `inbox done`.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** um conector do provedor na ferramenta do agente, com permissão de criar e ler arquivos. Sem conector, nada muda.

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Segue o `cmd_capture` e o `capture_name` da SPEC-0021, e a regra do ADR-0007: o `brain.py` é só biblioteca padrão, não usa rede e é o único que escreve fora da inbox. O celular já escreve na `inbox/` sem o `brain.py` (SPEC-0021), e o conector é mais um escritor desse tipo, com a mesma regra: só cria arquivo novo na inbox.

**Decisão:** em `cmd_capture`, a opção `--print` monta o nome com `capture_name` e o conteúdo com a mesma função que o `capture` usa, e imprime os dois sem escrever. Sem configuração, usa `inbox` como pasta, ou o `--inbox` informado. O resto é instrução ao agente no `SKILL.md` e em `references/connectors.md`, decidido no ADR-0013.

**Justificativa:** mantém o `brain.py` sem rede e o mesmo para todos os provedores. Dá ao conector o formato exato que o fluxo da inbox já sabe processar, e nada muda para quem não usa conector.

**Desvio do padrão existente:** Nenhum. O ADR-0013 complementa o ADR-0008, sem substituí-lo.

**Alternativas descartadas:**
- **`brain.py` usando a API do provedor:** rede e credenciais no script, um cliente por provedor. O ADR-0008 já descartou.
- **Agente escrevendo notas organizadas direto pelo conector:** fura a regra de que só o `brain.py` escreve fora da inbox, sem log, sem índice e sem as garantias de não sobrescrever.
- **Não fazer nada:** mantém a captura de qualquer lugar dependente do app do provedor.

**ADRs:** ADR-0013 (criado por esta spec); ADR-0008, ADR-0007 e ADR-0002 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — o `capture --print` só monta texto.
- **Segurança:** pelo conector, só se cria arquivo novo dentro de `inbox/`, e nunca se edita, move ou apaga um arquivo do vault (regra no `SKILL.md`, verificada no UT-03). O `--print` não escreve nada (IT-01).
- **Privacidade e dados pessoais:** o conector envia o conteúdo ao provedor que o usuário já usa para o vault. Nada vai para outro lugar. Credenciais ficam com a ferramenta, nunca na skill.
- **Disponibilidade e resiliência:** sem conector, ou com o conector sem permissão, o agente avisa e sugere os outros canais (`references/mobile-capture.md`). Se já existir um arquivo com o nome na inbox, o agente gera outro nome com o `--print` (o nome tem segundos) ou acrescenta `-1`.
- **Acessibilidade (UI):** N/A — CLI e instruções.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** opção `capture --print` e o modo "só conector" no `SKILL.md`.

```text
brain.py capture TEXTO --print [--context C] [--inbox PASTA] [--json]
  não escreve nada (nem no vault, nem na configuração local, nem no log)
  não exige configuração: com configuração usa layout.inbox; sem ela, "inbox" ou o --inbox informado
  nome: o mesmo do capture (capture_name), relativo ao vault: "<inbox>/AAAA-MM-DD-HHMMSS-<slug>.md"
  conteúdo: o mesmo do capture (frontmatter type: capture, created, context? + texto)
  texto: "<caminho>\n\n<conteúdo>"; json: {"path": "<caminho>", "content": "<conteúdo>"}
  TEXTO vazio: exit 2 (como o capture); contexto inválido com configuração: exit 2

SKILL.md — modo "só conector" (o `brain.py config` sai com 3, ou com 0 mas sem enxergar o vault, ou não há shell,
  e a ferramenta tem um conector do provedor):
  capturar: montar com `capture --print --json` (sem shell: nome AAAA-MM-DD-HHMMSS-<slug>.md e frontmatter
    type/created do references/connectors.md) e criar o arquivo em <vault>/inbox/ pelo conector; nunca sobrescrever
  consultar: buscar e ler pelo conector, só leitura; citar [[nota]]; avisar que é parcial (sem o índice e sem os
    vizinhos por link) e sugerir o fluxo completo no computador
  qualquer outra escrita (nota organizada, relação, índice, mover, apagar): recusar e explicar que é feita no
    computador com a pasta
  depois, no computador: "processa minha inbox" segue o fluxo da SPEC-0021

references/connectors.md: o modo, as regras, o formato da nota de captura, como achar o conector de cada provedor
  (Google Drive conferido no diretório de conectores do Claude em 2026-11-02; OneDrive, iCloud e outros:
  "não conferido") e os limites
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Mesmo arquivo do capture | `capture --print` e `capture` com o mesmo relógio | mesmo caminho e mesmo conteúdo | UT-01 |
| Sem configuração | `capture --print` sem `BRAIN_CONFIG_HOME` configurado | exit 0, caminho em `inbox/`, nada escrito | IT-01 |
| JSON | `--json` | `{"path", "content"}` | IT-01 |
| Pasta da inbox | com configuração (`layout.inbox: Inbox`) e com `--inbox entrada` | o caminho usa a pasta certa | UT-02 |
| Texto vazio | `capture "" --print` | exit 2 | IT-01 |
| Ida e volta | arquivo do `--print` gravado na inbox por fora | `inbox list` mostra como `text`; `inbox done` funciona | IT-02 |
| Instruções | `SKILL.md`, `connectors.md`, `mobile-capture.md` | modo só conector com as regras | UT-03 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — o `capture` da SPEC-0021 já é coberto pelos testes dela e não muda.

### 7.2 Testes Unitários
- **UT-01** — Dado um relógio fixo e um texto, quando o conteúdo e o nome são montados para `capture --print` e para `capture`, então são iguais byte a byte.
- **UT-02** — Dado uma configuração com `layout.inbox: Inbox`, quando roda `capture --print`, então o caminho começa com `Inbox/`; sem configuração e com `--inbox entrada`, começa com `entrada/`; sem nada, com `inbox/`.
- **UT-03** — Dado `SKILL.md`, `references/connectors.md` e `references/mobile-capture.md`, quando lidos, então o `SKILL.md` tem o modo "só conector" com as regras (só criar arquivo novo em `inbox/`, nunca editar, mover ou apagar; consulta só leitura, citando `[[nota]]` e avisando que é parcial; recusar outras escritas), `connectors.md` traz o formato da captura e o Google Drive com a data da conferência, e `mobile-capture.md` cita o conector.

### 7.3 Testes de Integração
- **IT-01** — Dado `HOME` e `BRAIN_CONFIG_HOME` vazios, quando roda `capture "Ideia rápida" --print` e `--print --json`, então sai com 0, mostra o caminho `inbox/AAAA-MM-DD-HHMMSS-ideia-rapida.md` e o conteúdo, não cria nenhum arquivo e não grava configuração; e `capture "" --print` sai com 2.
- **IT-02** — Dado um vault criado pelo `init`, quando o arquivo devolvido por `capture --print --json` é gravado na inbox por fora do `brain.py` (simulando o conector), então `inbox list --json` mostra o item como `text` e `inbox done ITEM --note X` o move para `raw/processed/`.

### 7.4 Testes de Contrato
- N/A — sem contrato entre specs; o formato da captura é o da SPEC-0021, coberto pelo UT-01 e pelo IT-02.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração. O uso do conector é feito pela ferramenta do agente, fora do `brain.py`, e as instruções são verificadas no UT-03.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** vaults e configurações temporários; relógio injetável; `BRAIN_CONFIG_HOME` e `HOME` isolados.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto. A opção e as instruções são novas, e nada muda para quem não usa conector.
- **Dados/schema:** N/A.
- **Compatibilidade:** `capture` sem `--print` não muda.
- **Observabilidade:** a captura pelo conector aparece no `inbox list` e, depois de processada, no `log.md`.
- **Rollback:** `git revert` do merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: capture --print**
- [x] Red: UT-01, UT-02 e IT-01 com a tag `SPEC-0044:<ID>`, falhando pelo motivo certo
- [x] Green: opção `--print` (com `--json` e `--inbox`), sem escrever nada e sem exigir configuração
- [x] Refactor mantendo tudo verde

**Fase 2: Ida e volta e instruções**
- [x] Red: IT-02 e UT-03 falhando pelo motivo certo
- [x] Green: modo "só conector" no `SKILL.md`, `references/connectors.md` e o canal em `mobile-capture.md`
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: pilar entrega dispensado
- [x] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — d71c978 | 2026-11-02 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=8)) — fa2b22c | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 5294eda | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 5294eda | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (5294eda; capture --print sem escrita com vault bloqueado/ausente/inbox ilegível, --inbox inválido recusado, precedência no SKILL.md; 2 nits de doc não bloqueantes) — 5294eda | 2026-11-02 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 84c40a0 | 2026-11-02 |
| H2 Integração aprovada | PASS | aprovado por política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-11-02 |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega

### O que foi entregue
Com o conector do provedor (por exemplo o do Google Drive no Claude), o agente consegue capturar e consultar o segundo cérebro sem a pasta do vault na máquina, como no celular ou numa conversa sem acesso ao disco. Para capturar, cria só um arquivo novo em `inbox/`, no formato do `capture`, que o `brain.py capture TEXTO --print` devolve sem escrever nada e sem exigir configuração. Para consultar, só lê, cita `[[nota]]` e avisa que a busca é parcial. As outras escritas são recusadas e ficam para o computador com a pasta. Quando o agente não consegue ler o vault (exit 3, ou exit 1 com a pasta bloqueada), o modo só conector tem prioridade, a menos que a pessoa queira configurar ou consertar a máquina.

### Como foi feito
- `scripts/brain.py` (`BRAIN_VERSION` 2026.11.2): `capture_note()` monta o conteúdo usado pelo `capture` e pelo `capture --print`. O `--print` aceita `--json` e `--inbox`. Com o vault, o `brain-config.yml` ou a inbox ilegíveis, ele usa `layout.inbox` (se pôde ser lido), senão `inbox` ou o `--inbox`. Um `--inbox` na raiz do vault ou fora dele sai com 2, e o `--inbox` só vale com `--print`. A regra do ADR-0007 continua valendo: o `--print` não escreve nada, nem no `log.md`.
- `SKILL.md` (seção "Modo só conector" e a precedência em "Antes de qualquer fluxo"), `references/connectors.md` (novo, com o Google Drive conferido em 2026-11-02) e `references/mobile-capture.md`. A decisão está no ADR-0013.
- Achados da revisão (G4 FAIL em bd507a0) corrigidos com testes vermelhos primeiro (6f6df09, `test_connector_review.py`, com as tags IT-01, UT-02 e UT-03) e depois a correção (a2f5141, 5294eda). A segunda revisão aprovou.
- Integração: conflito de versão com a SPEC-0043, que publicou a 2026.11.1 primeiro. A SPEC-0044 passou a ser a 2026.11.2 no merge 84c40a0.
- Sem emendas e sem dívida assumida. O G2 falhou duas vezes só em testes de tempo, com a máquina carregada (carga ~12), e passou com a carga em ~3,5.

### Prova de Correção
N/A — type feature.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | conteúdo e nome iguais em `capture` e `capture --print` | PASS | CI run 41430633575 (ci 3.9 e 3.15) em 84c40a0; G2 local em 5294eda |
| UT-02 | pasta da captura: `layout.inbox`, `--inbox` ou `inbox` | PASS | CI run 41430633575 (ci 3.9 e 3.15) em 84c40a0; G2 local em 5294eda |
| UT-03 | modo só conector no `SKILL.md`, `connectors.md` e `mobile-capture.md` | PASS | CI run 41430633575 (ci 3.9 e 3.15) em 84c40a0; G2 local em 5294eda |
| IT-01 | `--print` sem configuração não escreve nada; texto vazio sai com 2 | PASS | CI run 41430633575 (ci 3.9 e 3.15) em 84c40a0; G2 local em 5294eda |
| IT-02 | arquivo gravado por fora aparece no `inbox list` e sai com `inbox done` | PASS | CI run 41430633575 (ci 3.9 e 3.15) em 84c40a0; G2 local em 5294eda |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: pilar entrega dispensado, a skill é distribuída por cópia da pasta
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: o projeto não usa `living_docs`
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
N/A — sem deploy. A skill vale na máquina depois do merge, com a cópia de `skills/second-brain` para a pasta de skills do agente (README).

### Pendências
Nenhuma. Os dois detalhes da revisão ficam como observação, sem spec: com o vault ilegível, o `--print` usa `inbox/` mesmo que o vault use outra pasta (o agente pode passar `--inbox`), e o `--context` não é validado nesse caso.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0044`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
