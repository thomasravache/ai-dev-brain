---
id: SPEC-0022
title: "second-brain: processadores de vídeo e documento"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0021]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/processors.md, skills/second-brain/references/config.md, skills/second-brain/references/store-flow.md, skills/second-brain/assets/brain-config.yml, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0009, ADR-0007, ADR-0002]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0022 — second-brain: processadores de vídeo e documento

## 1. Visão Geral
O segundo cérebro passa a extrair texto de vídeos do YouTube, de vídeos e áudios locais e de PDFs, com as ferramentas que cada pessoa tem instaladas: yt-dlp, Whisper e pdftotext por padrão, ou outras. Os processadores são comandos declarados no `brain-config.yml` (ADR-0009). Quando existe um processador para o tipo, o `ingest` o chama sozinho e põe a transcrição ou o texto na nota de fonte. Quando não existe, a skill guarda só o bruto e avisa, como antes.

## 2. Motivação & Escopo
**Motivação:** para sintetizar uma aula gravada ou um vídeo, a LLM precisa do texto. Vídeo ela não lê, e PDF grande custa muitos tokens. Ter a transcrição em `raw/` também deixa o conteúdo encontrável pela busca (SPEC-0018).

**Objetivos (dentro do escopo):**
- `run_processor(kind, input)`: único ponto do `brain.py` que executa processo externo (ADR-0007). Roda sem shell, com marcadores, timeout e captura de saída.
- `process ENTRADA [--kind K]`: roda o processador e devolve o texto, ou grava num arquivo.
- `ingest` com detecção do tipo (URL do YouTube, extensões de vídeo e áudio, `.pdf`) e chamada automática do processador, que `--no-process` desliga.
- `--timestamps` para vídeo: as legendas e as transcrições com tempo viram linhas `[mm:ss] texto` e, no YouTube, links para o trecho (`t=<segundos>s`).
- `references/processors.md` com os modelos de yt-dlp, Whisper e pdftotext, conferidos contra a ajuda de cada ferramenta e com a data da conferência; o onboarding (SPEC-0017) passa a oferecer esses modelos.
- `doctor` passa a testar cada processador configurado com `--version` ou o comando de checagem declarado (`check`).

**Não-objetivos (fora do escopo):**
- Instalar as ferramentas.
- Resumo automático: quem sintetiza é o agente, no fluxo de guardar.
- OCR de imagens e PDFs escaneados: dá para configurar como processador `kind: ocr`, mas a v1 não traz modelo.

## 3. Dependências
- **Implementações necessárias:** SPEC-0021 — `ingest` com `--move` (os vídeos chegam pela inbox) e a nota de fonte da SPEC-0019.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** nenhum para a skill funcionar. Para extrair, as ferramentas que a pessoa configurar.

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Segue o ADR-0009 e o modelo da `sdd-management`, que só executa comandos declarados no `sdd-config.yml` (`gate --run`, em `spec_graph.py`), com a saída registrada.

**Decisão:** `run_processor` monta a lista de argumentos com `shlex.split(command)`, substitui `{input}`, `{output}` e `{output_dir}` em cada argumento e roda `subprocess.run(args, timeout=..., capture_output=True)` num diretório temporário. O texto vem de `{output}`, ou do maior arquivo com a extensão `output` gerado em `{output_dir}`, ou do stdout. Legendas `.vtt`/`.srt` são convertidas para texto, com tempo opcional, por uma função pura.

**Justificativa:** cumpre o ADR-0009 (sem shell, sem dependência Python, troca de ferramenta pela configuração) e o ADR-0007 (um só ponto de processo externo, verificado pelo teste de arquitetura).

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:**
- Rodar com `shell=True` (permitiria pipes): abre injeção a partir de nomes de arquivo vindos do celular.
- Bibliotecas Python das ferramentas: o ADR-0009 descarta.

