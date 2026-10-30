# Processadores

Um processador é um comando, declarado em `processors` no `brain-config.yml`, que transforma uma fonte em texto (ADR-0009). A skill não instala nada: use as ferramentas que a pessoa já tem, ou ajude-a a instalar a que ela escolher. Sem processador para o tipo, o `ingest` guarda só o bruto, com `_(pending)_`, e avisa "sem processador para <tipo>".

## Como a skill roda um processador

```yaml
processors:
  <tipo>:                    # youtube | video | audio | pdf | outro
    command: "<executável> ... {input} ..."
    output: vtt              # vtt | srt | txt: extensão procurada em {output_dir} (opcional)
    timeout: 1800            # segundos (opcional; padrão 1800)
    check: "<executável> --version"   # opcional; é o que o doctor roda
```

- O `command` é dividido em argumentos como num terminal (aspas agrupam), e `{input}`, `{output}` e `{output_dir}` são trocados dentro de cada argumento. **Não há shell:** pipes (`|`), redirecionamentos (`>`), `&&` e variáveis (`$HOME`) não funcionam. Um nome de arquivo com espaço, `;` ou `$()` chega à ferramenta como um argumento só.
- `{input}` é o caminho absoluto da cópia em `files` (ou a URL, no YouTube). `{output}` é um arquivo `output.<output>` num diretório temporário, e `{output_dir}` é uma pasta vazia nesse diretório. O diretório some no fim.
- O texto vem de `{output}`; se ele não foi escrito, do **maior** arquivo com a extensão `output` em `{output_dir}`; senão, do stdout. Legendas `.vtt` e `.srt` viram texto limpo, ou linhas `[mm:ss] texto` com `--timestamps` (no YouTube, `[mm:ss](<url>?t=<s>s) texto`, com link para o trecho).
- Executável ausente, saída diferente de 0, `timeout` estourado (o processo é encerrado) ou texto vazio é uma falha. No `ingest` vira um aviso com o stderr resumido (até 500 caracteres) e `_(extraction failed: <motivo>)_` na nota de fonte, e o bruto fica guardado. O `process` sai com 1.
- Tipo detectado no `ingest` e no `process`: `youtube` (URL de youtube.com, www.youtube.com, m.youtube.com ou youtu.be), `video` (`.mp4 .mov .mkv .webm .avi`), `audio` (`.mp3 .m4a .wav .ogg .opus`) e `pdf`. `--kind K` força o tipo; `--no-process` não roda o processador; `--text-file` tem prioridade.
- `brain.py doctor` mostra `OK|AVISO processor <tipo> — <executável> (<primeira linha da checagem>)`. A checagem é o `check`, ou `<executável> --version`.
- Teste sem guardar nada: `brain.py process ARQUIVO_OU_URL [--kind K] [--out ARQ] [--timestamps]`.

Copie os modelos abaixo para o `brain-config.yml` do vault (chave `processors`) depois que a ferramenta estiver instalada, e rode `brain.py doctor`. O `brain-config.yml` sincroniza entre as máquinas: a ferramenta precisa existir no PATH de cada máquina que for usar o processador (nas outras o `doctor` mostra AVISO).

## youtube — yt-dlp (legendas, sem baixar o vídeo)

Versão: yt-dlp 2026.08.19 — conferido contra `yt-dlp --help` nesta máquina em 2026-10-30.

```yaml
  youtube:
    command: 'yt-dlp --skip-download --write-subs --write-auto-subs --sub-langs "pt.*,en.*" --sub-format "vtt/best" --convert-subs vtt --no-playlist -o "{output_dir}/%(id)s.%(ext)s" {input}'
    output: vtt
    timeout: 600
```

