---
id: SPEC-0113
title: "photon-brain: inbox que separa ação de conhecimento e listas de tarefas por contexto"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-26
parent: SPEC-0093
depends_on: [SPEC-0108]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/references/inbox.md, skills/photon-brain/references/config.md, skills/photon-brain/SKILL.md, skills/photon-brain/CHANGELOG.md, skills/photon-brain/tests/test_inbox_actions.py, skills/photon-brain/tests/test_inbox_actions_cli.py, .claude-plugin/plugin.json]
adrs: [ADR-0007, ADR-0013, ADR-0027]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0113 — photon-brain: inbox que separa ação de conhecimento e listas de tarefas por contexto

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Ao processar a inbox, o agente separa o que é ação do que é conhecimento. O que se faz e se marca como feito ("comprar o gás até sexta") vira tarefa na ferramenta de tarefas do agente, na lista da área. O que tem hora marcada com outras pessoas vira sugestão de evento. O resto vira nota. Cada contexto do `brain-config.yml` passa a declarar as listas de tarefas da área (`contexts.<nome>.tasks`), e o `inbox done` registra no log que o item virou tarefa ou evento (pontos 12 e 13 da SPEC-0093).

## 2. Motivação & Escopo
**Motivação:** no ecossistema de vida (vault, Google Tasks e Calendar), os itens de ação da inbox estavam virando notas, e a lista de compras ficou duplicada entre o vault e o Tasks. A tabela "área → listas do Tasks" só existe numa nota do vault, e o agente não a encontra quando processa a inbox.

**Objetivos (dentro do escopo):**
- Chave opcional `contexts.<nome>.tasks`, com a lista de nomes de listas da ferramenta de tarefas da área, editada por `context add NOME --tasks "Lista A,Lista B"` e por `context set NOME --tasks ...`, e mostrada por `config --json`.
- `inbox done ITEM --outcome task|event [--target NOME]`, para o item que virou tarefa ou evento em vez de nota: move para `raw/processed/` como hoje, com o desfecho e a lista no log.
- `references/inbox.md` e `SKILL.md`, roteiro de processar a inbox:
  - classificar cada item em ação, compromisso com outras pessoas ou conhecimento;
  - ação: criar a tarefa com a ferramenta de tarefas que o agente tiver, na lista de `contexts.<c>.tasks` (sem lista, perguntar à pessoa), e depois rodar `inbox done --outcome task`;
  - compromisso: sugerir o evento à pessoa e só criar com o "sim" dela (é um convite para outros);
  - conhecimento: o fluxo de hoje, nota ou `list add` (SPEC-0108);
  - sem ferramenta de tarefas, o item fica na inbox e a pessoa é avisada; nunca vira checklist no vault.

**Não-objetivos (fora do escopo):**
- O `brain.py` chamar a API de tarefas ou de agenda (ADR-0027).
- Criar evento sem a confirmação da pessoa.
- Sincronizar tarefas de volta para o vault.

## 3. Dependências
- **Implementações necessárias:** SPEC-0108, que traz o `list add` e a regra "o que se marca como feito vai para as tarefas", que este roteiro usa.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** ferramenta de tarefas na sessão do agente (hoje o MCP do Google Tasks, de repositório próprio). A skill não depende dela: sem a ferramenta, o roteiro avisa e segue.

## 4. Decisão Arquitetural
**Contexto:**
- Os contextos são declarados por `context add` (`cmd_context_add`, `add_context_text`) como `contexts.<nome>: {folder, title}`.
- O `inbox done` (`cmd_inbox_done`) move o item e registra `inbox-done` no log, com `--note` opcional.
- O roteiro de processar a inbox está em `references/inbox.md` e no `SKILL.md`.

**Decisão:**
- `tasks` entra como campo opcional do contexto, validado como lista de nomes curtos.
- `context set` segue o `context add`, com edição pontual do `brain-config.yml` e linha no log.
- `--outcome` e `--target` entram no `inbox done`, exclusivos com `--note`.
- O roteiro novo é só texto: o agente usa as ferramentas que tiver.