**ADRs:** ADR-0009, ADR-0007 e ADR-0002 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** o tempo é o da ferramenta. A skill impõe o `timeout` (padrão 1800 s) e, ao estourar, mata o processo e avisa.
- **Segurança:** sem shell. Nomes de arquivo com espaços, `;`, `$()` e aspas são passados como um argumento só (UT-02). Só comandos do `brain-config.yml` são executados. URLs só são aceitas com `http` ou `https`.
- **Privacidade e dados pessoais:** o yt-dlp acessa a rede para baixar legendas: é ação do processador que a pessoa configurou, e o `processors.md` avisa. O Whisper e o pdftotext rodam localmente.
- **Disponibilidade e resiliência:** executável ausente, exit diferente de 0, timeout ou saída vazia → aviso com o stderr resumido (até 500 caracteres), nota de fonte com `_(extraction failed: <motivo>)_` e exit 0 no `ingest`, porque o bruto ficou guardado. O `process` sozinho sai com 1.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A — ferramentas locais e gratuitas por padrão.

## 6. Artefato A — Contrato
**Interface:** chave `processors` do `brain-config.yml`, comando `process`, mudanças no `ingest` e no `doctor`, e `references/processors.md`.

```text
brain-config.yml:
  processors:
    <kind>:                      # youtube | video | audio | pdf | <outro>
      command: "<comando com {input} {output} {output_dir}>"
      output: vtt | srt | txt    # extensão esperada em {output_dir} (opcional se usa {output} ou stdout)
      timeout: 1800              # segundos (opcional)
      check: "<comando de checagem>"   # opcional; padrão "<executável> --version"

Detecção do kind no ingest:
  youtube: URL com host youtube.com, www.youtube.com, m.youtube.com ou youtu.be
  video: .mp4 .mov .mkv .webm .avi · audio: .mp3 .m4a .wav .ogg .opus · pdf: .pdf
  --kind K força o tipo

brain.py process ENTRADA [--kind K] [--out ARQ] [--timestamps]
  roda o processador; texto no stdout ou em --out; exit 0
  sem processador para o kind: exit 2 "nenhum processador para <kind> — veja references/processors.md"
  falha do processador: exit 1, "processador <kind> falhou: <motivo>" (+ stderr resumido)

brain.py ingest FONTE ... [--no-process] [--timestamps]
  com processador do kind e sem --no-process: chama o processador e grava o texto sob "## Extracted text"
  (com --timestamps, linhas "[mm:ss] texto"; youtube: "[mm:ss](<url com t=<segundos>s>) texto", com "?t=" ou "&t=" conforme a URL já tenha query)
  falha: aviso, "_(extraction failed: <motivo>)_" na nota e exit 0
  sem processador: comportamento da SPEC-0019 + aviso "sem processador para <kind>"
  --text-file tem prioridade sobre o processador

brain.py doctor: para cada processador, "OK|AVISO processor <kind> — <executável> (<primeira linha da checagem>)"

references/processors.md: modelos para youtube (yt-dlp, legendas sem baixar o vídeo), video e audio (Whisper,
  saída txt ou vtt) e pdf (pdftotext), cada um com a versão e a data em que a linha foi conferida contra --help;
  aviso de rede do yt-dlp; como trocar por outra ferramenta (ex.: whisper.cpp)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Montagem do comando | marcadores e nome com espaço, `;` e `$()` | um argumento por marcador, sem shell | UT-02 |
| Legenda para texto | `.vtt` e `.srt` com e sem tempo | texto limpo ou linhas `[mm:ss]` | UT-03 |
| Detecção do kind | URLs do YouTube, extensões | kind do contrato | UT-01 |
| Ingest com processador | PDF e processador falso | texto na nota de fonte | IT-01 |
| Vídeo com tempo | vídeo do YouTube, `--timestamps` | linhas com link para o trecho (`?t=` ou `&t=`) | UT-03, IT-02 |
| Saída por arquivo | processador que grava em `{output_dir}` | texto do maior arquivo da extensão | IT-02 |
| Sem processador | kind sem processador | comportamento anterior + aviso | IT-03 |
| `--no-process` / `--text-file` | flags | processador não roda | IT-03 |
| Falha do processador | exit 3, executável ausente, timeout | aviso, nota com falha, exit 0 no ingest | IT-04 |
| `process` direto | com e sem processador, com falha | exit 0, 2 e 1 | IT-05 |
| Doctor | processador ok e ausente | OK e AVISO com a checagem | IT-06 |
| Arquitetura | `brain.py` | processo externo só em `run_processor` | UT-04 |
| Guia | `processors.md` | três modelos com versão e data, aviso de rede | UT-05 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — o `ingest` sem processador já é coberto pelos testes da SPEC-0019, que continuam passando (IT-03 cobre o caminho sem processador).

### 7.2 Testes Unitários
- **UT-01** — Dado `https://www.youtube.com/watch?v=x`, `https://youtu.be/x`, `aula.MP4`, `nota.m4a`, `slides.pdf` e `x.docx`, quando `detect_kind` roda, então devolve youtube, youtube, video, audio, pdf e nenhum.
- **UT-02** — Dado o comando `"tool --in {input} -o {output_dir}/x"` e a entrada `a b; $(rm -rf x) "c".pdf`, quando `build_args` roda, então devolve `["tool", "--in", "<entrada literal>", "-o", "<dir>/x"]`, com a entrada como um único argumento.
- **UT-03** — Dado um `.vtt` e um `.srt` com cabeçalho, linhas repetidas e marcações `<c>`, quando `subtitles_to_text` roda com e sem tempo, então devolve o texto sem duplicação e sem marcação, ou linhas `[mm:ss] texto`; com `https://youtu.be/abc` as linhas viram links `https://youtu.be/abc?t=<s>s`, e com `https://www.youtube.com/watch?v=abc`, links `…&t=<s>s`.
- **UT-04** — Dado o código do `brain.py`, quando o teste de arquitetura de processos criado na SPEC-0017 roda, então a única chamada a `subprocess` está em `run_processor`.
- **UT-05** — Dado `references/processors.md`, quando lido, então tem modelos para youtube, video ou audio e pdf, cada um com versão e data de conferência, e o aviso de que o yt-dlp acessa a rede.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault com `processors.pdf` apontando para um processador falso (script Python do teste que escreve "texto extraído" em `{output}`), quando roda `ingest slides.pdf --context college`, então a nota de fonte tem "texto extraído" sob `## Extracted text` e o log registra.
- **IT-02** — Dado `processors.youtube` com um processador falso que grava um `.vtt` em `{output_dir}`, quando roda `ingest https://youtu.be/abc --timestamps --context college`, então a nota de fonte tem linhas `[mm:ss](https://youtu.be/abc?t=<s>s) …` vindas do maior `.vtt`.
- **IT-03** — Dado um vault sem `processors.video`, quando roda `ingest aula.mp4`, `ingest slides.pdf --no-process` e `ingest slides.pdf --text-file t.txt`, então a primeira guarda o bruto com o aviso "sem processador para video", e nas outras duas o processador falso não roda (verificado pela ausência do arquivo-marcador que ele cria).
- **IT-04** — Dado processadores falsos que saem com 3, um executável inexistente e um que dorme além de `timeout: 1`, quando roda `ingest` com cada um, então o exit é 0, a nota de fonte tem `_(extraction failed: <motivo>)_` e o aviso traz o stderr resumido; o processo do timeout foi encerrado.
- **IT-05** — Dado os mesmos processadores, quando roda `process slides.pdf --out t.txt`, `process aula.mp4` (sem processador) e `process` com o que falha, então os exits são 0 (com o texto em `t.txt`), 2 e 1.
- **IT-06** — Dado um processador falso com `check` e um com executável ausente, quando roda `doctor`, então mostra OK com a primeira linha da checagem e AVISO para o ausente.

