---
id: SPEC-0018
title: "second-brain: busca e relações entre notas"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0017]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/references/search.md, skills/second-brain/SKILL.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0002]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0018 — second-brain: busca e relações entre notas

## 1. Visão Geral
Dá ao agente três comandos determinísticos para conhecer o vault antes de escrever ou responder:
- `search`: busca por texto, com pontuação.
- `related`: notas parecidas com uma nota ou com um texto.
- `links`: links de saída, backlinks e links quebrados de uma nota.

São a base do passo "buscar relações antes de escrever" do fluxo de guardar (SPEC-0019) e do passo "buscar e seguir links" do fluxo de consultar (SPEC-0020).

## 2. Motivação & Escopo
**Motivação:** os insights vêm de ligar a informação nova ao que já existe. Para isso o agente precisa achar as notas relacionadas de forma rápida, repetível e sem ler o vault inteiro a cada pedido.

**Objetivos (dentro do escopo):**
- Leitura de notas: frontmatter, título, tags (frontmatter e `#tag` no texto) e wikilinks (`[[Nota]]`, `[[Nota|apelido]]`, `[[Nota#seção]]`, `![[anexo]]`).
- Resolução de links como o Obsidian faz: pelo nome do arquivo, sem diferenciar maiúsculas, e pelo caminho quando o link tem `/`.
- `search QUERY`: pontuação por termos (TF-IDF simples, com peso maior para título e tags), com filtro por contexto, tipo e tag.
- `related (--note CAMINHO | --text TEXTO)`: pontuação combinando termos em comum, tags em comum, mesmo contexto e vizinhança de links.
- `links NOTA`: links de saída, backlinks e links quebrados.
- Saída em texto e em `--json` (para o agente), com o motivo de cada resultado.

**Não-objetivos (fora do escopo):**
- Busca semântica por embeddings: exigiria modelo ou serviço externo (ADR-0007). O agente cobre a semântica lendo os resultados.
- Índice persistente (SQLite FTS5 ou cache): a varredura atende a meta de desempenho; ver Alternativas.
- Ler o conteúdo de PDFs ou anexos: só o texto das notas e de `raw/`.

## 3. Dependências
- **Implementações necessárias:** SPEC-0017 — configuração efetiva (vault, layout, contextos) e parser de YAML.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Segue a SPEC-0017: `load_config()`, um `cmd_<comando>` por subcomando, saída `--json` no estilo de `export` da `sdd-management` (`spec_graph.py`, comando `export`). Funções puras para leitura e pontuação, testadas com unitários (ADR-0002).

**Decisão:** `scan_vault(config)` lê todas as notas `.md` do vault (ignorando `.obsidian/`, `.trash/` e a pasta de templates) e devolve objetos `Note` (caminho, título, frontmatter, tags, links, termos). `search`, `related` e `links` operam sobre essa lista em memória. A tokenização é em minúsculas, sem acentos (`unicodedata`), sem stopwords em português e inglês.

**Justificativa:** varredura em memória é simples, sem estado para sincronizar entre máquinas, e funciona igual em todos os provedores (ADR-0008). Para um vault pessoal (até alguns milhares de notas) fica abaixo de 2 s.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:**
- SQLite FTS5: depende de como o SQLite foi compilado em cada máquina, e um índice dentro do vault seria sincronizado e entraria em conflito; fora do vault, ficaria desatualizado entre máquinas.
- Embeddings: dependência externa e rede (ADR-0007).

**ADRs:** ADR-0007 e ADR-0002 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `search` e `related` em menos de 2 s num vault gerado com 5.000 notas de 1 KB, medido no teste de desempenho da 7.6.
- **Segurança:** só leitura; nenhum arquivo é escrito por estes comandos.
- **Privacidade e dados pessoais:** nada sai da máquina; saída só no terminal.
- **Disponibilidade e resiliência:** nota com frontmatter inválido ou encoding diferente de UTF-8 não derruba o comando: é lida como texto puro (com `errors="replace"`) e aparece como aviso no `--json` (`warnings`).
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comandos `search`, `related`, `links` e as funções `scan_vault`, `parse_note`, `resolve_link`, usadas pelas filhas seguintes.

