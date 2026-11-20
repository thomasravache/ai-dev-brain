---
id: ADR-0022
title: Serviço ligado ao repositório do código pela imagem, sem kind novo
status: proposed
origin: decision
date: 2026-11-20
pillars: []
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: testes da SPEC-0082 (CH-01, CT-01, UT-04 a UT-07)
---

# ADR-0022 — Serviço ligado ao repositório do código pela imagem, sem kind novo

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
No GitOps, a Application do Argo CD aponta para o repositório de configuração, e o atlas ligava o serviço só a ele (regra 1 do `build`, ADR-0011). Como ligar o serviço ao repositório do código sem quebrar máquinas na versão anterior? Elas revalidam cada snapshot no `build` (`read_snapshots` em `skills/boson-atlas/scripts/atlas.py`) e descartam o snapshot inteiro diante de um kind ou relação desconhecido. (SPEC-0082)

## Direcionadores da Decisão
- Nada configurado pode quebrar (ADR-0018, ADR-0020).
- O contrato dos coletores é público e versionado (ADR-0011).
- Nenhum dado de execução ou identificador sensível entra no atlas (tag, digest, id de conta no host do registry).

## Opções Consideradas
- Kind `image` e relações novas (`runs_image`, `publishes`).
- Atributo `images` no `deployment` e regra de inferência 4 no `build`.
- Ler packages e registries pela API de cada provedor.

## Resultado da Decisão
**Opção escolhida:** "atributo `images` e regra 4". É a única que não quebra a leitura em máquinas na versão anterior, porque o contrato `@1` já aceita listas de escalares em `attrs`. A ligação fica no `build`, como as regras 1 a 3. Ler registries exigiria permissões e um coletor por provedor.

Regras:
1. `images` guarda só o caminho normalizado da imagem, sem host, tag nem digest.
2. A regra 4 casa a imagem com um repositório nesta ordem: mapa `image_repositories`, `<dono>/<nome>` e nome único. Sem casamento seguro, não liga.
3. A aresta inferida leva a evidência `image:<caminho>`, e a página separa os repositórios em "Código" e "Configuração (GitOps)".

### Consequências
- **Boa**, porque as pipelines e os donos do repositório do código aparecem no serviço, e a seção "Do commit até o pod" sai só do grafo.
- **Ruim**, porque a imagem não é uma entidade própria e não pode ser consultada sozinha no `context`. Se isso for pedido, vira um `collector@2` com leitura dupla.

### Confirmação (G3)
CH-01 e CT-01 da SPEC-0082 falham se o grafo atual mudar sem imagens ou se o snapshot novo deixar de ser aceito pelo contrato `@1`. UT-04 a UT-07 fixam a regra 4 e a página.

## Prós e Contras das Opções
| Critério (peso) | Kind `image` | Atributo + regra 4 | API de registries |
|---|---|---|---|
| Máquina na versão anterior continua lendo (alto) | não | sim | sim |
| Sem dado sensível (alto) | depende | sim (sem host) | depende |
| Agnóstico de provedor (alto) | sim | sim | não |
| Imagem consultável sozinha (baixo) | sim | não | sim |

## Mais Informações
- SPEC-0082, SPEC-0076 (nome do serviço), SPEC-0080 (mensagens sem o item).
- ADR-0011, ADR-0018, ADR-0020.
- Fontes externas: N/A — decisão interna de modelo.
