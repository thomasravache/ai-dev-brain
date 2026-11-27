# Configuração em duas camadas

A photon-brain separa o que é de cada máquina do que é do vault (ADR-0008). `brain.py config` mostra a configuração efetiva e de onde veio cada valor: `local`, `vault` ou `padrão`.

## Camada local — `config.yml`

Fica em `$BRAIN_CONFIG_HOME/config.yml`; sem a variável, em `~/.config/photon-brain/config.yml`. Nunca vai para o vault nem para um repositório. Guarda só os caminhos desta máquina:

```yaml
vault: <pasta sincronizada pelo provedor>/Vault
files: <pasta sincronizada pelo provedor>/Vault-files
provider: google-drive          # google-drive | onedrive | icloud | local
backup_targets:                 # opcional: destinos de backup desta máquina (references/backup.md)
  - <pasta local fora do provedor>/photon-brain
  - <pasta de outro provedor ou conta>/photon-brain-backups
```

- `vault` — pasta do vault, dentro da pasta sincronizada do provedor. Cada máquina grava o seu caminho, inclusive um link simbólico.
- `files` — pasta dos arquivos pesados (PDFs, vídeos), **fora** do vault, no mesmo provedor. As notas guardam caminhos relativos a ela.
- `provider` — só escolhe o guia e os avisos do celular (`references/providers.md`); o código é o mesmo para todos.
- `backup_targets` — lista de pastas onde o `brain.py backup` grava os zips (opcional). São caminhos desta máquina, por isso ficam aqui e nunca no vault. Acrescente com `brain.py backup target add PASTA` (nunca dentro do vault nem da pasta `files`); o `init` mantém a lista quando regrava esta configuração. Detalhes: `references/backup.md`.

É escrita pelo `brain.py init` (e pelo `init --join` numa máquina nova). `BRAIN_CONFIG_HOME` troca a pasta, útil para testes ou para mais de um vault.

**Compatibilidade com o nome antigo:** uma máquina configurada antes da versão 2026.11.8 tem a configuração em `~/.config/second-brain/config.yml`. Sem `BRAIN_CONFIG_HOME`, o `brain.py` lê `~/.config/photon-brain/config.yml` se existir; se não, lê a pasta antiga como reserva, até a remoção anunciada no `CHANGELOG.md` (não antes de 2027-03, SPEC-0073). Toda gravação (`init`, `init --join`, `backup target add`) vai só para a pasta nova, com a configuração completa; a pasta antiga nunca é gravada, movida nem apagada. O `doctor` mostra um AVISO com o comando de cópia (`mkdir -p ~/.config/photon-brain && cp -p ~/.config/second-brain/config.yml ~/.config/photon-brain/`) quando só a antiga existe, e outro dizendo que ela é ignorada (e pode ser apagada) quando as duas existem. Com `BRAIN_CONFIG_HOME` vale só essa pasta, sem reserva nem aviso (SPEC-0069, ADR-0020).

## Camada compartilhada — `brain-config.yml`

Fica na raiz do vault e sincroniza com ele: todas as máquinas veem os mesmos contextos e a mesma estrutura. **Nunca tem caminho absoluto** — tudo é relativo ao vault. O `init` gera o arquivo a partir de `assets/brain-config.yml`, com os comentários do modelo; só mudam os valores de `--map` e as entradas de `--context`. Exemplo com `--context college=projects/college:College`:

