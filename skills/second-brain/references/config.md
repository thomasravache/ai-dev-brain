# Configuração em duas camadas

O second-brain separa o que é de cada máquina do que é do vault (ADR-0008). `brain.py config` mostra a configuração efetiva e de onde veio cada valor: `local`, `vault` ou `padrão`.

## Camada local — `config.yml`

Fica em `$BRAIN_CONFIG_HOME/config.yml`; sem a variável, em `~/.config/second-brain/config.yml`. Nunca vai para o vault nem para um repositório. Guarda só os caminhos desta máquina:

```yaml
vault: <pasta sincronizada pelo provedor>/Vault
files: <pasta sincronizada pelo provedor>/Vault-files
provider: google-drive          # google-drive | onedrive | icloud | local
```

- `vault` — pasta do vault, dentro da pasta sincronizada do provedor. Cada máquina grava o seu caminho, inclusive um link simbólico.
- `files` — pasta dos arquivos pesados (PDFs, vídeos), **fora** do vault, no mesmo provedor. As notas guardam caminhos relativos a ela.
- `provider` — só escolhe o guia e os avisos do celular (`references/providers.md`); o código é o mesmo para todos.

É escrita pelo `brain.py init` (e pelo `init --join` numa máquina nova). `BRAIN_CONFIG_HOME` troca a pasta, útil para testes ou para mais de um vault.

## Camada compartilhada — `brain-config.yml`

Fica na raiz do vault e sincroniza com ele: todas as máquinas veem os mesmos contextos e a mesma estrutura. **Nunca tem caminho absoluto** — tudo é relativo ao vault. O `init` gera o arquivo a partir de `assets/brain-config.yml`, com os comentários do modelo; só mudam os valores de `--map` e as entradas de `--context`. Exemplo com `--context college=projects/college:College`:

```yaml
# second-brain — configuração compartilhada padrão (copiada para <vault>/brain-config.yml pelo init).
# Sincroniza com o vault: só caminhos relativos ao vault, nunca absolutos (ADR-0008). Detalhes: references/config.md
version: 1
language: auto            # idioma do conteúdo das notas; a estrutura do vault é sempre em inglês
layout:                   # pastas e arquivos da skill, relativos ao vault
  inbox: inbox
  raw: raw
  mocs: mocs
  templates: templates
  index: index.md
  log: log.md
para:                     # pastas do método PARA
  projects: projects
  areas: areas
  resources: resources
  archive: archive
contexts:                 # nome → {folder: pasta relativa, title: título do MOC}
  college: {folder: projects/college, title: College}
processors: {}            # tipo → {command: "executável {input} {output}"} (ADR-0009)
```

- `version` — versão do schema; o `doctor` avisa quando é diferente da que a skill usa.
- `language` — idioma do conteúdo das notas (`auto` = o da pessoa).
- `layout` — onde ficam inbox, raw, MOCs, modelos, `index.md` e `log.md`. Num vault adotado, `init --adopt --map inbox=Inbox` aponta para a pasta que já existe.
- `para` — pastas do método PARA (projects, areas, resources, archive); também aceitam `--map`.
- `contexts` — assuntos com pasta própria e MOC em `mocs/<nome>.md`; crie com `brain.py context add`.
- `processors` — tipo (`youtube`, `video`, `audio`, `pdf` ou outro) → comando que converte a fonte em texto (ADR-0009; modelos de yt-dlp, Whisper e pdftotext em `references/processors.md`). Chaves de cada processador:
  - `command` (obrigatória) — linha de comando com os marcadores `{input}` (o arquivo guardado em `files`, ou a URL), `{output}` (arquivo de saída) e `{output_dir}` (pasta de saída); roda sem shell, num diretório temporário.
  - `output` — extensão esperada (`vtt`, `srt` ou `txt`): sem `{output}` escrito, o texto vem do maior arquivo dessa extensão em `{output_dir}`, senão do stdout; `.vtt`/`.srt` viram texto.
  - `timeout` — segundos até o processo ser encerrado (padrão 1800).
  - `check` — comando que o `doctor` roda para testar o processador (padrão `<executável> --version`).

  O `ingest` roda o processador do tipo detectado (`--no-process` desliga; `--text-file` tem prioridade) e o `process` roda sob demanda. O `doctor` mostra `OK|AVISO processor <tipo> — <executável> (<primeira linha da checagem>)`: AVISO quando o executável não está no PATH desta máquina ou a checagem falha. O `brain-config.yml` sincroniza, então a ferramenta precisa existir em cada máquina que for usá-la.
- `inbox_stale_days` — dias (número inteiro >= 0, padrão 7) até um item da inbox aparecer como parado (`stale`) no `inbox list` (`references/inbox.md`). Valor inválido (negativo, decimal ou texto) usa o padrão 7 e gera um aviso: na lista `warnings` do `config --json` e como `AVISO inbox_stale_days` no `doctor`.
- `conflict_patterns` — lista de regex sobre o nome do arquivo, cada uma com o grupo `base` (o nome do original sem `.md`), que o `brain.py lint` usa para achar cópias de conflito da sincronização (regra `conflict-copy`, só quando `<base>.md` existe na mesma pasta). Ausente = os padrões do `provider` da configuração local desta máquina, hoje os genéricos `(?P<base>.+) \(\d+\)\.md$` e `(?i)(?P<base>.+)[ _-]conflict.*\.md$` (sem diferença de maiúsculas) para os quatro provedores (`references/providers.md`). Regex inválido, ou sem o grupo `base`, vira um achado `config` (erro) no `lint`; os outros padrões e as outras regras continuam rodando. Um padrão com quantificador aninhado (`(a+)+`, `(a*)*`, `(a+)*`, `(?:a+)+`, `(\w+\s?)+` e variações) ou com mais de 500 caracteres também vira um achado `config` e nunca é usado: um padrão assim pode travar o `lint` e o `doctor` em todas as máquinas, porque o `brain-config.yml` sincroniza. Regras do `lint`: `references/maintenance.md`.

Todo valor de `layout`, `para` e `contexts.<nome>.folder` precisa ser relativo e ficar dentro do vault: caminho absoluto ou com `..` faz os comandos saírem com 1 (`brain-config.yml: <chave> fora do vault`), e o `doctor` mostra ERRO nessa chave. Um `brain-config.yml` que não pode ser lido aparece no `doctor` como `ERRO brain-config.yml — <erro>`, e os outros itens continuam.

`brain.py context add` só insere uma linha dentro de `contexts:`, com a indentação das entradas que já existem; comentários e o resto do arquivo não mudam. Se `contexts` estiver escrito em uma linha (`contexts: {college: {...}}`), o comando sai com 2 e pede para converter para a forma em bloco.

Chave ausente usa o padrão (origem `padrão` no `config`). Valores são texto; o arquivo pode ser editado à mão, e o `init` nunca o sobrescreve sem `--force` (o anterior fica em `brain-config.yml.bak`).

## YAML aceito

O `brain.py` lê um subconjunto de YAML sem dependências: `chave: valor`, mapas aninhados por indentação, `{a: b}` e `[a, b]` numa linha, listas com `- item`, comentários com `#` e textos entre aspas (use aspas quando o valor tiver `: ` ou ` #`).
