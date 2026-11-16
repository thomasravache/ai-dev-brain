---
id: SPEC-0066
title: "Dogfooding: o Fermion valida e melhora o próprio repositório"
tier: epic
type: feature
status: proposed
created: 2026-11-16
depends_on: []
adrs: []
external: []
approved_by:
approved_at:
---

# SPEC-0066 — Dogfooding: o Fermion valida e melhora o próprio repositório (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0066`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

> **Radar (2026-11-16):** pedido do thomas: medir se o repositório escreve código de qualidade com a arquitetura mais eficaz para o que entrega, usando o próprio Fermion para se validar e se melhorar. Diagnóstico inicial (2026-11-16), a detalhar antes do G0:
> - **Não usamos o que entregamos:** as sessões neste repositório carregam a cópia antiga `~/.claude/skills/sdd-management` (2026.10.12), não a `gluon-spec` do repositório (2026.11.3); o plugin `fermion` não está instalado; `tools/sdd/` está em 2026.11.1 (`whats-new` mostra duas versões atrasadas).
> - **Pilares no perfil mínimo,** com `segredos-dados` dispensado por "não usamos credenciais nem dados pessoais", o que deixou de ser verdade (notas confidenciais, servidor MCP com dados pessoais, probes da SPEC-0030). Sem documentos vivos (`living_docs`: mapa do sistema e jornadas).
> - **Arquitetura:** três scripts de 3,5 mil a 4,5 mil linhas (ADR-0001: um arquivo só, stdlib, instalável por cópia). Funções em geral pequenas (só 4 acima de 100 linhas, quase todas `main`), mas sem métrica de cobertura, complexidade ou tamanho no CI.
> - **Sem uso cruzado:** a `boson-atlas` não mapeia este repositório e a `photon-brain` não guarda as decisões do projeto.
> Filhas candidatas: (1) usar o plugin e a `gluon-spec` atuais no próprio desenvolvimento; (2) pilares no perfil padrão, revisão das dispensas e documentos vivos; (3) métricas de qualidade no CI (cobertura, complexidade, orçamento de tamanho) e ADR avaliando a divisão dos scripts sem perder a instalação por cópia; (4) atlas do próprio repositório; (5) ciclo de auto-melhoria agendado (doctor, `whats-new`, `validate`, `pillars`) que propõe specs, sem aplicar nada sozinho (ADR-0019).

## 1. Visão
{{Resultado de negócio e técnico esperado ao final do épico.}}

## 2. Escopo
**Objetivos (dentro do escopo):**
- {{O que o épico entrega}}

**Não-objetivos (fora do escopo):**
- {{O que fica explicitamente de fora}}

## 3. Arquitetura Alvo
**Contexto:** {{Projeto existente: arquitetura atual (ADRs as-is) e o que muda — se muda, type: migration | Projeto novo: stack e arquitetura definidas nos ADRs de fundação}}

{{Como o sistema fica ao final: módulos, fronteiras, fluxos principais, contratos entre as filhas. Diagrama se ajudar.}}

**Decisões (ADRs):** {{ADR-NNNN — decisão. Toda decisão transversal vira ADR (liste também no frontmatter `adrs`) | N/A}}

**Regras de arquitetura a garantir (G3):** {{ex: Domain não referencia Infrastructure; módulos só se comunicam por contratos públicos — cada regra com o teste de arquitetura que a garante}}

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| {{SPEC-NNNN}} | {{título}} | {{full}} | {{feature}} | {{M}} | {{—}} | {{—}} |

## 5. Estratégia de Entrega
- **Ambientes:** {{ex: staging automático a cada merge; produção via pipeline com aprovação}}
- **Entrega por onda:** {{o que vai para produção ao fim de cada onda e o que fica atrás de feature flag}}
- **Feature flags:** {{nome — o que controla — critério para ligar e para remover | N/A}}
- **Rollback:** {{como reverter cada onda}}
- **Métricas de sucesso pós-release:** {{o que observar e por quanto tempo}}

## 6. Riscos & Mitigações
- {{risco — mitigação | N/A}}

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] {{critério verificável — SPEC-NNNN:E2E-01}}

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0066` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
