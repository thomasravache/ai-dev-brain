---
id: SPEC-0022
title: "second-brain: processadores de vídeo e documento"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0021]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/processors.md, skills/second-brain/assets/brain-config.yml, skills/second-brain/CHANGELOG.md]
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
- **UT-04** — Dado o código do `brain.py`, quando o teste de arquitetura (SPEC-0017:UT-06) roda, então a única chamada a `subprocess` está em `run_processor`.
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
- [ ] Red: UT-01, UT-02, UT-03 com a tag `SPEC-0022:<ID>`, falhando pelo motivo certo
- [ ] Green: `detect_kind`, `build_args`, `subtitles_to_text`
- [ ] Refactor mantendo tudo verde

**Fase 2: Execução**
- [ ] Red: UT-04, IT-01, IT-02, IT-03, IT-04, IT-05, IT-06 com a tag `SPEC-0022:<ID>`, falhando pelo motivo certo
- [ ] Green: `run_processor`, `process`, `ingest` automático, checagem no `doctor`
- [ ] Refactor mantendo tudo verde

**Fase 3: Guia dos processadores**
- [ ] Red: UT-05 com a tag `SPEC-0022:<ID>`, falhando pelo motivo certo
- [ ] Green: `references/processors.md` conferido contra o `--help` de yt-dlp, Whisper e pdftotext (versão e data); onboarding oferece os modelos
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado (skill distribuída por cópia)
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0022`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
