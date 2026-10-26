---
id: SPEC-0013
title: Novidades da skill para os projetos (whats-new)
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-26
parent:
depends_on: []
consumes_contract: [SPEC-0003@1]
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/CHANGELOG.md, CHANGELOG.md, skills/sdd-management/SKILL.md, skills/sdd-management/references/brownfield.md, skills/sdd-management/references/sdd-config.template.yml, README.md]
adrs: [ADR-0001, ADR-0005, ADR-0006]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-26
---

# SPEC-0013 — Novidades da skill para os projetos (whats-new)

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Um projeto que usa a skill passa a descobrir o que há de novo nela: o comando `whats-new` compara o projeto com a skill instalada e mostra as entradas do CHANGELOG da skill desde a versão do projeto, as chaves do `sdd-config` que o projeto ainda não tem (com a explicação de cada uma) e os comandos para se atualizar. O `status` mostra uma linha quando há novidade. Para isso o CHANGELOG passa a viajar com a skill e a ser agrupado por versão.

## 2. Motivação & Escopo
**Motivação:** a skill evolui (ex.: documentos vivos na 2026.10.9), mas um projeto só fica sabendo que `tools/sdd` está desatualizado (aviso do `validate`). Depois do `vendor --force`, nada diz o que mudou, e funcionalidades opt-in como `living_docs` (chave ausente = desligado) ficam desligadas para sempre sem ninguém notar; o `upgrade` só atualiza specs, nunca o `sdd-config`. Além disso, o CHANGELOG fica na raiz do repositório `ai-dev-brain` e não vai junto quando a skill é copiada para `~/.claude/skills`, e as entradas estão todas em `[Unreleased]`, com a versão citada no meio do texto.

**Objetivos (dentro do escopo):**
- CHANGELOG da skill dentro da pasta da skill (`skills/sdd-management/CHANGELOG.md`), agrupado por versão (`## [AAAA.MM.N] - AAAA-MM-DD`), com o histórico atual reorganizado pelas versões que cada entrada cita.
- Comando `whats-new [--ack]`: novidades entre a versão do projeto e a da skill, chaves de topo do template do `sdd-config` ausentes no projeto (com o comentário do template) e comandos sugeridos.
- Versão do projeto: a de `tools/sdd/spec_graph.py`; sem ela (modo privado ou projeto sem `vendor`), a chave `sdd_version` do `sdd-config`, gravada por `whats-new --ack`.
- `status` mostra uma linha de aviso quando há novidade ou chave nova.
- Regra no ADR-0005: toda mudança de `SDD_TOOL_VERSION` move as entradas para a seção da versão; teste que garante que a versão atual tem seção no CHANGELOG.
- Instruções: SKILL.md (tabela de comandos e DISCOVER), `brownfield.md` (passo de atualização), `sdd-config.template.yml` (`sdd_version`), README.

**Não-objetivos (fora do escopo):**
- Saber se existe uma skill mais nova no GitHub ou atualizar a cópia instalada: seria rede/plataforma (ADR-0001); continua manual.
- Aplicar as chaves novas automaticamente no `sdd-config` do projeto: o comando sugere, o humano decide.
- Chaves aninhadas novas dentro de blocos que o projeto já tem (só chaves de topo).
- Calar o aviso de H2 repetido quando `h2_policy: auto-on-green` está declarada (spec lite própria, se fizer sentido).

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** SPEC-0003@1 — em modo privado o `sdd-config` é o do `spec_root` (`project.config_path`) e os registros são commitados lá (`commit_records`).
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Referências: aviso de versão do vendor em `validate_config` (`spec_graph.py:1515`, lê `SDD_TOOL_VERSION` de `tools/sdd`); `cmd_upgrade` (`:3871`) para um comando de atualização com simulação; `parse_yaml_subset` (`:187`) para ler o template e o `sdd-config`; `cmd_status` (`:3065`) para a linha de aviso; `RECORD_COMMANDS`/`commit_records` para gravar no `spec_root` em modo privado.

**Decisão:** funções puras `changelog_since(text, since, until)` (seções de versão no intervalo, em ordem) e `missing_config_keys(template_text, config)` (chaves de topo do template ausentes no projeto, com o comentário logo acima delas); `cmd_whats_new` monta a saída e, com `--ack`, grava `sdd_version`. O CHANGELOG vai para `skills/sdd-management/CHANGELOG.md` (lido de `SKILL_DIR`), e o `sdd-config` deste repositório aponta `changelog:` para ele.

**Justificativa:** tudo é local, comparando o projeto com a cópia da skill instalada (ADR-0001: só stdlib e git, sem plataforma); o CHANGELOG precisa estar na pasta da skill porque é a pasta que se copia para as ferramentas. Chaves de topo cobrem as funcionalidades opt-in (ex.: `living_docs`) sem precisar de um esquema do `sdd-config`.

