# Configuração em duas camadas

A boson-atlas separa o que é de cada máquina do que é do atlas (ADR-0010). `atlas.py config` mostra a configuração efetiva e de onde veio cada valor: `local`, `atlas` ou `padrão`; `config --json` imprime `{"values": {...}, "origins": {...}, "atlas_name": ..., "selected_by": ..., "atlases": [...]}` (veja [Vários atlas na mesma máquina](#vários-atlas-na-mesma-máquina)).

## Camada local — `config.yml`

Fica em `$ATLAS_CONFIG_HOME/config.yml`; sem a variável, em `~/.config/boson-atlas/config.yml`. Nunca vai para o atlas nem para um repositório. Guarda o caminho do atlas nesta máquina e as credenciais **só pelo nome**:

```yaml
atlas: /Users/<nome>/acme-atlas      # caminho absoluto do atlas nesta máquina
credentials:                          # só NOMES; nunca valores
  github: {env: [GITHUB_TOKEN], profile: work}
  aws:
    profile: acme-prod
```

- `atlas` — pasta do atlas. Cada máquina grava o seu caminho **absoluto** (o `init` e o `init --join` gravam assim); um caminho relativo editado à mão vira ERRO no `doctor`.
- `credentials` — por id de coletor: `env` (lista de nomes de variável de ambiente) e `profile` (nome de um profile da ferramenta, por exemplo da AWS CLI ou do `gh`). Cada nome de variável precisa seguir `^[A-Z_][A-Z0-9_]*$`; qualquer outra coisa (por exemplo um token colado no lugar do nome) faz `config` sair com 2 e `doctor` mostrar ERRO com "credentials aceita só nomes de variável: <coletor>", sem repetir o valor e sem gravar nada. Um `profile` com espaços sai do mesmo jeito, com "credentials aceita só um nome de profile, sem espaços: <coletor>".
- O `atlas.py` nunca lê o valor de uma variável: o `doctor` só confere se o nome existe no ambiente (`definida` ou `não definida`) e mostra o nome do profile sem verificá-lo.

É escrita pelo `atlas.py init` (e pelo `init --join` numa máquina nova, que não aceita `--org`, `--mode` nem `--force`), que mantém as `credentials` já declaradas para o mesmo atlas. `ATLAS_CONFIG_HOME` troca a pasta, útil para testes; para mais de um atlas, use a forma de vários atlas abaixo.

## Vários atlas na mesma máquina

Quem trabalha para mais de uma organização guarda vários atlas no mesmo `config.yml`, cada um com um nome e as suas credenciais (SPEC-0079, ADR-0021):

```yaml
default: acme                         # opcional; precisa existir em atlases
atlases:
  acme:                               # nome: [a-z0-9][a-z0-9-]{0,62}
    atlas: /Users/<nome>/acme-atlas
    credentials:
      github: {env: [ACME_GITHUB_TOKEN]}
  globex:
    atlas: /Users/<nome>/globex-atlas
    credentials: {}
```

- A forma de um atlas só (`atlas:` + `credentials:`) continua valendo e é a gravada enquanto houver um atlas. O nome dessa entrada é a `organization` do `atlas-config.yml` em minúsculas, com o que não for `[a-z0-9-]` trocado por `-` (vários `-` viram um, sem `-` nas pontas, até 63 caracteres; `Acme Corp` → `acme-corp`); se a `organization` não puder ser lida, o nome é `default`.
- As duas formas no mesmo arquivo, um nome inválido, um `default` que não está em `atlases` ou uma chave desconhecida numa entrada (só `atlas` e `credentials`) fazem todos os comandos saírem com 2, citando a chave.
- As credenciais de um atlas nunca são usadas por outro: `scan`, `config` e `doctor` leem e checam só as do atlas escolhido.
- O que o isolamento cobre: no `scan`, os coletores recebem o ambiente do shell **sem** as variáveis declaradas em `env` só nas credenciais de outros atlas (uma variável declarada também pelo atlas escolhido continua). Variáveis que nenhum atlas declara chegam como antes. Credenciais por `profile` ou por arquivo (por exemplo `~/.aws/credentials` ou o login do `gh`) não são isoladas pelo `atlas.py`: dependem da configuração de cada coletor, então aponte o coletor de cada atlas para o seu profile.
- A forma de vários atlas é gravada com as entradas em ordem de nome.

### Ordem de escolha

Todos os comandos menos o `init` (`scan`, `build`, `context`, `curate`, `vendor`, `lint`, `config` e `doctor`) usam um atlas só, o primeiro que se aplica:

1. `--atlas <nome|pasta>` — é pasta quando tem `/` ou começa com `~` ou `.` (casa pela pasta resolvida);
2. a variável `ATLAS_NAME=<nome|pasta>`;
3. o remote do projeto: o `origin` da pasta atual casado com `remotes:` do `atlas-config.yml` de cada atlas (abaixo, SPEC-0080);
4. o `default`;
5. o único atlas configurado.

Um nome ou uma pasta que não está no `config.yml` sai com 3: `atlas não configurado nesta máquina: <x> — rode init --join --atlas <caminho> (atlas configurados: acme, globex)`. Vários atlas sem `default` e sem escolha saem com 2: `vários atlas configurados (acme, globex) e nenhum escolhido — use --atlas <nome>, ATLAS_NAME ou config --set-default <nome>`.

`config` mostra a linha `atlas: <nome> (escolhido por: --atlas|ATLAS_NAME|remote do projeto|default|único)`; `config --json` traz também `atlas_name`, `selected_by` (`option`, `env`, `remote`, `default` ou `single`) e `atlases` (`[{"name", "atlas", "default"}]`, por nome; na forma de um atlas só, a única entrada tem `"default": true`).

### Atlas pelo remote do projeto (`remotes:`)

O `atlas-config.yml` compartilhado de cada atlas pode declarar os prefixos dos repositórios da organização. Como fica no atlas, vale para toda a organização e chega a cada máquina pelo `init --join` (SPEC-0080, ADR-0021):

```yaml
remotes:                       # opcional
  - github.com/acme
  - gitlab.acme.interno/plataforma
```

- Cada item é `host/caminho` em minúsculas, sem esquema, `@`, `:`, `?`, `#`, `=`, espaço, caractere de controle, `..` nem barra no início ou no fim. Um item fora disso faz os comandos do atlas escolhido saírem com 2; o `lint` aponta o mesmo problema. A mensagem nunca cita o item (nem mascarado): diz só a posição, a partir de 1, e o primeiro motivo que se aplica, por exemplo `remotes: item 2 inválido — tem esquema (ex.: https://); use host/caminho, como github.com/acme`. Os motivos, nesta ordem: `não é texto`, `vazio`, `tem esquema`, `tem credenciais (@)`, `tem ? , # ou =`, `tem : (porta ou formato scp)`, `tem espaço ou caractere de controle`, `tem maiúsculas` e `tem barra no início ou no fim, // ou segmento . ou ..` (que também cobre `~` no início e `\`).
- Um atlas com `remotes:` inválido conta como sem `remotes:` no passo 3 e não atrapalha os outros: o exit 2 só acontece quando ele é o escolhido, o `config --list` não falha por isso e o `doctor` mostra `AVISO remotes do atlas <nome>`, sem o item.
- `init --atlas <pasta> --org O --mode M --remote github.com/acme [--remote ...]` grava a lista no atlas novo (o `init --join` não aceita `--remote`: a lista já vem do atlas).
- No passo 3, a CLI lê `git -C <pasta atual> config --get remote.origin.url` (só leitura, `GIT_OPTIONAL_LOCKS=0`, prazo de 5 s) e o normaliza para `host/caminho` em minúsculas, sem esquema, usuário, senha ou token, porta nem `.git`: `https://usuario:token@GitHub.com/Acme/API.git` e `git@github.com:Acme/API.git` viram `github.com/acme/api`; `ssh://git@host:2222/g/r.git` vira `host/g/r`.
- Um item casa quando é igual ao remote ou prefixo dele por segmentos inteiros: `github.com/acme` casa `github.com/acme/api`, mas não `github.com/acme-labs/x`. Com mais de um atlas casando, vale o prefixo mais longo; empate no mesmo comprimento pula o passo (vale o `default`) e o `doctor` mostra um AVISO com os nomes dos atlas.
- Pasta sem git, sem `origin`, sem `git` no `PATH`, pasta atual removida ou prazo estourado: o passo é pulado sem erro. Sem nenhum atlas com `remotes:`, o `git` nem é chamado.
- O remote nunca aparece na saída: `selected_by` diz só `remote`, e o AVISO do `doctor` traz só os nomes dos atlas.
- Atualize todas as máquinas antes de declarar `remotes:`: a versão anterior ignora a chave nos comandos, mas o `lint` dela acusa `chave desconhecida: remotes`.

### Acrescentar, listar e trocar o padrão

- `init --atlas <pasta> --org O --mode M [--name N] [--default]` e `init --join --atlas <pasta> [--name N] [--default]` acrescentam ou atualizam a entrada `N` sem mudar as outras. Sem `--name`, vale o nome que a pasta já tem nesta máquina, senão o nome derivado da `organization`. A primeira entrada vira o `default`; `--default` torna `N` o padrão. Uma entrada nova começa com `credentials: {}`; o mesmo nome e a mesma pasta atualizam a entrada e mantêm as credenciais dela.
- Um nome já usado por outra pasta, ou uma pasta já configurada com outro nome, sai com 2 sem mudar o arquivo.
- Com um atlas só e sem `--name`, o `init`/`init --join` de outra pasta da mesma organização (mesmo nome derivado) só troca a pasta da entrada, como na versão anterior. O mesmo vale quando a pasta da única entrada não existe mais ou a `organization` dela não pode ser lida (o atlas foi movido com `mv`): a entrada é reapontada, mantém as credenciais e nenhum `.bak` é gravado.
- Ao passar da forma de um atlas só para a de vários, o `init` guarda o arquivo anterior em `config.yml.bak` (ou `.bak.1`, `.bak.2`…).
- `config --list [--json]` lista todos os atlas (nome, pasta, `organization` e `[default]`) e, na última linha, qual seria escolhido agora (`escolhido: acme (default)`) ou `escolhido: nenhum`; não falha com vários atlas sem escolha. O `--json` imprime `{"atlases": [{"name", "atlas", "default", "organization"}], "atlas_name", "selected_by"}`.
- `config --set-default <nome>` grava o `default`; um nome que não existe sai com 2, e com um atlas só o arquivo não muda.

Onboarding com duas organizações:

```bash
python3 scripts/atlas.py init --atlas ~/acme-atlas --org Acme --mode repo --remote github.com/acme   # vira o default
python3 scripts/atlas.py init --join --atlas ~/globex-atlas --name globex        # acrescenta; grava config.yml.bak
python3 scripts/atlas.py config --list
python3 scripts/atlas.py context "pagamentos" --atlas globex                      # ou ATLAS_NAME=globex
python3 scripts/atlas.py config --set-default globex
```

**Remover um atlas:** não há comando; edite o `config.yml` e apague a entrada (com uma entrada só, pode voltar à forma `atlas:` + `credentials:`). O `doctor` mostra um AVISO quando a pasta de outro atlas da lista não existe mais.

**Rollback:** a versão anterior da skill só entende a forma de um atlas só. Quem já tem dois atlas restaura o backup: `cp ~/.config/boson-atlas/config.yml.bak ~/.config/boson-atlas/config.yml` (ou na pasta de `ATLAS_CONFIG_HOME`).

**Compatibilidade com o nome antigo:** uma máquina configurada antes da versão 2026.11.7 tem a configuração em `~/.config/org-atlas/config.yml`. Sem `ATLAS_CONFIG_HOME`, o `atlas.py` lê `~/.config/boson-atlas/config.yml` se existir; se não, lê a pasta antiga como reserva, até a remoção anunciada no `CHANGELOG.md` (não antes de 2027-03, SPEC-0073). Toda gravação (`init`, `init --join`) vai só para a pasta nova, com a configuração completa (as `credentials` já declaradas na antiga vêm junto); a pasta antiga nunca é gravada, movida nem apagada, e os comandos que só leem não criam a pasta nova. O `doctor` mostra um AVISO com o comando de cópia (`mkdir -p ~/.config/boson-atlas && cp -p ~/.config/org-atlas/config.yml ~/.config/boson-atlas/`) quando só a antiga existe, e outro dizendo que ela é ignorada (e pode ser apagada) quando as duas existem. Com `ATLAS_CONFIG_HOME` vale só essa pasta, sem reserva nem aviso (SPEC-0070, ADR-0020).

## Camada compartilhada — `atlas-config.yml`

Fica na raiz do atlas e vai junto com ele (no repositório, no modo `repo`). **Nunca tem caminho absoluto nem segredo.** O `init` gera o arquivo a partir de `assets/atlas-config.yml`, com os comentários do modelo; só mudam `organization` e `mode`. Um `atlas-config.yml` diferente só é substituído com `init --force`, que guarda o anterior em `atlas-config.yml.bak` (ou `.bak.1`, `.bak.2`…, sem sobrescrever um backup antigo):

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
| `Atlas configurados` | quantos e quais (`2 (acme, globex)`) | — | — |
| `atlas <nome>` | — | a pasta de outro atlas da lista não existe mais | — |
| `atlas escolhido` | o nome e por que foi escolhido | — | vários atlas e nenhum escolhido (a mensagem da escolha) |
| `configuração no caminho antigo ~/.config/org-atlas` / `~/.config/org-atlas é ignorada` | — | só a pasta antiga existe (com o comando de cópia para `~/.config/boson-atlas`) ou as duas existem (vale a nova, `~/.config/boson-atlas`); nunca com `ATLAS_CONFIG_HOME` | — |
| `pasta do atlas` | a pasta existe e pode ser lida | — | `atlas` vazio, caminho relativo, pasta inexistente ou sem permissão de leitura (mostra o caminho) |
| `atlas-config.yml` | versão, chaves e formato certos | — | ausente, ilegível, `version` diferente de 1, sem `organization`/`mode`, `mode` inválido, caminho absoluto |
| `estrutura` | todas as pastas e páginas | — | o que falta |
| `git` | `.git` na pasta do atlas | a pasta não é repositório git | — |
| `pasta .org-atlas/ no atlas` | — | o atlas ainda tem a cópia da skill no nome antigo: `vendor --ci <ci> --force` (grava `.boson-atlas/skill`) e depois `git rm -r .org-atlas` (`references/modes.md`) | — |
| `coletor <id>` | executável encontrado | — | executável não encontrado ou sem `command` |
| `credencial <coletor> <NOME>` | `definida` | `não definida` | — |

O `doctor` não executa nenhum processo além do `git config --get remote.origin.url` de leitura do passo do remote (só quando algum atlas declara `remotes:`): usa arquivos, `shutil.which` e `os.environ`. Quando o remote da pasta casa com mais de um atlas no mesmo comprimento, mostra `AVISO remote do projeto — …` com os nomes dos atlas, nunca o remote. Exit 0 sem ERRO, 1 com ERRO, 3 sem configuração local ou com `--atlas`/`ATLAS_NAME` fora da lista. Com vários atlas, o `doctor` confere só o escolhido e as credenciais dele.

`doctor --json` imprime o mesmo diagnóstico como objeto:

```json
{"version": "2026.10.1", "ok": false, "checks": [{"status": "ERRO", "item": "coletor github", "detail": "executável gh-atlas-collector não encontrado no PATH"}]}
```

- `version` — `ATLAS_VERSION` da skill; `ok` — `true` quando não há nenhum ERRO; `checks` — uma entrada por linha do texto, na mesma ordem.

Erros de sistema de arquivos (sem permissão, disco só de leitura, `atlas-config.yml` que não é UTF-8) saem com 1 e uma mensagem `erro: ...`, sem traceback.
