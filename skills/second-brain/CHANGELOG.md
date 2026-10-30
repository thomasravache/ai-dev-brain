# Changelog

Todas as mudanças relevantes da skill `second-brain` são documentadas aqui. Este arquivo viaja com a skill (fica na
pasta dela).

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As versões são as de `BRAIN_VERSION` (`AAAA.MM.N`), uma seção por versão, a mais nova primeiro (ADR-0007, ADR-0005).
Cada entrada cita a spec de origem (`SPEC-NNNN`).

## [Unreleased]

## [2026.10.10] - 2026-10-30

### Fixed
- Busca (`scripts/brain.py`, `BRAIN_VERSION` 2026.10.10): arquivos `.md` ocultos (nome começando com `.`) não são mais lidos, como no Obsidian; alvo de link e caminhos são comparados em NFC (`[[Ação]]` acha `Ação.md` gravado em NFD); uma cerca de código só fecha com outra do mesmo caractere e com pelo menos o mesmo tamanho; termos com menos de 2 caracteres não contam; `fold` filtra as marcas combinantes com `unicodedata.combining` (SPEC-0026).
- `related` não lista o `index.md` nem o `log.md` (`layout.index` e `layout.log`), nem passa por eles na vizinhança de links; o `context` não expande vizinhos através deles; o `search` continua achando os dois (SPEC-0026).
- `Note` recusa campo desconhecido com `TypeError` (SPEC-0026).
- `references/search.md`: todo `![[anexo]]` aparece em `broken` do `links`; separar anexo de nota quebrada fica para o `lint` (SPEC-0026, SPEC-0023).

## [2026.10.9] - 2026-10-30

### Fixed
- `init` sem `--adopt` numa pasta que só tem `.obsidian/` (vault recém-criado no app do Obsidian), além de `.DS_Store`, `Thumbs.db` ou `desktop.ini`, cria a estrutura padrão completa em vez de pedir `--adopt`, e não altera nada dentro de `.obsidian/`; a checagem vira `is_empty_vault(folder)` no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.9). Qualquer outro arquivo ou pasta continua exigindo `--adopt`; `SKILL.md` e `references/vault-layout.md` citam o caso (SPEC-0025).

## [2026.10.8] - 2026-10-30

### Added
- `export-notebooklm MOC --out PASTA [--hops 0..2] [--combined] [--json]` no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.8), só leitura do vault: junta o MOC (nome do contexto ou caminho), as notas que ele cita e as vizinhas delas por link até `--hops` (padrão 1), reusando o `neighbors` do `context` com o MOC, o `index.md` e o `log.md` bloqueados; grava em `PASTA`, fora do vault, um `.md` por nota (título na primeira linha, sem frontmatter), `sources.md` (de onde veio cada nota) e, com `--combined`, `combined.md`. Cada arquivo é criado em modo exclusivo; `--out` dentro do vault, ou já com arquivos, sai com 2 e nada é escrito; o vault não muda, nem o `log.md` (SPEC-0024, ADR-0007).
- `flatten_links(text)`: wikilinks viram texto simples (`[[Nota|apelido]]` → `apelido`) e embeds de anexo viram `(anexo: nome)` (SPEC-0024).
- `references/notebooklm.md` com o passo a passo de envio, os formatos aceitos e os limites (500.000 palavras ou 200 MB por fonte; 50 fontes por notebook no plano gratuito), conferidos em 2026-10-30 na ajuda oficial do Google; `SKILL.md`: oferecer o pacote do MOC quando a pessoa vai estudar ou se preparar para uma prova (SPEC-0024).

## [2026.10.7] - 2026-10-30

### Added
- `lint [--json] [--only regra,...]` no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.7), só leitura: `broken-link`, `conflict-copy`, `missing-file` e `config` (erro); `orphan`, `stale-inbox` e `frontmatter` (aviso). Cada regra é uma função `check_<regra>` sobre uma única varredura do vault; texto `<ERRO|AVISO> <regra> <caminho> — <detalhe> (sugestão: …)` com o resumo "N erros, M avisos", ou JSON `{"findings", "summary"}`; exit 0 sem erro, 1 com erro, 2 com regra desconhecida em `--only` (SPEC-0023, ADR-0007).
- Chave `conflict_patterns` no `brain-config.yml` (regex sobre o nome do arquivo, com o grupo `base`); ausente = os padrões do provider da configuração local, documentados em `references/providers.md` (por enquanto os genéricos, sem os nomes reais de cada provedor conferidos). Regex inválido vira achado `config` e as outras regras rodam; pasta `files` inacessível vira achado `config` e `missing-file` é pulada (SPEC-0023).
- Link ou embed para anexo (`![[foto.png]]`) só é `broken-link` quando nenhum arquivo com esse nome existe no vault (SPEC-0023).
- `SKILL.md`: fluxo de manutenção em quatro passos (lint, explicar por severidade, propor por achado, aplicar só com o sim do usuário), quando rodar e a regra de nunca apagar; `references/maintenance.md`; `assets/brain-config.yml` com o exemplo comentado de `conflict_patterns` (SPEC-0023).