### 7.4 Testes de Contrato
- N/A — sem contrato consumido.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração. As ferramentas reais não rodam na CI. A linha de comando de cada modelo é conferida na implementação contra o `--help` (UT-05).

### 7.6 Outros
- Segurança: UT-02 (argumentos sem shell) e IT-04 (timeout encerra o processo).

**Dublês e dados de teste:** processadores falsos em Python (`sys.executable`) criados pelos testes; `.vtt` e `.srt` sintéticos; vaults temporários; `BRAIN_CONFIG_HOME` e `HOME` isolados.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15), sem yt-dlp, Whisper ou pdftotext instalados.

## 8. Plano de Rollout
- **Estratégia:** deploy direto. Sem `processors` configurado, nada muda para quem já usa.
- **Dados/schema:** chave `processors` já existe vazia desde a SPEC-0017; os campos novos são opcionais.
- **Compatibilidade:** `ingest` sem processador configurado se comporta como na SPEC-0019.
- **Observabilidade:** avisos no terminal, falha registrada na nota de fonte e no `log.md`, `doctor` por processador.
- **Rollback:** `git revert` do merge, ou remover o processador do `brain-config.yml`.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Funções puras**
- [x] Red: UT-01, UT-02, UT-03 com a tag `SPEC-0022:<ID>`, falhando pelo motivo certo
- [x] Green: `detect_kind`, `build_args`, `subtitles_to_text`
- [x] Refactor mantendo tudo verde

