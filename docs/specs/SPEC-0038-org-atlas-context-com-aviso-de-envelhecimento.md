---
id: SPEC-0038
title: "org-atlas: context com aviso de envelhecimento"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0036]
consumes_contract: [SPEC-0037@1]
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/context.md, skills/org-atlas/tests/test_context.py, skills/org-atlas/tests/fixtures/context/**, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010, ADR-0012]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0038 — org-atlas: context com aviso de envelhecimento

## 1. Visão Geral
Implementa o `atlas.py context QUERY`: o comando que as outras skills e o agente chamam. Para uma tarefa ("feature de cashout no backoffice"), ele monta um pacote só de leitura com:
- os serviços certos e o que está ligado a eles (repositório, deployments por ambiente, bancos, filas, outros serviços), até N passos no grafo;
- as convenções `confirmed` que valem para esses serviços, e as `inferred` separadas como **dica**;
- no topo, um **aviso de envelhecimento** quando algum coletor passou do `stale_days` ou falhou no último scan.

## 2. Motivação & Escopo
**Motivação:** é por aqui que o atlas chega a quem implementa (SPEC-0029). Um pacote pequeno e certo evita colocar o atlas inteiro no contexto do agente, e o aviso impede que ele decida com informação velha sem saber.

**Objetivos (dentro do escopo):**
- `context QUERY [--hops 0..2] [--limit N] [--max-chars N] [--json]`, na mesma linha do `context` da `second-brain` (SPEC-0020).
- Busca por termos no nome, no id, nos atributos e nas notas das páginas; vizinhos por aresta até `--hops` (padrão 1).
- Aviso de envelhecimento a partir do `_scan.json` e do `stale_days`.
- Instrução no `SKILL.md`: sempre rodar o `context` antes de responder sobre a organização, citar as páginas e repassar o aviso ao usuário.
- `references/context.md` com o formato do pacote.

**Não-objetivos (fora do escopo):**
- Rodar o `scan` sozinho quando o atlas está velho: o agente oferece, o usuário decide.
- Busca semântica ou por embeddings.

## 3. Dependências
- **Implementações necessárias:** SPEC-0036 — `graph.json` e páginas.
- **Contratos consumidos:** SPEC-0037@1 — formato dos arquivos de convenção (status e escopo).
- **Pré-requisitos externos:** N/A.

## 4. Decisão Arquitetural
**Contexto:** a referência é o `context` da `second-brain` (`skills/second-brain/scripts/brain.py`, SPEC-0020): busca por termos com pontuação, vizinhos por link até `--hops`, limite de caracteres com itens omitidos listados, mensagem fixa e exit 0 quando nada é encontrado.

**Decisão:** mesmo desenho sobre o `graph.json`; o aviso de envelhecimento é sempre a primeira seção do pacote quando existe.

**Justificativa:** comportamento já conhecido pelo agente e pelo usuário, e testado na outra skill.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** devolver o `ATLAS.md` inteiro (grande demais e sem foco); esconder as convenções `inferred` (perderia dica útil; ficam separadas e marcadas).

**ADRs:** ADR-0010, ADR-0012.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** menos de 1 s num atlas com 500 serviços.
- **Segurança:** só leitura.
- **Privacidade e dados pessoais:** N/A — só o que já está no atlas.
- **Disponibilidade e resiliência:** atlas sem scan → pacote vazio com o aviso "atlas ainda sem scan — rode scan".
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comando `context` e o formato do pacote (consumido pela `sdd-management` na SPEC-0041).

```text
atlas.py context QUERY [--hops 0..2 (padrão 1)] [--limit N (padrão 8)] [--max-chars N (padrão 30000)] [--json]
  pacote em Markdown (ou JSON):
    ## Aviso de envelhecimento   (só quando há): "Atlas com D dias desde o último scan de: A, B (stale_days: 14)"
                                 e "Último scan falhou: C"
    ## Serviços                  por serviço encontrado: página, repositório, deployments por ambiente, donos
    ## Dependências              arestas até --hops, com tipo, "inferida" quando for e a evidência
    ## Convenções (regra)        as confirmed do escopo organization e dos repositórios dos serviços
    ## Convenções (dica)         as inferred do mesmo escopo, marcadas "não confirmada"
    ## Omitidos                  o que não coube em --max-chars
  nada encontrado: "Nada encontrado no atlas para: QUERY" e exit 0 (com o aviso, se houver)
  --hops fora de 0..2: exit 2; sem configuração: exit 3
  convenções rejected nunca aparecem
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Tarefa com serviço conhecido | termo bate com um serviço | serviço, dependências e convenções do escopo | UT-01, IT-01 |
| Vizinhos | `--hops 0`, `1`, `2` | só o nó, vizinhos diretos, dois passos | UT-02 |
| Convenções | confirmed, inferred e rejected no escopo | regra, dica e nada, nessa ordem | UT-03, CT-01 |
| Atlas velho | coletor com `seen_at` além de `stale_days` ou falha | aviso no topo | UT-04, IT-02 |
| Limite | pacote maior que `--max-chars` | itens omitidos listados | UT-05 |
| Nada encontrado | termo inexistente | mensagem fixa e exit 0 | IT-01 |
| Argumento inválido | `--hops 3` | exit 2 | IT-01 |
| Jornada | init → scan → curate confirm → context | pacote com o serviço, o banco e a convenção confirmada | IT-03 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado um grafo de exemplo, quando a busca roda com "cashout backoffice", então o serviço `backoffice` vem primeiro, com pontuação e motivo.
- **UT-02** — Dado `--hops` 0, 1 e 2, quando os vizinhos são coletados, então o pacote tem só o nó, os vizinhos diretos e os de dois passos.
- **UT-03** — Dado convenções `confirmed`, `inferred` e `rejected` no escopo, quando o pacote é montado, então aparecem em "regra", "dica" e nenhuma seção.
- **UT-04** — Dado um `_scan.json` com um coletor de 20 dias e outro com `status: failed`, com `stale_days: 14`, quando o aviso é calculado, então cita os dois.
- **UT-05** — Dado um pacote maior que `--max-chars`, quando é montado, então os itens que não cabem vão para "Omitidos".

### 7.3 Testes de Integração
- **IT-01** — `context` pela CLI num atlas de fixture: termo conhecido gera o pacote; termo inexistente imprime a mensagem fixa e sai com 0; `--hops 3` sai com 2.
- **IT-02** — Com o `_scan.json` antigo, o pacote começa pelo aviso de envelhecimento.
- **IT-03** — Jornada pela CLI: `init`, `scan` com os coletores falsos de GitHub, Argo CD e um fato `generic` de banco, `curate confirm` de uma convenção e `context "<serviço>"` trazem o serviço, o banco como dependência inferida e a convenção como regra.

### 7.4 Testes de Contrato
- **CT-01** — O `context` lê os arquivos de convenção no formato da SPEC-0037@1 (fixtures geradas pelo `curate` da SPEC-0037) e separa os três status.

### 7.5 Testes E2E
- N/A — sem jornada de usuário em interface; a jornada da CLI usada pelo agente é o IT-03.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** atlas de fixture e coletores falsos das SPEC-0034 e SPEC-0035.

**Ambiente de execução:** local e CI, sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto.
- **Dados/schema:** N/A — só leitura.
- **Compatibilidade:** formato do pacote documentado em `references/context.md`.
- **Observabilidade:** N/A.
- **Rollback:** reverter o PR.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 80ff4f8 (árvore suja) | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0038`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
