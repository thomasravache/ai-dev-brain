# Redaction — o que o `scan` mascara antes de gravar

O atlas guarda só metadados, nunca valor de segredo (ADR-0010). Por isso o `atlas.py scan` passa toda saída de coletor já validada (`references/collector-contract.md`) pela função `redact` **antes** de gravar o snapshot: cada trecho de texto que casa com um dos padrões abaixo vira `[REDACTED]`. O resto do texto fica como está.

- Vale para todo texto da saída: `name`, `id`, valores de `attrs` (também dentro de listas), relações e sinais, e também as **chaves** dos objetos (um token usado como chave de `attrs` ou de `pattern_counts` vira `[REDACTED]` e conta). Se duas chaves do mesmo objeto viram `[REDACTED]`, as outras ficam `[REDACTED]#2`, `[REDACTED]#3`… numa ordem fixa, então nenhum valor se perde e o snapshot continua estável. Chave de `attrs` (ou de sinal) com nome de segredo e campo fora do contrato são descartados pelo validador, antes (regra abaixo).
- Números, booleanos e `null` ficam como estão.
- O relatório mostra só a contagem — `N valor(es) mascarado(s)` (`redacted` no `--json`) —, **nunca** o valor mascarado.
- O stderr de um coletor com falha é mascarado **inteiro** antes de ser cortado (últimas 20 linhas, 500 caracteres por linha): um bloco de chave em várias linhas some todo e um token no limite do corte não deixa pedaço. As mensagens de violação e os nomes descartados passam pelos mesmos padrões antes de aparecer na tela.

## Chave proibida

O validador descarta, e reporta pelo nome (nunca pelo valor), a chave de `attrs` ou de sinal cujo nome diz segredo. O nome é comparado em minúsculas, com camelCase separado (`apiToken` = `api_token`) e dividido em partes por qualquer caractere que não seja letra ou número (SPEC-0046):

- `password`, `passwd`, `secret` ou `credential` em qualquer lugar do nome (`db_password`, `clientSecret`);
- `token`, `tokens`, `private`, `pwd`, `auth` ou `authorization` como parte inteira (`api_token`, `db_pwd`, `auth`, `basic_auth`), ou o nome terminando em `token`/`tokens` (`accesstoken`);
- `key`/`keys` como parte inteira (`key`, `api_key`, `deploy_keys`), menos depois de um qualificador de chave de dados: `primary`, `sort`, `public`, `foreign`, `partition`, `range`, `hash`, `unique`, `composite`, `natural`, `surrogate`, `row`, `cache`, `idempotency`, `lookup`, `index` ou `join` (`primary_key`, `sort_keys` e `public_key` ficam);
- qualquer nome terminado em `key`/`keys` colado (`apikey`, `privkey`, `hmackey`, `accountkey`, `sessionkey`, `licensekey`, `hostkey`...), menos as palavras comuns `monkey`, `donkey`, `turkey`, `hockey`, `jockey` e `whiskey` (e os plurais) e um dos qualificadores acima colado no `key` (`primarykey`, `sortkey`, `publickey`).

Não são proibidas: `monkey`, `author`, `tokenizer`, `primary_key`, `sort_keys`, `public_key`. Na dúvida a regra descarta: o valor de uma chave descartada nunca chega ao snapshot.

> **Aviso:** `primary_key` (e `primaryKey`, `primarykey`) fica liberado porque a SPEC-0046 manda assim: na maioria dos sistemas é o nome da chave de uma tabela. Em alguns provedores de nuvem, como o Azure, `primaryKey` é a chave de acesso de uma conta de armazenamento ou de um serviço. Um coletor de nuvem nunca deve expor `primaryKey` (nem `secondaryKey`) de credencial como atributo: o validador não vai descartá-lo.

## Padrões embutidos

