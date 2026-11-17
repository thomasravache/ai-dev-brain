---
id: SPEC-0070
title: "boson-atlas: configuração, pasta .boson-atlas e mensagens com o nome novo e leitura dupla"
tier: full
type: migration
user_facing: false
status: in-progress
created: 2026-11-16
parent: SPEC-0067
depends_on: []
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/**, skills/boson-atlas/references/config.md, skills/boson-atlas/references/modes.md, skills/boson-atlas/references/maintenance.md, skills/boson-atlas/assets/atlas-config.yml, skills/boson-atlas/assets/ci/**, skills/boson-atlas/assets/pages/**, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, .claude-plugin/plugin.json, tests/plugin/test_skill_names.py]
adrs: [ADR-0010, ADR-0018, ADR-0019, ADR-0020]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0070 — boson-atlas: configuração, pasta .boson-atlas e mensagens com o nome novo e leitura dupla

## 1. Visão Geral
A `boson-atlas` passa a usar o próprio nome no que é técnico: a configuração da máquina vira `~/.config/boson-atlas`, a cópia da skill que a CI do atlas roda vira `.boson-atlas/skill/`, e mensagens, `--version`, cabeçalhos e arquivos de CI gerados dizem `boson-atlas`. Máquinas e atlas configurados com `org-atlas` continuam funcionando sem ação: leitura dupla, gravação só no nome novo e aviso do `doctor` com o comando de migração.

## 2. Motivação & Escopo
**Motivação:** depois da SPEC-0055 a skill se chama `boson-atlas`, mas a configuração, a pasta do atlas e as mensagens ainda dizem `org-atlas` (épico SPEC-0067, ADR-0020).

**Objetivos (dentro do escopo):**
- Configuração local: `--config-home`/`ATLAS_CONFIG_HOME` (sem mudança) → `~/.config/boson-atlas/config.yml` se existir → `~/.config/org-atlas/config.yml` se existir → `~/.config/boson-atlas/config.yml`; gravação (`init`, `init --join`) sempre na nova, com o conteúdo completo; a antiga nunca é gravada, movida nem apagada.
- Pasta do atlas: `vendor` grava `.boson-atlas/skill/` e arquivos de CI que a usam; `lint`, `build`, `scan` e a checagem de cópia desatualizada tratam `.org-atlas/skill/` e `.boson-atlas/skill/` do mesmo jeito (a cópia da ferramenta nunca é lida como conteúdo do atlas).
- Atlas com CI personalizada que ainda roda `.org-atlas/skill` (arquivo de CI mantido sem `--force`): o `vendor` continua atualizando `.org-atlas/skill/`, para a CI não rodar uma cópia velha, e avisa como migrar (`vendor --force`, depois `git rm -r .org-atlas`).
- `doctor` da máquina: AVISO quando só a configuração antiga existe (comando de cópia) e quando as duas existem (a antiga é ignorada); com o atlas configurado, AVISO quando o atlas tem `.org-atlas/` (com o passo de migração).
- Textos: `NOT_CONFIGURED`, cabeçalho do `config.yml` local, `--version`, `--help`, `assets/atlas-config.yml` (só atlas novos), `assets/ci/*` e as instruções finais do `vendor`.
- Referências `config.md`, `modes.md`, `maintenance.md` e `SKILL.md`; `ATLAS_VERSION` e CHANGELOG com a data de remoção (SPEC-0073).

**Não-objetivos (fora do escopo):**
- O nome do contrato dos coletores (SPEC-0071).
- Rodar git no atlas, apagar `.org-atlas/` ou mover a configuração (ADR-0010, ADR-0019).
- O aviso no `fermion_doctor` e a guarda de nomes do repositório (SPEC-0072); a remoção da leitura antiga (SPEC-0073).

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** brownfield; `local_config_path` em `skills/boson-atlas/scripts/atlas.py` resolve `config_home` → `ATLAS_CONFIG_HOME` → pasta padrão; `SKILL_COPY` (`.org-atlas/skill`) é usado por `copy_skill`, `cmd_vendor`, pela listagem de arquivos do atlas e pela checagem de cópia desatualizada; os arquivos de CI vêm de `assets/ci/`. Mesmo padrão da SPEC-0069 para a configuração.

**Decisão:** separar caminho de leitura e de gravação da configuração (como na SPEC-0069); trocar a constante `SKILL_COPY` por `SKILL_COPIES = (".boson-atlas/skill", ".org-atlas/skill")` nas leituras e por uma escolha de destino no `vendor` (a pasta que o arquivo de CI efetivamente gravado usa).

**Justificativa:** leitura dupla com remoção anunciada (ADR-0020), sem rodar git nem mudar arquivos que a pessoa não pediu (ADR-0010, ADR-0019); o atlas compartilhado pode ser usado por máquinas em versões diferentes, e as duas pastas funcionam nas duas versões.

**Desvio do padrão existente:** muda a pasta padrão de configuração e a do atlas vendorizado — coberto pelo ADR-0020 e pelo `type: migration` do épico.

**Alternativas descartadas:** o `vendor` apagar `.org-atlas/` (roda fora do que a pessoa pediu e quebraria a CI personalizada); sempre gravar `.boson-atlas/` (a CI personalizada continuaria rodando a cópia velha sem aviso).

**ADRs:** ADR-0010, ADR-0018, ADR-0019, ADR-0020.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — checagens de existência a mais.
- **Segurança:** a configuração local guarda só nomes de credenciais; o `lint` continua procurando segredo no atlas sem tratar nenhuma das cópias da ferramenta como conteúdo (UT-06).
- **Privacidade e dados pessoais:** N/A.
- **Disponibilidade e resiliência:** máquina e atlas antigos funcionam sem ação (IT-01); CI personalizada nunca fica rodando cópia velha (UT-05).
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** `atlas.py` (CLI), `local_config_path`, `local_config_write_path`, `SKILL_COPIES`, `cmd_vendor`

```text
Leitura da configuração local: --config-home DIR | $ATLAS_CONFIG_HOME → DIR/config.yml; senão ~/.config/boson-atlas/config.yml;
  senão ~/.config/org-atlas/config.yml; senão ~/.config/boson-atlas/config.yml (não configurado). Gravação: sempre a nova (ou DIR).
Mensagens: "boson-atlas não configurado nesta máquina — rode init (ou init --join)"; --version → "boson-atlas <ATLAS_VERSION>".
vendor --ci github|generic [--force]:
  arquivo de CI ausente ou regravado → grava .boson-atlas/skill/ e a CI aponta para ela; se .org-atlas/ existe: imprime
    "pode apagar .org-atlas/ (git rm -r .org-atlas) depois que a CI rodar com .boson-atlas/"
  arquivo de CI mantido (personalizado, sem --force) que roda .org-atlas/skill → atualiza .org-atlas/skill/ e imprime
    "a CI ainda roda .org-atlas/skill — para migrar: vendor --ci <ci> --force e depois git rm -r .org-atlas"
  instrução final: "Faça commit de .boson-atlas/ (ou .org-atlas/) e do arquivo da CI…"
lint/build/scan e a checagem de cópia desatualizada: as duas pastas são a ferramenta, nunca conteúdo do atlas.
doctor: só a configuração antiga → AVISO com "mkdir -p ~/.config/boson-atlas && cp -p ~/.config/org-atlas/config.yml ~/.config/boson-atlas/";
  as duas → AVISO "~/.config/org-atlas é ignorada"; atlas com .org-atlas/ → AVISO com o passo de migração do vendor.
Exit codes e formato do --json: sem mudança.
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Máquina antiga sem ação | só `~/.config/org-atlas/config.yml` | todos os comandos leem a antiga e funcionam | UT-01, IT-01 |
| Máquina nova | nenhuma pasta | `init` grava só na nova; mensagem "boson-atlas não configurado" antes | UT-02 |
| Gravação com só a antiga | `init --join` | configuração completa na nova; antiga idêntica byte a byte | UT-03 |
| Sobrescrita | `ATLAS_CONFIG_HOME`/`--config-home` | só essa pasta, sem aviso de caminho antigo | UT-04 |
| vendor em atlas novo ou com CI regravada | `vendor --ci github` (sem CI ou com `--force`) | grava `.boson-atlas/skill/` e CI apontando para ela; avisa que `.org-atlas/` pode sair | UT-05, IT-02 |
| vendor com CI personalizada antiga | CI mantida que roda `.org-atlas/skill` | atualiza `.org-atlas/skill/` e mostra como migrar | UT-05 |
| Ferramenta não é conteúdo | atlas com `.org-atlas/skill/` ou `.boson-atlas/skill/` | `lint`/`build` não acusam nem indexam a cópia; cópia velha avisada nas duas | UT-06 |
| doctor | configuração antiga, as duas, atlas com `.org-atlas/` | AVISOs com o comando; exit sem mudança | UT-07 |
| Textos | `--version`, `--help`, não configurado, cabeçalhos, `assets/ci/*` | dizem `boson-atlas` | UT-08, CH-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Dada a suíte atual da `boson-atlas` (guarda: passa antes da mudança), quando roda depois da mudança com as expectativas de texto e de pasta atualizadas, então nada mais muda (exit codes, `--json`, grafo, páginas, contrato).

### 7.2 Testes Unitários
- **UT-01** — Dado `HOME` temporário com só a pasta antiga, ou com as duas, quando `local_config_path()` resolve, então devolve a antiga no primeiro caso e a nova no segundo.
- **UT-02** — Dado `HOME` temporário sem pastas, quando a leitura e a gravação resolvem, então as duas apontam para `~/.config/boson-atlas/config.yml`, e o `init` cria só ela.
- **UT-03** — Dado só a pasta antiga, quando `init --join` grava, então a nova tem a configuração completa com a mudança e a antiga fica idêntica byte a byte.
- **UT-04** — Dado `ATLAS_CONFIG_HOME` (ou `--config-home`) com as duas pastas padrão presentes, quando lê, grava e roda `doctor`, então só a sobrescrita é usada e não há aviso de caminho antigo.
- **UT-05** — Dado um atlas (a) sem CI, (b) com `.org-atlas/` e CI gerada pela versão anterior regravada com `--force`, (c) com CI personalizada que roda `.org-atlas/skill` mantida sem `--force`, quando `vendor` roda, então (a) e (b) gravam `.boson-atlas/skill/` com CI apontando para ela e (b) avisa que `.org-atlas/` pode sair, e (c) atualiza `.org-atlas/skill/` e mostra o passo de migração; nunca apaga nada.
- **UT-06** — Dado um atlas com uma cópia da ferramenta em `.org-atlas/skill/` e outro em `.boson-atlas/skill/`, quando `lint` e `build` rodam, então nenhuma das cópias é tratada como conteúdo, e uma cópia desatualizada é avisada nas duas pastas.
- **UT-07** — Dado só a configuração antiga, depois as duas, depois um atlas com `.org-atlas/`, quando `doctor` (texto e `--json`) roda, então há os AVISOs do contrato, sem mudar exit code nem formato.
- **UT-08** — Quando `--version`, `--help`, um comando sem configuração e o `init` rodam, e os arquivos de `assets/ci/` e `assets/atlas-config.yml` são lidos, então dizem `boson-atlas` e rodam `.boson-atlas/skill`.

### 7.3 Testes de Integração
- **IT-01** — Dada uma máquina simulada configurada pela versão anterior em `~/.config/org-atlas` e um atlas real temporário com `.org-atlas/skill/`, quando `scan` (coletor generic), `build`, `lint`, `context` e `doctor` rodam pela CLI, então tudo funciona sem ação.
- **IT-02** — Dado um atlas temporário configurado em modo repositório, quando `vendor --ci generic` roda e depois o `atlas-scan.sh` gerado roda (com o `atlas.py` da cópia), então a CI usa `.boson-atlas/skill` e sai com 0 ou 10.

### 7.4 Testes de Contrato
- N/A — o contrato dos coletores fica na SPEC-0071; o MCP (SPEC-0054) só repassa a saída e sua suíte roda no G5.

### 7.5 Testes E2E
- N/A — nenhuma jornada muda de passos: os mesmos comandos funcionam com os nomes antigos ou novos (IT-01 e IT-02 rodam a CLI como processo).

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários (helpers de `skills/boson-atlas/tests/helpers.py`); atlas em pastas temporárias; coletor generic; nunca o `~/.config` real nem rede.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/boson-atlas/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin e pela cópia da skill.
- **Dados/schema:** N/A — formatos iguais; só pastas, com leitura dupla.
- **Compatibilidade:** máquinas em versões diferentes usando o mesmo atlas funcionam: as duas pastas são aceitas; a CI só muda quando alguém roda `vendor`.
- **Observabilidade:** AVISOs do `doctor` e as instruções do `vendor`.
- **Rollback:** reverter a versão; `.org-atlas/` e a configuração antiga nunca foram tocadas; um atlas que já migrou a CI para `.boson-atlas/` precisa de `vendor` da versão anterior para voltar (documentado no CHANGELOG).
- **Etapas de migração/coexistência:** leitura dupla agora; `vendor --force` migra a CI; a SPEC-0073 remove a reserva na versão anunciada.

## 9. Questões em Aberto
- [x] O `vendor` deve apagar `.org-atlas/` depois de gravar `.boson-atlas/`? — Não: só mostra o `git rm -r .org-atlas`, porque o `atlas.py` não roda git nem apaga nada no atlas (ADR-0010, ADR-0019) (thomas, 2026-11-16: piloto automático com o recomendado)
- [x] Com CI personalizada que ainda roda `.org-atlas/skill`, o `vendor` atualiza qual pasta? — A que a CI roda (`.org-atlas/skill`), com aviso de como migrar, para a CI nunca rodar cópia velha (thomas, 2026-11-16: piloto automático com o recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Configuração e textos**
- [x] Red: CH-01 (guarda), UT-01 a UT-04, UT-07, UT-08 e a guarda de nomes da SPEC-0055, com a tag `SPEC-0070:<ID>`
- [x] Green: leitura e gravação da configuração, AVISOs do `doctor`, textos e assets

**Fase 2: Pasta do atlas e vendor**
- [x] Red: UT-05, UT-06, IT-01, IT-02
- [x] Green: `SKILL_COPIES`, escolha de destino no `vendor`, `lint`/`build`/checagem de cópia velha nas duas pastas
- [x] Validar: suítes da boson-atlas, tests/plugin e mcp, arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e aprovação (H2)
- [x] Deploy via pipeline (G6) — N/A: skill distribuída pelo plugin e por cópia
- [x] Relatório de Entrega, references, SKILL.md, CHANGELOG com a data de remoção, versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3ec7d76 (árvore suja) | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=27, errors=7, skipped=1)) — 2832b68 | 2026-11-17 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — ed77282 | 2026-11-17 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 16665c0 | 2026-11-17 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (rodada 2; M1, M2, m1, m2 e ATLAS.md resolvidos e provados por experimento, inclusive o lint de origin/main na cópia nova; 2 minors — CI que não cita nenhuma pasta conta como migrada, e com dois tipos de CI a cópia nova pode ficar velha — levados para a SPEC-0071; 1 nit) — 1aae634 | 2026-11-17 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 53dd1b7 | 2026-11-17 |
| H2 Integração aprovada | PASS | aprovado por política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-17 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-17 |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
- A `boson-atlas` usa o próprio nome no que é técnico: configuração em `~/.config/boson-atlas`, ferramenta do atlas em `.boson-atlas/skill`, mensagens, `--version`, `--help`, cabeçalhos, CI gerada e `ATLAS.md` de atlas novo. Máquinas com `~/.config/org-atlas` e atlas com `.org-atlas/` funcionam sem ação; o `vendor` nunca deixa uma CI personalizada rodando cópia velha e só manda apagar `.org-atlas/` quando nenhuma CI a cita; `doctor` e `lint` mostram o passo de migração certo antes e depois. boson-atlas 2026.11.7, plugin 2026.11.16.

### Como foi feito
- Leitura dupla e `local_config_write_path` como na SPEC-0069; `SKILL_COPIES`, `ci_file_state`/`vendor_copies`/`ci_migrated` no `vendor`, `old_config_items`/`old_copy_items` no `doctor`; comentário do padrão `url` reescrito para a cópia da skill não parecer segredo em nenhuma versão.
- Testes em 2832b68 e 3d81068 (Emenda v2); implementação em cf87b56 e ed77282.
- **Revisão G4:** rodada 1 CHANGES_REQUESTED (lint da versão anterior acusava segredo falso na cópia nova; CI personalizada podia ficar na cópia velha com a ordem de apagar) → Emenda v2; rodada 2 APPROVED com os experimentos repetidos.

### Prova de Correção
N/A — `type: migration`.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Suíte atual sem outra mudança além de textos e pastas | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-01 | Leitura: só a antiga → antiga; as duas → nova | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-02 | Sem pastas: leitura e gravação na nova; `init` cria só ela | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-03 | `init --join` com só a antiga: configuração completa na nova, antiga idêntica | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-04 | Sobrescrita sem reserva nem aviso | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-05 | `vendor`: casos (a), (b), (c) e, pela Emenda v2, CI com link simbólico, com as duas pastas citadas e de outro tipo | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-06 | Cópias da ferramenta nunca são conteúdo; skill copiada não parece segredo; sugestão depois da migração | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-07 | AVISOs do `doctor`, inclusive depois da migração | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| UT-08 | Textos, assets de CI e `ATLAS.md` dizem `boson-atlas` | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| IT-01 | Máquina e atlas da versão anterior funcionam sem ação | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |
| IT-02 | `atlas-scan.sh` gerado roda `.boson-atlas/skill` | PASS | `skills/boson-atlas/tests/test_rename.py` e suítes da boson-atlas e `tests/plugin` — suíte local no G5 (53dd1b7) e CI do PR |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado — ADR-0020
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skill distribuída pelo plugin e por cópia
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — AVISOs do `doctor`/`lint` e instruções do `vendor`
- [x] Documentação raiz e CHANGELOG atualizados (G7) — CHANGELOG da boson-atlas 2026.11.7; o README entra na SPEC-0072
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: o projeto não define `living_docs`
- [x] Pendências registradas como novas specs (ou nenhuma) — ver Pendências

### Deploy
N/A — plugin 2026.11.16, PR desta spec.

### Pendências
- Minors da rodada 2, levados à SPEC-0071 (que também mexe em `atlas.py`): CI mantida que não cita nenhuma das duas pastas conta como migrada; com dois tipos de CI, `vendor --ci` de um tipo pode deixar a `.boson-atlas/skill` do outro desatualizada.
- Nit: atlas sem nenhum arquivo de CI recebe do `lint` a sugestão de `vendor`, que grava só `.boson-atlas/`.
- Descrições `--help` dos coletores ainda dizem `org-atlas` (SPEC-0071); README (SPEC-0072).

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0070`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| v1 (sem mudança de contrato) | 2026-11-17 | `touches` ganha `tests/plugin/test_skill_names.py`: o `KeptIdentifiersTest` (SPEC-0055:UT-04) passa a exigir os identificadores novos da `boson-atlas` (pasta padrão, `SKILL_COPY`/`SKILL_COPIES` e `--version`); o `CONTRACT` continua `org-atlas/collector@1` até a SPEC-0071 | o teste da SPEC-0055 fixa os nomes que esta spec troca (mesmo achado da SPEC-0069) | SPEC-0071, SPEC-0072 | thomas, 2026-11-17 (piloto automático com o recomendado) |
| v1 (sem mudança de contrato) | 2026-11-17 | Emenda v2 (G4 rodada 1): (1) nenhum arquivo copiado pelo `vendor` (`scripts/atlas.py` e `assets/**`) pode conter texto que o `lint` de qualquer versão acuse como segredo — teste novo copia a skill para um caminho fora de `SKILL_COPIES` e exige zero `secret-leak`; (2) o `vendor` também atualiza `.org-atlas/skill` quando ela existe e qualquer arquivo de CI de `CI_TARGETS` (de qualquer tipo) foi mantido e não se prova que roda só `.boson-atlas/skill` — link simbólico, arquivo ilegível ou que cita a pasta antiga; "pode apagar .org-atlas/" só sai quando nenhum arquivo de CI cita a pasta antiga; testes dos casos com link simbólico, com as duas pastas citadas e com outro tipo de CI; (3) depois da migração (nenhuma CI cita a pasta antiga), o AVISO de cópia velha do `lint` e o do `doctor` sugerem só `git rm -r .org-atlas`, sem repetir o `--force`; (4) `touches` ganha `skills/boson-atlas/assets/pages/**` (o `ATLAS.md` de atlas novo diz `boson-atlas`); (5) texto: `config set` (que o `atlas.py` não tem) trocado por `init --join` | G4 da SPEC-0070 (CHANGES_REQUESTED): máquina na versão anterior acusava segredo falso na cópia nova; CI personalizada podia ficar na cópia velha com a ordem de apagar | SPEC-0071 (descrição dos coletores), SPEC-0072 (README) | thomas, 2026-11-17 (piloto automático com o recomendado) |