**Desvio do padrão existente:** Nenhum. O ADR-0005 ganha uma regra (CHANGELOG por versão), aprovada junto com esta spec.

**Alternativas descartadas:** consultar o GitHub por versões novas (plataforma e rede; ADR-0001); um arquivo de novidades separado do CHANGELOG (duas fontes para a mesma coisa); `upgrade` aplicar as chaves no `sdd-config` (mudaria configuração sem decisão humana).

**ADRs:** ADR-0001 (fronteiras), ADR-0005 (versão e CHANGELOG — regra nova), ADR-0006 (modo privado).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `whats-new` e a linha do `status` leem dois arquivos pequenos; o `status` não fica mais de 10% mais lento num projeto com 100 specs (medido na revisão, como na SPEC-0011).
- **Segurança:** `--ack` só escreve a chave `sdd_version` no `sdd-config` do projeto (ou do `spec_root`); nada mais é alterado.
- **Privacidade e dados pessoais:** em modo privado nada é escrito no repositório do time (IT-04).
- **Disponibilidade e resiliência:** skill sem CHANGELOG, versão ilegível ou projeto sem versão conhecida → o comando avisa e mostra só o que consegue (chaves novas), sem erro.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** CHANGELOG da skill, comando `whats-new`, linha do `status`, chave `sdd_version`, regra do ADR-0005.

```text
skills/sdd-management/CHANGELOG.md (movido da raiz; Keep a Changelog):
  ## [Unreleased]                     (pode ficar vazio)
  ## [2026.10.10] - 2026-10-26        (uma seção por versão de SDD_TOOL_VERSION, a mais nova primeiro)
  ### Added | Changed | Fixed | ...
  - entradas citando SPEC-NNNN
  - histórico atual reorganizado: cada entrada vai para a versão que cita; entrada sem versão vai para a versão
    em que a spec dela foi entregue
  - SDD_TOOL_VERSION sempre tem seção (teste UT-03); docs/specs/sdd-config.yml deste repositório: changelog aponta para ele

Versão do projeto:
  1. SDD_TOOL_VERSION de tools/sdd/spec_graph.py, se existir
  2. senão, sdd_version do sdd-config (do spec_root em modo privado)
  3. senão, "desconhecida"
  versões comparadas como tupla de inteiros (2026.10.10 > 2026.10.9)

spec_graph.py whats-new:
  cabeçalho: "Projeto: <versão do projeto> · skill: <SDD_TOOL_VERSION>"
  projeto mais antigo: "Novidades desde <versão do projeto>:" + as seções do CHANGELOG da skill com versão
    > projeto e <= skill, na ordem do arquivo
  versão desconhecida sem tools/sdd: "Versão do projeto desconhecida — rode whats-new --ack depois de revisar"; não lista novidades
  tools/sdd sem versão legível: avisa e sugere "vendor --force" (sdd_version é ignorada quando tools/sdd existe)
  projeto mais novo que a skill: avisa que a skill instalada é mais antiga e sugere atualizá-la; não diz "em dia"
  chaves de topo do template ausentes no sdd-config: "Configurações novas (ausentes no seu sdd-config):" e, para
    cada uma, "- <chave>: <comentário logo acima da chave no template>"; chave presente com valor vazio conta como presente
  "Para se atualizar:" com, conforme o caso: "vendor --force" (tools/sdd mais antigo), "upgrade" (specs),
    "copie a chave do template references/sdd-config.template.yml" (chaves novas), "whats-new --ack" (sem tools/sdd e
    sdd_version ausente ou mais antiga que a skill — nunca para rebaixar)
  nada novo: "Projeto em dia com a skill (<versão>)."
  skill sem CHANGELOG: "CHANGELOG da skill não encontrado" e segue com as chaves
  exit 0 sempre

spec_graph.py whats-new --ack:
  grava sdd_version: <SDD_TOOL_VERSION> no sdd-config (cria ou troca a linha); imprime "sdd_version = <versão>"
  em modo privado grava no sdd-config do spec_root e commita lá (RECORD_COMMANDS)

status: com novidade (versão do projeto < skill) ou chave nova, uma linha no fim:
  "Novidades da skill: <N> versão(ões) e <M> configuração(ões) nova(s) — rode whats-new"; nada quando em dia

ADR-0005, nova regra: toda mudança de SDD_TOOL_VERSION abre "## [versão] - data" no CHANGELOG da skill com as
  entradas da mudança.

Instruções: SKILL.md (linha de whats-new na tabela; DISCOVER: rodar whats-new quando o status avisar);
  brownfield.md (passo 6: whats-new antes de vendor --force/upgrade); sdd-config.template.yml (sdd_version com
  comentário); README (onde fica o CHANGELOG e o comando)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. Movido: `CHANGELOG.md` → `skills/sdd-management/CHANGELOG.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Novidades entre versões | projeto 2026.10.8, skill 2026.10.10 | seções 2026.10.10 e 2026.10.9, nesta ordem, sem as anteriores | UT-01, IT-01 |
