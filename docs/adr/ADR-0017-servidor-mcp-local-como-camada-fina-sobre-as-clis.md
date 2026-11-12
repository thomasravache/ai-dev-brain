---
id: ADR-0017
title: Servidor MCP local como camada fina sobre as CLIs
status: proposed
origin: decision
date: 2026-11-12
pillars: []
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: mcp/tests/test_architecture.py (SPEC-0054:UT-07)
---

# ADR-0017 — Servidor MCP local como camada fina sobre as CLIs

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: mcp/tests/test_architecture.py (SPEC-0054:UT-07) teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
O plugin `fermion` vai expor as skills como tools MCP (SPEC-0031), começando pelo atlas (SPEC-0054). As skills já têm CLIs stdlib que são a fonte da verdade. Como o servidor MCP se liga a elas sem duplicar lógica nem trazer dependências?

## Direcionadores da Decisão
- Sem lógica duplicada entre MCP e CLI (ADR-0001).
- Só biblioteca padrão, Python 3.9+, instalação zero.
- Funcionar com clientes MCP das duas eras do protocolo.
- Política aplicada fora do alcance do agente: o servidor decide quais operações existem.

## Opções Consideradas
- A: servidor de arquivo único stdlib que chama as CLIs por `subprocess` (lista de argumentos, sem shell, timeout) e repassa a saída `--json`.
- B: servidor que importa os módulos das skills (`atlas.py` como biblioteca).
- C: SDK oficial de MCP em Python.

## Resultado da Decisão
**Opção escolhida:** A, porque mantém a CLI como única implementação, não traz dependência e deixa o servidor trocável e testável com processo real.

### Consequências
- **Boa**, porque toda melhoria da CLI chega à tool sem mudar o servidor, e o servidor só expõe o que foi decidido (leitura; confirmar convenção nunca, ADR-0012).
- **Ruim**, porque cada chamada abre um processo Python (dezenas de milissegundos) e o protocolo (JSON-RPC, as duas eras) é mantido à mão.

### Confirmação (G3)
`mcp/tests/test_architecture.py` (SPEC-0054:UT-07): só imports da stdlib, nenhum import de `skills/`, nenhum `shell=True`, processo só para as CLIs das skills; cada regra testada contra exemplo e contra o código real.

## Prós e Contras das Opções
| Critério (peso) | A | B | C |
|---|---|---|---|
| Sem lógica duplicada (3) | sim | não (acopla ao interno) | sim |
| Só stdlib (3) | sim | sim | não |
| Custo por chamada (1) | processo novo | baixo | processo novo |
| Manutenção do protocolo (2) | à mão | à mão | pelo SDK |

## Mais Informações
- modelcontextprotocol.io/specification/versioning — revisão atual `2026-07-28` — 2026-11-12.
- modelcontextprotocol.io/specification/2026-07-28/basic/versioning — eras legada (`initialize`, até `2025-11-25`) e moderna (`_meta`, `server/discover`, erro -32022); servidor das duas eras permitido — 2026-11-12.
- SPEC-0031, SPEC-0054.