- `--skip-download`: não baixa o vídeo, só os arquivos relacionados (as legendas). `--write-subs` pega as legendas enviadas pelo autor e `--write-auto-subs` as automáticas; `--sub-langs` escolhe os idiomas (regex, separados por vírgula; troque `pt.*,en.*` pelos da pessoa). `--sub-format`/`--convert-subs vtt` garantem `.vtt`; `-o` grava em `{output_dir}`. Se vierem vários idiomas, a skill usa o maior `.vtt`.
- **Rede:** o yt-dlp acessa a internet (o YouTube) para baixar as legendas. É a única ação de rede, e só acontece porque a pessoa configurou esse processador; o `brain.py` em si não usa rede. Vídeo sem legenda nenhuma = falha ("saída vazia" ou exit diferente de 0); aí dá para baixar o áudio com outra ferramenta e usar o processador `audio`.
- `--timestamps` no `ingest` faz cada linha virar um link para o trecho do vídeo.

## video e audio — Whisper (openai-whisper)

openai-whisper versão 20250625 — conferido na documentação oficial em 2026-10-30, não executado nesta máquina (argumentos de `whisper/transcribe.py` em github.com/openai/whisper).

```yaml
  video:
    command: "whisper {input} --model turbo --output_format vtt --output_dir {output_dir} --verbose False"
    output: vtt
    timeout: 7200
    check: "whisper --help"
  audio:
    command: "whisper {input} --model turbo --output_format txt --output_dir {output_dir} --verbose False"
    output: txt
    timeout: 3600
    check: "whisper --help"
```

- Roda localmente (o modelo é baixado pelo próprio Whisper na primeira execução). `--output_format` aceita `txt`, `vtt`, `srt`, `tsv`, `json` ou `all`: use `vtt` (ou `srt`) para ter `--timestamps`, ou `txt` para só o texto. `--language pt` evita a detecção de idioma; `--model` escolhe o tamanho (`turbo` é o padrão da ferramenta; `small` ou `base` são mais rápidos).
- O Whisper não tem `--version`; por isso o `check` é `whisper --help` (o `doctor` mostra a primeira linha, `usage: whisper ...`).
- Vídeo longo demora: ajuste o `timeout` (em segundos) ao tamanho das aulas.

## pdf — pdftotext (Poppler)

Versão: poppler 26.07.0 (página de manual do `pdftotext`; a versão estável mais nova em poppler.freedesktop.org é 26.10.0) — conferido na documentação oficial em 2026-10-30, não executado nesta máquina.

```yaml
  pdf:
    command: "pdftotext -enc UTF-8 -nopgbrk {input} {output}"
    output: txt
    timeout: 300
    check: "pdftotext -v"
```

- Uso: `pdftotext [opções] PDF [arquivo-texto]`; `-enc UTF-8` fixa a codificação, `-nopgbrk` tira as quebras de página e `-layout` (opcional) mantém a disposição das colunas. Roda localmente.
- `-v` imprime a versão. Se em alguma versão ele sair com código diferente de 0, o `doctor` mostra AVISO na checagem; o processador continua funcionando.
- PDF escaneado (só imagem) não tem texto: o resultado sai vazio e vira falha. OCR fica para um processador `kind: ocr` que a pessoa configure; a v1 não traz modelo.

## Trocar de ferramenta

Qualquer ferramenta de linha de comando serve: basta um `command` que leia `{input}` e escreva o texto em `{output}`, em `{output_dir}` (com o `output` certo) ou no stdout. Exemplo: trocar o Whisper pelo **whisper.cpp** (mais rápido em CPU e no Mac), cujo executável `whisper-cli` recebe o modelo com `-m`, o arquivo com `-f`, gera `.vtt` com `-ovtt` e escolhe o nome da saída com `-of` (não conferido nesta máquina: confira no `whisper-cli --help` da versão instalada antes de usar):

```yaml
  audio:
    command: "whisper-cli -m /caminho/do/ggml-base.bin -f {input} -ovtt -of {output_dir}/transcricao"
    output: vtt
    check: "whisper-cli --help"
```

O caminho do modelo é da máquina: se as máquinas guardam o modelo em lugares diferentes, prefira um modelo num caminho igual em todas, ou um script no PATH de cada uma que saiba onde ele está. Depois de trocar, rode `brain.py doctor` e `brain.py process <um arquivo de teste>`. O whisper.cpp lê WAV de 16 kHz; outros formatos podem precisar de conversão (ex.: ffmpeg) num script próprio, porque o `command` não tem shell.
