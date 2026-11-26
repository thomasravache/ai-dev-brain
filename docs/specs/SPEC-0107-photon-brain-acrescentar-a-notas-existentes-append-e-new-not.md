---
id: SPEC-0107
title: "photon-brain: acrescentar a notas existentes (append e new-note --body-file)"
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-11-26
parent: SPEC-0093
depends_on: []
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/SKILL.md, skills/photon-brain/references/store-flow.md, skills/photon-brain/CHANGELOG.md, skills/photon-brain/tests/test_append.py, skills/photon-brain/tests/test_append_cli.py, .claude-plugin/plugin.json]
adrs: [ADR-0007]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-26
---

# SPEC-0107 — photon-brain: acrescentar a notas existentes (append e new-note --body-file)

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Dois jeitos novos de escrever o corpo de uma nota pelo `brain.py`, sempre com linha no `log.md`: `append NOTA --section "Título" --text-file ARQ` acrescenta uma seção (ou texto a uma seção que já existe) antes de `## Relations`, e `new-note --body-file ARQ` cria a nota já com o corpo. Hoje o agente escreve esse texto à mão, fora do log (pontos 1, 10 e 11 da SPEC-0093).

## 2. Motivação & Escopo
**Motivação:** no uso real, completar notas existentes e escrever o corpo de uma nota nova foi feito com scripts à mão: nada no `log.md`, risco de inserir depois de `## Relations` e de quebrar o arquivo. A lista que cresce (ponto 1) também precisa de um jeito de acrescentar a uma nota que já existe.

**Objetivos (dentro do escopo):**
- `append NOTA --section TÍTULO --text-file ARQ [--json]`: com a seção `## TÍTULO` existente, o texto entra no fim dela; sem a seção, ela é criada antes de `## Relations` (ou no fim, sem `## Relations`).
- `new-note ... --body-file ARQ`: o texto do arquivo substitui o corpo do modelo entre o título e `## Relations`, mantendo frontmatter e `## Relations`.
- Uma linha no `log.md` por escrita, no formato de hoje.
- `SKILL.md` e `references/store-flow.md` passam a mandar usar os dois comandos em vez de editar à mão.

**Não-objetivos (fora do escopo):**
- Editar ou apagar texto que já está na nota (só acrescenta).
- Acrescentar pelo conector: pelo ADR-0013 o conector só cria arquivo novo na inbox; o que chega por lá entra na nota quando a inbox é processada com a pasta.
- O tipo `list` e o `list add` (SPEC-0108), que usam este `append`.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** segue o padrão do `relate` (`cmd_relate` e a função pura `append_relation` em `scripts/brain.py`): lê com `read_exact`, edita numa função pura, recusa link simbólico para fora do vault (`write_target`), grava de forma atômica (`rewrite_file`) e registra com `append_log`. O `new-note` segue `cmd_new_note` e `write_new_file` (nunca sobrescreve).

**Decisão:** uma função pura nova `append_section(text, heading, addition)` ao lado de `append_relation`, usando `RELATIONS_HEADING` e `SECTION_END_RE`; o subcomando `append` reaproveita o caminho de escrita do `relate`; `--body-file` em `cmd_new_note` troca o corpo do modelo pelo texto antes do `write_new_file`.

**Justificativa:** o padrão do `relate` já é o que garante escrita segura e com log (ADR-0007); repetir esse caminho mantém uma única forma de editar notas.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** `--text` com o conteúdo na linha de comando (quebra com texto longo e aspas; o arquivo é o padrão de entrada de texto longo da skill); editar a nota inteira com `--replace` (risco de perder texto do usuário, contra o ADR-0007).

**ADRs:** ADR-0007.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — uma nota por chamada, arquivos pequenos.
- **Segurança:** a nota tem de estar dentro do vault (mesma checagem do `relate`); link simbólico para fora é recusado; o arquivo de texto é lido como UTF-8 e recusado se for binário, maior que 1 MiB ou não existir; o título da seção não pode ter quebra de linha nem começar com `#` — verificado pelos UT.
- **Privacidade e dados pessoais:** a linha do log leva só o caminho da nota e o título da seção, nunca o texto acrescentado — UT-05.
- **Disponibilidade e resiliência:** escrita atômica (`rewrite_file`); falha antes de gravar não muda a nota nem o log.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A — local.

