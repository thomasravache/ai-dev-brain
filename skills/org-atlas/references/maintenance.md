# Manutenção do atlas — `atlas.py lint`

O `lint` **só lê** o atlas e aponta o que precisa de atenção: segredo em qualquer arquivo (inclusive no texto escrito por pessoas), configuração inválida, coletor que falhou ou está velho, referência quebrada, convenção esperando decisão e página de entidade que sumiu há muito tempo (SPEC-0039). Ele nunca corrige nada: quem corrige é a pessoa, ou o agente com a pessoa. É a última barreira contra vazamento — a redaction do `scan` (`references/redaction.md`) só cobre o que entra pelos coletores.

## Comando

```bash
python3 <skill-dir>/scripts/atlas.py lint [--json] [--only regra,...]
```

- Uma linha por achado e o resumo no fim:

  ```text
  ERRO secret-leak services/backoffice.md:57 — padrão github (o valor não é mostrado) (sugestão: apague o valor do arquivo ...)
  AVISO stale snapshots/_scan.json — coletor github: 20 dias desde o último scan (stale_days: 14) (sugestão: rode `atlas.py scan` ...)
  1 erros, 1 avisos
  ```

- `--only stale,secret-leak` roda só essas regras (o relatório segue a ordem da tabela abaixo); regra desconhecida sai com 2 e o nome dela.
- `--json` imprime um objeto `{"version", "ok", "rules", "errors", "warnings", "findings": [...]}`; cada achado é `{"rule", "severity": "error" | "warn", "path", "detail", "suggestion"}`, com `path` relativo à pasta do atlas (em `secret-leak`, `<arquivo>:<linha>`).
- Exit 0 sem ERRO (só avisos ainda é 0), 1 com algum ERRO, 2 com regra desconhecida em `--only`, 3 sem configuração nesta máquina (sem a configuração local, sem `atlas` nela ou com a pasta do atlas inexistente). Um `atlas-config.yml` ausente, inválido ou ilegível **não** é 2 nem 3: é um ERRO `config` e as outras regras rodam (exit 1).
- Da configuração local o `lint` só usa o caminho do atlas; o `atlas-config.yml` é lido como mais um arquivo do atlas.
- Lê só os **arquivos comuns** da pasta do atlas, menos as pastas de controle de versão (`.git`, `.hg`, `.svn`, `.bzr`, `_darcs`, `.jj`) e `.DS_Store`, `Thumbs.db`, `desktop.ini`. Link simbólico (para arquivo ou pasta, dentro ou fora do atlas), FIFO, socket e dispositivo **não** são lidos nem seguidos, e arquivo com mais de 32 MB não é lido: cada um vira um ERRO `config` com o caminho. Arquivo ou pasta sem permissão de leitura também vira `config`. Em todos os casos o lint segue com os outros.
- Ordem determinística: por regra (a ordem abaixo), caminho, linha e detalhe.
- **Nunca** mostra o valor de um segredo, nem em parte, nem no `--json`, nem no stderr: só o arquivo, a linha e o nome do padrão. Todo texto de um achado (`path`, `detail` e `suggestion`, inclusive ids de coletor e de convenção, chaves e links) passa pela máscara antes de aparecer (`[REDACTED]`). O `path` de todo achado, de qualquer regra, é mascarado do mesmo jeito que um nome é detectado: cada parte separada por `/`, e o nome dessa parte sem a extensão, passa sozinha pela máscara (padrões do `scan` e `extra_patterns` válidos), então um padrão ancorado como `^acme-[0-9a-f]{8}$` também esconde `process/acme-feedface.md` (vira `process/[REDACTED].md`). A mensagem do parser de YAML nunca é mostrada (ela repete o texto da linha), só o tipo do erro.

## Regras