```yaml
# photon-brain — configuração compartilhada padrão (copiada para <vault>/brain-config.yml pelo init).
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
- `contexts` — assuntos com pasta própria e MOC em `mocs/<nome>.md`; crie com `brain.py context add`. O nome e cada parte da pasta ficam em kebab-case (minúsculas, sem acento, cada sequência fora de `[a-z0-9]` vira `-`, sem traço nas pontas): o `init --context` e o `context add` ajustam e avisam "nome ajustado para kebab-case: `<de>` → `<para>`" (`Trabalho Novo` → `trabalho-novo`, `Areas/Trabalho Novo` → `areas/trabalho-novo`), e um nome ou parte sem letras a–z nem dígitos 0–9 sai com 2 — nomes só com outros alfabetos (ex.: `数学`) não são aceitos; use uma transliteração (`matematica`) no nome e o original no `title`. Dois contextos que viram o mesmo kebab (`Trabalho Novo` e `trabalho-novo`), no mesmo `init` ou contra um contexto já gravado, saem com 2 antes de qualquer escrita, citando os dois nomes. As partes iniciais da pasta que coincidem (sem diferença de maiúsculas) com uma pasta do `layout`/`para` ficam com a grafia configurada: num vault adotado com `--map projects=Projects`, `--folder Projects/Faculdade` vira `Projects/faculdade`. O `title` fica como foi escrito. Um contexto gravado à mão fora do padrão continua funcionando: o `doctor` mostra AVISO para o nome ou a pasta e não renomeia nada.
- `processors` — tipo (`youtube`, `video`, `audio`, `pdf` ou outro) → comando que converte a fonte em texto (ADR-0009; modelos de yt-dlp, Whisper e pdftotext em `references/processors.md`). Chaves de cada processador:
  - `command` (obrigatória) — linha de comando com os marcadores `{input}` (o arquivo guardado em `files`, ou a URL), `{output}` (arquivo de saída) e `{output_dir}` (pasta de saída); roda sem shell, num diretório temporário.
  - `output` — extensão esperada (`vtt`, `srt` ou `txt`): sem `{output}` escrito, o texto vem do maior arquivo dessa extensão em `{output_dir}`, senão do stdout; `.vtt`/`.srt` viram texto.
  - `timeout` — segundos até o processo ser encerrado (padrão 1800).
  - `check` — comando que o `doctor` roda para testar o processador (padrão `<executável> --version`).

  O `ingest` roda o processador do tipo detectado (`--no-process` desliga; `--text-file` tem prioridade) e o `process` roda sob demanda. O `doctor` mostra `OK|AVISO processor <tipo> — <executável> (<primeira linha da checagem>)`: AVISO quando o executável não está no PATH desta máquina ou a checagem falha. O `brain-config.yml` sincroniza, então a ferramenta precisa existir em cada máquina que for usá-la.
- `inbox_stale_days` — dias (número inteiro >= 0, padrão 7) até um item da inbox aparecer como parado (`stale`) no `inbox list` (`references/inbox.md`). Valor inválido (negativo, decimal ou texto) usa o padrão 7 e gera um aviso: na lista `warnings` do `config --json` e como `AVISO inbox_stale_days` no `doctor`.
- `timezone` — fuso do vault, um nome IANA como `America/Sao_Paulo` (opcional). Sem a chave, vale o fuso da máquina que roda o comando. As datas que o `brain.py` grava saem nesse fuso, mesmo numa sessão na nuvem em UTC: o `created` das capturas leva o deslocamento (`2026-11-26T09:15:02-03:00`; UTC sai `+00:00`) e o nome da captura usa a mesma hora; o `created` das notas organizadas continua `AAAA-MM-DD` e a linha do `log.md` mantém o formato, as duas no fuso do vault. O nome é conferido contra `^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$` antes de chegar ao `zoneinfo`: fora da regra, o `doctor` mostra `ERRO timezone — timezone inválido: use um nome como America/Sao_Paulo`; um nome que a base de fusos desta máquina não tem (comum no Windows sem o pacote `tzdata`) dá `ERRO timezone — fuso <nome> não encontrado nesta máquina (instale a base de fusos)`. Nos dois casos, os comandos que gravam datas (`capture`, `new-note`, `ingest`, `relate`, `append`, `index`, `inbox done`, `context add`...) saem com 2 sem gravar nada, e os que só leem (`search`, `config`, `inbox list`...) seguem. Com a chave válida, o `doctor` mostra `OK timezone — fuso: <nome>`; sem ela, `OK timezone — fuso: o da máquina (±HH:MM)`. O `capture --print --timezone NOME` vale só quando o `brain-config.yml` não pode ser lido (`references/connectors.md`) (SPEC-0109).
- `connectors` — IDs das pastas do vault e da inbox no provedor, por provedor (opcional; SPEC-0110): `connectors.<provedor>.vault_folder_id` e `connectors.<provedor>.inbox_folder_id` (este opcional), com `<provedor>` um de `google-drive`, `onedrive`, `icloud`, `local`. Servem ao agente que só tem o conector do provedor, como numa sessão na nuvem, onde não há configuração local (`references/connectors.md`, ADR-0027). São texto opaco, nunca credencial: cada ID segue `^[A-Za-z0-9_-]{8,128}$` e um valor com cara de segredo (o detector do `lint`, `references/confidential.md`) é recusado. Grave com `brain.py connector set PROVEDOR --vault-folder-id ID [--inbox-folder-id ID]`, que só troca ou acrescenta essas linhas (o resto do arquivo e os comentários não mudam; um campo não passado fica como está) e registra `connector set <provedor>` no `log.md`, sem os IDs; provedor desconhecido ou ID inválido sai com 2 sem gravar nada. Veja com `brain.py connector show [--json]` ou no `config --json` (`values.connectors`, `{}` sem a chave). O `doctor` mostra `OK connectors.<provedor> — ids gravados: vault, inbox` (sem os IDs), `AVISO connectors.<x> — provedor desconhecido` e `ERRO connectors.<provedor>.<campo> — id inválido ...` para um ID escrito à mão fora da regra. Sem a chave, nada muda: o agente acha o vault pelo nome do `brain-config.yml`. O `brain.py` nunca consulta o provedor (ADR-0008).
- `backup` — opções do backup (opcional; `references/backup.md`): `keep` (backups mantidos por destino e por tipo, inteiro >= 1, padrão 10), `warn_days` (dias até o `doctor` avisar que o último backup está velho, inteiro >= 0, padrão 7) e `with_files` (`true` inclui a pasta `files`, padrão `false`). Valor inválido usa o padrão e gera um aviso que cita a chave (`backup.keep`, `backup.warn_days`, `backup.with_files`), na lista `warnings` do `config --json` e como `AVISO` no `doctor`, como o `inbox_stale_days`.
- `conflict_patterns` — lista de regex sobre o nome do arquivo, cada uma com o grupo `base` (o nome do original sem `.md`), que o `brain.py lint` usa para achar cópias de conflito da sincronização (regra `conflict-copy`, só quando `<base>.md` existe na mesma pasta). Ausente = os padrões do `provider` da configuração local desta máquina, hoje os genéricos `(?P<base>.+) \(\d+\)\.md$` e `(?i)(?P<base>.+)[ _-]conflict.*\.md$` (sem diferença de maiúsculas) para os quatro provedores (`references/providers.md`). Regex inválido, ou sem o grupo `base`, vira um achado `config` (erro) no `lint`; os outros padrões e as outras regras continuam rodando. Um padrão com quantificador aninhado (`(a+)+`, `(a*)*`, `(a+)*`, `(?:a+)+`, `(\w+\s?)+`, `(a+){20}`, `(a*){2,5}` e variações) ou com mais de 500 caracteres também vira um achado `config` e nunca é usado: um padrão assim pode travar o `lint` e o `doctor` em todas as máquinas, porque o `brain-config.yml` sincroniza. A verificação é de melhor esforço: alternativas sobrepostas, como `(a|aa)+`, não são detectadas. Prefira padrões simples (um `.+` para o nome e o sufixo literal da cópia). Regras do `lint`: `references/maintenance.md`.
- `lint` — opções das regras de dado pessoal do `lint` (opcional; ausente = o padrão):
  - `personal_data` — lista dos detectores ligados da regra `personal-data`: `cpf`, `cnpj`, `card`, `labeled-document`. Ausente = todos; `[]` = nenhum. Detector desconhecido vira um achado `config` no `lint`.
  - `personal_data_patterns` — mapa `nome: regex` de padrões extras (ex.: `nif: '\bNIF:\s*\d{9}\b'`); o achado usa o nome como tipo e nunca mostra o valor. Regex inválido, com quantificador aninhado ou com mais de 500 caracteres vira um achado `config` citando o nome e não é usado (a mesma proteção do `conflict_patterns`); os outros padrões continuam rodando. Detalhes: `references/confidential.md`.

Todo valor de `layout`, `para` e `contexts.<nome>.folder` precisa ser relativo e ficar dentro do vault: caminho absoluto ou com `..` faz os comandos saírem com 1 (`brain-config.yml: <chave> fora do vault`), e o `doctor` mostra ERRO nessa chave. Um `brain-config.yml` que não pode ser lido aparece no `doctor` como `ERRO brain-config.yml — <erro>`, e os outros itens continuam.

`brain.py context add` só insere uma linha dentro de `contexts:`, com a indentação das entradas que já existem; comentários e o resto do arquivo não mudam. Se `contexts` estiver escrito em uma linha (`contexts: {college: {...}}`), o comando sai com 2 e pede para converter para a forma em bloco.

Chave ausente usa o padrão (origem `padrão` no `config`). Valores são texto; o arquivo pode ser editado à mão, e o `init` nunca o sobrescreve sem `--force` (o anterior fica em `brain-config.yml.bak`).

## YAML aceito

O `brain.py` lê um subconjunto de YAML sem dependências: `chave: valor`, mapas aninhados por indentação, `{a: b}` e `[a, b]` numa linha, listas com `- item`, comentários com `#` e textos entre aspas (use aspas quando o valor tiver `: ` ou ` #`).