```text
Nota (parse_note):
  path: caminho relativo ao vault, com "/"
  title: frontmatter.title, senão o primeiro "# Título", senão o nome do arquivo sem .md
  frontmatter: dict (vazio se não houver ou se inválido)
  tags: frontmatter.tags (lista ou string) + "#tag" no texto (fora de blocos de código), sem "#", em minúsculas
  links: wikilinks [[alvo]], [[alvo|apelido]], [[alvo#seção]], ![[anexo]] → alvo sem seção nem apelido
  context: frontmatter.context, senão o contexto cuja pasta contém a nota

resolve_link(alvo): com "/" → caminho relativo ao vault (com ou sem .md); sem "/" → arquivo de mesmo nome,
  sem diferenciar maiúsculas; vários candidatos → o de caminho mais curto; nenhum → quebrado

brain.py search QUERY [--context C] [--type T] [--tag G] [--limit N=10] [--json]
  pontuação: soma por termo de tf * idf, com peso 3 no título, 2 nas tags, 1 no corpo
  texto: uma linha por resultado "<pontos>  <caminho>  — <título>" e um trecho de até 160 caracteres com o termo
  json: {"query":..., "results":[{"path","title","score","snippet","context","type"}], "warnings":[...]}
  sem resultados: "Nenhuma nota encontrada para: QUERY", exit 0
  sem configuração: exit 3 (SPEC-0017)

brain.py related (--note CAMINHO | --text TEXTO) [--limit N=10] [--json]
  pontuação: 0,5 * similaridade de termos (cosseno TF-IDF) + 0,2 * tags em comum (Jaccard)
             + 0,1 * mesmo contexto + 0,2 * vizinhança (1 se link direto, 0,5 se a dois passos)
  exclui a própria nota; json: {"results":[{"path","title","score","reasons":["tags: x, y","mesmo contexto","link direto","termos: a, b"]}]}
  --note inexistente: exit 2 "nota não encontrada: CAMINHO"

brain.py links NOTA [--json]
  {"outgoing":[{"target","path"|null}], "backlinks":[caminhos], "broken":[alvos]}
  NOTA aceita caminho ou nome (resolve_link); inexistente: exit 2

Ignorados na varredura: .obsidian/, .trash/, a pasta layout.templates e arquivos que não são .md
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. O `SKILL.md` ganha a seção que diz quando usar cada comando, e `references/search.md` explica a pontuação.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Leitura de nota | frontmatter, `#tag`, wikilinks com apelido, seção e anexo | campos do contrato | UT-01 |
| Tag em bloco de código | `#tag` dentro de ``` | não conta | UT-01 |
| Resolução de link | nome, caminho, maiúsculas, vários candidatos | regra do contrato | UT-02 |
| Pontuação da busca | termo no título vs só no corpo | título pontua mais | UT-03 |
| Acentos | "integração" e "integracao" | mesmo resultado | UT-03 |
| Busca com filtros | `--context`, `--type`, `--tag` | só notas que batem | IT-01 |
| Busca sem resultado | termo inexistente | mensagem e exit 0 | IT-01 |
| Relacionadas por nota | nota com tags e links | ordem pela pontuação, com motivos | UT-04, IT-02 |
| Relacionadas por texto | `--text` | notas com termos em comum | IT-02 |
| Nota inexistente | `--note x.md` | exit 2 | IT-02 |
| Links | nota com link quebrado e backlinks | outgoing, backlinks e broken | IT-03 |
| Nota inválida | frontmatter quebrado, arquivo latin-1 | aviso em `warnings`, sem erro | IT-04 |
| Pastas ignoradas | `.obsidian/`, `.trash/`, templates | não aparecem | IT-04 |
| Instruções | `SKILL.md` | quando usar search, related e links | UT-05 |
| Desempenho | 5.000 notas | menos de 2 s | IT-05 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — código novo; a SPEC-0017 já cobre a configuração.

### 7.2 Testes Unitários
- **UT-01** — Dado uma nota com frontmatter (`title`, `tags: [a]`, `context: college`), `#b` no texto, `#c` dentro de bloco de código e os links `[[X]]`, `[[Y|apelido]]`, `[[Z#seção]]` e `![[img.png]]`, quando `parse_note` roda, então title, tags `[a, b]` e links `[X, Y, Z, img.png]` vêm como no contrato.
- **UT-02** — Dado as notas `a/Nota.md`, `b/c/Nota.md` e `Outra.md`, quando `resolve_link` recebe `nota`, `b/c/Nota`, `OUTRA` e `inexistente`, então devolve `a/Nota.md`, `b/c/Nota.md`, `Outra.md` e quebrado.
- **UT-03** — Dado duas notas, uma com o termo no título e outra só no corpo, e uma com "integração", quando `search` pontua "integracao", então a do título vem primeiro e a acentuada é encontrada.
- **UT-04** — Dado uma nota A, uma B com duas tags em comum e link direto para A, e uma C só com termos em comum, quando `related --note A` pontua, então B vem antes de C, A não aparece e os motivos de B citam as tags e o link direto.
- **UT-05** — Dado o `SKILL.md`, quando lido, então descreve `search`, `related` e `links` e em que passo de cada fluxo usar cada um.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault criado pelo `init` (SPEC-0017) com notas em dois contextos, de tipos e tags diferentes, quando roda `search` com e sem `--context`, `--type` e `--tag` e com `--json`, então os resultados respeitam os filtros, o JSON segue o contrato e um termo inexistente imprime "Nenhuma nota encontrada para: …" com exit 0.
- **IT-02** — Dado o mesmo vault, quando roda `related --note <nota>`, `related --text "<trecho>"` e `related --note inexistente.md`, então as duas primeiras listam notas com motivos, em ordem decrescente de pontuação, e a última sai com 2.
- **IT-03** — Dado uma nota com um link para outra nota existente e um link quebrado, e duas notas que apontam para ela, quando roda `links` pelo caminho e pelo nome, então `outgoing`, `backlinks` e `broken` vêm como no contrato.
- **IT-04** — Dado um vault com uma nota de frontmatter inválido, uma em latin-1 e notas em `.obsidian/`, `.trash/` e `templates/`, quando roda `search --json`, então o comando sai com 0, as duas primeiras aparecem em `warnings` e nada das pastas ignoradas aparece.
- **IT-05** — Dado um vault gerado com 5.000 notas de cerca de 1 KB, quando roda `search` e `related`, então cada comando termina em menos de 2 s na CI (medido com `time.monotonic`). É o teste do RNF de desempenho.