| Padrão | Regex (Python `re`) | O que vira `[REDACTED]` |
|---|---|---|
| Chave privada (PEM e PGP) | `-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----` até o `-----END ... PRIVATE KEY[ BLOCK]-----` correspondente (ou até o fim do texto, se o bloco não fecha); cobre `RSA`, `EC`, `OPENSSH` e `PGP PRIVATE KEY BLOCK` | o bloco inteiro, com o corpo |
| Credencial em URL | `\b[A-Za-z][A-Za-z0-9+.-]{0,31}://[^\s/:@]{0,256}:[^\s@]{0,256}@(?:[^\s@]*@)*` | só a senha, até o último `@` antes de um espaço: `https://bot:[REDACTED]@host/...`, `redis://:[REDACTED]@cache:6379` (usuário vazio); senha com `/` ou `@` some inteira. Na dúvida mascara mais: `https://host:8080/x?to=a@b` perde `8080/x?to=a` |
| Token fine-grained do GitHub | `github_pat_[A-Za-z0-9_]{20,}` | o token |
| Tokens do GitHub (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`) | `(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}` ou, colado a letras ou dígitos, `gh[pousr]_[A-Za-z0-9]{36}(?![A-Za-z0-9])` (o formato exato do token) | o token |
| Tokens do Slack (`xoxb-`, `xoxp-`, `xoxa-`...) | `xox[abposr]-[A-Za-z0-9-]{10,}` | o token |
| Chave de acesso da AWS (`AKIA`, `ASIA`) | `(?:AKIA\|ASIA)[0-9A-Z]{16}(?![0-9A-Z])` | a chave |
| JWT | `eyJ[A-Za-z0-9_-]{8,1024}\.[A-Za-z0-9_-]{8,8192}\.[A-Za-z0-9_-]{8,}` | o token inteiro (cabeçalho, corpo e assinatura) |

Token colado a pontuação (`_ghp_…`, `=ghp_…`, `token:ghp_…`) é mascarado. Dentro de uma palavra comum não há falso positivo: `laughs_abcdefghijklmnopqrstuvwxyz` e `ASIAPACIFICNORTHEAST1` ficam como estão. Um token do GitHub colado a letras (por exemplo no meio de uma linha longa de log) só é mascarado com o tamanho exato do token (36 caracteres depois do prefixo).

Cada padrão embutido roda **sozinho** no texto original, não numa alternância única (que acharia os casamentos da esquerda para a direita, sem sobreposição, e deixaria um token colado a outro escapar em parte: `xoxb-…-ghp_…`, `ghp_…eyJ….…`) (SPEC-0092). Todos os padrões (estes e os do `redaction.extra_patterns`) procuram casamentos no texto original e os trechos casados são juntados: cada trecho resultante vira um `[REDACTED]` só, então nenhum padrão impede outro e não aparece marcador aninhado (SPEC-0088, Emenda v6). Casamentos que se sobrepõem contam uma vez só (um trecho já mascarado não é contado de novo); cada ocorrência conta 1 (uma URL com senha e um token no mesmo texto contam 2).

### Limites de tamanho

Para a máscara levar tempo linear mesmo com entrada hostil ou com defeito (1 MB de `a://:` repetido ou de `eyJ…` repetido é mascarado em bem menos de 2 s), as partes que poderiam voltar atrás (backtracking) a cada posição de começo têm tamanho máximo (SPEC-0092):

- **Credencial em URL:** esquema até 32 caracteres, usuário até 256 e a senha até o primeiro `@` até 256; os pedaços depois desse primeiro `@` não têm limite (o casamento já deu certo ali e não volta atrás).
- **JWT:** cabeçalho até 1024 caracteres e corpo até 8192; a assinatura, a última parte, não tem limite.

Uma credencial ou um JWT acima desses tamanhos não é mascarado por esses padrões: se a organização usa um formato assim, acrescente-o em `redaction.extra_patterns`.

Não há detecção por entropia: só padrões conhecidos e os da configuração (SPEC-0033). O `lint` reforça a varredura no atlas inteiro (SPEC-0039).

## Acrescentar padrões — `redaction.extra_patterns`

Segredos com formato próprio da organização (tokens internos, chaves de um fornecedor que não está na tabela) entram em `redaction.extra_patterns` no `atlas-config.yml`, como regex do Python (`re`). Cada trecho que casa vira `[REDACTED]` e conta no relatório, igual aos embutidos:

```yaml
redaction:
  extra_patterns:
    - 'acme-internal-[0-9]{4}'          # tokens internos da Acme
    - '\bsk_live_[A-Za-z0-9]{24,}'      # chave de um fornecedor
```

- Escreva cada regex entre **aspas simples**: dentro delas a barra invertida fica literal (`\b`, `\d`) e `{`, `}`, `[`, `]` e `,` não confundem o YAML.
- Regex inválida, item vazio ou regex que casa com o texto vazio (por exemplo `z*`, que poria `[REDACTED]` entre cada caractere) faz o `scan` sair com 2 antes de rodar qualquer coletor, com `redaction.extra_patterns[<i>] não é uma regex válida: ...` ou `redaction.extra_patterns[<i>] casa com o texto vazio — exija ao menos um caractere` — a mensagem cita a posição, não o texto da regex.
- Casamento de largura zero (`\b`, `(?=a)`, `^`) nunca mascara nada: só trechos com pelo menos um caractere viram `[REDACTED]` e contam.
- O `atlas-config.yml` vai junto com o atlas: coloque nele o **formato** do segredo, nunca um segredo de verdade.
- **O desempenho das regex do `extra_patterns` é responsabilidade do time.** Elas rodam como estão, sem limite de tempo, em toda saída de coletor, nas probes e no `lint`: evite repetição aninhada ou sem limite seguida de algo que pode falhar (`(a+)+b`, `.*x.*y`), que leva tempo quadrático ou exponencial numa entrada longa e trava o `scan` ou a `probe`. Use repetição com tamanho máximo (`{20,64}`), como os padrões embutidos.
- Prefira regex específica (prefixo fixo + tamanho): uma regex genérica demais mascara nomes e ids comuns e deixa o diff do atlas instável.

## Quando um segredo escapou

Se um valor de segredo já chegou a um snapshot (um formato que nenhum padrão cobria): acrescente o padrão em `extra_patterns`, rode `atlas.py scan` de novo (o snapshot é regravado já mascarado), **revogue o segredo** na origem e, no modo `repo`, trate o histórico do git do atlas como exposto.