| Comparação de versões | 2026.10.10 vs 2026.10.9 | numérica, não textual | UT-01 |
| Chaves novas | template com `living_docs` e projeto sem | chave listada com o comentário do template | UT-02, IT-01 |
| Chave presente vazia | `living_docs: {journeys: ""}` no projeto | não listada | UT-02 |
| Em dia | mesma versão e todas as chaves | "Projeto em dia com a skill" | IT-02 |
| Linha do status | com e sem novidade | linha "Novidades da skill: …" só com novidade | IT-03 |
| Sem tools/sdd | modo privado ou sem vendor | versão de `sdd_version`; sem ela, "desconhecida" e sugestão de `--ack` | IT-04, CT-01 |
| Ack | `whats-new --ack` | grava `sdd_version`; em modo privado no spec_root, com commit | IT-04, CT-01 |
| Skill sem CHANGELOG | arquivo ausente | aviso e lista de chaves, exit 0 | IT-05 |
| CHANGELOG por versão | CHANGELOG da skill | tem `## [SDD_TOOL_VERSION]`, nenhuma entrada solta em versão antiga sem cabeçalho | UT-03 |
| Instruções | SKILL.md, brownfield.md, template, README | trazem whats-new / sdd_version | UT-04 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — o aviso de versão do `validate` e o `upgrade` já são fixados pela suíte (`test_spec_graph.py`) e não mudam.

### 7.2 Testes Unitários
- **UT-01** — Dado um CHANGELOG com `[Unreleased]`, `[2026.10.10]`, `[2026.10.9]` e `[2026.10.8]`, quando `changelog_since(texto, "2026.10.8", "2026.10.10")` roda, então devolve as seções 2026.10.10 e 2026.10.9 nessa ordem; e a comparação trata 2026.10.10 como maior que 2026.10.9.
- **UT-02** — Dado um template com as chaves de topo `base_branch`, `living_docs` (com duas linhas de comentário acima) e `h2_policy`, e um config com `base_branch` e `h2_policy`, quando `missing_config_keys` roda, então devolve só `living_docs` com o comentário; com `living_docs` presente e valores vazios, devolve lista vazia.
- **UT-03** — Dado o CHANGELOG da skill (`skills/sdd-management/CHANGELOG.md`), quando lido, então tem a seção `## [<SDD_TOOL_VERSION>]` e todas as seções de versão seguem o formato `## [AAAA.MM.N] - AAAA-MM-DD`, da mais nova para a mais antiga.
- **UT-04** — Dado SKILL.md, `references/brownfield.md`, `references/sdd-config.template.yml` e README, quando lidos, então SKILL.md e brownfield.md citam `whats-new`, o template tem `sdd_version` e o README cita o CHANGELOG da skill.

### 7.3 Testes de Integração
- **IT-01** — Dado um repositório temporário com `tools/sdd/spec_graph.py` de versão 2026.10.8 e `sdd-config` sem `living_docs`, quando roda `whats-new` com a skill atual, então a saída tem o cabeçalho com as duas versões, as seções do CHANGELOG mais novas que 2026.10.8, `living_docs` em "Configurações novas" e `vendor --force` em "Para se atualizar"; exit 0.
- **IT-02** — Dado um projeto com `tools/sdd` na versão da skill e todas as chaves do template, quando roda `whats-new`, então imprime "Projeto em dia com a skill (<versão>)."
- **IT-03** — Dado os projetos do IT-01 e do IT-02, quando roda `status`, então só o primeiro mostra "Novidades da skill: … — rode whats-new".
- **IT-04** — Dado um projeto sem `tools/sdd` e sem `sdd_version`, quando roda `whats-new`, então mostra versão "desconhecida" e sugere `--ack`; depois de `whats-new --ack`, o `sdd-config` tem `sdd_version` igual à da skill e um novo `whats-new` não lista novidades de versão.
- **IT-05** — Dado uma cópia temporária da skill sem CHANGELOG, quando roda `whats-new` com ela, então avisa "CHANGELOG da skill não encontrado", ainda lista as chaves novas e sai com 0.