### 7.4 Testes de Contrato
- N/A — as filhas que usam estas funções dependem da implementação (`depends_on`), e o contrato fica coberto pelos testes daqui.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração.

### 7.6 Outros
- Desempenho: IT-05.

**Dublês e dados de teste:** vaults temporários gerados pelo `init` da SPEC-0017 e notas sintéticas; `BRAIN_CONFIG_HOME` e `HOME` isolados.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto (comandos novos).
- **Dados/schema:** N/A — só leitura.
- **Compatibilidade:** N/A — primeira versão dos comandos.
- **Observabilidade:** `warnings` no `--json` e `doctor` (SPEC-0017).
- **Rollback:** `git revert` do merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Leitura de notas e links**
- [ ] Red: UT-01, UT-02 com a tag `SPEC-0018:<ID>`, falhando pelo motivo certo
- [ ] Green: `parse_note`, `resolve_link`, `scan_vault`
- [ ] Refactor mantendo tudo verde

**Fase 2: Busca e relações**
- [ ] Red: UT-03, UT-04, IT-01, IT-02, IT-03, IT-04 com a tag `SPEC-0018:<ID>`, falhando pelo motivo certo
- [ ] Green: `search`, `related`, `links` com `--json` e `warnings`
- [ ] Refactor mantendo tudo verde

**Fase 3: Desempenho e instruções**
- [ ] Red: IT-05, UT-05 com a tag `SPEC-0018:<ID>`, falhando pelo motivo certo
- [ ] Green: ajustes de desempenho; `SKILL.md` e `references/search.md`
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `BRAIN_VERSION` e seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado (skill distribuída por cópia)
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — dbf5614 (árvore suja) | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=20)) — 3dbe306 | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0018`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
