---
id: SPEC-0074
title: "gluon-spec: retrospectiva entre projetos (spec_graph.py retro)"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-17
parent: SPEC-0066
depends_on: []
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/tests/**, skills/gluon-spec/SKILL.md, skills/gluon-spec/CHANGELOG.md, skills/gluon-spec/references/retro.md, README.md, CHANGELOG.md, .claude-plugin/plugin.json]
adrs: [ADR-0001, ADR-0002, ADR-0006, ADR-0019]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0074 — gluon-spec: retrospectiva entre projetos (spec_graph.py retro)


## 1. Visão Geral
Novo comando só de leitura `spec_graph.py retro`, que lê os projetos feitos com o Fermion (pastas informadas e os `spec_root` do modo privado) e mostra o que o processo está seguindo e o que não está. O relatório traz números por projeto, achados com o que fazer e sugestões de spec para a própria skill. Nada é alterado nos projetos e nenhuma spec é criada sozinha (ADR-0019).

## 2. Motivação & Escopo
**Motivação:** o thomas pediu, em 2026-11-16, para medir o que é seguido de verdade nos projetos reais. Um levantamento manual em 2026-11-17 cobriu 25 projetos com specs: 8 pessoais e 17 em modo privado de organizações de terceiros. Os sinais:
- **Uma reprovação em cerca de 2.100 gates registrados.** A causa está na ferramenta: `gate` sobrescreve a linha, então o PASS apaga o FAIL anterior. O rigor real só aparece no histórico do git.
- **Specs paradas:** juker tem 23 de 28 em `approved` e o crash-games-provider 25 de 51. Vários projetos privados têm specs em `in-progress` com gates até o G5 e sem G7.
- **Evidência escrita à mão:**
  - Nos projetos privados, de 40% a 80% dos gates estão como `MANUAL:`.
  - No jogo-da-velha-multiplayer, nenhuma evidência foi gerada pela ferramenta (versão antiga).
- **N/A recorrente:** G6 em quase todos os projetos e G3 em 29 de 65 specs do jogo-da-velha-multiplayer.
- **Ferramenta atrasada:** os projetos pessoais têm `tools/sdd` em 2026.09.x, sem commit desde outubro.

Fazer esse levantamento à mão não se repete nem se compara ao longo do tempo. Um comando faz.

**Objetivos (dentro do escopo):**
- `retro [PASTA ...] [--registry] [--stale-days N] [--json] [--out ARQUIVO]`. Lê projetos com `docs/specs`, projetos em modo privado (pelo registro) e `spec_root` passados direto.
- Métricas por projeto:
  - Inventário: specs por status e tier, versão da ferramenta e última atividade.
  - Fluxo: specs paradas, entregues sem G7 e lead time do H1 ao G7.
  - Rigor dos gates: estado atual e reprovações no histórico do git.
  - Origem da evidência e N/A por gate.
  - Emendas e impedimentos.
- Achados com regras fixas (R1 a R7 do contrato), cada um com o número e o comando que resolve.
- Seção "O que ajustar na skill": regras que disparam em pelo menos metade dos projetos analisados viram sugestão de spec, em texto.
- Saída em Markdown (padrão) e em JSON neutro. Documentação em `references/retro.md`, tabela de comandos da `SKILL.md`, README e CHANGELOGs.

**Não-objetivos (fora do escopo):**
- Alterar qualquer arquivo nos projetos lidos, rodar `vendor` ou `upgrade` por eles, ou criar specs. O relatório só sugere.
- Guardar o histórico de FAIL no próprio Registro de Gates. A mudança no `gate` é outra spec, se a retrospectiva confirmar o problema.
- Tool MCP `sdd_retro` e agendamento periódico: são as frentes (5) e o MCP do épico, para depois.
- Ordem red→green por spec com `verify` nos projetos lidos: caro (exige checkout e base de cada spec); o G1 registrado já é contado.
- Projetos no layout legado (pastas de status): aparecem como ignorados com o motivo.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** `git` no PATH para o histórico de reprovações (sem ele, a coluna sai como "sem git" e o resto funciona)

## 4. Decisão Arquitetural
**Contexto:** a `gluon-spec` é um script só, stdlib, Python 3.9+ (ADR-0001). Comandos de leitura que agregam o estado já existem: `export` (`build_export`), `pillars` (N/A recorrente) e `whats-new` (versão do projeto contra a instalada). O modo privado resolve o `spec_root` pelo registro em `SDD_CONFIG_HOME` (ADR-0006).

**Decisão:** novo `cmd_retro` no `spec_graph.py`, que reutiliza `Project`, `parse_tables`, `open_impediments`, a leitura do registro do modo privado e a comparação de versões do `whats-new`. O histórico de reprovações vem de `git log -p` só da pasta de specs, com `GIT_OPTIONAL_LOCKS=0`, e conta as linhas removidas do Registro de Gates com status FAIL. A classificação da evidência segue o que o próprio `gate` escreve:
- **gerada:** formato do `--run`;
- **manual:** prefixo `MANUAL:`;
- **humana:** `aprovado por`;
- **à mão:** o resto.

**Justificativa:** mesmo padrão dos comandos de leitura já existentes. Não precisa de dependência nem de arquivo novo de código, e continua instalável por cópia.

**Desvio do padrão existente:** Nenhum

**Alternativas descartadas:**
- Script separado em `tools/`: fugiria do ADR-0001 e não chegaria aos projetos.
- Ler o `export --out` de cada projeto: exigiria rodar a ferramenta vendorizada de cada um, em versões antigas e sem o histórico.
- Criar as specs sugeridas automaticamente: contraria o ADR-0019.

**ADRs:** ADR-0001 (um script, stdlib), ADR-0002 (CLI coberta por integração), ADR-0006 (modo privado e registro), ADR-0019 (só lê e avisa)

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** os 25 projetos desta máquina em menos de 15 s, medido na revisão (G4) com `time`.
- **Segurança:** só lê. Nenhum arquivo dos projetos é criado ou alterado, e o git roda só com `log`, sem lock (IT-01 compara o estado antes e depois). Os caminhos vêm só dos argumentos e do registro.
- **Privacidade e dados pessoais:** projetos privados são de terceiros. O relatório traz nome da pasta ou chave do registro, IDs de spec e números. Ficam de fora títulos, evidências, motivos de N/A e textos de impedimento (UT-04). O relatório não é gravado em lugar nenhum sem `--out`.
- **Disponibilidade e resiliência:** projeto ilegível, spec malformada ou repositório sem git não derrubam o relatório. O projeto entra como ignorado ou com a coluna "sem git", e o motivo aparece.
- **Acessibilidade (UI):** N/A — saída de terminal
- **Custo:** N/A — local, sem rede

## 6. Artefato A — Contrato
**Interface:** `spec_graph.py retro [PASTA ...] [--registry] [--stale-days N] [--json] [--out ARQUIVO]`

```text
Entradas
  PASTA          raiz de projeto (docs/specs, ou modo privado resolvido pelo registro)
                 ou spec_root (pasta com sdd-config.yml e specs/). Sem PASTA e sem
                 --registry: o projeto atual.
  --registry     inclui todos os spec_root do registro do modo privado
                 (SDD_CONFIG_HOME, padrão ~/.config/sdd/projects.json); duplicatas
                 (mesma pasta de specs) contam uma vez.
  --stale-days N inteiro >= 1; padrão 30. Limite para "parada" (R2) e impedimento velho (R7).
  --json         JSON em vez de Markdown.
  --out ARQUIVO  grava a saída no arquivo (único arquivo escrito pelo comando).

Métricas por projeto (nome = pasta ou chave do registro; private: true|false)
  specs            total e por status e por tier
  tool             versão da ferramenta do projeto (tools/sdd/spec_graph.py, senão
                   sdd_version do sdd-config; "desconhecida" sem nenhum) e a instalada
  last_activity    data mais recente entre created, approved_at e datas de gate
  stale            IDs approved/in-progress sem atividade há mais de N dias
  unclosed         IDs approved/in-progress com G5 PASS e G7 não PASS
  lead_time_days   mediana e p90 de approved_at até a data do G7 PASS (implementadas)
  gates            PASS, FAIL e N/A atuais por gate (G0–G7, H2)
  fail_history     linhas FAIL removidas do Registro de Gates no git das specs;
                   null quando a pasta não está num repositório git
  evidence         G0–G5 PASS por origem: gerada | manual | humana | a_mao
  na_by_gate       por gate: N/A e total registrado
  amendments       linhas de Emendas (total e por spec)
  impediments      total, abertos e abertos há mais de N dias (IDs)

Achados (regras fixas; cada um: regra, projeto, valor, ação)
  R1 ferramenta atrasada   versão do projeto < instalada ou desconhecida
                           → `whats-new` e `vendor --force` (privado: `whats-new --ack`)
  R2 spec parada           stale não vazio → retomar, fechar ou marcar deprecated
  R3 entregue sem fechar   unclosed não vazio → fechar o G7 (Relatório de Entrega)
  R4 evidência à mão       (manual + a_mao) / G0–G5 PASS > 30%, com >= 10 PASS
                           → `gate <G> --run`; revisar os comandos do sdd-config
  R5 nenhuma reprovação    >= 20 PASS de G1–G5, fail_history == 0 e nenhum FAIL atual
                           (Emenda v2)
                           → conferir se os gates rodam (`--run`) e se reprovações
                             são registradas com `gate --fail`
  R6 N/A recorrente        gate com N/A em >= 50% das specs que o registram (mín. 5)
                           → dispensa em `pillars.waived` ou spec da capacidade que falta
  R7 impedimento velho     aberto há mais de N dias → resolver ou `resolve`

"O que ajustar na skill": regra que dispara em >= 50% dos projetos analisados
(mín. 2) vira uma linha com sugestão de spec, em texto, da tabela fixa de títulos
de references/retro.md. Nunca cria arquivo.

Saída Markdown: Resumo | Projetos (tabela) | N/A por gate | Achados | O que ajustar
na skill | Ignorados (pasta e motivo).
Saída JSON: {"retro_version": 1, "generated_at", "installed_tool", "stale_days",
"projects": [...métricas...], "findings": [{"rule","project","value","action"}],
"skill_suggestions": [{"rule","projects","suggestion"}],
"ignored": [{"path","reason"}]}

Erros
  exit 2  PASTA não existe → "pasta não encontrada: <pasta>"
  exit 2  --stale-days não é inteiro >= 1
  exit 2  nenhum projeto analisável → "nenhum projeto SDD encontrado" + ignorados
  exit 0  relatório gerado (com ou sem achados); pasta sem specs, layout legado ou
          ilegível entra em "Ignorados" com o motivo
```

**Design:** N/A — sem interface

**Arquivos/módulos afetados:** ver `touches`.
- `cmd_retro` e as funções de métrica ficam em `spec_graph.py`.
- `references/retro.md` traz as regras, os limites e a tabela de sugestões.
- Linha nova na tabela de comandos da `SKILL.md`.
- Versão da skill e do plugin.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Métricas de um projeto | projeto com specs em vários status, gates, emendas e impedimentos | contagens, lead time e origem da evidência corretos | UT-01, IT-01 |
| Reprovações no histórico | spec que teve G2 FAIL num commit e PASS no seguinte | fail_history = 1 com a tabela atual sem FAIL | UT-02, IT-01 |
| Sem git | pasta de specs fora de repositório git | fail_history null, "sem git", resto calculado | UT-02 |
| Regras R1–R7 | valores no limite e logo abaixo | dispara no limite, não dispara abaixo; ação correta | UT-03 |
| Sugestão para a skill | regra em >= 50% dos projetos (mín. 2) | linha em "O que ajustar na skill"; nenhum arquivo criado | UT-03, IT-01 |
| Privacidade | títulos, evidências, motivos de N/A, impedimentos e slug do nome do arquivo com marcadores | nenhum marcador na saída Markdown nem JSON; spec sem `id` aparece só como `SPEC-NNNN` | UT-04 |
| Projeto ilegível (Emenda v2) | spec não UTF-8, arquivo ou pasta de specs sem permissão de leitura, ao lado de um projeto válido | exit 0; o projeto ilegível em "Ignorados" com o motivo; o válido no relatório | UT-07 |
| Histórico ilegível (Emenda v2) | arquivo não UTF-8 commitado na pasta de specs | só `fail_history` null; o resto do projeto calculado | UT-07 |
| Pasta em worktree ou sem remoto (Emenda v2) | PASTA numa worktree de projeto privado; repositório sem remoto | worktree resolvida pelo `commondir` para o mesmo projeto do registro, contado uma vez; sem remoto, projeto público pelo caminho | UT-08 |
| Modo privado | `--registry` com spec_root registrado | projeto privado incluído uma vez, com private: true | IT-01 |
| Só leitura | relatório sobre projetos reais temporários | arquivos, HEAD e status do git idênticos antes e depois | IT-01 |
| Saída JSON e arquivo | `--json --out` | JSON válido com as chaves do contrato; só o arquivo de saída é criado | IT-02 |
| Pasta inexistente | PASTA que não existe | exit 2 + "pasta não encontrada" | UT-05 |
| Pasta sem specs / legado | uma pasta válida e outra sem specs ou em layout legado | exit 0; a segunda em "Ignorados" com o motivo | UT-05 |
| Nada analisável | só pastas ignoradas | exit 2 + "nenhum projeto SDD encontrado" | UT-05 |
| `--stale-days` inválido | 0, negativo ou texto | exit 2 | UT-06 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo; os comandos existentes não mudam e já têm testes

### 7.2 Testes Unitários
- **UT-01** — Dado um projeto temporário com specs `proposed`, `approved` (uma parada há 40 dias, outra com G5 PASS sem G7), `in-progress` e `implemented` (`approved_at` e G7 com datas conhecidas), gates com evidência gerada, `MANUAL:`, `aprovado por` e à mão, N/A em G3 e G6, emendas e um impedimento aberto, quando as métricas são calculadas com `--stale-days 30`, então inventário, `stale`, `unclosed`, lead time (mediana e p90), gates, origem da evidência, `na_by_gate`, emendas e impedimentos batem com os valores esperados.
- **UT-02** — Dado um repositório git temporário em que uma spec teve G2 FAIL num commit e PASS no seguinte, quando o histórico é lido, então `fail_history` = 1 e a contagem atual de FAIL = 0; dada a mesma pasta copiada para fora de um repositório git, então `fail_history` é null e o projeto aparece com "sem git".
- **UT-03** — Dadas métricas sintéticas no limite de cada regra e logo abaixo, quando os achados são calculados, então cada uma de R1 a R7 dispara no limite com a ação do contrato e não dispara abaixo. Com 4 projetos e uma regra em 2 deles, ela aparece em "O que ajustar na skill"; em 1 deles, não aparece.
- **UT-04** — (Emenda v2: inclui spec sem `id` com marcador no slug do nome do arquivo, que sai só como `SPEC-NNNN`) Dado um projeto com marcadores únicos em títulos, evidências, motivos de N/A e descrições de impedimento, quando o relatório sai em Markdown e em JSON, então nenhum marcador aparece.
- **UT-05** — Dada uma pasta inexistente, quando `retro` roda, então exit 2 com "pasta não encontrada". Dadas uma pasta válida, uma sem specs e uma em layout legado, então exit 0 e as duas últimas em "Ignorados" com o motivo. Dadas só as duas últimas, então exit 2 com "nenhum projeto SDD encontrado".
- **UT-06** — Dado `--stale-days` igual a 0, -3 ou "abc", quando `retro` roda, então exit 2 com mensagem de uso.
- **UT-07** — (Emenda v2) Dado um projeto válido ao lado de outro com uma spec não UTF-8, de outro com um arquivo de spec sem permissão de leitura e de outro com a pasta de specs sem permissão, quando `retro` roda, então exit 0, o válido no relatório e cada ilegível em "Ignorados" com o motivo, sem traceback; dado um arquivo não UTF-8 commitado na pasta de specs de um projeto válido, então só `fail_history` é null e o resto é calculado. R5 não dispara com FAIL atual na tabela.
- **UT-08** — (Emenda v2) Dada a PASTA numa worktree git de um projeto privado registrado, quando `retro <worktree> --registry` roda, então o projeto aparece uma vez, como privado; dado um repositório sem remoto, então é tratado como projeto público pelo caminho.

### 7.3 Testes de Integração
- **IT-01** — Dados dois repositórios git temporários reais, um com `docs/specs` e outro em modo privado com `spec_root` registrado num `SDD_CONFIG_HOME` temporário, quando o script roda como processo com `retro <projeto público> --registry`, então:
  - o Markdown traz os dois projetos (o privado uma vez só, com private: true), os achados esperados e a seção "O que ajustar na skill";
  - o conteúdo e o mtime de todos os arquivos, o HEAD e o `git status --porcelain` dos dois repositórios e do `spec_root` ficam iguais antes e depois.
- **IT-02** — Dado o mesmo cenário, quando roda com `--json --out <arquivo temporário>`, então o arquivo contém JSON válido com as chaves do contrato (`retro_version` = 1), a saída padrão diz onde gravou e nenhum outro arquivo é criado.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs

### 7.5 Testes E2E
- N/A — a jornada é a CLI e, conforme o ADR-0002, é coberta pelos testes de integração

### 7.6 Outros
- Desempenho (RNF): `time python3 skills/gluon-spec/scripts/spec_graph.py retro <os projetos desta máquina> --registry` abaixo de 15 s. Na revisão (G4), o relatório real é comparado com o levantamento manual de 2026-11-17 desta spec.

**Dublês e dados de teste:** projetos e repositórios git temporários com specs sintéticas, `SDD_CONFIG_HOME` temporário, data de hoje fixa por parâmetro interno nas métricas, nunca o `~/.config/sdd` real.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15), com `git` no PATH.

## 8. Plano de Rollout
- **Estratégia:** merge direto. Comando novo, opt-in, que nada chama sozinho.
- **Dados/schema:** N/A — só lê; `retro_version` no JSON permite mudar o formato depois.
- **Compatibilidade:** os comandos existentes não mudam. A `tools/sdd` dos projetos ganha o comando quando eles rodarem `vendor --force`.
- **Observabilidade:** o próprio relatório; a primeira execução real nos projetos desta máquina fica registrada no Relatório de Entrega (só números agregados).
- **Rollback:** `git revert` do merge; nenhum projeto lido foi alterado.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Quais projetos a retrospectiva cobre? — pastas informadas, o projeto atual e, com `--registry`, os `spec_root` do modo privado; a busca automática em pastas fica de fora para não varrer o disco (thomas, 2026-11-17, piloto automático com o recomendado)
- [x] O relatório pode citar títulos e textos das specs? — não: só nomes de projeto, IDs e números, porque os projetos privados são de terceiros (thomas, 2026-11-17, piloto automático com o recomendado)
- [x] Os limites das regras (30 dias, 30%, 20 gates, 50%) são fixos? — fixos nesta versão e documentados em `references/retro.md`; só `--stale-days` é parâmetro. Ajuste depois de rodar nos dados reais vira emenda (thomas, 2026-11-17, piloto automático com o recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
- [x] Fase 1 (test-writer): UT-01 a UT-06, IT-01 e IT-02 com a tag `SPEC-0074:<ID>`, falhando pelo motivo certo
- [x] Fase 2 (implementer): `cmd_retro` e métricas em `spec_graph.py`, `references/retro.md`, linha na `SKILL.md`, README, CHANGELOGs e versões da skill e do plugin
- [ ] Emenda v2: test-writer (UT-04 ampliado, UT-07, UT-08 e R5 com FAIL atual) e implementer (resiliência, histórico ilegível, R5, ID sem slug)
- [ ] Fase 3 (reviewer): G4 independente, com o desempenho e a comparação com o levantamento manual (7.6)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 2e2f265 | 2026-11-17 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=8, skipped=1)) — 8fddd6f | 2026-11-17 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 10b8a7f | 2026-11-17 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 6fd76b8 | 2026-11-17 |
| G4 Review | FAIL | reviewer independente: CHANGES_REQUESTED — major: spec malformada/ilegível derruba o relatório (RNF de resiliência); minors: fail_history com arquivo não UTF-8, R5 ignora FAIL atual, slug do título vaza em spec sem id; lacunas de teste | 2026-11-17 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0074`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-17 | R5 também exige nenhum FAIL atual; UT-04 ampliado (slug do arquivo); UT-07 (projeto e histórico ilegíveis) e UT-08 (worktree e sem remoto); texto da Motivação sem nome de organização | G4 da revisão independente: relatório caía com spec ilegível, R5 dizia "nenhuma reprovação" com FAIL em aberto, slug do título vazava; repositório público | — | thomas, 2026-11-17 (piloto automático com o recomendado) |
