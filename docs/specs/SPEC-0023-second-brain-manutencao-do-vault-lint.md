---
id: SPEC-0023
title: "second-brain: manutenção do vault (lint)"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent: SPEC-0016
depends_on: [SPEC-0021]
consumes_contract: []
contract_version: 2
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/maintenance.md, skills/second-brain/references/providers.md, skills/second-brain/references/config.md, skills/second-brain/assets/brain-config.yml, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0008, ADR-0002]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0023 — second-brain: manutenção do vault (lint)

## 1. Visão Geral
O comando `lint` aponta o que está deixando o segundo cérebro pior, sem consertar nada sozinho:
- links quebrados;
- notas órfãs, sem nenhum link e fora de qualquer MOC;
- itens parados na inbox;
- cópias de conflito criadas pela sincronização;
- arquivos citados pelas notas que não existem na pasta `files`;
- notas da skill sem frontmatter válido.

O `SKILL.md` diz ao agente quando rodar o `lint` e como propor cada correção, que só é feita com o sim do usuário.

## 2. Motivação & Escopo
**Motivação:** com várias máquinas, um celular e uma LLM escrevendo, o vault acumula links quebrados, conflitos de sincronização e notas soltas. Sem manutenção, a busca e as relações pioram, e conflitos podem esconder a versão certa de uma nota.

**Objetivos (dentro do escopo):**
- `lint [--json] [--only regra,...]` com as regras do contrato, cada achado com regra, severidade, caminho e sugestão.
- Detecção de cópia de conflito por padrões configuráveis (`conflict_patterns` no `brain-config.yml`). Os padrões da v1 para cada provedor ficam em `references/providers.md`. Um achado só conta quando existe a nota original na mesma pasta.
- `doctor` com uma linha de resumo do `lint` (total por severidade).
- No `SKILL.md`, o fluxo de manutenção: rodar `lint`, explicar os achados, propor correções e aplicar só com o sim do usuário, usando os comandos que só criam e acrescentam (`relate`, `index`).

**Não-objetivos (fora do escopo):**
- Corrigir automaticamente, mesclar conflitos ou apagar cópias (ADR-0007).
- Checar ortografia ou qualidade do conteúdo.
- Rodar o `lint` por agendamento.

## 3. Dependências
- **Implementações necessárias:** SPEC-0021 — `inbox_stale_days` e a classificação de itens da inbox. Inclui por transitividade `scan_vault`, `resolve_link` e `links` (SPEC-0018) e o frontmatter dos tipos (SPEC-0019).
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Segue o `validate` da `sdd-management`: lista de achados com severidade, saída em texto e exit diferente de 0 quando há erro. Reusa `scan_vault` e `resolve_link` (SPEC-0018) e `classify_inbox_item` (SPEC-0021).

**Decisão:** cada regra é uma função `check_<regra>(vault) -> list[Finding]`, registrada num dicionário. `lint` roda todas (ou as de `--only`) sobre uma única varredura do vault.

**Justificativa:** regras independentes são fáceis de testar uma a uma e de estender. Uma varredura só mantém o comando rápido.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** `lint --fix` automático: viola o ADR-0007 e tiraria a decisão do usuário.

**ADRs:** ADR-0007, ADR-0008 e ADR-0002 (aplicados).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `lint` em menos de 3 s num vault com 5.000 notas (IT-03).
- **Segurança:** só leitura (IT-02 confere que nada mudou).
- **Privacidade e dados pessoais:** nada sai da máquina.
- **Disponibilidade e resiliência:** regex inválido em `conflict_patterns` vira um achado `config` e não derruba o comando. A pasta `files` inacessível vira achado `config` e a regra `missing-file` é pulada.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comando `lint`, chave `conflict_patterns`, resumo no `doctor` e fluxo de manutenção no `SKILL.md`.