**Justificativa:** os dados ficam no vault e a ação fica com o agente (ADR-0027). O `brain.py` só registra o desfecho.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:**
- O `brain.py` criar a tarefa (exige rede, contra o ADR-0008).
- Manter a tabela de áreas só na nota do vault (o agente não sabe ler a nota certa).
- Checklist no vault (duplica as tarefas, que foi o problema do feedback).

**ADRs:** ADR-0007, ADR-0013, ADR-0027.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A, configuração pequena.
- **Segurança:**
  - Nome de lista: 1 a 100 caracteres, sem quebra de linha nem caractere de controle, até 20 por contexto.
  - `--target` segue a mesma regra.
  - Os dois são recusados se parecerem segredo (UT-02).
- **Privacidade e dados pessoais:** o log registra o desfecho e o nome da lista, nunca o texto da tarefa (UT-04).
- **Disponibilidade e resiliência:** sem a chave ou sem a ferramenta de tarefas, o fluxo de hoje continua igual.
- **Acessibilidade (UI):** N/A, sem interface gráfica.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** `contexts.<nome>.tasks`, `context add|set --tasks`, `inbox done --outcome`, e o roteiro de processar a inbox

```text
brain-config.yml
  contexts:
    moradia:
      folder: areas/moradia
      title: Moradia
      tasks: [Home Care, Home Maintenance, Groceries]     # opcional

brain.py context add NOME [...] --tasks "Lista A,Lista B"
brain.py context set NOME --tasks "Lista A,Lista B"     ("" remove a chave)
  sucesso (exit 0): chave gravada, resto do arquivo igual; log.md: "- <agora> context set NOME — tasks (N)"
  erros (exit 2, nada gravado): contexto inexistente (set) | nome de lista vazio, > 100, com quebra ou controle,
    com cara de segredo | mais de 20 listas
config --json: contexts.<nome>.tasks quando existir

brain.py inbox done ITEM --outcome task|event [--target NOME]
  move como hoje; log.md: "- <agora> inbox-done inbox/<nome> → raw/processed/AAAA-MM/<nome> tarefa: <NOME>"
    (event → "evento"; sem --target, só "tarefa" ou "evento")
  --outcome junto com --note: exit 2 "use --note (virou nota) ou --outcome (virou tarefa ou evento)"
  item file ou syncing, item fora da inbox: erros de hoje

roteiro (references/inbox.md e SKILL.md), por item:
  ação (algo a fazer e marcar como feito) → tarefa na lista de contexts.<c>.tasks pela ferramenta de tarefas
    → inbox done --outcome task --target <lista>
  compromisso com outras pessoas e hora → sugerir o evento; criar só com o "sim" da pessoa → inbox done --outcome event
  conhecimento → nota (new-note, append) ou list add; inbox done --note
  sem ferramenta de tarefas ou sem lista para a área → perguntar ou deixar na inbox, avisando; nunca checklist no vault
```

