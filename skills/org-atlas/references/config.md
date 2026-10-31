# Configuração em duas camadas

O org-atlas separa o que é de cada máquina do que é do atlas (ADR-0010). `atlas.py config` mostra a configuração efetiva e de onde veio cada valor: `local`, `atlas` ou `padrão`; `config --json` imprime `{"values": {...}, "origins": {...}}`.

## Camada local — `config.yml`

Fica em `$ATLAS_CONFIG_HOME/config.yml`; sem a variável, em `~/.config/org-atlas/config.yml`. Nunca vai para o atlas nem para um repositório. Guarda o caminho do atlas nesta máquina e as credenciais **só pelo nome**:

```yaml
atlas: /Users/<nome>/acme-atlas      # caminho absoluto do atlas nesta máquina
credentials:                          # só NOMES; nunca valores
  github: {env: [GITHUB_TOKEN], profile: work}
  aws:
    profile: acme-prod
```

- `atlas` — pasta do atlas. Cada máquina grava o seu caminho (o `init` e o `init --join` gravam o caminho absoluto).
- `credentials` — por id de coletor: `env` (lista de nomes de variável de ambiente) e `profile` (nome de um profile da ferramenta, por exemplo da AWS CLI ou do `gh`). Cada nome de variável precisa seguir `^[A-Z_][A-Z0-9_]*$`; qualquer outra coisa (por exemplo um token colado no lugar do nome) faz `config` sair com 2 e `doctor` mostrar ERRO com "credentials aceita só nomes de variável: <coletor>", sem repetir o valor e sem gravar nada.
- O `atlas.py` nunca lê o valor de uma variável: o `doctor` só confere se o nome existe no ambiente (`definida` ou `não definida`) e mostra o nome do profile sem verificá-lo.

É escrita pelo `atlas.py init` (e pelo `init --join` numa máquina nova), que mantém as `credentials` já declaradas. `ATLAS_CONFIG_HOME` troca a pasta, útil para testes ou para mais de um atlas.

## Camada compartilhada — `atlas-config.yml`

Fica na raiz do atlas e vai junto com ele (no repositório, no modo `repo`). **Nunca tem caminho absoluto nem segredo.** O `init` gera o arquivo a partir de `assets/atlas-config.yml`, com os comentários do modelo; só mudam `organization` e `mode`:

```yaml
version: 1
organization: Acme
mode: repo                # repo | local
language: auto            # idioma do conteúdo; a estrutura é sempre em inglês
stale_days: 14
categories: [code, delivery]
collectors: []
redaction: {extra_patterns: []}
```

- `version` — versão do schema (hoje `1`); o `doctor` mostra ERRO quando é outra.
- `organization` — nome da organização (`init --org`).
- `mode` — `repo` (repositório git compartilhado com o time) ou `local` (pasta só desta máquina).
- `language` — idioma do conteúdo das páginas (`auto` = o da organização); a estrutura e as chaves ficam em inglês.
- `stale_days` — dias (número inteiro, padrão 14) até um fato coletado aparecer como desatualizado.
- `categories` — categorias de coletores habilitadas (ADR-0011), padrão `[code, delivery]`.
- `collectors` — coletores declarados (SPEC-0033), cada um com `id`, `category` e `command` (lista: o executável e os argumentos, sem shell). Hoje o `doctor` só confere se o executável (`command[0]`) existe no PATH:

  ```yaml
  collectors:
    - id: github
      category: code
      command: [gh-atlas-collector, --org, acme]
  ```

- `redaction.extra_patterns` — regex extras de mascaramento antes de gravar (SPEC-0033).

Chave ausente usa o padrão (origem `padrão` no `config`).

## O que o `doctor` confere

| Item | OK | AVISO | ERRO |
|---|---|---|---|
| `configuração local` | arquivo lido, credenciais só com nomes | — | credencial com valor |
| `pasta do atlas` | a pasta existe | — | `atlas` vazio ou pasta inexistente (mostra o caminho) |
| `atlas-config.yml` | versão, chaves e formato certos | — | ausente, ilegível, `version` diferente de 1, sem `organization`/`mode`, `mode` inválido, caminho absoluto |
| `estrutura` | todas as pastas e páginas | — | o que falta |
| `git` | `.git` na pasta do atlas | a pasta não é repositório git | — |
| `coletor <id>` | executável encontrado | — | executável não encontrado ou sem `command` |
| `credencial <coletor> <NOME>` | `definida` | `não definida` | — |

O `doctor` não executa nenhum processo: usa só arquivos, `shutil.which` e `os.environ`. Exit 0 sem ERRO, 1 com ERRO, 3 sem configuração local.
