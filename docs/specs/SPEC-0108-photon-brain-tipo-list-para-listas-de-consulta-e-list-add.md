---
id: SPEC-0108
title: "photon-brain: tipo list para listas de consulta e list add"
tier: full
type: feature
user_facing: false
status: approved
created: 2026-11-26
parent: SPEC-0093
depends_on: [SPEC-0107]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/assets/templates/list.md, skills/photon-brain/references/note-types.md, skills/photon-brain/references/inbox.md, skills/photon-brain/SKILL.md, skills/photon-brain/CHANGELOG.md, skills/photon-brain/tests/test_list.py, skills/photon-brain/tests/test_list_cli.py, .claude-plugin/plugin.json]
adrs: [ADR-0007, ADR-0027]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-26
---

# SPEC-0108 — photon-brain: tipo list para listas de consulta e list add

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Um tipo de nota `list` para listas de consulta (o que se lê e se procura: ideias, livros, contatos de prestadores, itens que costumam faltar em casa) e o comando `list add NOTA --item TEXTO [--item ...]`, que acrescenta itens à lista com linha no `log.md`. A regra fica escrita: o que se marca como feito vai para a ferramenta de tarefas; o que se consulta fica no vault (pontos 2 e 14 da SPEC-0093).

## 2. Motivação & Escopo
**Motivação:** nenhum tipo de nota serve para lista; uma lista que cresce vira várias capturas soltas na inbox; e a lista de compras ficou duplicada entre o vault e o Google Tasks. O tipo `list` dá um lugar para listas de consulta, e a regra evita uma segunda lista de tarefas no vault.

**Objetivos (dentro do escopo):**
- Tipo `list` em `NOTE_TYPES`, com o modelo `assets/templates/list.md` (`## Items` antes de `## Relations`) e a documentação em `references/note-types.md`, com a regra "se marca como feito → tarefas; se consulta → vault".
- `list add NOTA --item TEXTO [--item ...] [--json]`: cada item vira uma linha `- TEXTO` no fim de `## Items`, pelo `append_section` da SPEC-0107; item repetido (mesmo texto, sem diferença de caixa e de espaços nas pontas) não é duplicado.
- Ao processar a inbox (`references/inbox.md` e `SKILL.md`), capturas que são itens de uma lista existente entram com `list add` em vez de virar nota nova.

**Não-objetivos (fora do escopo):**
- Checkbox `- [ ]` e marcar item como feito (a regra manda isso para a ferramenta de tarefas, SPEC-0113).
- Remover ou reordenar itens.
- Acrescentar pelo conector (ADR-0013).

## 3. Dependências
- **Implementações necessárias:** SPEC-0107 — `list add` usa o `append_section` e o caminho de escrita com log.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** os tipos vivem em `NOTE_TYPES` (`scripts/brain.py`) com um modelo por tipo em `assets/templates/`, copiados para `templates/` do vault no `init`; a documentação dos tipos é `references/note-types.md`. A escrita segue o `relate` e o `append` (SPEC-0107).

**Decisão:** `list` entra em `NOTE_TYPES` com o modelo novo; `cmd_list_add` resolve a nota como o `relate`, exige `type: list` no frontmatter e chama `append_section(text, "Items", linhas)` uma vez com os itens novos.

**Justificativa:** reaproveita o tipo e o modelo como os outros nove, e a escrita com log da SPEC-0107.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** checklist `- [ ]` no vault (duplicaria a ferramenta de tarefas, que foi exatamente o problema do feedback); um arquivo por item (vira as capturas soltas de hoje).

**ADRs:** ADR-0007, ADR-0027.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — até 50 itens por chamada.
- **Segurança:** item com quebra de linha, vazio, maior que 500 caracteres ou mais de 50 itens numa chamada é recusado — UT-04.
- **Privacidade e dados pessoais:** a linha do log leva a nota e a quantidade de itens, nunca o texto dos itens — UT-05.
- **Disponibilidade e resiliência:** uma escrita atômica por chamada; recusa antes de gravar não muda nada.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A — local.

## 6. Artefato A — Contrato
**Interface:** tipo `list`; `brain.py list add`