**Design:** N/A, sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/brain.py`: validação de `tasks`, `context add --tasks`, `context set`, `config --json`, `inbox done --outcome/--target`.
- `references/inbox.md`, `references/config.md` e `SKILL.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Listas da área | `context add moradia --tasks "Home Care,Groceries"` ou `context set` | `contexts.moradia.tasks` gravado; resto igual; log | UT-01, IT-01 |
| Lista inválida | nome vazio, longo, com quebra, com cara de segredo, mais de 20; contexto inexistente no `set` | exit 2, nada muda | UT-02 |
| Mostrar | `config --json` | `tasks` do contexto | UT-01 |
| Item virou tarefa | `inbox done X --outcome task --target Groceries` | item em `raw/processed/`, log com "tarefa: Groceries" | UT-03, IT-01 |
| Opções em conflito | `--outcome` com `--note`; `--outcome` fora de task/event | exit 2, nada muda | UT-03 |
| Log sem o texto | qualquer `inbox done --outcome` | log sem o texto do item | UT-04 |
| Roteiro | `references/inbox.md` e `SKILL.md` | ação → tarefa; compromisso → sugestão com confirmação; conhecimento → nota ou lista; sem ferramenta → avisar | UT-05 |
| Hoje | `context add` sem `--tasks` e `inbox done --note` | iguais | CH-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — `context add` sem `--tasks` e `inbox done --note` num vault temporário dão o arquivo, a saída e a linha de log de hoje (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — `context add moradia --tasks "Home Care, Home Maintenance,Groceries"` grava `tasks: [Home Care, Home Maintenance, Groceries]`, sem os espaços nas pontas. Depois, `context set moradia --tasks "Groceries"` troca a lista e `context set moradia --tasks ""` remove a chave. O `config --json` mostra cada estado e as outras chaves do arquivo não mudam.
- **UT-02** — Saem com 2, sem mudar nada:
  - nome de lista vazio, com 101 caracteres, com quebra de linha ou caractere de controle, ou com cara de segredo;
  - 21 listas;
  - `context set` de um contexto que não existe.
- **UT-03** — `inbox done` de um item de texto:
  - com `--outcome task --target Groceries`, move o item e grava a linha de log do contrato;
  - com `--outcome event`, grava "evento";
  - com `--outcome task --note x`, ou com `--outcome other`, sai com 2 e deixa o item na inbox.
- **UT-04** — A linha do log de `inbox done --outcome` tem o nome do item, o desfecho e a lista, e nenhuma linha do texto do item.
- **UT-05** — `references/inbox.md` e `SKILL.md` dizem que:
  - ação vira tarefa pela ferramenta de tarefas, na lista de `contexts.<c>.tasks`, seguida de `inbox done --outcome task`;
  - compromisso com outras pessoas vira sugestão de evento e só é criado com o "sim" da pessoa;
  - conhecimento vira nota ou `list add`;
  - sem ferramenta ou sem lista, o agente pergunta ou deixa o item na inbox, avisando, e nunca cria checklist no vault;
  - o `brain.py` não cria tarefa nem evento.

### 7.3 Testes de Integração
- **IT-01** — Num vault do `init` com `context add moradia --tasks "Groceries"` e duas capturas, uma de ação ("comprar o gás até sexta") e uma de conhecimento:
  - a de ação é fechada com `inbox done --outcome task --target Groceries`;
  - a de conhecimento vira nota com `new-note` e é fechada com `inbox done --note`;
  - no fim, a inbox fica vazia, o `log.md` tem as duas linhas na ordem e o `doctor` não mostra nenhum ERRO.

### 7.4 Testes de Contrato
- N/A, não há contrato entre specs.

### 7.5 Testes E2E
- N/A: `user_facing: false` e nenhuma jornada crítica declarada. A criação real da tarefa é do agente, fora do `brain.py`.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `Sandbox` e capturas montadas nos testes. Nenhuma ferramenta de tarefas real.

**Ambiente de execução:** local e CI.

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin.
- **Dados/schema:** campo opcional no contexto. Vaults sem ele seguem iguais.
- **Compatibilidade:** opções e subcomando novos; `inbox done --note` não muda.
- **Observabilidade:** as linhas `inbox-done` com o desfecho.
- **Rollback:** reverter o merge. Se a chave ficar no arquivo, a versão anterior a ignora; se não ignorar, o `doctor` só avisa.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] O nome da lista é o da ferramenta (Google Tasks) ou um nome nosso? — O nome exato da lista na ferramenta de tarefas da pessoa (ex.: Home Care, Groceries), para o agente achá-la sem tradução (thomas, 2026-11-25, ponto 13 da SPEC-0093)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0113`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