**Fase 2: Execução**
- [x] Red: UT-04, IT-01, IT-02, IT-03, IT-04, IT-05, IT-06 com a tag `SPEC-0022:<ID>`, falhando pelo motivo certo
- [x] Green: `run_processor`, `process`, `ingest` automático, checagem no `doctor`
- [x] Refactor mantendo tudo verde

**Fase 3: Guia dos processadores**
- [x] Red: UT-05 com a tag `SPEC-0022:<ID>`, falhando pelo motivo certo
- [x] Green: `references/processors.md` conferido contra o `--help` de yt-dlp, Whisper e pdftotext (versão e data); onboarding oferece os modelos
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=21)) — 18b2900 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — a80288f | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — a80288f | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (a80288f; 1 major e 3 minor da 1ª rodada corrigidos) — a80288f | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 355419d | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 737b6bc | 2026-10-30 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
Vídeos do YouTube, vídeos e áudios locais e PDFs passam a chegar ao segundo cérebro com o texto extraído:
- o `ingest` chama sozinho o processador configurado para o tipo (yt-dlp, Whisper, pdftotext ou outro) e grava a transcrição ou o texto na nota de fonte, com links para o trecho do vídeo quando há `--timestamps`;
- `brain.py process` roda um processador direto;
- o `doctor` confere se cada processador está instalado.