## 6. Artefato A — Contrato
**Interface:** `brain.py append` e `brain.py new-note --body-file`

```text
brain.py append NOTA --section TÍTULO --text-file ARQ [--json]
  NOTA: caminho relativo ao vault ou nome da nota ([[nome]] sem colchetes), resolvido como no relate
  sucesso (exit 0): "acrescentado: <rel> — ## TÍTULO" (texto) | {"note": rel, "section": TÍTULO, "created_section": bool} (--json)
    - com "## TÍTULO" na nota: o texto entra no fim da seção (antes do próximo título de nível 1 ou 2),
      separado por uma linha em branco
    - sem a seção: "## TÍTULO\n\n<texto>\n" entra logo antes de "## Relations"; sem "## Relations", no fim
    - BOM e fim de linha da nota preservados; o texto termina com uma quebra de linha
    - log.md: "- <agora> append <rel> — ## TÍTULO"
  erros (exit 2, nada gravado): nota não encontrada | nota fora do vault | --text-file ausente,
    binário, vazio ou > 1 MiB | TÍTULO vazio, com quebra de linha, começando com "#" ou igual a "Relations"
  erro (exit 3): sem configuração (como os outros comandos)

brain.py new-note --type T --title X [...] --body-file ARQ
  o texto do arquivo substitui as seções do modelo entre o "# título" e "## Relations";
  frontmatter e "## Relations" ficam como no modelo; sem --body-file, o comportamento de hoje
  log.md: "- <agora> new-note <rel> — <tipo>; com corpo"
  erros (exit 2, nada criado): --body-file ausente, binário, vazio ou > 1 MiB;
    corpo com uma linha "## Relations" (a seção é do modelo)
```

