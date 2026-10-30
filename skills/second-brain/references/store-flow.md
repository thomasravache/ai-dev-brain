# Fluxo de guardar

O `SKILL.md` define os seis passos; aqui estão os detalhes de cada comando. Toda escrita do `brain.py` acrescenta uma linha no fim do `log.md`: `- AAAA-MM-DD HH:MM <comando> <caminho> [<detalhe>]`, com o caminho relativo ao vault. Comando que falha ou não muda nada não escreve no log. Nenhum comando sobrescreve ou apaga arquivo.

## Exemplo: guardar os slides de uma aula

```bash
brain.py ingest slides.pdf --context college --text-file /tmp/slides.txt --json
# {"raw": "raw/2026-10-30-slides.md", "file": "college/2026/slides.pdf", "url": null}
brain.py related --text "integração por partes, regra do produto da derivada" --json
brain.py new-note --type lecture --title "Integrais por partes" --context college --source raw/2026-10-30-slides.md --json
# {"path": "projects/college/Integrais por partes.md"}  → escreva o corpo sintetizado neste arquivo
brain.py relate "Integrais por partes" "Regra do produto" --why "aplica" --both
brain.py index --context college
```

## `ingest FONTE`

- **Arquivo:** copiado para `<files>/<contexto ou inbox>/<AAAA>/<nome>`. Nome que já existe vira `<nome>-1`, `-2`... — a cópia anterior nunca muda. A cópia acontece antes da nota de fonte: pasta `files` inexistente ou sem permissão sai com 1 e nada é criado no vault.
- **URL (http/https):** nada é copiado; a nota guarda `source_url`. O `brain.py` não baixa nada; só um processador `youtube` configurado (yt-dlp) acessa a rede, para baixar as legendas. Ler outras páginas é com você, se tiver ferramenta para isso.
- **Nota de fonte:** `raw/AAAA-MM-DD-<slug>.md` (`-1`, `-2`... no mesmo dia), `type: source`, com o texto extraído sob `## Extracted text`, ou `_(pending)_`.
- **Processador:** o tipo é detectado pela fonte (URL do YouTube; `.mp4 .mov .mkv .webm .avi`; `.mp3 .m4a .wav .ogg .opus`; `.pdf`), ou forçado com `--kind K`. Com processador configurado para o tipo (`references/processors.md`), o `ingest` o roda sobre a cópia em `files` (ou a URL) e grava o texto na nota de fonte; o log registra `texto extraído (<tipo>)`.
  - `--text-file ARQ` tem prioridade: o texto vem do arquivo e o processador não roda. `--no-process` também não roda o processador (fica `_(pending)_`).
  - `--timestamps`: legendas e transcrições com tempo viram linhas `[mm:ss] texto`; no YouTube, `[mm:ss](<url>?t=<s>s) texto` (`&t=` quando a URL já tem `?`), com link para o trecho — útil para citar uma aula gravada.
  - Sem processador para o tipo: o bruto é guardado como antes, com `_(pending)_` e o aviso `sem processador para <tipo>`.
  - Falha (executável ausente, saída diferente de 0, `timeout` estourado ou texto vazio): o bruto fica guardado, a nota de fonte recebe `_(extraction failed: <motivo>)_`, o aviso traz o stderr resumido, o log registra a falha e o `ingest` sai com 0. Para tentar de novo sem guardar outra vez, use `brain.py process FONTE --out ARQ` (ARQ novo, fora do vault; nunca sobrescreve) e depois leia o texto (ou passe-o com `--text-file` num ingest novo).
- Fonte inexistente sai com 2 (`fonte não encontrada: FONTE`).

## `new-note`

- Caminho: `<pasta do contexto ou resources>/<título sanitizado>.md`; `/ \ : * ? " < > | # ^ [ ]` viram espaço. Pasta que sairia do vault é recusada (exit 2).
- Nota que já existe: exit 2 `nota já existe: CAMINHO`, sem mudar nada. Escolha outro título ou complemente a nota existente (só acrescentando).
- Tipo desconhecido ou contexto inexistente: exit 2 com a lista válida.
- `--source` aceita o caminho da nota de fonte (vira `"[[raw/...]]"`) ou uma URL.

## `relate DE PARA --why "motivo" [--both]`

- DE e PARA são o nome ou o caminho da nota (resolvidos como links do Obsidian); inexistente sai com 2.
- Acrescenta `- [[PARA]] — motivo` no fim da seção `## Relations` de DE (cria a seção no fim se faltar); com `--both`, o mesmo em PARA apontando para DE.
- A mesma linha já presente: nada muda e o comando diz `relação já existe`.
- Motivos úteis: "aplica", "contradiz", "exemplo de", "pré-requisito de", "complementa".

## `index [--context C]`

- `mocs/<contexto>.md`: região `notes` com as notas do contexto agrupadas por `type` (`### lecture`, `### note`...), ordenadas por título. MOC ausente é criado do modelo `moc`; MOC sem a região ganha a região no fim.
- `index.md`: região `contexts` (link para cada MOC e o total de notas) e região `recent` (as 20 notas mais recentes pelo `created`).
- Texto fora das regiões nunca muda. Com `--context C`, só o MOC de C (e o `index.md`) é regenerado.
- Num vault de 5.000 notas termina em menos de 3 s (o limite garantido).
- Marcadores de região quebrados (begin sem end, end antes do begin, região duplicada) ou um MOC que é link simbólico para fora do vault fazem o `index` parar com erro nomeando o arquivo, sem escrever nada.
