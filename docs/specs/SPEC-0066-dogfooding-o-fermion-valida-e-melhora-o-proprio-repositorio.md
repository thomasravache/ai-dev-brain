---
id: SPEC-0066
title: "Dogfooding: o Fermion valida e melhora o próprio repositório"
tier: epic
type: feature
status: implemented
created: 2026-11-16
depends_on: []
adrs: [ADR-0019]
external: []
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0066 — Dogfooding: o Fermion valida e melhora o próprio repositório (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0066`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

> **Radar (2026-11-16):** pedido do thomas: medir se o repositório escreve código de qualidade com a arquitetura mais eficaz para o que entrega, usando o próprio Fermion para se validar e se melhorar. Diagnóstico inicial (2026-11-16), a detalhar antes do G0:
> - **Não usamos o que entregamos:** as sessões neste repositório carregam a cópia antiga `~/.claude/skills/sdd-management` (2026.10.12), não a `gluon-spec` do repositório (2026.11.3); o plugin `fermion` não está instalado; `tools/sdd/` está em 2026.11.1 (`whats-new` mostra duas versões atrasadas).
> - **Pilares no perfil mínimo,** com `segredos-dados` dispensado por "não usamos credenciais nem dados pessoais", o que deixou de ser verdade (notas confidenciais, servidor MCP com dados pessoais, probes da SPEC-0030). Sem documentos vivos (`living_docs`: mapa do sistema e jornadas).
> - **Arquitetura:** três scripts de 3,5 mil a 4,5 mil linhas (ADR-0001: um arquivo só, stdlib, instalável por cópia). Funções em geral pequenas (só 4 acima de 100 linhas, quase todas `main`), mas sem métrica de cobertura, complexidade ou tamanho no CI.
> - **Sem uso cruzado:** a `boson-atlas` não mapeia este repositório e a `photon-brain` não guarda as decisões do projeto.
> - **Retrospectiva dos projetos feitos com o Fermion (pedido do thomas, 2026-11-16):** medir o que está sendo seguido e o que não está nos projetos reais, não só neste repositório. Levantamento inicial: 5 projetos pessoais (`juker`, `jogo-da-velha-multiplayer`, `video-downloader`, `video-downloader-ci-title`, `crash-games-provider`; 181 specs, 105 implementadas, 28 emendas e só 1 gate FAIL registrado no total, todos com `tools/sdd` em 2026.09.x e sem commit desde outubro) e os projetos em modo privado do registro `~/.config/sdd/projects.json`. Sinais a investigar: specs paradas em `proposed`/`approved`, gates quase nunca reprovados (rigor real ou gate registrado sem evidência gerada?), N/A recorrentes, emendas e impedimentos por spec, ordem red→green, tempo de H1 até `implemented` e atraso de versão da ferramenta.
> Filhas candidatas: (1) usar o plugin e a `gluon-spec` atuais no próprio desenvolvimento; (2) pilares no perfil padrão, revisão das dispensas e documentos vivos; (3) métricas de qualidade no CI (cobertura, complexidade, orçamento de tamanho) e ADR avaliando a divisão dos scripts sem perder a instalação por cópia; (4) atlas do próprio repositório; (5) ciclo de auto-melhoria agendado; (6) retrospectiva entre projetos: um comando só de leitura (ex.: `spec_graph.py retro <pastas>`, inclusive `spec_root` do modo privado) com as métricas acima e um relatório com o que ajustar no processo e na skill (doctor, `whats-new`, `validate`, `pillars`) que propõe specs, sem aplicar nada sozinho (ADR-0019).

## 1. Visão
O Fermion passa a se medir com as próprias ferramentas. Ele mostra o que o processo SDD está seguindo de verdade nos projetos que o usam e usa isso para melhorar a skill e este repositório. O resultado técnico é um ciclo repetível: medir, achar o que não é seguido, propor specs e o humano decidir. Nada é alterado sozinho (ADR-0019).

## 2. Escopo
**Objetivos (dentro do escopo):**
- **Retrospectiva entre projetos (SPEC-0074):** comando só de leitura com métricas de fluxo, rigor dos gates, evidência, N/A, emendas e impedimentos, mais achados com o que fazer. É a primeira filha porque dá os dados para priorizar as outras e a SPEC-0065.
- As demais frentes do radar entram como filhas depois do primeiro relatório real, cada uma com H1 próprio:
  1. Usar o plugin e a `gluon-spec` atuais no próprio desenvolvimento.
  2. Pilares no perfil padrão e documentos vivos.
  3. Métricas de qualidade no CI.
  4. Atlas do próprio repositório.
  5. Ciclo agendado.

**Não-objetivos (fora do escopo):**
- Corrigir os projetos analisados. Cada projeto decide o que fazer com o relatório.
- Mudar o comportamento do `gate`, por exemplo para guardar o histórico de FAIL, antes que a retrospectiva confirme o problema com dados.
- Atualização automática de qualquer coisa (ADR-0019).

## 3. Arquitetura Alvo
**Contexto:** projeto existente. Três skills de um script cada, stdlib, instaláveis por cópia (ADR-0001), plugin `fermion` com MCP fino sobre as CLIs (ADR-0016, ADR-0017) e auto-melhoria que só lê e avisa (ADR-0019). Não muda arquitetura: type feature.

O ciclo funciona assim:
1. A `gluon-spec` ganha `retro`, que lê `docs/specs` e os `spec_root` do modo privado e gera um relatório em Markdown ou JSON.
2. O relatório aponta o que ajustar na skill.
3. O humano transforma as sugestões em specs pelo fluxo normal.

As filhas seguintes consomem o relatório, não um contrato de código.

**Decisões (ADRs):** ADR-0019 — auto-melhoria só lê e avisa; o relatório sugere specs e nunca as cria

**Regras de arquitetura a garantir (G3):** as regras atuais de `skills/gluon-spec/tests/architecture_rules.py` (script único, stdlib, Python 3.9+); a SPEC-0074 prova por teste de integração que o `retro` não altera os projetos lidos

## 4. Decomposição
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0074 | gluon-spec: retrospectiva entre projetos (spec_graph.py retro) | full | feature | M | — | — |
| SPEC-0078 | gluon-spec: ajustes do processo apontados pela primeira retrospectiva | full | feature | M | SPEC-0074 | — |

## 5. Estratégia de Entrega
- **Ambientes:** N/A — skills distribuídas por cópia e pelo plugin, sem deploy
- **Entrega por onda:** onda 1: SPEC-0074 no plugin. Depois do merge, a primeira execução real nos projetos desta máquina alimenta as próximas filhas.
- **Feature flags:** N/A — comando novo e opt-in
- **Rollback:** `git revert` do merge de cada filha
- **Métricas de sucesso pós-release:** a primeira retrospectiva real roda sem erro nos 25 projetos e gera pelo menos uma spec decidida pelo thomas.

## 6. Riscos & Mitigações
- **Expor conteúdo de projetos privados de terceiros:** o relatório traz só nomes, IDs e números, provado por teste (SPEC-0074:UT-04).
- **Métrica enganosa,** por exemplo FAIL apagado pelo PASS: o histórico de reprovações vem do git (SPEC-0074:UT-02), e os limites das regras são revisados com dados reais por emenda.
- **Alterar um projeto lido sem querer:** o comando só lê, o git roda só com `log` e sem lock, e o estado é comparado antes e depois (SPEC-0074:IT-01).

## 7. Critérios de Aceite do Épico
- [x] A retrospectiva roda nos projetos públicos e privados sem alterar nenhum deles — SPEC-0074:IT-01
- [x] Os achados e as sugestões para a skill seguem as regras documentadas — SPEC-0074:UT-03
- [x] O relatório não expõe títulos nem textos dos projetos — SPEC-0074:UT-04

## 8. Questões em Aberto
- [x] Qual frente começa? — a retrospectiva (frente 6), para chegar à SPEC-0065 e às demais frentes com dados (thomas, 2026-11-17)
- [x] As outras frentes entram agora? — não: entram como filhas depois do primeiro relatório real, cada uma com H1 próprio (thomas, 2026-11-17, piloto automático com o recomendado)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0066` ajuda a montar. -->

### O que foi entregue
- **SPEC-0074 (PR #50, plugin 2026.11.19):** comando só de leitura `spec_graph.py retro`, a retrospectiva entre projetos públicos e privados. Ele traz métricas de fluxo, rigor dos gates, origem da evidência, N/A, emendas e impedimentos, os achados R1 a R7 com a ação de cada um e as sugestões para a skill.
- **SPEC-0078 (PR #51, plugin 2026.11.20):** corrige o que a primeira retrospectiva mostrou.
  - O histórico de reprovações fica na própria spec, e a regra dos 3 FAILs passa a ser conferível.
  - O `status` e o `next` avisam das specs entregues sem fechar.
  - O `private init` grava `sdd_version`.
  - O `retro` separa a versão desconhecida da atrasada.

### Como
- **Onda 1:** SPEC-0074. A primeira rodada real, em 25 projetos e 2,6 s, confirmou a hipótese do radar: 1 FAIL na tabela atual contra 183 no histórico do git.
- **Onda 2:** SPEC-0078, com os achados da onda 1 como entrada.
- Cada filha passou por test-writer, implementer e reviewer independentes, com emendas registradas: a v2 da SPEC-0074 e as v2 e v3 da SPEC-0078.
- Distribuição pelo plugin, sem deploy (G6 N/A).

### Critérios de aceite
| Critério | Prova | Resultado |
|---|---|---|
| A retrospectiva roda nos projetos públicos e privados sem alterar nenhum deles | SPEC-0074:IT-01, mais a rodada real com o estado do git igual antes e depois (G4 da SPEC-0074 e da SPEC-0078) | PASS |
| Os achados e as sugestões seguem as regras documentadas | SPEC-0074:UT-03, mais SPEC-0078:UT-05 e UT-07 | PASS |
| O relatório não expõe títulos nem textos | SPEC-0074:UT-04, mais SPEC-0078:UT-05 (evidência do histórico) | PASS |

### Métricas pós-release
Na primeira retrospectiva, 25 projetos foram analisados sem nenhum ignorado. As regras que mais apareceram:

| Regra | Projetos |
|---|---|
| R1 (versão desconhecida ou atrasada) | 25 |
| R3 (entregue sem fechar) | 14 |
| R4 (evidência à mão) | 12 |

A métrica de sucesso do épico ("pelo menos uma spec decidida pelo thomas a partir do relatório") foi cumprida pela SPEC-0078, aprovada em 2026-11-17. A próxima retrospectiva mostra se R1, R3 e R5 caem com a versão 2026.11.20.

### Pendências
- As frentes do radar que ficaram fora deste épico entram como épico novo quando forem priorizadas:
  - o plugin e a `gluon-spec` atuais no próprio desenvolvimento;
  - pilares no perfil padrão e documentos vivos;
  - métricas de qualidade no CI;
  - atlas do próprio repositório;
  - ciclo de auto-melhoria agendado.
- A ideia está registrada neste épico (seção 2 e radar). Nenhuma spec foi criada ainda, por decisão do thomas em 2026-11-17 ("fechar o épico").

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| — | 2026-11-17 | Filha SPEC-0078 (radar) incluída na Decomposição, com os ajustes apontados pela primeira retrospectiva real | Pendências da SPEC-0074 | SPEC-0078 | thomas, 2026-11-17 (piloto automático com o recomendado) |
