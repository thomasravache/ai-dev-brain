---
id: SPEC-0020
title: "second-brain: fluxo de consultar"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0019]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/query-flow.md, skills/second-brain/references/note-types.md, skills/second-brain/assets/templates/**, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0002]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0020 — second-brain: fluxo de consultar

## 1. Visão Geral
Implementa o fluxo padrão para perguntar ao segundo cérebro ("o que eu sei sobre X", "me prepara para a P2 de Cálculo II"). O comando `context` monta, num único pacote, as notas que respondem à pergunta: os resultados da busca, as notas ligadas a eles e o MOC do contexto. Assim o agente lê o necessário sem varrer o vault. O `SKILL.md` define os quatro passos: buscar, ler e seguir links, responder citando as notas e apontando lacunas, e oferecer salvar a resposta como nota `answer`.

## 2. Motivação & Escopo
**Motivação:** o segundo cérebro só tem valor se a consulta for rápida e confiável. A resposta precisa vir das suas notas, com citação, e não da memória do modelo. Cada consulta também pode enriquecer o vault.

**Objetivos (dentro do escopo):**
- `context QUERY`: pacote com as notas mais relevantes (`search`), os vizinhos por link até `--hops` passos, e o MOC quando a busca é filtrada por contexto, com limite de tamanho (`--max-chars`).
- Tipo de nota `answer` (modelo com pergunta, resposta, notas citadas e lacunas), salvo pelo `new-note` da SPEC-0019.
- No `SKILL.md`, o fluxo de consultar e as regras de resposta: citar `[[nota]]` para cada afirmação vinda do vault, separar o que vem do vault do que é conhecimento geral, apontar lacunas.

**Não-objetivos (fora do escopo):**
- Gerar a resposta: isso é com o agente.
- Busca semântica por embeddings (ver SPEC-0018).
- Exportar para o NotebookLM (SPEC-0024).

## 3. Dependências
- **Implementações necessárias:** SPEC-0019 — `new-note` e os modelos, para o tipo `answer`. Inclui por transitividade `search`, `related` e `links` (SPEC-0018).
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Reusa `scan_vault`, `search` e `resolve_link` (SPEC-0018) e `new-note` (SPEC-0019). Segue a saída texto/`--json` dos outros comandos.

**Decisão:** `build_context(query, filtros, hops, limit, max_chars)` faz a busca, expande os vizinhos em largura (links de saída e backlinks) até `hops` passos e ordena: resultados da busca pela pontuação, depois vizinhos pela distância. Corta pelo `max_chars`: as notas entram inteiras enquanto couberem, e as que não couberem entram só com título e caminho em `omitted`.

**Justificativa:** um comando entrega ao agente o recorte certo do vault, com tamanho previsível, em qualquer ferramenta.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** o agente encadear `search` e `links` sozinho funciona, mas cada agente faria de um jeito e com custo de tokens imprevisível.

**ADRs:** ADR-0007 e ADR-0002 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `context` em menos de 2 s num vault com 5.000 notas (IT-04).
- **Segurança:** só leitura.
- **Privacidade e dados pessoais:** nada sai da máquina; o pacote vai para a saída do terminal, lida pelo agente.
- **Disponibilidade e resiliência:** link quebrado no meio da expansão é ignorado e listado em `broken`.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** `--max-chars` (padrão 40.000) limita o que o agente lê, e com isso os tokens gastos por consulta.

## 6. Artefato A — Contrato
**Interface:** comando `context`, tipo `answer` e fluxo de consultar no `SKILL.md`.

```text
brain.py context QUERY [--context C] [--hops N=1] [--limit N=8] [--max-chars N=40000] [--json]
  1. search QUERY (com --context) → até --limit notas
  2. com --context, o MOC do contexto entra primeiro
  3. vizinhos (links de saída e backlinks) até --hops passos, sem repetir nota
  4. ordem: MOC, resultados da busca por pontuação, vizinhos por distância e depois título
  5. notas inteiras até somar --max-chars; as demais vão para omitted
  texto: para cada nota "=== <caminho> (<motivo>) ===" e o conteúdo; no fim "Omitidas:" e "Links quebrados:"
  json: {"query":..., "notes":[{"path","title","reason":"search:<pontos>"|"moc"|"link:<distância>","content"}],
         "omitted":[{"path","title","reason"}], "broken":[...]}
  nada encontrado: "Nenhuma nota encontrada para: QUERY", exit 0
  --hops fora de 0..2: exit 2

Tipo answer — modelo templates/answer.md:
  frontmatter: type: answer, title, context, created, question, cites: [<títulos das notas citadas>]
  corpo: "# {title}", "## Question", "## Answer", "## Gaps", "## Relations"

SKILL.md — fluxo de consultar:
  1. Buscar: context QUERY (com --context quando a pergunta é de um contexto)
  2. Ler e seguir links: ler o pacote; se faltar, related/links nas notas centrais
  3. Responder: cada afirmação vinda do vault cita [[nota]]; o que vier de conhecimento geral é marcado como tal;
     apontar lacunas (o que a pergunta pede e o vault não tem)
  4. Oferecer salvar: com o sim do usuário, new-note --type answer e relate com as notas citadas, depois index
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Pacote básico | pergunta com resultados | notas da busca com conteúdo e motivo | UT-01, IT-01 |
| Vizinhos | `--hops 1` e `--hops 2` | inclui vizinhos até a distância, sem repetir | UT-01, IT-01 |
| MOC do contexto | `--context college` | MOC primeiro | IT-01 |
| Limite de tamanho | `--max-chars` pequeno | notas que não cabem em `omitted` | UT-02 |
| Link quebrado | vizinho inexistente | listado em `broken`, sem erro | UT-01 |
| Nada encontrado | termo inexistente | mensagem e exit 0 | IT-02 |
| hops inválido | `--hops 3` | exit 2 | IT-02 |
| Salvar resposta | `new-note --type answer` + `relate` | nota answer ligada às citadas | IT-03 |
| Instruções | `SKILL.md` | quatro passos e regras de citação | UT-03 |
| Desempenho | 5.000 notas | menos de 2 s | IT-04 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — código novo.

### 7.2 Testes Unitários
- **UT-01** — Dado notas A (resultado da busca) → B → C e D → A, e A com link para uma nota inexistente, quando `build_context` roda com `hops=1` e `hops=2`, então com 1 vêm A, B e D; com 2 vem também C; nenhuma se repete; e a inexistente aparece em `broken`.
- **UT-02** — Dado três notas de 1.000 caracteres e `max_chars=2500`, quando `build_context` roda, então duas vão em `notes` e a terceira em `omitted`, com título e motivo.
- **UT-03** — Dado o `SKILL.md` e o modelo `assets/templates/answer.md`, quando lidos, então o fluxo de consultar tem os quatro passos na ordem do contrato, manda citar `[[nota]]` e apontar lacunas, e o modelo tem as seções `Question`, `Answer`, `Gaps` e `Relations`.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault com o contexto `college`, o MOC dele e notas ligadas, quando roda `context "integrais" --context college --hops 1 --json`, então o MOC vem primeiro, seguem os resultados da busca e os vizinhos, e o JSON segue o contrato.
- **IT-02** — Dado o mesmo vault, quando roda `context "termo-inexistente"` e `context x --hops 3`, então o primeiro imprime "Nenhuma nota encontrada para: …" com exit 0 e o segundo sai com 2.
- **IT-03** — Dado o vault do IT-01, quando roda `new-note --type answer --title "P2 de Cálculo II" --context college`, `relate "P2 de Cálculo II" "Integrais por partes" --why "cita" --both` e `index --context college`, então a nota answer existe com as seções do modelo, as duas notas se citam e o MOC lista a answer. É o critério de aceite "consultar" do épico.
- **IT-04** — Dado um vault gerado com 5.000 notas, quando roda `context` com `--hops 2`, então termina em menos de 2 s. É o teste do RNF de desempenho.

### 7.4 Testes de Contrato
- N/A — sem contrato consumido.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração. A resposta citando notas é do agente e segue o `SKILL.md` (UT-03).

### 7.6 Outros
- Desempenho: IT-04.

**Dublês e dados de teste:** vaults temporários criados pelo `init` e pelas notas da SPEC-0019; `BRAIN_CONFIG_HOME` e `HOME` isolados.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto (comando e tipo novos).
- **Dados/schema:** tipo `answer` acrescentado a `note-types.md`; vaults já criados recebem o modelo ao rodar `init` de novo (só cria o que falta) ou usam o modelo da skill.
- **Compatibilidade:** N/A — primeira versão.
- **Observabilidade:** N/A — só leitura; a nota answer salva aparece no `log.md` pelo `new-note`.
- **Rollback:** `git revert` do merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Pacote de contexto**
- [ ] Red: UT-01, UT-02, IT-01, IT-02, IT-04 com a tag `SPEC-0020:<ID>`, falhando pelo motivo certo
- [ ] Green: `build_context` e comando `context`
- [ ] Refactor mantendo tudo verde

**Fase 2: Tipo answer e instruções**
- [ ] Red: IT-03, UT-03 com a tag `SPEC-0020:<ID>`, falhando pelo motivo certo
- [ ] Green: modelo `answer`, fluxo de consultar no `SKILL.md`, `query-flow.md`
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=11)) — b3ba61e | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0020`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
