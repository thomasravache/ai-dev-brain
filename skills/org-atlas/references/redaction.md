# Redaction — o que o `scan` mascara antes de gravar

O atlas guarda só metadados, nunca valor de segredo (ADR-0010). Por isso o `atlas.py scan` passa toda saída de coletor já validada (`references/collector-contract.md`) pela função `redact` **antes** de gravar o snapshot: cada trecho de texto que casa com um dos padrões abaixo vira `[REDACTED]`. O resto do texto fica como está.

- Vale para todo texto da saída: `name`, `id`, valores de `attrs` (também dentro de listas), relações e sinais. As **chaves** dos objetos não são mascaradas; chave de `attrs` com nome de segredo (`password`, `token`, `api_key`...) é descartada pelo validador, antes.
- Números, booleanos e `null` ficam como estão.
- O relatório mostra só a contagem — `N valor(es) mascarado(s)` (`redacted` no `--json`) —, **nunca** o valor mascarado.
- O stderr de um coletor com falha (só as últimas 20 linhas) e as mensagens de violação passam pelos mesmos padrões antes de aparecer na tela.

## Padrões embutidos

| Padrão | Regex (Python `re`) | O que vira `[REDACTED]` |
|---|---|---|
| Chave privada (PEM) | `-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----` até o `-----END ... PRIVATE KEY-----` correspondente (ou até o fim do texto, se o bloco não fecha) | o bloco inteiro, com o corpo |
| Credencial em URL | `\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@` | só a senha: `https://bot:[REDACTED]@host/...` |
| Token fine-grained do GitHub | `\bgithub_pat_[A-Za-z0-9_]{20,}` | o token |
| Tokens do GitHub (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`) | `\bgh[pousr]_[A-Za-z0-9]{20,}` | o token |
| Tokens do Slack (`xoxb-`, `xoxp-`, `xoxa-`...) | `\bxox[abposr]-[A-Za-z0-9-]{10,}` | o token |
| Chave de acesso da AWS (`AKIA`, `ASIA`) | `\b(?:AKIA\|ASIA)[0-9A-Z]{16}\b` | a chave |
| JWT | `\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}` | o token inteiro (cabeçalho, corpo e assinatura) |

Os padrões são aplicados nessa ordem; um trecho já mascarado não é contado de novo. Cada ocorrência conta 1 (uma URL com senha e um token no mesmo texto contam 2).

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
- Regex inválida (ou item vazio) faz o `scan` sair com 2 antes de rodar qualquer coletor, com `redaction.extra_patterns[<i>] não é uma regex válida: ...` — a mensagem cita a posição, não o texto da regex.
- O `atlas-config.yml` vai junto com o atlas: coloque nele o **formato** do segredo, nunca um segredo de verdade.
- Prefira regex específica (prefixo fixo + tamanho): uma regex genérica demais mascara nomes e ids comuns e deixa o diff do atlas instável.

## Quando um segredo escapou

Se um valor de segredo já chegou a um snapshot (um formato que nenhum padrão cobria): acrescente o padrão em `extra_patterns`, rode `atlas.py scan` de novo (o snapshot é regravado já mascarado), **revogue o segredo** na origem e, no modo `repo`, trate o histórico do git do atlas como exposto.