### 7.4 Testes de Contrato
- **CT-01** — Dado um `Project` em modo privado criado pela API da SPEC-0003@1, quando roda `whats-new` e `whats-new --ack`, então lê e grava `sdd_version` no `sdd-config` do `spec_root` (`project.config_path`), commita lá, e o repositório do time não muda.

### 7.5 Testes E2E
- N/A — a jornada do usuário é a CLI e, conforme o ADR-0002, é coberta por testes de integração.

### 7.6 Outros
- Tempo do `status` com e sem a checagem, num projeto com 100 specs (RNF de desempenho), medido na revisão.

**Dublês e dados de teste:** repositórios temporários; CHANGELOG e template sintéticos nos testes unitários; registro do usuário isolado (`SDD_CONFIG_HOME`).

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** merge direto; projetos só veem algo novo ao rodar `status` ou `whats-new` com a skill atualizada.
- **Dados/schema:** chave nova e opcional `sdd_version` no `sdd-config`; CHANGELOG muda de lugar.
- **Compatibilidade:** projetos sem `sdd_version` funcionam como hoje; quem lia o CHANGELOG da raiz passa a ler o da skill (README aponta).
- **Observabilidade:** linha do `status` e saída do `whats-new`.
- **Rollback:** `git revert` do merge; `SDD_TOOL_VERSION` e CHANGELOG conforme o ADR-0005.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Checar se há skill mais nova no GitHub? — Não: comparação só local, com a skill instalada; atualizar a cópia instalada continua manual (thomas concordou com a proposta, 2026-10-26)
- [x] Onde fica o CHANGELOG? — Dentro da pasta da skill, que é o que se copia para as ferramentas; a raiz deixa de ter CHANGELOG próprio (proposta do Architect, confirmada no H1 por thomas, 2026-10-26)
- [x] Como o projeto sem `tools/sdd` sabe sua versão? — Chave `sdd_version` gravada por `whats-new --ack` depois de revisar (proposta do Architect, confirmada no H1 por thomas, 2026-10-26)
- [x] O `whats-new` aplica as chaves novas? — Não: só sugere; o humano copia do template (proposta do Architect, confirmada no H1 por thomas, 2026-10-26)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: CHANGELOG da skill e funções puras**
- [ ] Red: UT-01, UT-02, UT-03 com a tag `SPEC-0013:<ID>`, falhando pelo motivo certo
- [ ] Green: CHANGELOG movido para a skill e agrupado por versão; `changelog_since`, `missing_config_keys` e comparação de versões
- [ ] Refactor mantendo tudo verde

**Fase 2: Comando, status e ack**
- [ ] Red: IT-01 a IT-05 e CT-01 falhando pelo motivo certo
- [ ] Green: `cmd_whats_new` (`--ack`), linha do `status`, `sdd_version`
- [ ] Refactor mantendo tudo verde

**Fase 3: Instruções**
- [ ] Red: UT-04 falhando pelo motivo certo
- [ ] Green: SKILL.md, brownfield.md, sdd-config.template.yml, README; `changelog:` do sdd-config deste repositório
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] `SDD_TOOL_VERSION` 2026.10.11 e seção no CHANGELOG da skill (ADR-0005)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2 (política auto-on-green)
- [ ] Deploy via pipeline (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — ea39027 | 2026-10-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=10, skipped=1)) — cc9001c | 2026-10-26 |
| G2 Green | PASS | MANUAL: CI do GitHub no PR #10 em b7e5535 (run 40386292100): ruff check 'All checks passed!' e 158 testes OK em Python 3.9 e 3.15; local (macOS) 158 testes OK — só o lint não roda aqui (sem uv/ruff) | 2026-10-26 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 1cae0b3 | 2026-10-26 |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-26 | G4 | spec | Revisão achou casos de borda que o contrato manda fazer errado: 'Versão do projeto desconhecida — rode whats-new --ack' também quando tools/sdd existe (onde sdd_version é ignorado), e sugestão de --ack quando sdd_version é mais nova que a skill (rebaixaria a versão) | testes red da 2ª rodada em c0456f6 | thomas | Emenda v2 do contrato (aprovada por thomas em 2026-10-26) — --ack só sem tools/sdd e nunca para rebaixar; implementada em a072e1f e testada em c0456f6 | 2026-10-26 |

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0013`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-10-26 | "Versão desconhecida — rode whats-new --ack" só sem tools/sdd (com tools/sdd sem versão: vendor --force); --ack nunca sugerido quando sdd_version é mais nova que a skill; projeto mais novo que a skill não é "em dia" | revisão G4: o contrato mandava sugerir um --ack inútil (tools/sdd presente) ou que rebaixaria a versão (IMP-01) | Nenhuma | thomas, 2026-10-26 |