**Esclarecimentos (Emenda v2):**
- Uma linha dentro de bloco de código cercado (aberto por ```` ``` ```` ou `~~~`, até o fechamento com a mesma cerca) nunca é título: não abre nem fecha seção, no `append_section`, no `section_start` e na recusa de `## Relations` do corpo. Bloco sem fechamento vai até o fim do arquivo.
- O `append` recusa com exit 2, sem gravar, um texto que tenha uma linha `## Relations` fora de bloco de código, como o `new-note --body-file`.
- Nas duas recusas, `## Relations` é comparado sem diferença de maiúsculas e com qualquer quantidade de espaço depois de `##` (`## relations`, `##  Relations`).

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** `scripts/brain.py` (`append_section`, `cmd_append`, parser do `append`, `--body-file` no `new-note`); `SKILL.md` (fluxo de guardar: usar `append` e `--body-file`, nunca editar à mão); `references/store-flow.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Seção nova | nota sem `## Resumo` | seção criada antes de `## Relations`; log com a linha do append | UT-01, IT-01 |
| Seção existente | nota com `## Resumo` e texto | texto acrescentado no fim da seção, nada perdido | UT-02, IT-01 |
| Nota sem Relations | nota sem `## Relations` | seção no fim do arquivo | UT-01 |
| Formato preservado | nota com BOM e CRLF | BOM e CRLF mantidos | UT-03 |
| Entrada inválida | título vazio, com `#`, `Relations`, arquivo ausente/binário/vazio/grande, nota fora do vault | exit 2, nota e log iguais | UT-04 |
| Log sem o texto | qualquer append | a linha do log tem caminho e título, não o texto | UT-05 |
| Corpo na criação | `new-note --body-file` | nota com o corpo, frontmatter e `## Relations` do modelo; log "com corpo" | UT-06, IT-02 |
| Corpo inválido | corpo com `## Relations` ou arquivo inválido | exit 2, nenhuma nota criada | UT-06 |
| Sem as opções novas | `new-note` e `relate` de hoje | comportamento igual | CH-01 |
| Bloco de código | `# comentário` ou `## Título` dentro de bloco cercado na nota ou no texto | não conta como título; o texto entra fora do bloco | UT-07 |
| Relations no texto | texto do `append` ou corpo do `new-note` com `## relations`/`##  Relations` fora de bloco | exit 2, nada gravado | UT-08 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Dado o `new-note` sem `--body-file` e o `relate` de hoje, quando rodam num vault temporário, então o arquivo criado e as linhas do log são iguais aos de antes da mudança (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dada uma nota com `## Summary` e `## Relations`, quando `append_section` recebe `Resumo` e um texto, então `## Resumo` com o texto aparece logo antes de `## Relations`; sem `## Relations`, no fim.
- **UT-02** — Dada uma nota com `## Resumo` seguida de `## Relations`, quando `append_section` recebe `Resumo`, então o texto entra no fim de `## Resumo`, depois do texto antigo e de uma linha em branco, e nada mais muda.
- **UT-03** — Dada uma nota com BOM e fim de linha CRLF, quando o `append` grava, então o BOM e o CRLF são mantidos, inclusive nas linhas acrescentadas.
- **UT-04** — Quando o `append` recebe título vazio, com quebra de linha, começando com `#` ou igual a `Relations`, arquivo de texto ausente, binário, vazio ou maior que 1 MiB, ou nota fora do vault (inclusive por link simbólico), então sai com 2 e a nota e o `log.md` ficam iguais.
- **UT-05** — Em todo append com sucesso, a linha nova do `log.md` segue o `LOG_LINE` de hoje, cita o caminho e `## <título>` e não contém nenhuma linha do texto acrescentado.
- **UT-06** — Quando o `new-note` recebe `--body-file` válido, então a nota tem o frontmatter do modelo, o `# título`, o corpo do arquivo e `## Relations`; com o corpo contendo `## Relations` ou o arquivo inválido, sai com 2 e não cria nada.
- **UT-07** — Dada uma nota com `## Setup` contendo um bloco ```` ```bash ```` com a linha `# instala`, e um bloco `~~~` com a linha `## Resumo` em outra seção, quando `append_section` recebe `Setup` e um texto, então o texto entra no fim de `## Setup`, depois do fechamento do bloco, e o bloco fica igual; quando recebe `Resumo`, a seção `## Resumo` é criada antes de `## Relations` (a do bloco não conta).
- **UT-08** — Quando o texto do `append` ou o corpo do `new-note --body-file` tem uma linha `## Relations`, `## relations` ou `##  Relations` fora de bloco de código, então sai com 2 e nada é gravado; a mesma linha dentro de um bloco cercado é aceita.

### 7.3 Testes de Integração
- **IT-01** — Num vault temporário criado pelo `init`, quando o `append` roda duas vezes na mesma nota (seção nova, depois a mesma seção), então a nota tem a seção com os dois textos na ordem, o `lint` não acusa nada novo e o `log.md` tem duas linhas `append`.
- **IT-02** — No mesmo vault, quando o `new-note --body-file` cria uma nota e o `relate` liga outra a ela, então a nota tem o corpo e a relação em `## Relations`, e o `log.md` tem a linha `new-note … com corpo` e a do `relate`.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs (a SPEC-0108 usa a função pela implementação, com `depends_on`).

### 7.5 Testes E2E
- N/A — CLI de uso do agente; sem jornada crítica declarada (`critical_journeys` vazio) e `user_facing: false`, como nas specs anteriores da skill.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** vault temporário do `Sandbox` (`tests/brain_support.py`), notas montadas nos testes, arquivos de texto temporários.

**Ambiente de execução:** local e CI, `python3 -m unittest discover -s skills/photon-brain/tests`.

## 8. Plano de Rollout
- **Estratégia:** deploy direto — a skill chega pelo plugin `fermion`.
- **Dados/schema:** N/A — nenhuma mudança de formato do vault.
- **Compatibilidade:** comandos e opções novos; nada do que existe muda.
- **Observabilidade:** as linhas do `log.md`.
- **Rollback:** reverter o merge; o vault continua válido.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] O `append` aceita o texto pela linha de comando? — Não: só `--text-file`, como sugerido no feedback; texto longo e aspas quebram na linha de comando (Architect, 2026-11-26, no piloto automático)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [x] Red: CH-01, UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, IT-01, IT-02 com a tag `SPEC-0107:<ID>`, falhando pelo motivo certo (CH passando)
- [x] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [x] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — f2669b5 (árvore suja) | 2026-11-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=40)) — 1bef1d1 | 2026-11-26 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — b5483bc | 2026-11-26 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 35be308 | 2026-11-26 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED na segunda rodada (M1 e m1–m4 resolvidos; n1/n2 minors para o radar) — 5a6e897 | 2026-11-26 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 1ec47ef | 2026-11-26 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-26 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-26 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 1d5f21b | 2026-11-26 |

