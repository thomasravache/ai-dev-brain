---
id: SPEC-0021
title: "second-brain: inbox e captura pelo celular"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0019]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/inbox.md, skills/second-brain/references/mobile-capture.md, skills/second-brain/references/config.md, skills/second-brain/assets/brain-config.yml, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0008, ADR-0002]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0021 — second-brain: inbox e captura pelo celular

## 1. Visão Geral
A `inbox/` do vault vira a porta de entrada para capturar sem pensar:
- No computador, `capture "texto"` cria uma nota rápida.
- No celular, você joga ali qualquer coisa (texto, link, foto, PDF, vídeo), pelo menu de compartilhar para a pasta do provedor ou por uma nota rápida no Obsidian mobile.

Depois, em qualquer máquina com a skill, "processa minha inbox" passa cada item pelo fluxo de guardar (SPEC-0019) e tira o item da inbox, sem apagar nada.

## 2. Motivação & Escopo
**Motivação:** no celular não roda a skill com acesso aos arquivos (ADR-0008). Para guardar uma ideia na hora, a captura precisa ser só "jogar na pasta", e o trabalho de classificar e ligar fica para depois, numa máquina com a skill.

**Objetivos (dentro do escopo):**
- `capture TEXTO [--context C]`: nota rápida em `inbox/` com data e hora no nome.
- `inbox list`: itens da inbox (notas, textos e arquivos), com tipo, tamanho, idade e uma prévia do texto.
- `ingest --move` para itens da inbox: o arquivo vai da inbox para `files` em vez de ser copiado, para não deixar arquivo pesado dentro do vault.
- `inbox done ITEM [--note CAMINHO]`: tira da inbox um item de texto já processado, movendo-o para `raw/processed/AAAA-MM/`, e registra no log qual nota saiu dele.
- `inbox_stale_days` no `brain-config.yml` (padrão 7), usado pelo `inbox list` e pelo `lint` (SPEC-0023).
- `references/mobile-capture.md`: como capturar pelo celular com cada provedor da v1 (compartilhar para a pasta `inbox/`) e pelo Obsidian mobile (pasta padrão de notas novas = `inbox/`), para iOS e Android.
- No `SKILL.md`, o fluxo "processar a inbox".

**Não-objetivos (fora do escopo):**
- Processar a inbox automaticamente por tarefa agendada na nuvem: spec futura, decidido na SPEC-0016.
- App ou atalho próprio para o celular: só os recursos dos apps existentes.
- Captura pelo app do Claude com conector do provedor: fora dos canais documentados na v1 (SPEC-0016).

## 3. Dependências
- **Implementações necessárias:** SPEC-0019 — `ingest` (estendido aqui com `--move`), `new-note`, `relate`, `index` e o log.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** app do provedor sincronizando a pasta do vault no computador (ADR-0008); no celular, o app do provedor ou o Obsidian mobile.

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Segue a SPEC-0019: escrita só por `write_new_file` e funções de append, mais a linha no `log.md`. O ADR-0007 já prevê a exceção de tirar um item processado da inbox sem apagar.

**Decisão:** `move_out_of_inbox(item, destino)` é a única função que move arquivo. Ela recusa origem fora de `layout.inbox` e destino que já exista, e registra no log. O `ingest --move` usa essa função para arquivos, e o `inbox done` usa para textos.

**Justificativa:** mantém "nada se apaga" (ADR-0007) e ainda tira os arquivos pesados do vault (ADR-0008).

**Desvio do padrão existente:** Nenhum. Esta spec detalha a exceção já prevista no ADR-0007.

**Alternativas descartadas:**
- Apagar o item da inbox depois de processar: viola o ADR-0007.
- Deixar o item na inbox com uma marca de "processado": a inbox nunca esvazia, e marcar exigiria alterar o arquivo do usuário.

