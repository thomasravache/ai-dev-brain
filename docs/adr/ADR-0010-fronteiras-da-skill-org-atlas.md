---
id: ADR-0010
title: Fronteiras da skill org-atlas
status: accepted
origin: decision
date: 2026-10-30
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0029
---

# ADR-0010 — Fronteiras da skill org-atlas

## Contexto e Problema
O `ai-dev-brain` passa a ter uma terceira skill, `org-atlas`, que varre como uma organização desenvolve e opera software (vários repositórios, entrega, infraestrutura, dados, processo) e gera um atlas para os agentes (SPEC-0029). Diferente das outras skills, ela toca credenciais e sistemas de terceiros. Precisamos decidir se ela segue as fronteiras do ADR-0001 e do ADR-0007 e o que é próprio dela: o que pode ser executado, o que pode ser guardado e como ela se liga à `sdd-management`.

## Direcionadores da Decisão
- Funcionar em qualquer organização, agente e máquina só com Python 3.9+, sem `pip install` (ADR-0001).
- Ser agnóstica de provedor: GitHub, GitLab, Argo CD, Flux, AWS, GCP, bancos variados.
- Nunca guardar valor de segredo, dado de negócio ou código-fonte da organização.
- As skills são instaladas separadamente; uma não pode quebrar a outra (ADR-0007).

## Opções Consideradas
- **A — Skill própria com script único stdlib** (`skills/org-atlas/scripts/atlas.py`), coletores como comandos externos declarados na configuração.
- **B — Feature da `sdd-management`** (comandos novos no `spec_graph.py`).
- **C — Pacote Python com SDKs** (ex.: clientes oficiais de nuvem, Kubernetes e bancos).

## Resultado da Decisão
**Opção escolhida:** A, porque mantém a instalação por cópia, deixa a skill útil sem a `sdd-management` e põe o específico de cada provedor fora do código.

**Regras (verificáveis):**
- `skills/org-atlas/SKILL.md` contém os fluxos e as regras do agente; detalhe vai para `skills/org-atlas/references/`.
- `skills/org-atlas/scripts/atlas.py` é um arquivo único que importa só a biblioteca padrão e roda em Python 3.9.
- Nenhum código de `skills/org-atlas/` importa de outra skill nem de `tools/`, e vice-versa. A `sdd-management` usa o atlas só pela CLI (`atlas.py context`) e pela chave opcional `org_context` do `sdd-config.yml`.
- O `atlas.py` só executa os coletores (e, com a SPEC-0030, os probes) declarados na configuração, sem shell. Nunca faz chamada de rede por conta própria e nunca chama a CLI de um provedor que não esteja declarada.
- **Só metadados:** o atlas guarda nomes, estrutura e relações; nunca valores de segredo, dados de negócio nem código-fonte. Antes de gravar, o `atlas.py` mascara o que parecer segredo; o `lint` acusa vazamento como erro.
- **Credenciais fora do atlas:** a configuração local (fora do repositório e do atlas) guarda só nomes de profile e de variável de ambiente; a compartilhada nunca tem segredo nem caminho absoluto.
- **Texto humano preservado:** o `atlas.py` só reescreve regiões delimitadas por `<!-- atlas:begin <nome> -->` e `<!-- atlas:end <nome> -->`, e snapshots e arquivos gerados.
- Todo fato do atlas registra `source`, `seen_at` e `confidence` (`inferred` ou `confirmed`).
- Nenhum caminho absoluto de usuário em arquivos de `skills/org-atlas/` fora dos testes.
- **Versão:** `ATLAS_VERSION` (AAAA.MM.N) e `skills/org-atlas/CHANGELOG.md` atualizados no mesmo PR de toda mudança de comportamento (ADR-0005).
- Testes seguem o ADR-0002: `unittest`, unitários importando `atlas` e integração pela CLI com coletores falsos em diretórios temporários e `HOME` isolado.

### Consequências
- **Boa**, porque a skill é copiada com uma pasta, roda em qualquer organização e mantém segredos e dados fora do atlas por regras testadas.
- **Ruim**, porque cada organização precisa declarar os coletores (mitigado pelos guias por provedor), e o parser de YAML e os checadores de arquitetura ficam duplicados em relação às outras skills.

### Confirmação (G3)
`skills/org-atlas/tests/test_architecture.py`, criado pela primeira filha da SPEC-0029: imports só da biblioteca padrão, arquivo único, nenhum import entre skills, processo externo só na função que executa coletores, nenhum caminho pessoal, nenhum segredo plantado chegando ao atlas. Roda na CI junto com as outras suítes.

## Prós e Contras das Opções
| Critério (peso) | A — skill própria stdlib | B — feature da sdd-management | C — pacote com SDKs |
|---|---|---|---|
| Instalação por cópia de uma pasta (3) | sim | sim | não (pip) |
| Útil sem a `sdd-management` (3) | sim | não | sim |
| Agnóstica de provedor no código (3) | sim | sim | não (um SDK por provedor) |
| Tamanho do `spec_graph.py` (1) | não muda | cresce bastante | não muda |

## Mais Informações
ADR-0001 (fronteiras da `sdd-management`), ADR-0007 a ADR-0009 (`second-brain`: fronteiras, configuração em duas camadas, processos externos declarados), ADR-0002 (testes), ADR-0005 (fluxo de mudança e versão). Fontes: não verificado — decisão sobre a estrutura do próprio código, sem ferramenta externa nem versão a conferir.