### Histórico de reprovações
- G0 FAIL 2026-11-26 — validate: 1 erro(s) — f2669b5
- G0 PASS 2026-11-26 — depois de 1 reprovação(ões)
- G4 FAIL 2026-11-26 — CHANGES_REQUESTED: append_section toma linha '#'/'##' dentro de bloco de código cercado como título e grava o texto dentro do bloco (M1); minors: append aceita linha '## Relations' no texto, recusa do new-note só na grafia exata — fc5ccdd
- G4 PASS 2026-11-26 — depois de 1 reprovação(ões)

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
<!-- comportamento entregue do ponto de vista do usuário/sistema -->
Dois caminhos de escrita da photon-brain que faltavam para não editar notas à mão: `brain.py append NOTA --section TÍTULO --text-file ARQ [--json]`, que acrescenta o texto no fim da seção (ou cria a seção antes de `## Relations`), e `new-note --body-file ARQ`, que cria a nota já com o corpo. Os dois gravam uma linha no `log.md` sem o texto. Linhas dentro de bloco de código cercado nunca contam como título, e `## Relations` no texto é recusado (Emenda v2). Versões: photon-brain 2026.11.9 e plugin 2026.11.45.

### Como foi feito
<!-- decisões de implementação, módulos/arquivos principais, desvios e emendas (com versão), dívidas assumidas -->
- **`scripts/brain.py`:** função pura `append_section` com `heading_lines` (marca o que é título fora de bloco cercado), `section_start` e `has_relations_line`; `cmd_append` segue o caminho de escrita do `relate` (`find_note`, `write_target`, `read_exact`, `rewrite_file`, `append_log`); `--body-file` no `new-note` por `with_body`; entrada até 1 MiB, UTF-8, sem NUL.
- **Documentação:** `SKILL.md` (fluxo de guardar com `append` e `--body-file`) e `references/store-flow.md`.
- **Emenda v2:** blocos de código e `## Relations` no texto, depois do G4 reprovado.

### Prova de Correção
<!-- type fix: o teste de regressão falhou antes da correção (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
N/A — `type: feature`. Red em 1bef1d1 e f6831d7 (G1) e green em b5483bc (G2).

### Verificação
<!-- Uma linha por teste do plano (todos os IDs da seção 7). Resultado: PASS. Evidência: execução de CI, commit ou relatório. -->
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | new-note e relate sem as opções novas iguais aos de hoje | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-01 | seção nova antes de ## Relations ou no fim | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-02 | texto no fim de uma seção existente | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-03 | BOM e CRLF preservados | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-04 | entradas inválidas: exit 2, nota e log iguais | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-05 | linha do log com caminho e título, sem o texto | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-06 | new-note --body-file válido e inválido | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-07 | linhas em bloco de código cercado não são título | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| UT-08 | ## Relations no texto recusado sem diferença de caixa e espaço | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| IT-01 | append de ponta a ponta num vault do init | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |
| IT-02 | new-note --body-file de ponta a ponta | PASS | `test_append.py` e `test_append_cli.py`; G2 PASS em b5483bc; G4 `verify` 11/11 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6)
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7)
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
<!-- ambiente(s), versão/tag, data, estratégia, estado da feature flag, execução do pipeline -->
Sem deploy: a skill chega pelo plugin `fermion` 2026.11.45 depois do merge.

### Pendências
<!-- specs criadas para o que ficou de fora, ou "Nenhuma" -->
- **Minors do G4 para o radar** do épico SPEC-0093:
  - um `--text-file`/`--body-file` com bloco de código sem fechamento engole o `## Relations` real para o `append` seguinte;
  - `append_relation` (do `relate`) não ignora blocos de código; usar `heading_lines` nele.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0107`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-26 | Linhas em bloco de código cercado não são título; `append` recusa `## Relations` no texto; recusa sem diferença de maiúsculas e de espaços (UT-07, UT-08) | G4 da SPEC-0107: append dentro de bloco de código corrompe a nota | nenhuma | thomas, 2026-11-26 (piloto automático com o recomendado) |
