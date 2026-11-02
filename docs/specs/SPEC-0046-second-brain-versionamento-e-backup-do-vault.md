---
id: SPEC-0046
title: "second-brain: versionamento e backup do vault"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-02
parent:
depends_on: [SPEC-0017]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/backup.md, skills/second-brain/references/config.md, skills/second-brain/assets/brain-config.yml, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007, ADR-0008]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0046 — second-brain: versionamento e backup do vault

> Rascunho no radar (pedido do usuário em 2026-11-02). Desenho proposto abaixo; contrato e testes são detalhados depois das Questões em Aberto.

## 1. Visão Geral
Hoje o segundo cérebro **evita** perda de dados, mas não tem **como voltar atrás**:
- o `brain.py` nunca apaga nem sobrescreve e só reescreve as regiões geradas;
- as escritas são atômicas;
- tudo vai para o `log.md`.

Mesmo assim, nada protege contra:
- um erro da pessoa ou de outro programa (apagar uma nota no Obsidian);
- um conflito de sincronização que vence errado;
- uma pasta corrompida.

A proposta é dar ao vault um histórico e cópias restauráveis, sem depender de um provedor:
- **Versionamento:** um histórico local das notas. Opções: um repositório git dentro do vault, se a pessoa quiser; ou snapshots do `brain.py` em `.brain/history/`, só com a biblioteca padrão.
- **Backup:** `brain.py backup` gera um arquivo `.zip` datado do vault inteiro (sem `files/` pesados, opcional) numa pasta de destino fora do vault, com rotação (manter os N mais recentes). `brain.py backup verify` confere se o último backup abre e bate com o vault.
- **Restauração:** `brain.py restore NOTA --from <backup>` recupera uma nota como arquivo novo (`<nome> (restaurado AAAA-MM-DD).md`), nunca por cima da atual, conforme o ADR-0007.

## 2. Motivação & Escopo
**Motivação:** a pessoa quer garantir que não aconteça nenhuma perda de dados. O vault é sincronizado pelo provedor, e a sincronização replica um apagamento ou uma corrupção para todas as máquinas. Alguns provedores mantêm histórico de versões, mas é diferente em cada um e não foi conferido aqui.

**Objetivos (proposta):**
- `backup` (zip datado fora do vault, com rotação e exclusões configuráveis), `backup verify`, `backup list`.
- `restore` não destrutivo: sempre um arquivo novo, nunca sobrescreve.
- Configuração em `brain-config.yml`: destino (`backup.dest`, por máquina, na configuração local, porque é um caminho), retenção e inclusão de `files/`.
- O `doctor` mostra a idade do último backup e avisa quando passa de N dias.
- Opcional, se escolhido: guia de versionamento com git (`references/backup.md`), sem o `brain.py` executar git.

**Não-objetivos:**
- Backup na nuvem pela API do provedor (ADR-0008): o destino é uma pasta, que pode ser outra pasta sincronizada ou um disco externo.
- Agendar o backup sozinho: o guia mostra como usar o agendador do sistema, mas a skill não instala nada.

## 3. Dependências
- **Implementações necessárias:** SPEC-0017 (configuração em duas camadas e `doctor`).
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** nenhum (`zipfile` é da biblioteca padrão).

## 4. Decisão Arquitetural
**Contexto:** projeto existente; segue o ADR-0007 (só biblioteca padrão, nunca apaga nem sobrescreve) e o ADR-0008 (pastas, sem API). A rotação de backups apaga zips antigos **fora do vault**, numa pasta só da skill. Isso pode exigir ajustar o ADR-0007 ou um ADR novo.

**Decisão:** a detalhar depois das Questões em Aberto.

**Justificativa:** zip da biblioteca padrão funciona igual em qualquer provedor e sistema.

**Desvio do padrão existente:** a definir (rotação = apagar backups antigos fora do vault).

**Alternativas descartadas (prévia):** depender só do histórico de versões do provedor (diferente por provedor, não conferido); o `brain.py` executar git (processo externo fora dos processadores, ADR-0007).

**ADRs:** ADR-0007 e ADR-0008 (aplicados); ADR novo a criar, se a rotação for aceita.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** a definir (ex.: backup de 5.000 notas em poucos segundos).
- **Segurança:** o backup inclui itens confidenciais (SPEC-0045)? A definir; se incluir, o destino precisa ser tão protegido quanto o vault.
- **Privacidade e dados pessoais:** o destino fica fora do repositório e é escolhido pela pessoa.
- **Disponibilidade e resiliência:** `backup verify` prova que o arquivo abre; um backup que falha no meio não substitui o anterior.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** espaço em disco do destino, controlado pela retenção.

## 6. Artefato A — Contrato
**Interface:** a definir depois das Questões em Aberto.

```text
(proposta) brain.py backup [--dest PASTA] [--with-files] [--json]  → <dest>/second-brain-AAAA-MM-DD-HHMMSS.zip
(proposta) brain.py backup list | backup verify [ARQ]
(proposta) brain.py restore NOTA --from ARQ                       → arquivo novo "<nome> (restaurado AAAA-MM-DD).md"
(proposta) config local: backup.dest; brain-config.yml: backup.keep, backup.with_files, backup.warn_days
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| A detalhar | depois das Questões em Aberto | — | UT-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — rascunho.

### 7.2 Testes Unitários
- **UT-01** — A detalhar depois das Questões em Aberto.

### 7.3 Testes de Integração
- **IT-01** — A detalhar depois das Questões em Aberto.

### 7.4 Testes de Contrato
- N/A — sem contrato entre specs.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** a definir.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto; sem `backup.dest`, nada acontece (o `doctor` sugere configurar).
- **Dados/schema:** chaves novas opcionais.
- **Compatibilidade:** nenhum comando existente muda.
- **Observabilidade:** linha do último backup no `doctor` e no `log.md`.
- **Rollback:** `git revert` do merge; os zips já criados continuam válidos.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [ ] Onde os backups devem ficar: outra pasta sincronizada (ex.: outra conta ou provedor), um disco externo, ou os dois? (thomas)
- [ ] Quer histórico fino das notas (git dentro do vault, com o guia) além dos backups zip, ou só os backups? (thomas)
- [ ] A rotação pode apagar backups antigos na pasta de backups (fora do vault)? Quantos manter? (thomas)
- [ ] O backup inclui a pasta `files/` (vídeos e PDFs, pesada) ou só as notas? (thomas)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PENDING | | |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0046`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