```text
assets/templates/list.md
  frontmatter: type: list, title, created (AAAA-MM-DD), context, tags
  "# <título>" / "## Items" (vazia) / "## Relations"

brain.py new-note --type list --title X [...]   (como os outros tipos)

brain.py list add NOTA --item TEXTO [--item TEXTO ...] [--json]
  sucesso (exit 0): "N item(ns) acrescentado(s) a <rel>; M já estavam" | {"note", "added", "skipped"}
    - cada item novo vira "- TEXTO" no fim de "## Items" (cria a seção antes de "## Relations" se faltar)
    - repetido = mesmo texto sem diferença de caixa nem de espaços nas pontas, contra a lista e entre os --item
    - todos repetidos: exit 0, nada gravado, sem linha no log
    - log.md: "- <agora> list add <rel> — N item(ns)"
  erros (exit 2, nada gravado): nota não encontrada ou fora do vault | nota sem "type: list" |
    nenhum --item | item vazio, com quebra de linha ou > 500 caracteres | mais de 50 itens
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** `scripts/brain.py` (`NOTE_TYPES`, `cmd_list_add`, parser); `assets/templates/list.md`; `references/note-types.md` (tipo e regra); `references/inbox.md` e `SKILL.md` (capturas que são itens de lista).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Criar lista | `new-note --type list` | nota com `## Items` e `## Relations`, no contexto | UT-01, IT-01 |
| Acrescentar itens | `list add` com itens novos | linhas `- item` no fim de `## Items`, log com a quantidade | UT-02, IT-01 |
| Item repetido | item já na lista ou repetido na chamada | não duplica; todos repetidos não grava nem loga | UT-03 |
| Entrada inválida | nota não `list`, sem item, item vazio/longo/com quebra, mais de 50 | exit 2, nada muda | UT-04 |
| Log sem o texto | qualquer `list add` | log com nota e quantidade, sem o texto | UT-05 |
| Regra documentada | `references/note-types.md`, `SKILL.md`, `references/inbox.md` | regra "marca como feito → tarefas; consulta → vault" e o uso do `list add` ao processar a inbox | UT-06 |
| Tipos de hoje | os nove tipos existentes | modelos e `new-note` iguais | CH-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Dado o `init` e o `new-note` dos nove tipos de hoje, quando rodam num vault temporário, então os modelos copiados e as notas criadas são iguais aos de antes (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Quando o `new-note --type list` roda, então a nota tem `type: list`, `# título`, `## Items` vazia antes de `## Relations`, e o `init` copia `templates/list.md` para o vault.
- **UT-02** — Dada uma lista com dois itens, quando o `list add` recebe dois itens novos, então eles entram no fim de `## Items`, na ordem, como `- item`, e o resto da nota não muda.
- **UT-03** — Dados itens já presentes (com diferença só de caixa ou de espaços nas pontas) e um item repetido na mesma chamada, então nenhum é duplicado; quando todos já estão, a nota e o `log.md` ficam iguais e a saída diz `0 item(ns) acrescentado(s)`.
- **UT-04** — Quando a nota não é `type: list`, não há `--item`, um item é vazio, tem quebra de linha ou mais de 500 caracteres, ou há mais de 50 itens, então sai com 2 e nada muda.
- **UT-05** — Em todo `list add` com item novo, a linha do log segue o `LOG_LINE`, cita a nota e a quantidade e não contém o texto de nenhum item.
- **UT-06** — `references/note-types.md` lista o tipo `list` com a regra de que o que se marca como feito vai para a ferramenta de tarefas e o que se consulta fica no vault; `SKILL.md` e `references/inbox.md` mandam usar `list add` quando uma captura é item de uma lista existente.

### 7.3 Testes de Integração
- **IT-01** — Num vault do `init`, quando o agente cria uma lista com `new-note --type list`, roda `list add` duas vezes e depois `index`, então a lista aparece no índice com o tipo `list`, tem os itens sem repetição e o `lint` não acusa nada novo.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs.

### 7.5 Testes E2E
- N/A — CLI de uso do agente; `user_facing: false` e sem jornada crítica declarada.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `Sandbox` de `tests/brain_support.py`; listas montadas nos testes.

**Ambiente de execução:** local e CI, suíte da photon-brain.

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin.
- **Dados/schema:** vaults já criados não têm `templates/list.md`; o `new-note` usa o modelo da skill como hoje (fallback de `TEMPLATES_DIR`) e o `doctor` não reclama da falta.
- **Compatibilidade:** tipo e comando novos; nada muda nos existentes.
- **Observabilidade:** linhas `list add` no `log.md`.
- **Rollback:** reverter o merge; notas `list` continuam Markdown válido.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] A lista usa checkbox? — Não: o que se marca como feito vai para a ferramenta de tarefas (regra do ecossistema, thomas, 2026-11-25, registrada no ponto 14 da SPEC-0093)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [ ] Red: CH-01, UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01 com a tag `SPEC-0108:<ID>`, falhando pelo motivo certo (CH passando)
- [ ] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [ ] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 266f556 (árvore suja) | 2026-11-26 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Todos os testes do plano passando e listados na Verificação
- [ ] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [ ] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [ ] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [ ] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [ ] Observabilidade e rollback prontos conforme o Plano de Rollout
- [ ] Documentação raiz e CHANGELOG atualizados (G7)
- [ ] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0108`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
