---
id: ADR-0014
title: "Itens confidenciais: referência ao cofre e opacidade"
status: proposed
origin: decision
date: 2026-11-02
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0050
---

# ADR-0014 — Itens confidenciais: referência ao cofre e opacidade

## Contexto e Problema
A pessoa quer guardar no segundo cérebro também o que é sensível: onde estão as senhas (hoje no KeePass) e documentos com os dados dela. O vault não é um lugar seguro para segredos:
- ele sincroniza com o provedor e é copiado para todas as máquinas e para os backups;
- a LLM lê o que a busca, o `context` e o conector devolvem;
- a exportação manda notas para o NotebookLM.

Precisamos decidir como o segundo cérebro lida com segredo e dado pessoal sem perder a agnosticidade de gerenciador de senhas, de provedor e de agente.

## Direcionadores da Decisão
- Nenhum segredo em texto no vault, no log, na saída dos comandos ou num pacote exportado.
- Funcionar com qualquer gerenciador de senhas, sem integração específica.
- Só biblioteca padrão e nada de criptografia própria (ADR-0007).
- A LLM não vê item confidencial a menos que a pessoa peça.

## Opções Consideradas
- **A — Referência ao cofre e itens opacos:** o segredo fica no gerenciador da pessoa, o vault guarda só `vault_ref: "<esquema>://<caminho>"`, documentos confidenciais nunca são extraídos, e itens marcados ficam fora de vista por padrão.
- **B — Segredos cifrados no vault**, com uma senha mestra e cripto implementada no `brain.py`.
- **C — Integração com o gerenciador** (API ou CLI do KeePassXC, Bitwarden, 1Password) para buscar e mostrar o segredo quando pedido.

## Resultado da Decisão
**Opção escolhida:** A, porque é a única que mantém o segredo fora do alcance do vault e do agente e funciona com qualquer gerenciador.

**Regras (verificáveis):**
- O `brain.py` nunca lê, grava, gera nem mostra o valor de um segredo, e nunca abre o arquivo de um gerenciador de senhas.
- `vault_ref` é texto livre no formato `<esquema>://<caminho>`. O `brain.py` só valida o formato e nunca o resolve nem o abre.
- Uma nota é confidencial só com `confidential: true` (booleano) no frontmatter. Qualquer tipo de nota pode ser.
- `ingest --confidential` nunca chama `run_processor` e nunca grava texto do arquivo no vault. A nota de fonte registra só o nome, o tamanho e o sha256.
- `search`, `related`, `context`, `links` e `index` deixam itens confidenciais de fora por padrão, e `--include-confidential` os inclui. `export-notebooklm` nunca inclui item confidencial. As saídas só informam quantos foram omitidos.
- As regras `secret-in-note` e `personal-data` do `lint` nunca imprimem o valor encontrado.
- Nenhum import de biblioteca de criptografia de terceiros nem de gerenciador de senhas (continua valendo o teste de imports do ADR-0007).
- O agente só usa `--include-confidential` quando a pessoa pede, e no modo só conector (ADR-0013) não cita nem resume um arquivo confidencial (`SKILL.md`).

### Consequências
- **Boa**, porque um vazamento do vault, de um backup ou de uma exportação não expõe nenhuma senha, e a pessoa continua com o gerenciador que já usa.
- **Ruim**, porque o segredo exige um passo fora da skill (abrir o gerenciador), e o vault em si não é cifrado: documento muito sensível deve ser anexado no próprio gerenciador, com só a referência no vault.

### Confirmação (G3)
Testes da SPEC-0050: o `ingest --confidential` não roda processador (IT-03), os filtros (UT-07, IT-04, IT-05) e as saídas do `lint` sem o valor (UT-05, IT-06). O teste de imports do ADR-0007 (`skills/second-brain/tests/test_architecture.py`) continua garantindo só biblioteca padrão.

## Prós e Contras das Opções
| Critério (peso) | A — referência e opacidade | B — cifrado no vault | C — integração com o gerenciador |
|---|---|---|---|
| Segredo fora do vault e do agente (3) | sim | não (cifrado, mas no vault e ao alcance da senha mestra) | não (o agente recebe o segredo) |
| Agnóstico de gerenciador (3) | sim | sim | não (um adaptador por gerenciador) |
| Só biblioteca padrão, sem cripto própria (2) | sim | não | sim, mas com processo externo fora dos processadores |
| Segredo à mão sem sair da skill (1) | não | sim | sim |

## Mais Informações
ADR-0007 (fronteiras da skill), ADR-0008 (pasta sincronizada), ADR-0013 (conector). Fontes: não verificado — o KeePass e o KeePassXC aceitarem anexos em entradas é citado só como recomendação ao usuário e deve ser conferido na documentação deles ao escrever `references/confidential.md`.
