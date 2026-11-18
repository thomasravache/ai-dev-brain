---
id: ADR-0021
title: Vários atlas por máquina e ordem de escolha
status: proposed
origin: decision
date: 2026-11-18
pillars: []
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: testes das SPEC-0079 e SPEC-0080 (CH-01, IT-01, IT-02, CT-01) e tests/test_architecture.py
---

# ADR-0021 — Vários atlas por máquina e ordem de escolha

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
O ADR-0010 deixou a configuração local da `boson-atlas` com um atlas só. A configuração fica em `~/.config/boson-atlas/config.yml`, com `atlas:` e `credentials:`, e é lida por `read_local`/`scan_config` em `skills/boson-atlas/scripts/atlas.py`. Quem trabalha para várias organizações troca de atlas exportando `ATLAS_CONFIG_HOME`, e um `init --join` regrava o ponteiro e perde o anterior. Como manter vários atlas na mesma máquina e escolher o certo para cada projeto, no terminal, nas tools MCP, no hook e na `gluon-spec`? (SPEC-0077)

## Direcionadores da Decisão
- Nada configurado pode quebrar, e o plugin não muda arquivos da pessoa sozinho (ADR-0018, ADR-0019, ADR-0020).
- As credenciais ficam fora do atlas e só pelo nome, isoladas por organização (ADR-0010).
- Usar o atlas errado traz convenções e credenciais de outra organização: a escolha precisa ser explícita ou determinística, nunca um palpite.
- Nada de caminho da máquina nem dado local no repositório do time.

## Opções Consideradas
- Um `ATLAS_CONFIG_HOME` por organização (como hoje), trocado pela pessoa.
- Um só arquivo local com vários atlas nomeados (`atlases:` + `default:`) e uma ordem de escolha fixa na CLI.
- Um arquivo no repositório de cada projeto apontando para o atlas.

## Resultado da Decisão
**Opção escolhida:** "um só arquivo local com vários atlas e ordem de escolha fixa", porque:
- mantém as credenciais locais e isoladas por atlas;
- não toca o repositório do time;
- deixa a mesma escolha valer para a CLI, o MCP, o hook e a `gluon-spec`.

A troca de `ATLAS_CONFIG_HOME` não deixa o hook nem o MCP escolherem, e o arquivo no repositório levaria dados da máquina para o time.

Regras:
1. **Formato:** `atlases: {<nome>: {atlas, credentials}}` com `default:` opcional. A forma de um atlas só (`atlas:` + `credentials:`) continua lida e é gravada enquanto houver uma entrada, e a forma nova só é gravada ao acrescentar o segundo atlas, com `.bak`.
2. **Ordem de escolha:** `--atlas` → `ATLAS_NAME` → remote `origin` do projeto casado com `remotes:` do `atlas-config.yml` (prefixo por segmentos, o mais longo; empate pula o passo) → `default` → atlas único. Vários atlas sem escolha dão exit 2 com o passo, e um nome ou caminho fora da lista dá exit 3.
3. **Credenciais:** as de um atlas nunca são usadas por outro.
4. **Visibilidade:** toda saída de configuração diz qual atlas foi escolhido e por quê (`selected_by`), sem mostrar caminhos, remotes nem credenciais no hook.
5. **`gluon-spec`:** continua chamando só a CLI, agora com `--atlas <org_context>` (ADR-0010).

Este ADR revisa a regra de "um atlas por máquina" implícita no ADR-0010. As demais regras do ADR-0010 continuam.

### Consequências
- **Boa**, porque quem trabalha para várias organizações usa o atlas certo sem trocar variável, e quem tem um atlas só não vê mudança.
- **Boa**, porque a escolha fica num ponto só e é testada uma vez.
- **Ruim**, porque com vários atlas o rollback para a versão anterior exige restaurar o `.bak`.
- **Ruim**, porque `remotes:` declarado num atlas compartilhado é acusado pelo `lint` de máquinas na versão anterior até todas atualizarem.

### Confirmação (G3)
- Testes da SPEC-0079 (CH-01, IT-01, IT-02, CT-01) e da SPEC-0080 (UT-01 a UT-05, IT-01, CT-01) falham se a forma antiga quebrar, se a ordem mudar ou se uma credencial cruzar atlas.
- `tests/test_architecture.py` das skills garante `atlas.py` stdlib e sem importação entre skills.

## Prós e Contras das Opções
| Critério (peso) | `ATLAS_CONFIG_HOME` por organização | Arquivo local com vários atlas | Arquivo no repositório |
|---|---|---|---|
| Nada quebra para quem tem um atlas (alto) | sim | sim (forma antiga mantida) | sim |
| Escolha automática por projeto (alto) | não | sim (remote) | sim |
| Nada da máquina no repositório do time (alto) | sim | sim | não |
| Credenciais isoladas por organização (alto) | sim | sim | sim |
| Esforço (médio) | nenhum | médio | médio |

## Mais Informações
- SPEC-0077 (épico), SPEC-0079, SPEC-0080, SPEC-0081.
- ADR-0010, ADR-0018, ADR-0019, ADR-0020.
- Fontes externas: N/A — decisão interna de configuração, sem tecnologia nova.
