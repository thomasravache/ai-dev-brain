# Servidor MCP `fermion`

Servidor MCP local do plugin `fermion` (SPEC-0054, SPEC-0059, SPEC-0060, SPEC-0061, ADR-0017, ADR-0019). Arquivo único, `mcp/fermion_mcp.py`, só biblioteca padrão, Python 3.9+, transporte stdio.

Ele expõe o atlas da organização (`atlas_*`), o segundo cérebro (`brain_*`), o processo SDD do projeto (`sdd_*`) e o doctor de instalação antiga do plugin (`fermion_doctor`) como tools de leitura. Cada tool chama a CLI da skill (`skills/boson-atlas/scripts/atlas.py ... --json`, `skills/photon-brain/scripts/brain.py ... --json` ou `skills/gluon-spec/scripts/spec_graph.py --root <projeto> ...`) e devolve o resultado dela, sem interpretar o conteúdo. A CLI continua sendo a única implementação (ADR-0001).

## Tools

Todas têm `annotations.readOnlyHint: true` e `inputSchema` fechado (`additionalProperties: false`).

| Tool | Argumentos | Linha de comando |
|---|---|---|
| `atlas_config` | nenhum | `atlas.py config --json` |
| `atlas_doctor` | nenhum | `atlas.py doctor --json` |
| `atlas_context` | `query` (texto, 1 a 500, obrigatório), `hops` (0 a 2), `limit` (1 a 200), `max_chars` (500 a 200000) | `atlas.py context [--hops H] [--limit L] [--max-chars M] --json -- <palavras da query>` |
| `atlas_lint` | `only` (lista de nomes de regra `[a-z-]+`) | `atlas.py lint --json [--only a,b]` |
| `atlas_curate_list` | `status` (`inferred`, `confirmed` ou `rejected`) | `atlas.py curate list --json [--status S]` |
| `brain_config` | nenhum | `brain.py config --json` |
| `brain_doctor` | nenhum | `brain.py doctor --json` |
| `brain_search` | `query` (texto, 1 a 500, obrigatório), `context` (1 a 100), `type` (1 a 50), `tag` (1 a 100), `limit` (1 a 100) | `brain.py search [--context=C] [--type=T] [--tag=G] [--limit=L] --json -- <palavras da query>` |
| `brain_related` | exatamente um de `note` (1 a 500) ou `text` (1 a 2000); `limit` (1 a 100) | `brain.py related (--note=N \| --text=X) [--limit=L] --json` |
| `brain_links` | `note` (texto, 1 a 500, obrigatório) | `brain.py links --json -- <note>` |
| `brain_context` | `query` (texto, 1 a 500, obrigatório), `context` (1 a 100), `hops` (0 a 2), `limit` (1 a 50), `max_chars` (500 a 200000) | `brain.py context [--context=C] [--hops=H] [--limit=L] [--max-chars=M] --json -- <palavras da query>` |
| `brain_inbox_list` | nenhum | `brain.py inbox list --json` |
| `brain_lint` | `only` (lista de nomes de regra `[a-z-]+`) | `brain.py lint --json [--only=a,b]` |
| `sdd_status` | `ids` (lista de 0 a 20 `SPEC-NNNN`) | `spec_graph.py --root <projeto> status [ids...]` |
| `sdd_validate` | `ids` (lista de 0 a 20 `SPEC-NNNN` ou `ADR-NNNN`) | `spec_graph.py --root <projeto> validate [ids...]` |
| `sdd_next` | nenhum | `spec_graph.py --root <projeto> next` |
| `sdd_waves` | nenhum | `spec_graph.py --root <projeto> waves` |
| `sdd_report` | `id` (`SPEC-NNNN`, obrigatório) | `spec_graph.py --root <projeto> report <id>` |
| `sdd_whats_new` | nenhum | `spec_graph.py --root <projeto> whats-new` |
| `fermion_doctor` | nenhum | `scripts/fermion_doctor.py --project <projeto> --json` |

As cinco `atlas_*` aceitam também `atlas` (texto opcional, 1 a 200 caracteres, sem nenhum caractere de controle, nem tab ou quebra de linha): o nome ou a pasta de um atlas desta máquina, passado colado à CLI como `--atlas=<valor>` (antes do `--` do `atlas_context`). Elas rodam a CLI com a pasta corrente em `<projeto>` (abaixo), então, sem `atlas`, vale a ordem de escolha da CLI naquela pasta: `ATLAS_NAME`, o atlas cujo `remotes:` casa o remote `origin` do projeto, o `default` e o único configurado (SPEC-0080, ADR-0021). Com vários atlas e nenhum escolhido (exit 2), a tool devolve `isError: true` com a mensagem da CLI.

Nas `atlas_*` (pasta corrente da CLI), nas `sdd_*` e na `fermion_doctor`, `<projeto>` é o valor de `CLAUDE_PROJECT_DIR` quando a variável não está vazia, senão a pasta corrente do servidor. Os dois são lidos a cada chamada, nunca vêm do agente. Nas `atlas_*`, um `CLAUDE_PROJECT_DIR` que não é uma pasta existente cai na pasta corrente do servidor.

Como o resultado é montado:

- exit 0, exit 1 no `atlas_lint` e exit 1 no `brain_doctor` e no `brain_lint` com stdout objeto JSON (que significa "há ERRO no relatório"): o stdout da CLI vai em `content` como texto, e também em `structuredContent` quando é um objeto JSON. `isError` fica `false`.
- nas `sdd_*`, exit 0 e exit 1 no `sdd_validate` (que significa "há ERRO na validação"): o stdout da CLI vai em `content` como texto, sem `structuredContent`, e `isError` fica `false`. Qualquer outro exit, inclusive exit 1 nas demais `sdd_*`, dá `isError: true`, com o código e o stderr da CLI. O timeout dá "spec_graph.py não respondeu em 120 s".
- na `fermion_doctor`, exit 0: o JSON do doctor (`plugin_versions` e `findings`, cada achado com `check`, `level`, `path`, `detail` e `fix`) vai em `content` como texto e em `structuredContent`, e `isError` fica `false`, com ou sem achado. Exit 0 sem um objeto JSON com `findings` dá `isError: true`, com o stderr e sem `structuredContent`. O doctor sempre sai com 0, então qualquer outro exit dá `isError: true`, com o código e o stderr; o timeout dá "fermion_doctor.py não respondeu em 120 s".
- exit 1 sem relatório JSON (erro de leitura do vault) e exit 2 nas `brain_*` (nota não encontrada, nota confidencial recusada, regra desconhecida no lint): `isError: true`, com o stderr da CLI.
- exit 3: `isError: true`, com a orientação de onboarding ("rode a skill boson-atlas" ou "rode a skill photon-brain") e o stderr da CLI.
- outro exit: `isError: true`, com o código e o stderr da CLI.
- timeout de 120 s, `python3` ausente ou CLI ausente: `isError: true`, com o motivo. Quando a CLI falta, o texto traz o caminho procurado.

Argumento fora do schema ou tool desconhecida recebem o erro JSON-RPC `-32602`, e a CLI nem é chamada. Isso inclui lista com menos itens que `minItems` ou mais que `maxItems` (por exemplo, mais de 20 `ids`). O mesmo vale para `brain_related` com `note` e `text` juntos ou sem nenhum dos dois, e para `brain_search` ou `brain_context` com `query` só de espaços.

## Segurança

- A CLI roda por `subprocess.run` com argv em lista, sem shell, com timeout e o ambiente herdado (`ATLAS_CONFIG_HOME` e afins).
- O texto livre da `query` vai depois de `--`, uma palavra por argumento. Uma `query` como `-rf --hops 9; rm` vira só termos de busca. Uma `query` com caractere de controle (abaixo de 0x20 ou DEL) recebe `-32602`. A exceção são tab, `\n` e `\r`, que a CLI separa como espaço.
- Nas `brain_*`, toda opção com valor vai colada (`--note=<valor>`, `--context=<valor>`), e o texto livre (`query`, `note` do `brain_links`) só depois de `--`. Assim nenhum valor vira opção própria.
- Notas confidenciais nunca saem por MCP: o servidor nunca passa `--include-confidential` e nenhuma tool aceita pedir isso (ADR-0014). A CLI omite essas notas e recusa `links` e `related` por nome de nota confidencial. Nota confidencial só sai pela CLI, quando a pessoa pede.
- Nas `sdd_*`, os ids só passam se casam com `SPEC-NNNN` (ou `ADR-NNNN` no `sdd_validate`), então nenhum vira opção. O servidor nunca passa `--ack`, `--apply`, `--create` nem `--out`: nenhuma `sdd_*` grava no projeto.
- A `fermion_doctor` não aceita argumento nenhum. O doctor só lê arquivos: nunca grava, apaga nem move nada, não abre processo nem usa rede, e nunca atualiza sozinho o que está velho; o achado traz o comando, e quem roda é a pessoa (ADR-0019).
- O processo externo só é aberto na função `run_cli`, e só para as CLIs das skills e o `scripts/fermion_doctor.py`. O servidor não importa código das skills nem o doctor. Os testes de arquitetura do ADR-0017 (`mcp/tests/test_architecture.py`) garantem as duas coisas.
- O stdout é só do protocolo. O stderr recebe uma linha por erro, sem argumentos nem saída da CLI. O nome do método aparece cortado no primeiro caractere de controle e truncado em 64 caracteres, para que ninguém forje linhas no log.

## Por que não há tools que gravam

Só há leitura. `scan`, `build`, `init` e `vendor` mudam o atlas ou a máquina e continuam na skill, onde a pessoa vê o que acontece. No segundo cérebro, `capture`, `ingest`, `new-note`, `relate`, `index`, `inbox done`, `context add`, `process`, `backup`, `restore` e `init` também ficam na skill: gravação por MCP depende de um ADR de política de escrita. No processo SDD, `new`, `set`, `gate`, `impede`, `resolve`, `validate --apply`, `whats-new --ack` e `report --out` mudam specs ou estado e continuam na skill gluon-spec. `curate confirm` e `curate reject` nunca viram tool: confirmar ou rejeitar uma convenção é decisão de pessoas, não de agente (ADR-0012). Como o servidor decide quais operações existem, essa política fica fora do alcance do agente.

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
