# Itens confidenciais e segredos

O segundo cérebro convive com informação sensível sem expô-la (SPEC-0050, ADR-0014). A regra de ouro: **o segredo nunca entra no vault nem passa pela LLM.** O vault sincroniza com a nuvem do provedor, é copiado para todas as máquinas e backups, a LLM lê o que a busca devolve, e existem a exportação e o conector. Por isso o vault guarda só a referência ao segredo e mantém itens confidenciais fora de vista.

São quatro peças, todas agnósticas de gerenciador de senhas, de provedor e de agente:

1. **Referência ao cofre** — nota `secret-ref` com `vault_ref: "<esquema>://<caminho>"`: diz que o segredo existe e onde está, sem o segredo.
2. **Documento confidencial opaco** — `ingest ARQ --confidential`: o arquivo vai para `files` sem processador e sem extração de texto.
3. **Fora de vista por padrão** — notas com `confidential: true` ficam fora da busca, do `context`, do `related`, dos `links`, dos MOCs e do `index.md`; só aparecem com `--include-confidential`, e nunca na exportação.
4. **Alarme de vazamento** — as regras `secret-in-note` e `personal-data` do `lint` apontam segredo ou dado pessoal numa nota comum, sem mostrar o valor.

## O gerenciador de senhas guarda o segredo

A skill nunca lê, grava, gera nem mostra uma senha, e nunca abre o arquivo do gerenciador (`.kdbx` do KeePass e outros). Quem abre o cofre é a pessoa, no app dela. O arquivo do cofre continua onde ela já o guarda; a nota só aponta para a entrada.

### Exemplo: KeePass e KeePassXC

No KeePass ou no KeePassXC, a entrada fica num grupo, como `Pessoal` › `Banco`. A referência usa o esquema `keepass` e o caminho do grupo até a entrada:

```bash
python3 <skill-dir>/scripts/brain.py new-note --type secret-ref --title "Banco" \
  --vault-ref keepass://Pessoal/Banco --context financas --json
```

A nota criada (modelo `assets/templates/secret-ref.md`):

```markdown
---
type: secret-ref
title: "Banco"
context: financas
created: 2026-11-02
tags: []
confidential: true
vault_ref: "keepass://Pessoal/Banco"
---

# Banco

## Summary

## Relations
```

No `## Summary` vale escrever o que **não** é segredo: para que serve a conta, quem é o gerente, quando a senha foi trocada. A senha, o PIN, o token e as respostas de segurança ficam só no gerenciador.

### Outros gerenciadores: `<esquema>://<caminho>`

Qualquer gerenciador funciona pelo mesmo formato, sem código específico: `<esquema>://<caminho>`, com o esquema em minúsculas (`[a-z][a-z0-9+.-]*`) e um caminho não vazio. Exemplos:

| Gerenciador | Referência |
|---|---|
| KeePass / KeePassXC | `keepass://Pessoal/Banco` |
| Bitwarden | `bitwarden://Pessoal/Banco` (pasta e item) ou `bitwarden://item/<id>` |
| 1Password | `op://Pessoal/Banco` (cofre e item, o formato de referência do 1Password) |
| Outro | `<esquema>://<onde a pessoa acha o item>` |

O `brain.py` só confere o formato: sem `--vault-ref`, com um valor fora do formato (`banco`, `keepass:`, `://x`) ou com `--vault-ref` num tipo que não é `secret-ref`, o `new-note` sai com 2 e nada é criado. A referência nunca é resolvida nem aberta.

## Documento confidencial

Para documento com dados da pessoa (RG escaneado, contrato, comprovante, exame):

```bash
python3 <skill-dir>/scripts/brain.py ingest "<arquivo>" --confidential --context C --json
python3 <skill-dir>/scripts/brain.py ingest inbox/<arquivo> --confidential --move --json   # da inbox
```

- O arquivo vai para `<files>/<contexto ou inbox>/<AAAA>/` como num `ingest` comum (com `--move`, sai da inbox).
- **Nunca roda processador** e nunca grava texto do arquivo no vault. A nota de fonte em `raw/` tem `confidential: true`, `size` (bytes), `sha256` e `_(confidential: not extracted)_` no lugar do texto.
- O `log.md` cita só o caminho da nota e o do arquivo.
- URL, `--text-file`, `--kind` ou `--timestamps` junto com `--confidential` saem com 2, sem criar nada.

### Documento muito sensível: anexo no gerenciador

O vault e a pasta `files` ficam no provedor **sem uma cifra da pessoa**: quem tem acesso à conta do provedor vê os arquivos. Para documento muito sensível, a recomendação é anexar o arquivo na própria entrada do gerenciador de senhas (o KeePass e o KeePassXC aceitam anexos na entrada, na parte avançada dela; confira na documentação da versão que você usa) e deixar no vault só a nota `secret-ref` apontando para a entrada.

## Marca `confidential: true`

Qualquer tipo de nota pode ser confidencial: `new-note --type T --title X --confidential` grava `confidential: true` no frontmatter, ou a pessoa acrescenta a linha à mão. **Só o booleano `true`** marca a nota: `"true"` entre aspas, `yes` ou qualquer outro valor não marcam, para que um frontmatter estranho não esconda nem revele nada por engano.

Com a marca, a nota:

