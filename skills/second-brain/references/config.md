# Configuração em duas camadas

O second-brain separa o que é de cada máquina do que é do vault (ADR-0008). `brain.py config` mostra a configuração efetiva e de onde veio cada valor: `local`, `vault` ou `padrão`.

## Camada local — `config.yml`

Fica em `$BRAIN_CONFIG_HOME/config.yml`; sem a variável, em `~/.config/second-brain/config.yml`. Nunca vai para o vault nem para um repositório. Guarda só os caminhos desta máquina:

```yaml
vault: /Users/<nome>/Library/CloudStorage/GoogleDrive-<conta>/My Drive/Vault
files: /Users/<nome>/Library/CloudStorage/GoogleDrive-<conta>/My Drive/Vault-files
provider: google-drive          # google-drive | onedrive | icloud | local
```

- `vault` — pasta do vault, dentro da pasta sincronizada do provedor. Cada máquina grava o seu caminho, inclusive um link simbólico.
- `files` — pasta dos arquivos pesados (PDFs, vídeos), **fora** do vault, no mesmo provedor. As notas guardam caminhos relativos a ela.
- `provider` — só escolhe o guia e os avisos do celular (`references/providers.md`); o código é o mesmo para todos.

É escrita pelo `brain.py init` (e pelo `init --join` numa máquina nova). `BRAIN_CONFIG_HOME` troca a pasta, útil para testes ou para mais de um vault.

## Camada compartilhada — `brain-config.yml`

Fica na raiz do vault e sincroniza com ele: todas as máquinas veem os mesmos contextos e a mesma estrutura. **Nunca tem caminho absoluto** — tudo é relativo ao vault. Nasce de `assets/brain-config.yml`:

```yaml
version: 1
language: auto                  # idioma do conteúdo; a estrutura é sempre em inglês
layout:                         # pastas e arquivos da skill, relativos ao vault
  inbox: inbox
  raw: raw
  mocs: mocs
  templates: templates
  index: index.md
  log: log.md
para: {projects: projects, areas: areas, resources: resources, archive: archive}
contexts:                       # nome → pasta (relativa ao vault) + título do MOC
  college: {folder: projects/college, title: College}
processors: {}                  # tipo → {command: "executável {input} {output}"}
```

- `version` — versão do schema; o `doctor` avisa quando é diferente da que a skill usa.
- `language` — idioma do conteúdo das notas (`auto` = o da pessoa).
- `layout` — onde ficam inbox, raw, MOCs, modelos, `index.md` e `log.md`. Num vault adotado, `init --adopt --map inbox=Inbox` aponta para a pasta que já existe.
- `para` — pastas do método PARA (projects, areas, resources, archive); também aceitam `--map`.
- `contexts` — assuntos com pasta própria e MOC em `mocs/<nome>.md`; crie com `brain.py context add`.
- `processors` — conversores de arquivo em texto (executados numa versão futura); o `doctor` confere se a primeira palavra de `command` existe no PATH.

Chave ausente usa o padrão (origem `padrão` no `config`). Valores são texto; o arquivo pode ser editado à mão, e o `init` nunca o sobrescreve sem `--force` (o anterior fica em `brain-config.yml.bak`).

## YAML aceito

O `brain.py` lê um subconjunto de YAML sem dependências: `chave: valor`, mapas aninhados por indentação, `{a: b}` e `[a, b]` numa linha, listas com `- item`, comentários com `#` e textos entre aspas (use aspas quando o valor tiver `: ` ou ` #`).