Sem processador, nada muda: o arquivo fica guardado e a skill avisa.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- `brain.py` (versão 2026.10.6) ganhou `detect_kind`, `build_args` (`shlex.split` e substituição em uma passada) e `subtitles_to_text`.
- `run_processor` é o único ponto que roda processo externo: `Popen` sem shell, num grupo de processos próprio, numa pasta temporária, com timeout que encerra o grupo inteiro.
- `references/processors.md` traz os modelos. O yt-dlp 2026.08.19 foi conferido contra o `--help` instalado nesta máquina. O Whisper (20250625) e o pdftotext (poppler 26.07.0, página de manual via manpages.debian.org) foram conferidos na documentação em 2026-10-30, sem executar nesta máquina, e nada foi instalado.
- O escopo passou a incluir `references/config.md` e `references/store-flow.md`, que estavam desatualizados.
- A 1ª revisão G4 pediu mudanças: 1 major (o timeout matava só o processo direto e deixava netos rodando) e 3 minor (`--out` sobrescrevia; fonte do pdftotext; ffmpeg do Whisper). Os testes de regressão vieram antes da correção (red b102931; fix 5c29b00 e a80288f), e a 2ª revisão aprovou sem achados.
- O 1º registro do G1 falhou porque o `verify` da `sdd-management` tratou como teste desta spec uma citação a outro teste no texto do plano. A citação foi reescrita.
- Um G2 falhou uma vez com a máquina carregada (outra suíte rodando em paralelo) e não se repetiu.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Detecção do tipo (YouTube, vídeo, áudio, PDF) | PASS | `test_processors.py::DetectKindTest.test_kinds_of_the_contract` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| UT-02 | Argumentos montados sem shell, um por marcador | PASS | `test_processors.py::BuildArgsTest.test_each_marker_becomes_one_literal_argument_without_shell; test_processors.py::BuildArgsTest.test_a_value_with_a_marker_inside_is_kept_literally` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| UT-03 | Legendas para texto, com tempo e links do YouTube | PASS | `test_processors.py::SubtitlesToTextTest.test_plain_text_without_header_markup_or_repeated_lines; test_processors.py::SubtitlesToTextTest.test_timestamps_become_mm_ss_lines; test_processors.py::SubtitlesToTextTest.test_youtube_timestamps_link_to_the_moment` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| UT-04 | Processo externo só em run_processor, sem shell | PASS | `test_architecture.py::ProcessRulesTest.test_brain_runs_processes_only_in_run_processor; test_architecture.py::ProcessRulesTest.test_run_processor_is_the_one_place_that_runs_a_process_and_never_with_shell` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| UT-05 | Guia dos processadores com versão, data, aviso de rede e pré-requisitos | PASS | `test_processors_instructions.py::ProcessorsGuideTest.test_three_models_each_with_command_version_and_check_date; test_processors_instructions.py::ProcessorsGuideTest.test_network_warning_for_yt_dlp_and_how_to_swap_tools; test_processors_review.py::ProcessorsGuideReviewTest.test_pdf_section_cites_manpages_debian_with_version_date_and_not_run; test_processors_review.py::ProcessorsGuideReviewTest.test_whisper_section_states_the_ffmpeg_prerequisite` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| IT-01 | ingest com processador grava o texto extraído | PASS | `test_processors_cli.py::IngestWithProcessorTest.test_pdf_text_goes_under_extracted_text_and_is_logged` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| IT-02 | YouTube com tempo e saída por arquivo | PASS | `test_processors_cli.py::YoutubeTimestampsTest.test_timestamps_link_each_line_to_the_moment_from_the_largest_vtt; test_processors_cli.py::YoutubeTimestampsTest.test_without_timestamps_the_largest_vtt_becomes_plain_text` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| IT-03 | Sem processador, --no-process e --text-file | PASS | `test_processors_cli.py::WithoutProcessingTest.test_no_processor_no_process_and_text_file_do_not_run_the_processor` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| IT-04 | Falha, executável ausente e tempo esgotado (grupo de processos encerrado) | PASS | `test_processors_cli.py::ProcessorFailureTest.test_exit_3_keeps_the_raw_note_with_the_failure_and_a_short_stderr; test_processors_cli.py::ProcessorFailureTest.test_missing_executable_keeps_the_raw_note_with_the_failure; test_processors_cli.py::ProcessorFailureTest.test_timeout_kills_the_processor_and_keeps_the_raw_note; test_processors_review.py::TimeoutKillsProcessGroupTest.test_ingest_timeout_kills_the_grandchild; test_processors_review.py::TimeoutKillsProcessGroupTest.test_process_timeout_kills_the_grandchild` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| IT-05 | process direto; --out nunca sobrescreve nem escreve no vault | PASS | `test_processors_cli.py::ProcessCommandTest.test_process_exits_0_2_and_1; test_processors_review.py::ProcessOutNeverOverwritesTest.test_existing_out_file_exits_2_and_is_left_unchanged; test_processors_review.py::ProcessOutNeverOverwritesTest.test_out_inside_the_vault_exits_2_and_writes_nothing` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |
| IT-06 | doctor confere cada processador | PASS | `test_processors_cli.py::DoctorProcessorsTest.test_doctor_runs_each_check_and_warns_on_missing_executable` — CI do PR #15 em 355419d (run 41076965759, Python 3.9 e 3.15) e suíte local (G5) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — tempo limitado pelo `timeout` do processador (padrão 1800 s), com o grupo de processos encerrado ao estourar (IT-04); segurança: sem shell, nomes vindos do celular viram um argumento só (UT-02), só URLs http/https
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: pilar entrega dispensado; vale na `main` com o merge do PR #15
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: sem `living_docs` configurado
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #15. Versão da skill: 2026.10.6. Rollback: revert do merge ou remover o processador do `brain-config.yml`.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
Nenhuma nova spec desta entrega. Fica uma observação para a `sdd-management`: o `verify` não deveria tratar como teste da spec uma citação a outra spec (por exemplo `SPEC-0017:UT-06`) no texto do plano. Esse ponto é candidato a uma correção lite da skill.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0022`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