### Changed
- `doctor` ganha a linha `OK|AVISO|ERRO lint — N erros, M avisos (rode lint)` e passa a sair com 1 quando o `lint` tem erro (SPEC-0023).

## [2026.10.6] - 2026-10-30

### Added
- Processadores no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.6): `run_processor` é o único ponto que roda processo externo — o `command` de `processors.<tipo>` do `brain-config.yml` vira uma lista de argumentos (`shlex.split`, `{input}`, `{output}` e `{output_dir}` trocados numa passada), sem shell, num diretório temporário, com `timeout` (padrão 1800 s; o processo é encerrado) e saída capturada; o texto vem de `{output}`, do maior arquivo da extensão `output` em `{output_dir}` ou do stdout, e legendas `.vtt`/`.srt` viram texto (SPEC-0022, ADR-0009).
- `process ENTRADA [--kind K] [--out ARQ] [--timestamps]`: texto no stdout ou em `--out` (exit 0); sem processador sai com 2 ("nenhum processador para <tipo> — veja references/processors.md"); falha sai com 1 ("processador <tipo> falhou: <motivo>", com o stderr resumido em até 500 caracteres) (SPEC-0022).
- `ingest` detecta o tipo (URL do YouTube, extensões de vídeo e áudio, `.pdf`; `--kind` força) e chama o processador, com o texto sob `## Extracted text`; `--no-process` desliga e `--text-file` tem prioridade; `--timestamps` gera linhas `[mm:ss]` e, no YouTube, `[mm:ss](<url>?t=<s>s)` (ou `&t=`). Falha: aviso, `_(extraction failed: <motivo>)_` na nota, registro no `log.md` e exit 0; sem processador: `_(pending)_` e aviso "sem processador para <tipo>" (SPEC-0022).
- `doctor`: `OK|AVISO processor <tipo> — <executável> (<primeira linha da checagem>)`, rodando o `check` declarado ou `<executável> --version` pelo `run_processor` (SPEC-0022).
- `references/processors.md` com os modelos de yt-dlp (só legendas, `--skip-download`), Whisper (vídeo e áudio) e pdftotext, cada um com versão e data da conferência, o aviso de rede do yt-dlp e como trocar por whisper.cpp; `assets/brain-config.yml` com os modelos comentados; `SKILL.md`: o onboarding oferece os modelos e o passo 2 do fluxo de guardar usa o processador (SPEC-0022).

### Fixed
- Revisão dos processadores: o `run_processor` roda o processador na própria sessão/grupo de processos e, no `timeout` (ou em qualquer erro no meio da execução), encerra o grupo inteiro (`os.killpg` com `SIGKILL` no POSIX; `kill` no Windows), inclusive os netos (ex.: o `ffmpeg` que o Whisper chama) (SPEC-0022, ADR-0009).
- `process --out ARQ` nunca sobrescreve: ARQ que já existe sai com 2 ("já existe: <ARQ>"), ARQ dentro do vault sai com 2 sem gravar nada, e a gravação usa criação exclusiva (SPEC-0022).
- `references/processors.md`: a seção do pdf cita a página de manual do `pdftotext` lida em manpages.debian.org (cópia da página upstream, poppler 26.07.0, 2026-10-30, não executado nesta máquina) e a do Whisper diz que o `ffmpeg` no PATH é pré-requisito (SPEC-0022).

## [2026.10.5] - 2026-10-30