- fica fora de `search`, `related`, `context` e `links` (resultados, vizinhas, links de saída e backlinks). Um link para ela não vira "link quebrado": só não é listado. As saídas `--json` dizem quantas ficaram fora em `confidential_omitted`, sem citar nenhuma;
- não aparece no MOC (região `notes`) nem no `recent` do `index.md`;
- nunca vai para o pacote do `export-notebooklm` (não há opção para incluir); o texto que a pessoa escreveu no MOC fica como está;
- não é acusada como `orphan` pelo `lint`;
- só entra na contagem do `doctor`: `OK confidential — N notas confidenciais`, sem título nem caminho.

`related --note` e `links` numa nota confidencial saem com 2 ("nota confidencial — use --include-confidential …").

## Regras para o agente

- Nunca escrever senha, token ou chave no vault, nem na inbox pelo conector do provedor.
- Quando a pessoa der um segredo: não guardar o valor, sugerir o gerenciador de senhas e oferecer a nota `secret-ref`.
- Usar `--include-confidential` só quando a pessoa pedir, nesta conversa, para incluir itens confidenciais.
- No modo só conector (`references/connectors.md`), um arquivo com `confidential: true` não é citado nem resumido.
- Nunca abrir o arquivo do gerenciador de senhas (`.kdbx` e outros), nem pedir a senha mestra.
- Para documento muito sensível, recomendar o anexo no gerenciador, com só a `secret-ref` no vault.

## O alarme do `lint`

Duas regras, as duas **AVISO** (o exit do `lint` não muda), rodam só em notas **sem** `confidential: true` e fora de `templates/`. A saída tem o caminho, a linha (contada do topo do arquivo, frontmatter incluído) e o tipo; **o valor encontrado nunca aparece** (nem no texto, nem no `--json`, nem no `log.md`):

```text
AVISO secret-in-note projects/college/Acessos.md:9 — senha rotulada (sugestão: …)
AVISO personal-data projects/college/Acessos.md:10 — cpf (sugestão: …)
```

### `secret-in-note`

| Tipo | O que acusa |
|---|---|
| chave privada | bloco `-----BEGIN … PRIVATE KEY-----` |
| token | prefixo conhecido: `ghp_` (+ 36), `github_pat_`, `AKIA` (+ 16), `xoxa-`/`xoxb-`/`xoxp-`/`xoxr-`, `sk-` (+ 20 ou mais) |
| senha rotulada | `senha`, `password`, `passwd`, `pwd`, `pin`, `token`, `api key`, `api_key`, `secret` ou `segredo`, seguido de `:` ou `=` e de um valor de 4 ou mais caracteres sem espaço |

Marcadores não contam: `***`, `<seu token>`, `${KEY}`, `{{segredo}}`, `xxx`, `...` e os valores `true`, `false`, `null`, `yes`, `no`.

Correção: tirar o valor da nota, guardá-lo no gerenciador e deixar uma `secret-ref`; ou, se a nota precisa mesmo ficar como está, marcá-la com `confidential: true`.

### `personal-data`

| Detector (`lint.personal_data`) | Tipo | O que acusa |
|---|---|---|
| `cpf` | cpf | `000.000.000-00`, ou 11 dígitos logo depois de `CPF`, com os dígitos verificadores certos |
| `cnpj` | cnpj | `00.000.000/0000-00`, ou 14 dígitos depois de `CNPJ`, com os dígitos verificadores |
| `card` | cartão | 13 a 19 dígitos em grupos separados por espaço ou hífen, ou depois de `cartão`/`card`, que passam no Luhn |
| `labeled-document` | documento rotulado | `RG`, `CNH`, `passaporte`, `passport`, `SSN`, `DNI` ou `NIF`, seguido de `:` e de um valor com dígito |

E-mail e telefone não contam. Correção: tirar o dado da nota, ou marcá-la com `confidential: true`; um documento pessoal entra com `ingest --confidential`. Tirar dados de notas antigas é da pessoa: o `lint` só aponta.

### Falsos positivos

As regras procuram texto com cara de segredo ou de documento, então podem acusar o que não é: `Senha: mínimo oito caracteres` (o rótulo seguido de uma palavra comum), um número de pedido de 16 dígitos que por acaso passa no Luhn, um `token: abcd` de exemplo. São só AVISO: a pessoa confere a linha e decide. Para silenciar um detector de dado pessoal que não serve no país dela, tire-o de `lint.personal_data`; para um segredo de exemplo, prefira um marcador (`senha: ***`, `token: <seu token>`).

### Padrões extras

Os detectores são configuráveis no `brain-config.yml`, para a skill servir em qualquer país (`references/config.md`):

```yaml
lint:
  personal_data: [cpf, cnpj, card, labeled-document]   # detectores ligados; ausente = todos; [] = nenhum
  personal_data_patterns:                                # extras: nome → regex; o achado usa o nome como tipo
    nif: '\bNIF:\s*\d{9}\b'
```

Cada regex de `personal_data_patterns` passa pela mesma proteção do `conflict_patterns`: regex inválido, com quantificador aninhado (`(a+)+` e variações) ou com mais de 500 caracteres vira um achado `config` (erro) citando o nome do padrão e nunca é usado; os outros padrões e as outras regras rodam normalmente. Um detector desconhecido em `personal_data` também vira achado `config`.
