---
id: SPEC-0040
title: "org-atlas: modo repositório com scan agendado e modo local"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-10-30
parent: SPEC-0029
depends_on: [SPEC-0039]
consumes_contract: []
contract_version: 1
touches: [skills/org-atlas/SKILL.md, skills/org-atlas/scripts/atlas.py, skills/org-atlas/references/modes.md, skills/org-atlas/assets/ci/**, skills/org-atlas/assets/atlas-config.yml, skills/org-atlas/tests/test_vendor.py, skills/org-atlas/CHANGELOG.md]
adrs: [ADR-0010]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0040 — org-atlas: modo repositório com scan agendado e modo local

## 1. Visão Geral
Fecha o ciclo de envelhecimento nos dois modos do atlas:
- **Modo repositório:** `atlas.py vendor --ci github` instala no repositório do atlas um workflow agendado. Ele roda `scan` e `lint` e, quando algo mudou, **abre um PR com o diff** ("serviço novo", "fila nova"); a aprovação desse PR também confirma as convenções que ele muda (ADR-0012). `vendor --ci generic` gera um script para qualquer outra CI.
- **Modo local:** sem CI, quem garante é o aviso de envelhecimento (SPEC-0038); `references/modes.md` explica como agendar com cron ou `/schedule` e como migrar para o modo repositório.

## 2. Motivação & Escopo
**Motivação:** a skill detecta e avisa sozinha, mas não roda sozinha, porque não tem relógio (SPEC-0029). No modo repositório, a CI vira o relógio e o PR vira a revisão.

**Objetivos (dentro do escopo):**
- `vendor --ci github|generic [--schedule CRON] [--force]`, com modelos em `assets/ci/`.
- Chave `ci.env` no `atlas-config.yml`: os **nomes** das variáveis que o workflow recebe dos secrets da plataforma (o valor fica no cofre da plataforma, nunca no atlas).
- Workflow do GitHub Actions: agenda (padrão semanal), `scan`, `lint`, branch e PR quando há mudança, e `lint` também em todo PR do atlas.
- `references/modes.md`: os dois modos, agendamento local e migração local → repositório (`git remote add` e `mode: repo`).

**Não-objetivos (fora do escopo):**
- Modelos para GitLab CI e outras plataformas além do `generic`: entram com os coletores e guias de cada provedor.
- Mudar de modo por comando: é uma linha no `atlas-config.yml`, documentada.

## 3. Dependências
- **Implementações necessárias:** SPEC-0039 — o workflow roda o `lint` (e, por ela, o `scan` e o `curate` das filhas anteriores).
- **Contratos consumidos:** N/A.
- **Pré-requisitos externos:** no uso real, um repositório do atlas no GitHub com os secrets das variáveis de `ci.env`.

## 4. Decisão Arquitetural
**Contexto:** a referência é o `vendor --ci` da `sdd-management` (`skills/sdd-management/scripts/spec_graph.py`, ADR-0001): copia um modelo de workflow, mantém o que o projeto customizou (mostrando quantas linhas diferem) e só sobrescreve com `--force`.

**Decisão:** mesmo comportamento. O workflow (e não o `atlas.py`) chama `gh pr create`; o `atlas.py` só escreve arquivos (ADR-0010).

**Justificativa:** comportamento conhecido e testado; o `atlas.py` continua sem chamar CLI de plataforma.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** o próprio `atlas.py` abrir o PR (quebraria o ADR-0010); commit direto na branch principal do atlas (sem revisão, contra a curadoria do ADR-0012).

**ADRs:** ADR-0010.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — custo é o tempo dos coletores na CI.
- **Segurança:** o workflow tem permissões mínimas (`contents: write`, `pull-requests: write`), ações fixadas por SHA como na CI do repositório, e as credenciais só pelos secrets da plataforma.
- **Privacidade e dados pessoais:** N/A — mesmos dados do `scan`.
- **Disponibilidade e resiliência:** coletor falhando na CI → o PR (ou o log, sem mudanças) mostra a falha; o `lint` com ERRO falha o job.
- **Acessibilidade (UI):** N/A.
- **Custo:** minutos de CI de um job semanal.

## 6. Artefato A — Contrato
**Interface:** comando `vendor`, chave `ci` e os arquivos gerados.

```text
atlas-config.yml:
  ci:
    env: [GH_TOKEN, ARGOCD_AUTH_TOKEN]     # só nomes; o valor fica nos secrets da plataforma
    schedule: "0 6 * * 1"                  # padrão: segunda 06:00 UTC

atlas.py vendor --ci github|generic [--schedule CRON] [--force]
  github:  .github/workflows/atlas-scan.yml — schedule + workflow_dispatch: scan, lint, branch atlas/scan-AAAA-MM-DD
           e gh pr create quando há mudança; pull_request: lint
           cada nome de ci.env vira uma entrada env NOME lida do secret de mesmo nome (expressão secrets.NOME do Actions)
  generic: ci/atlas-scan.sh — roda scan e lint; exit 0 sem mudança, 10 com mudança (para a CI decidir), 1 com falha
  arquivo existente igual: "já atualizado"; diferente sem --force: mantido, "customizado — N linha(s) diferem;
           use --force para sobrescrever"; com --force: sobrescrito
  mode: local: exit 2 "vendor --ci é do modo repo — veja references/modes.md"
  nome em ci.env fora de ^[A-Z_][A-Z0-9_]*$: exit 2
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Workflow do GitHub | `vendor --ci github` | arquivo com agenda, env dos secrets e passos | UT-01, IT-01 |
| Script genérico | `vendor --ci generic` | script com os códigos de saída do contrato | IT-03 |
| Arquivo customizado | workflow diferente do modelo | mantido sem `--force`; sobrescrito com `--force` | IT-02 |
| Modo local | `mode: local` | exit 2 | IT-02 |
| Nome inválido | `ci.env` com valor de segredo | exit 2 | UT-02 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — comando novo.

### 7.2 Testes Unitários
- **UT-01** — Dado `ci.env` e `--schedule`, quando o workflow é gerado, então tem a agenda, um `env` por nome lendo de `secrets`, permissões mínimas e ações fixadas por SHA.
- **UT-02** — Dado `ci.env` com um valor que não é nome de variável, quando a configuração é validada, então sai com 2.

### 7.3 Testes de Integração
- **IT-01** — `vendor --ci github` pela CLI num atlas no modo `repo` cria `.github/workflows/atlas-scan.yml`; rodar de novo diz "já atualizado".
- **IT-02** — Com o workflow alterado à mão, `vendor` mantém o arquivo e mostra quantas linhas diferem; com `--force`, sobrescreve; num atlas `mode: local`, sai com 2.
- **IT-03** — O `ci/atlas-scan.sh` gerado, rodado num atlas git com coletor falso, sai com 10 quando o coletor muda a saída e com 0 quando não muda.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs.

### 7.5 Testes E2E
- N/A — a execução real do workflow depende de um repositório na plataforma; o conteúdo do workflow é coberto por UT-01 e o comportamento do script por IT-03.

### 7.6 Outros
- O workflow gerado passa no `actionlint` na revisão, se disponível.

**Dublês e dados de teste:** atlas temporário com `git init` e coletor falso.

**Ambiente de execução:** local e CI (precisa de `git`), sem rede.

## 8. Plano de Rollout
- **Estratégia:** deploy direto; o workflow só existe no atlas que rodar `vendor`.
- **Dados/schema:** chave `ci` nova, opcional.
- **Compatibilidade:** N/A.
- **Observabilidade:** execuções do workflow e os PRs de scan no repositório do atlas.
- **Rollback:** apagar o workflow do atlas ou reverter o PR.
- **Etapas de migração/coexistência:** local → repositório documentado em `references/modes.md`.

## 9. Questões em Aberto
- [x] Onde fica o atlas — repositório próprio da organização como preferido, modo local também suportado (thomas, 2026-10-30)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 81b467c (árvore suja) | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0040`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
