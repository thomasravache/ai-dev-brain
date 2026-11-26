# Onboarding do acesso local (`access setup`)

`atlas.py access setup` grava o acesso local desta máquina (`access.clusters`, `access.cloud`, `access.urls` e `access.databases`, `references/config.md`) por perguntas simples, em vez de escrever o YAML à mão (SPEC-0104, ADR-0025). Roda depois do `build`: as perguntas vêm do `graph.json`, então só se pergunta o que o atlas usa. Pode ser repetido.

## Passo a passo

1. Ligue a máquina ao atlas (`init --join`) e tenha o `graph.json` (`scan` e `build`). Sem ele, o setup sai com 2 `sem graph.json: rode atlas.py build`.
2. Rode `atlas.py access setup` num terminal (`--atlas X` escolhe o atlas, como nos outros comandos).
3. Responda cada pergunta: o número de um nome detectado, um nome digitado, ou Enter para pular.
4. Confira o resumo e responda `s` (ou `sim`) em `Gravar? [s/N]`. Qualquer outra resposta, Enter inclusive, não muda nada (`nada gravado`, exit 0).
5. Confira com `atlas.py doctor` (mostra só `definido`) e rode a probe que estava recusada.

## Perguntas

Nesta ordem, só para o que o grafo usa:

| Item | Pergunta | Detectado |
|---|---|---|
| cada cluster de algum deployment | `Qual o contexto do kubectl do cluster <cluster>?` | os nomes de `kubectl config get-contexts -o name` |
| cada ambiente com recurso (datastore, fila, tópico, bucket) ligado a um deployment | `Qual profile da AWS você usa no ambiente <ambiente>? (use um profile só de leitura)` | os nomes das seções do arquivo de configuração da AWS CLI |
| cada ambiente `tier: test` (`environments:` do `atlas-config.yml`) | `Qual a URL base do ambiente <ambiente> (para as jornadas funcionais em teste)?` | — |
| cada `datastore` com `engine` `postgres` ou `aurora-postgresql` | `Qual usuário só de leitura do banco <datastore>?`, `Qual o nome do banco?`, `Qual o arquivo de senhas (.pgpass) desse usuário?` | `~/.pgpass`, quando existe |

- Os detectados aparecem numerados na pergunta (`Detectados: 1) … 2) …`); `1` escolhe o primeiro. Quando um nome contém o do cluster ou o do ambiente, a pergunta mostra a sugestão.
- Item já definido: `já definido — Enter mantém, '-' apaga, ou digite outro`. O valor atual não aparece.
- Resposta inválida: a pergunta se repete com o motivo, até 3 vezes; depois o item é pulado.
- Enter no usuário de um banco ainda não definido pula o bloco do banco.
- Recomende papel e usuário só de leitura: as probes só leem, e o setup nunca cria usuário, papel ou profile.

## Modo não interativo

Com qualquer uma das opções, nada é perguntado:

```text
atlas.py access setup [--atlas X] [--dry-run]
    [--cluster <cluster>=<contexto>]... [--cloud <ambiente>=<profile>]... [--base-url <ambiente>=<url>]...
    [--db-user <datastore>=<usuário>]... [--db-name <datastore>=<banco>]... [--db-passfile <datastore>=<caminho>]...
```

- Ordem das verificações: configuração local (exit 3), `graph.json` (exit 2), nomes, valores, gravação.
- Nomes: `<cluster>` precisa ser um `cluster:<n>` do grafo, `<ambiente>` um `environment:<n>` e `<datastore>` um `datastore:<id>`. Senão, exit 2 `<tipo> <nome> não está no atlas` (`ambiente qa não está no atlas`). Um nome fora da regra sai com `opção --cloud: item 1 inválido — nome fora da regra`.
- Valores: as mesmas regras de `access.*` (`references/config.md`), com a opção, a posição e o motivo, nunca o valor: `--cloud: item 2 inválido — o profile com quebra de linha ou caractere de controle`, `--base-url: item 1 inválido — a URL base com usuário ou senha`.
- Banco: `--db-user`, `--db-name` e `--db-passfile` de um datastore se somam aos campos que ele já tem; faltando algum, exit 2 `datastore <id>: faltam <campos>`.
- O que já está na entrada e não veio nas opções fica como está (`mantido` no resumo).
- `--dry-run` mostra só o resumo; o arquivo fica igual byte a byte.
- Sem opções e sem terminal no stdin: exit 2 `access setup interativo precisa de um terminal; use --cluster, --cloud, --base-url ou --db-*`.

## Resumo e gravação

- Uma linha por item, nunca o valor: `access.<bloco>.<nome>: definido | não definido | mantido | apagado`.
- Avisos que não impedem gravar (o arquivo é conferido só por `os.stat`, nunca aberto): `arquivo de senhas de <datastore> não encontrado` e `arquivo de senhas de <datastore> legível por outros: o psql ignora (use chmod 600)`.
- Grava só a chave `access` da entrada do atlas escolhido; o resto do `config.yml` (as outras chaves e os outros atlas) fica igual. O arquivo é escrito num temporário exclusivo, renomeado, com permissão 0600.
- Exits: 0 gravado, nada gravado ou dry-run; 2 argumento, nome ou valor inválido; 3 sem configuração local.

## O que é lido (só leitura)

- `kubectl config get-contexts -o name`, como lista de argumentos e sem shell, com timeout de 10 s e o ambiente do shell (`KUBECONFIG` inclusive). Sem `kubectl`, com erro ou com o tempo esgotado, a pergunta sai sem sugestão.
- O arquivo de configuração da AWS CLI (`AWS_CONFIG_FILE` ou `~/.aws/config`), pelo `configparser`: só os nomes das seções (`[default]` vira `default`, `[profile x]` vira `x`; as outras seções são ignoradas). O arquivo de credenciais (`AWS_SHARED_CREDENTIALS_FILE` ou `~/.aws/credentials`) nunca é aberto.
- Do arquivo de senhas, só `os.stat` (existe, é arquivo, permissão).

O setup não faz login na nuvem nem testa a conexão: quem testa é a probe. Depois de gravar, nenhuma saída (`access setup`, `config`, `doctor`, `probes stats`, `probes.log`) mostra o contexto, o profile, a URL base, o usuário, o nome do banco ou o caminho do arquivo de senhas (ADR-0010, ADR-0025).

## Depois do setup

As recusas por falta de acesso aparecem no `probes stats` e no `doctor` como sugestão `… rode atlas.py access setup` (`references/probes.md`).
