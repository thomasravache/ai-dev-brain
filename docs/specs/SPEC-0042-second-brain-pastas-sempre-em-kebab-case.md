---
id: SPEC-0042
title: "second-brain: pastas sempre em kebab-case"
tier: lite
type: feature
user_facing: false
status: in-progress
created: 2026-10-30
parent:
depends_on: [SPEC-0016]
consumes_contract: []
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/config.md, skills/second-brain/references/vault-layout.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007]
external: []
size: S
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0042 — second-brain: pastas sempre em kebab-case

## 1. Problema
O usuário quer que toda pasta criada pela skill tenha nome em kebab-case: minúsculas, sem acento, palavras separadas por traço (`second-brain`, e não `SecondBrain`). Hoje o `brain.py` aceita qualquer nome:
- `init --context Faculdade=Projects/Faculdade` e `context add Trabalho_Novo --folder Areas/Trabalho Novo` criam as pastas com maiúsculas, espaço ou `_`;
- o nome do contexto, que também vira a pasta em `files/<contexto>/` e o arquivo `mocs/<contexto>.md`, aceita `_` e maiúsculas (`CONTEXT_NAME_RE`);
- o onboarding no `SKILL.md` não sugere um padrão de nome para as pastas do vault e de `files`.

## 2. Causa Raiz
Melhoria pequena. `check_context_name` (`CONTEXT_NAME_RE = ^[\w][\w-]*$`) e `relative_folder` só validam se o nome é seguro e fica dentro do vault, sem padronizar. O `slugify` já existe para nomes de notas de fonte, mas não é usado em pastas.

## 3. Mudança Proposta
- Nova função `kebab(name)`: minúsculas, sem acento (`fold`), e cada sequência fora de `[a-z0-9]` vira um `-`, sem traço no começo nem no fim. Exemplos: `Faculdade` → `faculdade`, `Trabalho Novo` → `trabalho-novo`, `Cálculo_II` → `calculo-ii`.
- **Nomes de contexto** (`init --context`, `context add`) e **cada parte da pasta** de um contexto passam por `kebab`. Se o nome mudar, o comando segue e avisa "nome ajustado para kebab-case: `<de>` → `<para>`". Um nome que fica vazio depois do ajuste (só símbolos) sai com 2. O título do MOC (`--title` ou `:título`) mantém o que o usuário escreveu.
- **Pastas do vault com `--adopt --map`** não mudam: são pastas que já existem, e o ADR-0007 proíbe renomear o que é do usuário.
- **Caminhos do vault e de `files`** são escolha do usuário. O onboarding do `SKILL.md` passa a sugerir nomes em kebab-case (ex.: `~/second-brain/vault` e `~/second-brain/files`), e o `doctor` mostra AVISO quando a pasta do vault, a de `files` ou a pasta que contém cada uma delas não está em kebab-case (ex.: `.../SecondBrain/vault` avisa sobre `SecondBrain`; v2). O aviso é uma linha AVISO própria, que não muda as linhas `OK vault` e `OK files` nem vira ERRO.
- `references/config.md` e `references/vault-layout.md` documentam a regra.

NÃO muda: nomes de arquivos de nota (seguem o título, SPEC-0019), a estrutura padrão (já em kebab-case: `inbox`, `raw`, `projects`…), contextos já gravados no `brain-config.yml` (o `doctor` mostra AVISO para nome ou pasta fora do padrão, sem renomear).

**Padrão seguido:** `slugify` e `check_context_name` do `brain.py`; testes `test_cli.py` (`ContextAddTest`, `NewVaultTest`) e `test_config.py`.

**Rollback:** `git revert` do commit.

**Outras ocorrências:** Nenhuma.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — os testes atuais de `init` e `context add` com nomes já em kebab-case continuam valendo.
- **UT-01** — Dado `Faculdade`, `Trabalho Novo`, `Cálculo_II`, `--Ok--` e `???`, quando `kebab` roda, então devolve `faculdade`, `trabalho-novo`, `calculo-ii`, `ok` e vazio.
- **IT-01** — Dado um vault novo, quando roda `init --context "Faculdade=Projects/Faculdade:Faculdade"` e depois `context add "Trabalho Novo" --folder "Areas/Trabalho Novo"`, então as pastas criadas são `projects/faculdade` e `areas/trabalho-novo`, os contextos ficam gravados como `faculdade` e `trabalho-novo` com os MOCs `mocs/faculdade.md` e `mocs/trabalho-novo.md`, a saída avisa o ajuste e o título do MOC continua "Faculdade"; e `context add "???" --folder x` sai com 2.
- **IT-02** — Dado um vault adotado com `--adopt --map inbox=Inbox`, quando roda `init`, então `Inbox` não é renomeada; e dado um vault em `.../SecondBrain/vault` e um contexto gravado à mão como `Work` em `Areas/Work`, quando roda `doctor`, então mostra AVISO para a pasta do vault, o nome do contexto e a pasta, sem renomear nada.

## 5. Questões em Aberto
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01, IT-01 e IT-02 com a tag `SPEC-0042:<ID>`, falhando pelo motivo certo
- [ ] Green: `kebab`, contextos e pastas ajustados com aviso, AVISOs no `doctor`, docs
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] Seção no `skills/second-brain/CHANGELOG.md` (ADR-0007)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega e CHANGELOG (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 2e6ace1 | 2026-10-30 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=3)) — 56a7836 | 2026-10-30 |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-30 | G1 | spec | Contradição: §3 manda avisar quando a última pasta do vault ou de files não está em kebab-case, mas o IT-02 usa .../SecondBrain/vault (última pasta 'vault' já é kebab) e espera aviso sobre SecondBrain | Test-writer seguiu o IT-02 (aviso cita SecondBrain) | Architect + thomas (Emenda) | Emenda v2 — o doctor olha a pasta e a pasta-mãe do vault e de files; aprovada por thomas em 2026-10-30 | 2026-10-30 |

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue

### Como foi feito

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Teste de regressão falhou antes e passa depois da correção
- [ ] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão existente mantido
- [ ] Disponível no ambiente-alvo via pipeline (G6)
- [ ] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [ ] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-10-30 | O AVISO do `doctor` olha a pasta do vault e de `files` e também a pasta que contém cada uma; é uma linha AVISO própria | IMP-01: a §3 falava só da última pasta, mas o IT-02 (`.../SecondBrain/vault`) espera o aviso sobre `SecondBrain` | Nenhuma | thomas (2026-10-30) |