**ADRs:** ADR-0007, ADR-0008 e ADR-0002 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `inbox list` em menos de 1 s com 500 itens.
- **Segurança:** só move de dentro da inbox; nunca sobrescreve o destino (UT-02).
- **Privacidade e dados pessoais:** nada sai da máquina; o celular usa a sincronização do provedor escolhido.
- **Disponibilidade e resiliência:** arquivo ainda sincronizando, como um placeholder do iCloud (`.icloud`) ou um arquivo de 0 bytes recente, aparece como `syncing` no `inbox list` e não é processado. Nome com caracteres estranhos vindos do celular é aceito.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comandos `capture`, `inbox list`, `inbox done`, a opção `ingest --move`, a chave `inbox_stale_days` e o fluxo de processar a inbox no `SKILL.md`.

```text
brain.py capture TEXTO [--context C] [--json]
  cria inbox/AAAA-MM-DD-HHMMSS-<slug das 6 primeiras palavras>.md com frontmatter
  {type: capture, created, context?} e o TEXTO; imprime o caminho; mesmo nome no mesmo segundo → sufixo -1
  TEXTO vazio: exit 2

brain.py inbox list [--json]
  um item por arquivo de layout.inbox (sem subpastas ocultas), do mais antigo para o mais novo
  kind: text (.md, .txt) | link (.url, .webloc, ou texto que é só uma URL) | file (o resto) | syncing
  campos: path, kind, size, age_days, stale (age_days > inbox_stale_days), preview (até 120 caracteres de texto)
  inbox vazia: "Inbox vazia", exit 0

brain.py ingest ITEM_DA_INBOX --move [...opções da SPEC-0019]
  igual ao ingest da SPEC-0019, mas move o arquivo para files em vez de copiar
  --move com fonte fora da inbox: exit 2 "--move só vale para itens da inbox"

brain.py inbox done ITEM [--note CAMINHO]
  ITEM text ou link: move para raw/processed/AAAA-MM/<nome> (nome existente → sufixo -1)
  log: "- … inbox-done <ITEM> → <destino> [nota: <CAMINHO>]"
  ITEM file: exit 2 "arquivo: use ingest --move"; ITEM syncing: exit 2 "ainda sincronizando"
  ITEM fora da inbox ou inexistente: exit 2

brain-config.yml: inbox_stale_days: 7

SKILL.md — processar a inbox ("processa minha inbox"):
  1. inbox list
  2. para cada item (do mais antigo): fluxo de guardar (SPEC-0019); arquivo → ingest --move; texto ou link → nota
  3. item de texto ou link já guardado → inbox done ITEM --note <nota criada>
  4. pular itens syncing e avisar; reportar no fim o que entrou, onde e as relações criadas

references/mobile-capture.md: uma seção por provedor da v1 (Google Drive, OneDrive, iCloud, pasta local), cada uma
  com iOS e Android: como salvar na pasta inbox pelo compartilhar; Obsidian mobile: pasta padrão de notas novas
  = inbox, e em quais provedores o Obsidian mobile abre o vault (conforme ADR-0008)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Captura | `capture "ideia"` | nota em `inbox/` com frontmatter | IT-01 |
| Captura vazia | `capture ""` | exit 2 | IT-01 |
| Mesmo segundo | duas capturas iguais | sufixo `-1` | UT-01 |
| Listar | texto, link, PDF, `.icloud` | kinds corretos, stale pela idade | UT-03, IT-02 |
| Inbox vazia | nenhum item | "Inbox vazia" | IT-02 |
| Ingest com move | PDF da inbox | vai para `files`, sai da inbox, nota de fonte criada | IT-03 |
| Move fora da inbox | `--move` em arquivo de outra pasta | exit 2 | IT-03 |
| Done de texto | item de texto processado | movido para `raw/processed/AAAA-MM/`, log com a nota | IT-04 |
| Done de arquivo | item file | exit 2 com orientação | IT-04 |
| Done sincronizando | item syncing | exit 2 | IT-04 |
| Destino existente | mesmo nome em `raw/processed` | sufixo `-1`, nada sobrescrito | UT-02 |
| Outra máquina | item jogado na inbox e processado com outra configuração local | mesmo resultado do fluxo de guardar | IT-05 |
| Instruções | `SKILL.md`, `mobile-capture.md` | fluxo da inbox e um guia por provedor e sistema | UT-04 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — o `ingest` da SPEC-0019 continua coberto pelos testes dela; `--move` é opção nova.

### 7.2 Testes Unitários
- **UT-01** — Dado um relógio fixo, quando `capture_name("Ideia para o TCC sobre grafos de conhecimento")` é chamado duas vezes no mesmo segundo, então os nomes são `AAAA-MM-DD-HHMMSS-ideia-para-o-tcc-sobre-grafos.md` e o mesmo com `-1`.
- **UT-02** — Dado um item em `inbox/` e um arquivo de mesmo nome já em `raw/processed/AAAA-MM/`, quando `move_out_of_inbox` roda, então o destino ganha o sufixo `-1`, o arquivo existente não muda e uma origem fora da inbox é recusada.
- **UT-03** — Dado arquivos `a.md`, `b.txt` só com uma URL, `c.webloc`, `d.pdf`, `e.pdf.icloud` e um de 0 bytes modificado agora, quando `classify_inbox_item` roda, então os kinds são text, link, link, file, syncing e syncing.
- **UT-04** — Dado o `SKILL.md` e `references/mobile-capture.md`, quando lidos, então o `SKILL.md` tem os quatro passos de processar a inbox, e `mobile-capture.md` tem uma seção para cada provedor da v1, cada uma com iOS e Android, e a seção do Obsidian mobile.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault criado pelo `init`, quando roda `capture "Ideia sobre grafos" --context college` e `capture ""`, então a primeira cria a nota na inbox com `type: capture` e `context: college`, imprime o caminho e grava o log; a segunda sai com 2.
- **IT-02** — Dado uma inbox com uma nota de 10 dias, um link, um PDF e um placeholder `.icloud`, com `inbox_stale_days: 7`, quando roda `inbox list --json`, então os quatro aparecem com os kinds certos e só a nota antiga é `stale`; numa inbox vazia, imprime "Inbox vazia".
- **IT-03** — Dado um PDF em `inbox/`, quando roda `ingest inbox/aula.pdf --move --context college`, então o PDF está em `files/college/<ano>/`, não está mais na inbox, a nota de fonte existe em `raw/` e o log registra; `ingest outro/x.pdf --move` sai com 2.
- **IT-04** — Dado uma nota de texto na inbox já guardada como "Ideia sobre grafos", quando roda `inbox done <item> --note "Ideia sobre grafos"`, então o item está em `raw/processed/AAAA-MM/` e o log cita a nota; `inbox done` num PDF ou num `.icloud` sai com 2 e com a mensagem do contrato.
- **IT-05** — Dado um vault com duas configurações locais (máquinas A e B, caminhos diferentes, como no IT-04 da SPEC-0017), quando a máquina A só joga um arquivo de texto na inbox e a máquina B roda `inbox list`, `new-note`, `relate`, `index` e `inbox done`, então a nota criada pela B está no contexto, ligada, no MOC, e a inbox fica vazia. É o critério de aceite "inbox" do épico.

### 7.4 Testes de Contrato
- N/A — sem contrato consumido.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração. A captura no celular usa apps de terceiros, e a sincronização é do provedor (ADR-0008). O guia é verificado no UT-04.

### 7.6 Outros
- `inbox list` com 500 itens gerados em menos de 1 s, medido na revisão.

**Dublês e dados de teste:** vaults temporários; placeholders `.icloud` e arquivos de 0 bytes simulando sincronização; relógio injetável para os nomes; `BRAIN_CONFIG_HOME` e `HOME` isolados.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto.
- **Dados/schema:** chave nova `inbox_stale_days` no `brain-config.yml`, com padrão 7 quando ausente (vaults criados antes funcionam sem mudança).
- **Compatibilidade:** `ingest` sem `--move` não muda.
- **Observabilidade:** `log.md` registra cada movimentação; `inbox list` mostra itens parados.
- **Rollback:** `git revert` do merge; os itens já movidos continuam em `raw/processed/` e em `files`.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Captura e classificação**
- [x] Red: UT-01, UT-03, IT-01, IT-02 com a tag `SPEC-0021:<ID>`, falhando pelo motivo certo
- [x] Green: `capture`, `classify_inbox_item`, `inbox list`, `inbox_stale_days`
- [x] Refactor mantendo tudo verde

**Fase 2: Saída da inbox**
- [x] Red: UT-02, IT-03, IT-04, IT-05 com a tag `SPEC-0021:<ID>`, falhando pelo motivo certo
- [x] Green: `move_out_of_inbox`, `ingest --move`, `inbox done`
- [x] Refactor mantendo tudo verde

**Fase 3: Instruções**
- [x] Red: UT-04 com a tag `SPEC-0021:<ID>`, falhando pelo motivo certo
- [x] Green: fluxo da inbox no `SKILL.md`, `inbox.md`, `mobile-capture.md`
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: pilar entrega dispensado (skill distribuída por cópia)
- [x] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=24)) — 39abbc4 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — a344a93 | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — a344a93 | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (a344a93; achados da 1ª rodada corrigidos; 4 minor) — a344a93 | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — c9d3b34 | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
A inbox virou a porta de entrada para capturar sem pensar:
- `brain.py capture "texto"` cria uma nota rápida;
- `inbox list` mostra os itens com tipo, idade e prévia;
- `ingest ITEM --move` tira um arquivo da inbox para a pasta `files`, sem deixar cópia pesada no vault;
- `inbox done ITEM --note …` tira um texto já processado para `raw/processed/AAAA-MM/`.

Itens ainda sincronizando são ignorados. O `SKILL.md` traz os quatro passos de "processa minha inbox", e `references/mobile-capture.md` explica como capturar pelo celular em cada provedor, no iOS e no Android.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `brain.py` (versão 2026.10.5) ganhou `capture_name`, `classify_inbox_item` e `move_out_of_inbox`. Esta última é a única função que move arquivos: reserva o destino com criação exclusiva, faz `os.replace`, nunca sobrescreve e nunca apaga dado do usuário.
- Entraram também a chave `inbox_stale_days` (padrão 7) e os arquivos `references/inbox.md` e `references/mobile-capture.md`.
- A 1ª revisão G4 pediu mudanças: 1 major (um `--note` absoluto ia para o `log.md`) e 10 minor. Decisões do Architect, com testes de regressão antes da correção (red 64941a4, fix 9ef338d e a344a93):
  - `--note` absoluto vira caminho relativo, e fora do vault é recusado;
  - symlinks e subpastas ocultas são recusados;
  - caracteres de controle são escapados;
  - texto com NUL vira arquivo;
  - prévia limpa;
  - aviso para `inbox_stale_days` inválido;
  - documentação da janela de corrida e da falha segura entre volumes.
- O escopo passou a incluir `references/config.md`. A 2ª revisão aprovou.
- Achados minor aceitos: algumas mensagens de erro no stderr não escapam controles; `.txt` em UTF-16 é tratado como arquivo; uma pasta vazia de destino pode sobrar em `files` quando a mudança entre volumes falha.
- O teste de desempenho da busca falhou uma vez sob carga, e o revisor não conseguiu reproduzir em 8 execuções.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Nome da captura com data, hora e slug, sem colisão | PASS | `test_inbox.py::CaptureNameTest.test_same_second_gets_suffix_1_and_slug_has_the_first_six_words` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| UT-02 | move_out_of_inbox nunca sobrescreve e recusa origem fora da inbox | PASS | `test_inbox.py::MoveOutOfInboxTest.test_existing_destination_gets_suffix_1_and_source_outside_inbox_is_refused` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| UT-03 | Classificação dos itens da inbox (texto, link, arquivo, sincronizando; NUL vira arquivo) | PASS | `test_inbox.py::ClassifyInboxItemTest.test_kinds_text_link_file_and_syncing; test_inbox_review.py::ClassifyNulTest.test_text_with_nul_bytes_is_a_file` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| UT-04 | SKILL.md com os quatro passos da inbox e guias de captura por provedor e sistema | PASS | `test_inbox_instructions.py::InboxInstructionsTest.test_skill_md_has_the_four_inbox_steps_in_order; test_inbox_instructions.py::InboxInstructionsTest.test_mobile_capture_has_a_section_per_provider_with_ios_and_android; test_inbox_instructions.py::InboxInstructionsTest.test_mobile_capture_has_the_obsidian_mobile_section; test_inbox_review.py::ReviewInstructionsTest.test_mobile_capture_does_not_list_paid_among_the_verified_facts; test_inbox_review.py::ReviewInstructionsTest.test_config_md_documents_inbox_stale_days; test_inbox_review.py::ReviewInstructionsTest.test_inbox_md_says_ingest_move_fails_safely_on_another_volume` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| IT-01 | capture cria a nota na inbox; texto vazio recusado | PASS | `test_inbox_cli.py::CaptureCliTest.test_capture_creates_a_capture_note_in_the_inbox_and_empty_text_exits_2` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| IT-02 | inbox list com tipos, idade, itens parados, prévia limpa e inbox_stale_days | PASS | `test_inbox_cli.py::InboxListCliTest.test_list_shows_kinds_oldest_first_and_only_the_old_note_is_stale; test_inbox_cli.py::InboxListCliTest.test_stale_days_comes_from_brain_config; test_inbox_cli.py::InboxListCliTest.test_empty_inbox_prints_inbox_vazia; test_inbox_review.py::PreviewTest.test_previews_have_no_control_characters_and_webloc_entities_are_unescaped; test_inbox_review.py::InvalidStaleDaysTest.test_invalid_stale_days_falls_back_to_7_with_a_warning` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| IT-03 | ingest --move tira o arquivo da inbox; recusas fora da inbox, symlink, oculto e sincronizando | PASS | `test_inbox_cli.py::IngestMoveCliTest.test_ingest_move_takes_the_pdf_out_of_the_inbox_into_files; test_inbox_cli.py::IngestMoveCliTest.test_move_outside_the_inbox_exits_2_and_plain_ingest_still_copies; test_inbox_review.py::SymlinkItemTest.test_symlinked_items_are_refused_by_ingest_move_and_done; test_inbox_review.py::ControlCharacterNameTest.test_ingest_move_logs_a_name_with_control_characters_on_one_line_each; test_inbox_review.py::SyncingMoveTest.test_ingest_move_refuses_syncing_items_and_list_shows_a_recent_empty_file_as_syncing` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| IT-04 | inbox done move texto e link para raw/processed; recusas; --note relativo; nomes com controles | PASS | `test_inbox_cli.py::InboxDoneCliTest.test_done_moves_text_to_raw_processed_and_logs_the_note; test_inbox_cli.py::InboxDoneCliTest.test_done_refuses_file_syncing_missing_and_outside_items; test_inbox_review.py::DoneNoteAbsolutePathTest.test_absolute_note_inside_the_vault_is_logged_relative; test_inbox_review.py::DoneNoteAbsolutePathTest.test_absolute_note_outside_the_vault_exits_2_and_nothing_moves; test_inbox_review.py::HiddenSubfolderTest.test_items_in_hidden_inbox_subfolders_are_refused; test_inbox_review.py::ControlCharacterNameTest.test_done_logs_and_prints_a_name_with_control_characters_on_one_line` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |
| IT-05 | Item jogado numa máquina processado por outra | PASS | `test_inbox_cli.py::OtherMachineCliTest.test_item_dropped_on_machine_a_is_stored_by_machine_b_and_the_inbox_empties` — CI do PR #15 em c9d3b34 (run 41070051416, Python 3.9 e 3.15) e suíte local (G5) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — `inbox list` com 500 itens em 0,09–0,18 s (meta: menos de 1 s); segurança pelo UT-02, IT-03 e IT-04 (nada sobrescrito ou apagado, nenhum caminho absoluto no log)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: pilar entrega dispensado; vale na `main` com o merge do PR #15
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: sem `living_docs` configurado
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #15. Versão da skill: 2026.10.5. Rollback: revert do merge.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
Nenhuma nova spec. Os 4 achados minor aceitos estão descritos em "Como foi feito". Se o teste de desempenho voltar a falhar, ele vira spec de teste instável (ADR-0002).

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0021`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