| Regra | Severidade | Quando | Como corrigir |
|---|---|---|---|
| `secret-leak` | ERRO | uma linha de qualquer arquivo casa com um padrão de segredo do `scan` (`private-key`, `url`, `github-pat`, `github`, `slack`, `aws-access-key`, `jwt`) ou com `redaction.extra_patterns` (`extra_patterns[<i>]`; uma regex inválida é ERRO `config` e as válidas continuam valendo); o caminho é `<arquivo>:<linha>` da linha onde o valor começa e o detalhe é `padrão <tipo>`. Arquivo não UTF-8 também é varrido (além do achado `config`). Nome de arquivo ou de pasta com segredo também é achado (o nome inteiro ou o nome sem a extensão casa com o padrão), com o caminho mascarado (`process/[REDACTED].md`, `process/[REDACTED]/`) e sem linha | apague o valor do arquivo (ou renomeie) **e troque a credencial** (o histórico do git do atlas ainda guarda o valor: trate como vazado). Nunca copie o valor para a conversa nem para outro arquivo. Texto `[REDACTED]` não conta |
| `config` | ERRO | `atlas-config.yml` inválido (YAML, `version`, `mode`, `stale_days`, formato de `categories`/`collectors`/`redaction`/`curation`), **caminho absoluto** em qualquer valor, **chave desconhecida** (por exemplo `colectors`), coletor inválido, regex inválida em `extra_patterns`; `atlas-config.yml` ausente; qualquer arquivo ou pasta **ilegível** (não UTF-8, sem permissão, JSON inválido em `graph.json` ou `snapshots/*.json`, ou com formato inesperado: `graph.json` sem as listas `nodes`/`edges`, nó sem `key` de texto, aresta sem `from`/`to` de texto, `_scan.json` que não é um objeto de objetos); link simbólico, FIFO, socket, dispositivo ou arquivo com mais de 32 MB (não lidos) | corrija o `atlas-config.yml` (`references/config.md`, `references/collector-contract.md`), troque caminhos absolutos por `{skill}`/`{atlas}`; para arquivo gerado ilegível (`snapshots/`, `graph.json`), rode `atlas.py scan`; para nota, regrave em UTF-8; troque o link simbólico ou o arquivo especial por um arquivo comum, ou tire-o da pasta do atlas |
| `failed-collector` | ERRO | coletor declarado com `status: failed` em `snapshots/_scan.json` | `atlas.py scan --only <id>` e leia o motivo da `FALHA` (credencial não definida, timeout, saída fora do contrato) |
| `stale` | AVISO | coletor declarado com o último scan `ok` há **mais** de `stale_days` dias (UTC; `stale_days` do `atlas-config.yml`, padrão 14), sem data válida, ou que nunca foi escaneado (não aparece no `_scan.json`) | `atlas.py scan` (ou `scan --only <id>`) |
| `broken-ref` | AVISO | aresta do `graph.json` com `from` ou `to` que não é nó do grafo; link Markdown `[texto](destino)` de uma página para um arquivo que não existe ou que fica fora da pasta do atlas (relativo à página, com `%20` e outros escapes decodificados; `http(s)://`, `mailto:`, `#âncora`, trechos entre crases e blocos de código — cercados por ```` ``` ```` ou `~~~`, ou indentados — são ignorados; link para dentro de uma pasta ilegível não é verificado nem acusado, porque a pasta já é um ERRO `config`) | rode o coletor que declara a entidade, corrija o coletor que aponta para ela, ou corrija o link / crie a página |
| `pending-convention` | AVISO | convenção com `status: inferred` em `conventions/` (formato em `references/curation.md`) | mostre a evidência a uma pessoa e registre a decisão: `atlas.py curate confirm <id> --by NOME --via "PR #n"\|local` ou `curate reject <id> ...` |
| `orphan-page` | AVISO | página `services/<id>.md` com `_Não visto desde AAAA-MM-DD._` há **mais** de 2 × `stale_days` dias | pergunte ao time se o serviço foi desligado; se foi, apagar a página ou mover as notas é decisão do time (o `atlas.py` nunca apaga) |

Toda linha traz `(sugestão: …)` com a correção da regra.

## Quando rodar

- Depois de cada `scan`, e antes de commitar ou abrir o PR do atlas (no modo `repo`, a CI do atlas pode rodar `lint` e bloquear com ERRO).
- Sempre que alguém editar notas à mão: um token colado numa nota só é pego pelo `lint`.
- Com `--only secret-leak` antes de compartilhar o atlas ou uma página.