### Added
- Inbox no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.5): `capture TEXTO [--context C] [--json]` cria a nota rápida `inbox/AAAA-MM-DD-HHMMSS-<slug>.md` (`type: capture`; mesmo nome no mesmo segundo → `-1`; texto vazio sai com 2); `inbox list [--json]` lista os itens do mais antigo para o mais novo com `kind` (`text`, `link`, `file`, `syncing` para placeholders `.icloud` e arquivos de 0 bytes recentes), `size`, `age_days`, `stale` e `preview`; `inbox done ITEM [--note CAMINHO]` move um item de texto ou link já guardado para `raw/processed/AAAA-MM/` e registra a nota no log (`file` e `syncing` saem com 2) (SPEC-0021).
- `ingest ITEM --move`: o arquivo sai da inbox para `files` em vez de ser copiado; fonte fora da inbox sai com 2 ("--move só vale para itens da inbox"). `move_out_of_inbox` é a única função que move arquivo: só de dentro da inbox, nunca sobrescreve o destino (`-1`, `-2`...) e nunca apaga (SPEC-0021, ADR-0007).
- `inbox_stale_days` no `brain-config.yml` (padrão 7 quando ausente), visível no `config` (SPEC-0021).
- `SKILL.md`: fluxo de processar a inbox em quatro passos; `references/inbox.md`; `references/mobile-capture.md` com a captura pelo celular em cada provedor da v1 (iOS e Android) e pelo Obsidian mobile, só com os fatos verificados do ADR-0008 (SPEC-0021).

### Fixed
- Revisão da inbox: `inbox done --note` com caminho absoluto dentro do vault grava o caminho relativo ao vault, e fora do vault sai com 2 sem mover nada (o `log.md` nunca tem caminho absoluto) (SPEC-0021).
- `ingest --move` e `inbox done` recusam com 2 item que é link simbólico ou que está numa subpasta oculta da inbox (como o `inbox list`, que não os mostra); nada se move e o log não muda (SPEC-0021).
- Caracteres de controle no nome de um item saem escapados (`\n`, `\t`, `\x1b`) no `log.md` e na saída: um registro por linha (SPEC-0021).
- `.md`/`.txt` com bytes NUL é `file`; a prévia do `inbox list` não tem caracteres de controle; a prévia de `.webloc` resolve as entidades XML (`&amp;` → `&`) (SPEC-0021).
- `inbox_stale_days` inválido (negativo, decimal, texto) usa 7 com aviso na lista `warnings` do `config --json` e `AVISO inbox_stale_days` no `doctor` (SPEC-0021).
- Documentação: `mobile-capture.md` sem "pago" entre os fatos verificados e com a linha do iCloud no Android como orientação não verificada; `config.md` documenta `inbox_stale_days`; `inbox.md` diz que o `ingest --move` falha com segurança quando `files` fica em outro volume (sem cópia automática na v1) e descreve a janela teórica entre a reserva do destino e o `os.replace` (SPEC-0021).

## [2026.10.4] - 2026-10-30

### Added
- Fluxo de consultar no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.4): `context QUERY [--context] [--hops 0..2] [--limit] [--max-chars] [--json]` monta, só lendo o vault, o pacote de notas da pergunta — o MOC do contexto primeiro, os resultados da busca pela pontuação e os vizinhos por link (saída e backlinks) por distância e título, sem repetir nota; notas inteiras até `--max-chars` (padrão 40.000), pulando para `omitted` a que não cabe e continuando com as seguintes; o MOC nunca é atravessado na expansão; links quebrados em `broken`. `context add` continua igual: vale quando `add` é a primeira palavra depois de `context` (SPEC-0020).
- Tipo de nota `answer` (`assets/templates/answer.md`, com `question`, `cites` e as seções `Question`, `Answer`, `Gaps` e `Relations`), aceito pelo `new-note --type answer` (SPEC-0020).
- `SKILL.md`: fluxo de consultar em quatro passos (buscar com `context`, ler e seguir links, responder citando `[[nota]]` e apontando lacunas, oferecer salvar como `answer` com o sim da pessoa); `references/query-flow.md`; `references/note-types.md` com o tipo `answer` (SPEC-0020).

### Fixed
- Revisão do fluxo de consultar: com `--context` o MOC entra primeiro mas não é atravessado (notas alcançáveis só por ele ficam fora); o corte por `--max-chars` pula a nota que não cabe e continua tentando as seguintes; `context` reaproveita a leitura do vault dos outros comandos; `query-flow.md` explica que vaults já configurados usam o modelo `answer` da skill até copiá-lo para `templates/` (SPEC-0020).

## [2026.10.3] - 2026-10-30

