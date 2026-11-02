---
id: ADR-0013
title: Conector do provedor como canal de captura e leitura
status: accepted
origin: decision
date: 2026-11-02
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0044
---

# ADR-0013 — Conector do provedor como canal de captura e leitura

## Contexto e Problema
O ADR-0008 decidiu que a skill acessa o vault por uma pasta sincronizada pelo app do provedor, sem API nem credenciais, e deixou o acesso por API para uma spec futura. Na prática, essa pasta nem sempre está ao alcance do agente:
- no celular e no navegador não há pasta montada;
- no macOS, a proteção de privacidade (TCC) bloqueou o acesso desta sessão à pasta do Google Drive.

As ferramentas de agente oferecem conectores dos provedores, como o conector do Google Drive no app do Claude, que leem e criam arquivos pela conta do usuário. Precisamos decidir se e como a skill usa esses conectores sem perder as garantias do ADR-0007 e do ADR-0008.

## Direcionadores da Decisão
- `brain.py` só com a biblioteca padrão, sem rede e sem credenciais (ADR-0007, ADR-0008).
- Só o `brain.py` escreve fora da inbox, sem sobrescrever e com log (ADR-0007).
- Agnóstica de provedor e de agente: o conector é opcional e qualquer provedor com conector serve.
- Capturar e consultar de qualquer lugar, inclusive no celular.

## Opções Consideradas
- **A — Conector como canal do agente, só para criar arquivos na inbox e ler notas.** O `brain.py` continua sem rede e só monta o arquivo de captura (`capture --print`).
- **B — `brain.py` com cliente da API de cada provedor.** Já descartada no ADR-0008.
- **C — Agente usando o conector para todo o fluxo.** Escreveria notas organizadas, relações e índice pelo conector.

## Resultado da Decisão
**Opção escolhida:** A, porque libera a captura e a consulta de qualquer lugar sem mexer nas garantias do `brain.py`.

**Regras (verificáveis):**
- O conector é usado pelo agente, nunca pelo `brain.py`, que continua sem rede (teste de arquitetura do ADR-0007).
- Pelo conector, o agente só **cria arquivo novo** em `<vault>/<layout.inbox>/`, no formato da nota de captura (`brain.py capture --print`). Nunca edita, move ou apaga um arquivo do vault pelo conector.
- Pelo conector, consultas são **só leitura**. A resposta cita `[[nota]]` e avisa que é parcial, porque não tem o índice nem os vizinhos por link.
- Organizar (processar a inbox, `new-note`, `relate`, `index`, `lint`) continua só pela pasta, com o `brain.py`.
- Credenciais e autorização do conector ficam com a ferramenta do agente. A skill não guarda nem pede credencial.
- Sem conector disponível, nada muda: valem os canais do ADR-0008 e da SPEC-0021.

### Consequências
- **Boa**, porque dá para capturar e consultar do celular ou do navegador sem pasta montada e sem tocar no `brain.py`.
- **Ruim**, porque a consulta pelo conector é mais fraca que a do `brain.py` (sem pontuação, índice nem links), e o formato da captura precisa ser seguido pelo agente quando não há shell para rodar o `capture --print`.

### Confirmação (G3)
O teste de arquitetura da SPEC-0017 continua garantindo que o `brain.py` não importa biblioteca de rede. O UT-03 da SPEC-0044 verifica as regras do modo "só conector" no `SKILL.md`. O resto é verificado na revisão G4.

## Prós e Contras das Opções
| Critério (peso) | A — canal do agente, só inbox e leitura | B — API no `brain.py` | C — fluxo todo pelo conector |
|---|---|---|---|
| `brain.py` sem rede e sem credenciais (3) | sim | não | sim |
| Garantias de escrita do ADR-0007 (3) | sim | sim | não |
| Captura e consulta de qualquer lugar (2) | sim | sim | sim |
| Mesmo código para todos os provedores (2) | sim | não | sim |

## Mais Informações
- Diretório de conectores do Claude, consultado em 2026-11-02: o conector "Google Drive" (`drivemcp.googleapis.com`) oferece `create_file`, `read_file_content`, `search_files`, `download_file_content`, `list_recent_files` e outros.
- ADR-0008 (armazenamento), ADR-0007 (fronteiras) e SPEC-0021 (inbox).
