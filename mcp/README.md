# Servidor MCP `fermion`

Servidor MCP local do plugin `fermion` (SPEC-0054, ADR-0017). Arquivo único, `mcp/fermion_mcp.py`, só biblioteca padrão, Python 3.9+, transporte stdio.

Ele expõe o atlas da organização como tools de leitura. Cada tool chama a CLI da `boson-atlas` (`skills/boson-atlas/scripts/atlas.py ... --json`) e devolve o resultado dela, sem interpretar o conteúdo. A CLI continua sendo a única implementação (ADR-0001).

## Tools

Todas têm `annotations.readOnlyHint: true` e `inputSchema` fechado (`additionalProperties: false`).

| Tool | Argumentos | Linha de comando |
|---|---|---|
| `atlas_config` | nenhum | `atlas.py config --json` |
| `atlas_doctor` | nenhum | `atlas.py doctor --json` |
| `atlas_context` | `query` (texto, 1 a 500, obrigatório), `hops` (0 a 2), `limit` (1 a 200), `max_chars` (500 a 200000) | `atlas.py context [--hops H] [--limit L] [--max-chars M] --json -- <palavras da query>` |
| `atlas_lint` | `only` (lista de nomes de regra `[a-z-]+`) | `atlas.py lint --json [--only a,b]` |
| `atlas_curate_list` | `status` (`inferred`, `confirmed` ou `rejected`) | `atlas.py curate list --json [--status S]` |

Como o resultado é montado:

- exit 0, e exit 1 no `atlas_lint` (que significa "há ERRO no relatório"): o stdout da CLI vai em `content` como texto, e também em `structuredContent` quando é um objeto JSON. `isError` fica `false`.
- exit 3: `isError: true`, com a orientação de onboarding ("rode a skill boson-atlas") e o stderr da CLI.
- outro exit: `isError: true`, com o código e o stderr da CLI.
- timeout de 120 s, `python3` ausente ou CLI ausente: `isError: true`, com o motivo. Quando a CLI falta, o texto traz o caminho procurado.

Argumento fora do schema ou tool desconhecida recebem o erro JSON-RPC `-32602`, e a CLI nem é chamada.

## Segurança

- A CLI roda por `subprocess.run` com argv em lista, sem shell, com timeout e o ambiente herdado (`ATLAS_CONFIG_HOME` e afins).
- O texto livre da `query` vai depois de `--`, uma palavra por argumento. Uma `query` como `-rf --hops 9; rm` vira só termos de busca. Uma `query` com caractere de controle (abaixo de 0x20, inclusive tab e quebra de linha, ou DEL) recebe `-32602`.
- O processo externo só é aberto na função `run_cli`. O servidor não importa código das skills. Os testes de arquitetura do ADR-0017 (`mcp/tests/test_architecture.py`) garantem as duas coisas.
- O stdout é só do protocolo. O stderr recebe uma linha por erro, sem argumentos nem saída da CLI. O nome do método aparece cortado no primeiro caractere de controle e truncado em 64 caracteres, para que ninguém forje linhas no log.

## Por que não há tools que gravam

Só há leitura. `scan`, `build`, `init` e `vendor` mudam o atlas ou a máquina e continuam na skill, onde a pessoa vê o que acontece. `curate confirm` e `curate reject` nunca viram tool: confirmar ou rejeitar uma convenção é decisão de pessoas, não de agente (ADR-0012). Como o servidor decide quais operações existem, essa política fica fora do alcance do agente.

## As duas eras do protocolo

O servidor atende clientes das duas eras do MCP.

**Legada** (`2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`): o cliente manda `initialize` e depois `notifications/initialized`. O servidor ecoa a versão pedida quando a suporta, senão responde `2025-11-25`. `ping` devolve `{}`. `tools/list` e `tools/call` também são atendidos antes do `initialize`. As respostas seguem o schema legado, sem `resultType`, `ttlMs` nem `cacheScope`.

**Moderna** (`2026-07-28`): não há handshake. Cada request traz a versão em `params._meta["io.modelcontextprotocol/protocolVersion"]`, e a falta de `clientCapabilities` é tolerada.

- Todo resultado moderno leva `resultType: "complete"`.
- `server/discover` devolve as versões suportadas, `capabilities.tools`, `ttlMs: 3600000`, `cacheScope: "private"` e a identidade em `_meta["io.modelcontextprotocol/serverInfo"]`.
- O `tools/list` moderno também leva `ttlMs` e `cacheScope`.
- Uma versão não suportada recebe o erro `-32022` ("Unsupported protocol version"), com `data.supported` e `data.requested`.

Um request sem a versão em `_meta` é atendido como legado.

Erros de transporte: JSON inválido recebe `-32700` com `id: null`. Isso inclui linha que não é UTF-8 e JSON aninhado além de 256 níveis. Um objeto que não é request recebe `-32600`, inclusive request com `"id": null`, e um método desconhecido recebe `-32601`. Notificações nunca recebem resposta. Nenhum desses erros derruba o servidor, e ele sai com 0 quando o stdin fecha.

## Como depurar

Rode o servidor à mão e mande uma mensagem por linha:

```sh
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 mcp/fermion_mcp.py

echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"atlas_context","arguments":{"query":"payments","hops":1}}}' \
  | python3 mcp/fermion_mcp.py

echo '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}' \
  | python3 mcp/fermion_mcp.py
```

O diagnóstico aparece no stderr (`fermion-mcp: ...`). No Claude Code, o mesmo stderr está nos logs de MCP, e `/mcp` mostra o estado do servidor. Para comparar com a CLI, rode a linha de comando da tabela acima: o texto do resultado deve ser igual ao stdout dela.

Testes:

```sh
python3 -m unittest discover -s mcp/tests -v
```