### Added
- Fluxo de guardar no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.3): `ingest FONTE` (arquivo copiado para `<files>/<contexto ou inbox>/<AAAA>/` sem sobrescrever, URL sem cópia, nota de fonte `raw/AAAA-MM-DD-<slug>.md` com `## Extracted text` de `--text-file` ou `_(pending)_`), `new-note` (modelo do tipo, do vault ou da skill, na pasta do contexto ou em `resources/`), `relate DE PARA --why [--both]` (linha `- [[Nota]] — motivo` na seção `## Relations`) e `index [--context]` (regiões `notes` dos MOCs e `contexts`/`recent` do `index.md`) (SPEC-0019).
- Escrita segura: `note_path` (título sanitizado, caminho fora do vault recusado com exit 2), `write_new_file` (nunca sobrescreve: "nota já existe"), `append_relation` e `replace_region` (só a região muda; ausente é acrescentada no fim); toda escrita com uma linha no `log.md` (SPEC-0019).
- `SKILL.md`: fluxo de guardar em seis passos (classificar, guardar o bruto, buscar relações, escrever, ligar e indexar, reportar) e o formato da seção `Relations`; `references/store-flow.md` e `references/note-types.md` com os sete tipos e o frontmatter comum (SPEC-0019).

### Fixed
- Revisão do fluxo de guardar: `replace_region`/`index` recusam marcadores de região órfãos, invertidos ou duplicados e o `index` valida tudo antes de escrever; nomes de contexto do `brain-config.yml` validados (nada fora de `files` nem do vault; `doctor` aponta); título com `{date}`, aspas ou ` #` mantido literal e legível no frontmatter; nome de arquivo de título longo cortado em 200 bytes; relação com apelido não se repete; CRLF mantido; `ingest` com `raw/` sem permissão diz onde ficou a cópia; `created` inválido fora dos recentes; nota ou MOC que é link simbólico nunca vira arquivo comum; `store-flow.md` com o limite garantido (< 3 s para 5.000 notas) (SPEC-0019).

## [2026.10.2] - 2026-10-30

### Added
- Comandos de só leitura `search QUERY [--context] [--type] [--tag] [--limit] [--json]` (TF-IDF com peso 3 no título, 2 nas tags e 1 no corpo, sem acentos e sem stopwords pt/en, trecho de até 160 caracteres), `related (--note | --text) [--limit] [--json]` (cosseno TF-IDF, tags em comum, mesmo contexto e vizinhança de links, com os motivos) e `links NOTA [--json]` (saída, backlinks e quebrados) no `scripts/brain.py` (`BRAIN_VERSION` 2026.10.2) (SPEC-0018).
- Leitura de notas (`parse_note`, `scan_vault`) com frontmatter, título, tags (frontmatter e `#tag` fora de código) e wikilinks, e resolução de links como o Obsidian (`resolve_link`: nome sem diferenciar maiúsculas, caminho com `/`, o mais curto nos empates); ignora `.obsidian/`, `.trash/`, a pasta de templates e o que não é `.md`; frontmatter inválido ou arquivo que não é UTF-8 vira aviso em `warnings` sem derrubar o comando (SPEC-0018).
- `SKILL.md`: quando usar `search`, `related` e `links` nos fluxos de guardar e de consultar; `references/search.md` com a pontuação e os filtros (SPEC-0018).

## [2026.10.1] - 2026-10-30

### Added
- Skill `second-brain`: `SKILL.md` com o onboarding (vault novo, `--adopt`, `init --join`) e o uso direto quando configurado; `references/config.md`, `providers.md` (Google Drive, OneDrive, iCloud e pasta local, com avisos de iOS e Android) e `vault-layout.md`; modelos de nota e `brain-config.yml` padrão em `assets/` (SPEC-0017).
- `scripts/brain.py` (`BRAIN_VERSION` 2026.10.1, só biblioteca padrão): configuração em duas camadas (`$BRAIN_CONFIG_HOME/config.yml` local e `<vault>/brain-config.yml` compartilhada) com a origem de cada valor; comandos `init` (novo, `--adopt` com `--map`, `--context`, `--force` com `.bak`, `--join`), `config [--json]`, `context add` e `doctor [--json]`; toda escrita no vault registrada no `log.md` (SPEC-0017).
- Proteções do vault (SPEC-0017, emenda v2): valores de `layout`, `para` e `contexts.<c>.folder` fora do vault (absolutos ou com `..`) fazem os comandos saírem com 1 e aparecem como ERRO no `doctor`; `init` recusa pasta não vazia sem `--adopt` e não adota `log.md`/`index.md` do usuário (`--map log=<outro>`); `brain-config.yml` gerado a partir de `assets/brain-config.yml` com os comentários; `context add` só insere a linha nova em `contexts`, com a indentação existente, e recusa `contexts` inline; `doctor` continua com `brain-config.yml` ilegível; `providers.md` só afirma o que a fonte verificada do ADR-0008 diz.