```text
brain.py lint [--json] [--only regra1,regra2]
  regras (severidade):
    broken-link (error)   — wikilink que não resolve (resolve_link); sugestão: criar a nota ou corrigir o link
    conflict-copy (error) — arquivo que casa com conflict_patterns e cujo original (nome sem o sufixo) existe na
                            mesma pasta; sugestão: comparar com o original e escolher
    missing-file (error)  — caminho em frontmatter.files que não existe em <files>
    orphan (warn)         — nota sem link de entrada nem de saída e fora de qualquer MOC; ignora raw/, inbox/,
                            mocs/, templates/, index.md e log.md
    stale-inbox (warn)    — item da inbox com idade maior que inbox_stale_days
    frontmatter (warn)    — nota com type da skill e sem title ou created, ou com frontmatter que não é lido
    config (error)        — regex inválido em conflict_patterns ou pasta files inacessível
  texto: "<SEVERIDADE> <regra> <caminho> — <detalhe> (sugestão: …)" e um resumo "N erros, M avisos"
  json: {"findings":[{"rule","severity","path","detail","suggestion"}], "summary":{"error":N,"warn":M}}
  exit 0 sem error; 1 com algum error; --only com regra desconhecida: exit 2 com a lista

brain-config.yml:
  conflict_patterns: [<regex sobre o nome do arquivo, com um grupo "base">]
  padrão quando ausente: os padrões do provider da configuração local, documentados em references/providers.md
  (ex.: genéricos "(?P<base>.+) \(\d+\)\.md$" e "(?P<base>.+)[ _-]conflict.*\.md$"); na v1 os quatro provedores
  usam os padrões genéricos, marcados em providers.md como não conferidos com cópias reais (v2); a conferência com
  cópias reais de cada provedor fica para a SPEC-0027

doctor: linha "OK|AVISO|ERRO lint — N erros, M avisos (rode lint)"

SKILL.md — manutenção:
  quando: o usuário pede, ou o doctor mostra achados, ou depois de processar a inbox
  1. lint; 2. explicar os achados por severidade; 3. propor correção por achado (relate, index, nota nova, ou
  orientar o usuário a comparar conflitos); 4. aplicar só com o sim do usuário; nunca apagar arquivo
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Link quebrado | `[[Inexistente]]` | broken-link error | UT-01, IT-01 |
| Conflito com original | `Aula.md` e `Aula (1).md` | conflict-copy error | UT-02, IT-01 |
| Sufixo sem original | `Aula 2.md` sem `Aula.md` | nenhum achado | UT-02 |
| Arquivo ausente | `files: [college/2026/x.pdf]` inexistente | missing-file error | UT-03, IT-01 |
| Órfã | nota sem links e fora de MOC | orphan warn | UT-04, IT-01 |
| Pastas ignoradas | órfãs em `raw/` e `inbox/` | nenhum achado | UT-04 |
| Inbox parada | item mais velho que o limite | stale-inbox warn | IT-01 |
| Frontmatter | nota da skill sem `created` | frontmatter warn | IT-01 |
| Regex inválido | `conflict_patterns: ["("]` | config error, demais regras rodam | IT-04 |
| files inacessível | pasta sem permissão | config error, missing-file pulada | IT-04 |
| Só leitura | `lint` | nenhum arquivo muda | IT-02 |
| Vault limpo | sem achados | "0 erros, 0 avisos", exit 0 | IT-02 |
| `--only` | `--only broken-link` e regra desconhecida | só a regra; exit 2 | IT-02 |
| Doctor | vault com achados | linha de resumo | IT-05 |
| Instruções | `SKILL.md`, `providers.md` | fluxo de manutenção; padrões por provedor | UT-05 |
| Desempenho | 5.000 notas | menos de 3 s | IT-03 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — código novo; as funções reusadas têm testes nas SPEC-0018 e SPEC-0021.

### 7.2 Testes Unitários
- **UT-01** — Dado notas com `[[Existe]]`, `[[existe#seção]]` e `[[Inexistente]]`, quando `check_broken_link` roda, então só `[[Inexistente]]` é achado.
- **UT-02** — Dado os pares `Aula.md` + `Aula (1).md`, `Plano.md` + `Plano conflict 2026-10-30.md` e um `Aula 2.md` sozinho, com os padrões genéricos, quando `check_conflict_copy` roda, então os dois primeiros são achados e o terceiro não.
- **UT-03** — Dado uma nota com `files: [college/2026/a.pdf, college/2026/b.pdf]` e só `a.pdf` na pasta `files`, quando `check_missing_file` roda, então só `b.pdf` é achado.
- **UT-04** — Dado uma nota sem links e fora de MOC, uma citada num MOC, uma com um backlink e notas soltas em `raw/` e `inbox/`, quando `check_orphan` roda, então só a primeira é achada.
- **UT-05** — Dado o `SKILL.md` e `references/providers.md`, quando lidos, então o `SKILL.md` tem os quatro passos de manutenção e a regra de nunca apagar, e `providers.md` tem os padrões de conflito de cada provedor da v1 com a data da conferência.

### 7.3 Testes de Integração
- **IT-01** — Dado um vault criado pelo `init` com um exemplo de cada regra (link quebrado, conflito, arquivo ausente, órfã, item de inbox com 10 dias, nota sem `created`), quando roda `lint --json`, então há um achado por regra com a severidade do contrato, o resumo conta 3 erros e 3 avisos e o exit é 1.
- **IT-02** — Dado o mesmo vault, quando roda `lint`, então nenhum arquivo do vault nem da pasta `files` tem conteúdo ou data de modificação alterados; `lint --only broken-link` mostra só essa regra; `--only foo` sai com 2; e num vault limpo imprime "0 erros, 0 avisos" com exit 0.
- **IT-03** — Dado um vault gerado com 5.000 notas, quando roda `lint`, então termina em menos de 3 s. É o teste do RNF de desempenho.
- **IT-04** — Dado `conflict_patterns: ["("]` e, em outro caso, a pasta `files` sem permissão de leitura, quando roda `lint --json`, então aparece um achado `config` em cada caso e as demais regras continuam rodando (no segundo, sem `missing-file`).
- **IT-05** — Dado o vault do IT-01, quando roda `doctor`, então aparece a linha "ERRO lint — 3 erros, 3 avisos (rode lint)" e o exit do `doctor` é 1.

### 7.4 Testes de Contrato
- N/A — sem contrato consumido.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração. As correções propostas são do agente e seguem o `SKILL.md` (UT-05).

### 7.6 Outros
- Desempenho: IT-03.

**Dublês e dados de teste:** vaults temporários com cópias de conflito sintéticas, seguindo os nomes documentados em `providers.md`; `BRAIN_CONFIG_HOME` e `HOME` isolados.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto.
- **Dados/schema:** chave nova opcional `conflict_patterns`; sem ela, valem os padrões do provedor.
- **Compatibilidade:** o `doctor` ganha uma linha; o exit dele passa a ser 1 quando o `lint` tem erro (documentado no CHANGELOG da skill).
- **Observabilidade:** o próprio `lint` e a linha no `doctor`.
- **Rollback:** `git revert` do merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
Nenhuma

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Regras**
- [ ] Red: UT-01, UT-02, UT-03, UT-04 com a tag `SPEC-0023:<ID>`, falhando pelo motivo certo
- [ ] Green: `check_*` e registro das regras; padrões de conflito conferidos e documentados em `providers.md`
- [ ] Refactor mantendo tudo verde

**Fase 2: Comando e doctor**
- [ ] Red: IT-01, IT-02, IT-03, IT-04, IT-05 com a tag `SPEC-0023:<ID>`, falhando pelo motivo certo
- [ ] Green: `lint` com `--json` e `--only`; linha no `doctor`
- [ ] Refactor mantendo tudo verde

**Fase 3: Instruções**
- [ ] Red: UT-05 com a tag `SPEC-0023:<ID>`, falhando pelo motivo certo
- [ ] Green: fluxo de manutenção no `SKILL.md` e `maintenance.md`
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
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=23)) — 9f2b536 | 2026-10-30 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 5556f65 | 2026-10-30 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 5556f65 | 2026-10-30 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (5556f65; 6 minor; padrões de conflito genéricos = desvio do contrato a registrar em emenda) — 5556f65 | 2026-10-30 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 84241ab | 2026-10-30 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-10-30 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-10-30 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0023`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-10-30 | Padrão de conflito por provedor: na v1, genéricos para os quatro provedores, marcados como não conferidos; a conferência com cópias reais passa para a SPEC-0027 | Revisão G4: não dá para gerar cópias de conflito reais dos provedores nesta máquina; precisa de aparelhos do usuário | Nenhuma (nenhuma spec consome o contrato da SPEC-0023) | |
