---
id: SPEC-0005
title: Rastreio sem marcas no repositório
tier: full
type: feature
user_facing: false
status: implemented
created: 2026-10-14
parent: SPEC-0002
depends_on: []
consumes_contract: [SPEC-0003@1]
contract_version: 1
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/references/template-full.md, skills/sdd-management/references/template-lite.md, CHANGELOG.md]
adrs: [ADR-0006]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0005 — Rastreio sem marcas no repositório

## 1. Visão Geral
Em modo privado, prova "teste antes do código" e escopo sem `Refs: SPEC` nos commits nem tags nos testes: os commits da spec são os da branch dela, registrados no `spec_root` com SHA e `patch-id`; red e green são classificados pelos arquivos de cada commit; o G1 roda os testes **no commit red**; cada teste do plano aponta `caminho::nome`; e o G7 acha o merge na branch base mesmo depois de squash ou rebase. O `gate G1 --at <sha>` vale também no modo completo, corrigindo a armadilha encontrada na SPEC-0001 (G1 só olhava o HEAD).

## 2. Motivação & Escopo
**Motivação:** hoje o `verify` só reconhece commits que citam a spec na mensagem, classifica red/green pelo tipo do Conventional Commits e exige a tag `SPEC-X:ID` no código (`spec_graph.py:1902`, `:1936`) — três marcas proibidas no modo privado. E a evidência por SHA some quando o time faz squash.

**Objetivos (dentro do escopo):**
- Registro de commits da spec ("Commits", na spec do `spec_root`) com papel, SHA, `patch-id` e arquivos.
- `verify` em modo privado: commits pela branch, papel pelos arquivos, testes pelo `caminho::nome`; escopo (`touches`) igual ao de hoje.
- `gate G1 --run --at <sha>` (os dois modos), executado numa worktree temporária; em modo privado o padrão é o último commit red do registro; no modo completo, dica quando o HEAD já está verde.
- G7 em modo privado: acha o merge por SHA (merge commit) ou `patch-id` (squash e rebase).
- Templates: a linha do plano de testes aceita `→ caminho::nome`.

**Não-objetivos (fora do escopo):**
- Mudar o rastreio do modo completo (continua com `Refs:` e tags; `caminho::nome` é opcional lá).
- Rodar só os testes do plano (o G1 roda o comando `test` inteiro e espera falha, como hoje).
- Descobrir o PR ou a plataforma do merge (agnóstico: só `git`).

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** SPEC-0003@1 — modo do `Project` e `spec_root` (onde o registro de commits é gravado e comitado).
- **Pré-requisitos externos:** N/A — `git patch-id --stable` e `git worktree` já fazem parte do git.

## 4. Decisão Arquitetural
**Contexto:** projeto existente. `cmd_verify` (`spec_graph.py:1865`) monta a lista de commits e os resultados `(nível, gate, mensagem)`; `cmd_gate` (`:2128`) executa e grava a evidência; `worktree` (`:874`) já cria worktrees fora do repositório.

**Decisão:** separar em `cmd_verify` a coleta dos commits (por mensagem no modo completo, pela branch no privado) da avaliação, que fica comum aos dois modos. O papel do commit no modo privado vem dos arquivos: só `test_paths` = red; algum arquivo fora = green. O `--at` cria `git worktree add --detach` num diretório temporário fora do repositório e remove ao fim.

**Justificativa:** reaproveita as regras de G1/G4 já testadas, mudando só a origem dos dados; os arquivos do commit são um critério mais forte que o tipo da mensagem, e a execução no commit red é a prova direta.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** `git notes` fora do remoto (somem num novo clone e confundem `git log`); mapear testes por nome sem caminho (ambíguo entre arquivos).

**ADRs:** ADR-0006.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `gate G1 --at` adiciona no máximo o tempo de um `git worktree add` + a suíte; medido no IT-04.
- **Segurança:** a worktree temporária é criada dentro do diretório temporário do sistema e sempre removida (também em erro).
- **Privacidade e dados pessoais:** N/A — só SHAs, caminhos e nomes de teste.
- **Disponibilidade e resiliência:** SHA inexistente em `--at` → exit 2; falha ao remover a worktree → aviso com o comando `git worktree remove`.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** seção "Commits", `verify` no modo privado, `gate G1 --at`, G7 por `patch-id`, linha do plano com `caminho::nome`.

```text
Plano de testes (os dois modos; obrigatório no privado):
  - **UT-01** — Dado …, quando …, então … → tests/Pagamentos/CartaoTests.cs::Adiciona_segundo_cartao
  modo privado: o G1 exige, para cada ID do plano, que <caminho> exista no HEAD da branch e contenha <nome> (texto literal)

Seção "Commits" (gravada pelo gate --run em modo privado; ausente no modo completo):
  | Papel | SHA | patch-id | Arquivos |
  papel: red (só test_paths) | green (algum arquivo fora de test_paths) | branch (diff total base..HEAD)

verify SPEC-X em modo privado (rodado na worktree da spec):
  commits = <merge-base com base_branch>..HEAD da branch atual
  [G1] FAIL nenhum commit red | primeiro commit não-red antes do primeiro red
  [G1] FAIL teste do plano sem <caminho>::<nome> no HEAD: <IDs>
  [G4] escopo por touches (igual ao modo completo)

gate SPEC-X G1 --run [--at SHA] [--cwd WT]
  --at: worktree temporária em SHA, roda `test`, espera exit ≠ 0 (ou --expect-green), evidência cita SHA; remove a worktree
  modo privado sem --at: usa o último red do registro de commits
  modo completo sem --at, HEAD verde e há commit red: FAIL com dica "rode com --at <sha do último red>"

gate SPEC-X G7 --run em modo privado: procura na base_branch, nesta ordem:
  1. merge commit cujo segundo pai contém o HEAD da spec → "merge <sha7>"
  2. commit único com o patch-id do diff total da branch → "squash <sha7>"
  3. commits com os patch-ids de todos os commits da spec → "rebase <sha7>..<sha7>"
  nada achado → G7 = FAIL "merge da spec não encontrado em <base>"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. `spec_graph.py`: coleta em `cmd_verify`, registro de commits, `--at` em `cmd_gate`, busca do merge no G7, parse de `caminho::nome`. Templates: exemplo da linha com `→ caminho::nome` no comentário do plano.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Papel pelo arquivo | commit só em test_paths; commit com código | red; green | UT-01 |
| Linha do plano | `**UT-01** — … → caminho::nome`, com `->` e sem mapeamento | caminho e nome extraídos; ausente = None | UT-02 |
| Red antes do green sem marcas | modo privado, commits sem `Refs:` nem tipo convencional | G1 PASS | IT-01 |
| Green antes do red | primeiro commit com código antes do teste | G1 FAIL | IT-02 |
| Teste do plano ausente | `caminho::nome` não existe no HEAD | G1 FAIL citando o ID | IT-03 |
| G1 no commit red | `gate G1 --run --at <red>` (os dois modos); HEAD verde sem --at no completo | PASS citando o SHA; FAIL com dica | IT-04 |
| Squash | spec integrada por squash na base | G7 acha por patch-id | IT-05 |
| Rebase | spec integrada por rebase | G7 acha a sequência | IT-06 |
| Merge commit | spec integrada com merge commit | G7 acha o merge | IT-07 |
| Merge ausente | spec não integrada | G7 FAIL | IT-07 |
| Registro de commits | `gate --run` em modo privado | seção Commits com papel, SHA, patch-id; commit no spec_root | IT-08 |
| Modo completo | verify por mensagens e tags | igual a hoje | IT-09 |
| SHA inválido | `--at` com SHA inexistente | exit 2 | IT-04 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — o `verify` do modo completo já é fixado por `test_red_before_green_passes`, `test_green_before_red_and_scope_fail` e `test_order_is_enforced`; IT-09 os mantém como guarda.

### 7.2 Testes Unitários
- **UT-01** — Dado `test_paths` padrão e commits com arquivos `[tests/a_test.py]`, `[src/a.py, tests/a_test.py]` e `[src/a.py]`, quando o papel é classificado, então dá red, green e green.
- **UT-02** — Dado linhas de plano com `→ tests/x.py::test_y`, com `-> tests/x.py::test_y` e sem mapeamento, quando o plano é lido, então devolve `("tests/x.py", "test_y")` nas duas primeiras e nada na terceira.

### 7.3 Testes de Integração
- **IT-01** — Dado o modo privado e uma branch com um commit só de teste ("adiciona teste") seguido de um commit de código ("implementa"), sem `Refs:` nem tipo convencional, e o plano com `caminho::nome`, quando roda `verify SPEC-0001`, então G1 = PASS.
- **IT-02** — Dado o modo privado e o commit de código antes do commit de teste, quando roda `verify`, então G1 = FAIL apontando o commit fora de ordem.
- **IT-03** — Dado o plano apontando `tests/a_test.py::test_inexistente`, quando roda `verify`, então G1 = FAIL citando o ID do teste.
- **IT-04** — Dado uma branch já verde com um commit red anterior, quando roda `gate G1 --run --at <red>` (modo privado e modo completo), então G1 = PASS e a evidência cita o SHA do red; sem `--at` no modo completo, G1 = FAIL com a dica do `--at`; com `--at` inexistente, exit 2; e nenhuma worktree temporária sobra (`git worktree list`).
- **IT-05** — Dado a spec integrada na base por squash (`git merge --squash` + commit), quando roda `gate G7 --run` em modo privado, então a evidência cita "squash" e o SHA certo.
- **IT-06** — Dado a spec integrada por rebase (commits reaplicados na base), quando roda `gate G7 --run`, então a evidência cita "rebase" e o intervalo.
- **IT-07** — Dado a spec integrada com `git merge --no-ff`, quando roda `gate G7 --run`, então a evidência cita "merge"; e numa spec não integrada, G7 = FAIL.
- **IT-08** — Dado o modo privado, quando roda `gate G1 --run` e depois `gate G2 --run`, então a spec no `spec_root` tem a seção "Commits" com papel, SHA, patch-id e arquivos, e o git do `spec_root` tem o commit; o repositório do time continua limpo.
- **IT-09** — (guarda: passa antes da mudança) Dado o modo completo, quando roda `verify` com commits `test(...)`/`feat(...)` com `Refs:` e tags, então o resultado é o mesmo de hoje.

### 7.4 Testes de Contrato
- **CT-01** — Dado um `Project` em modo privado criado pela API da SPEC-0003@1, quando os comandos desta spec leem `project.private`, `project.spec_root` e `project.config_path`, então usam esses valores (e não caminhos fixos) — verificado com um registro de teste e um `spec_root` fora do repositório.

### 7.5 Testes E2E
- N/A — a jornada do usuário é a CLI e, conforme o ADR-0002, é coberta por testes de integração; a jornada privada completa é o IT-05 da SPEC-0006.

### 7.6 Outros
- Tempo do `--at` lido no IT-04 (RNF de desempenho).

**Dublês e dados de teste:** repositórios temporários; `test` do sdd-config apontando para um script de teste mínimo que falha ou passa conforme o arquivo de código existe (sem depender de stack).

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** merge direto; o rastreio novo só atua em modo privado; `--at` é opcional no completo.
- **Dados/schema:** seção "Commits" nova só nas specs do `spec_root`; `upgrade` não a exige no modo completo.
- **Compatibilidade:** modo completo inalterado (IT-09 e suíte existente); a dica do G1 só aparece quando antes haveria um FAIL sem explicação.
- **Observabilidade:** evidência dos gates cita SHA, papel e forma do merge.
- **Rollback:** `git revert` do merge.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Como ligar commits à spec sem mensagem? — Pela branch da spec (merge-base..HEAD), registrada no `spec_root` (proposta do Architect, confirmada no H1 por thomas, 2026-10-14)
- [x] Como reconhecer red e green sem o tipo do commit? — Pelos arquivos (só `test_paths` = red) e pela execução dos testes no commit red (proposta do Architect, confirmada no H1 por thomas, 2026-10-14)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação

**Fase 1: Classificação e plano**
- [x] Red: UT-01, UT-02 e CT-01 com a tag `SPEC-0005:<ID>`; IT-09 (guarda) passando
- [x] Green: papel pelo arquivo, parse de `→ caminho::nome`, exemplo nos templates

**Fase 2: verify e G1 no commit red**
- [x] Red: IT-01, IT-02, IT-03, IT-04, IT-08
- [x] Green: coleta por branch no modo privado, avaliação comum, seção "Commits", `gate G1 --at` com worktree temporária, dica no modo completo

**Fase 3: G7 por merge, squash e rebase**
- [x] Red: IT-05, IT-06, IT-07
- [x] Green: busca do merge na base por SHA e `patch-id`
- [x] Refactor mantendo tudo verde; validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [x] `SDD_TOOL_VERSION` e CHANGELOG atualizados (ADR-0005)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e aprovação (H2)
- [x] Deploy: N/A — pilar entrega dispensado
- [x] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 38819da | 2026-10-14 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=9, errors=2, skipped=1)) — e451978 | 2026-10-14 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 71036b0 | 2026-10-14 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 71036b0 | 2026-10-14 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (modo solo) — 0 blocker/major; minor: G7 calcula patch-id de até 200 commits da base (segundos em repositório grande); detecção de scaffold no completo passou de tipo chore para assunto iniciado por chore (equivalente); TEST_DEFECTs corrigidos em commits test próprios: placeholders do lite (antes do red) e rebase sem avanço da base (21d0973) — 71036b0 | 2026-10-14 |
| G5 Integração & CI | PASS | test exit 0 (OK (skipped=1)); arch_test exit 0 (OK); nota: CI do GitHub verde no PR #3 em ee02ae2: ci 3.9 e 3.15 (run 38677000910) e sdd/pr-check (run 38677000897) — substitui o bypass local — 98d3dba | 2026-10-15 |
| H2 Integração aprovada | PASS | aprovado por thomas — autorizou os merges em 2026-10-15 ('pode ir seguindo com os merges quando tudo passar'), com G5 verde na CI do GitHub | 2026-10-15 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): a skill vale na main pelo link simbólico | 2026-10-15 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 4214e4f | 2026-10-15 |

## 13. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). -->

### O que foi entregue
Rastreio sem marcas no modo privado: commits da spec são os da branch, registrados no `spec_root` com papel, SHA e `patch-id`; red/green pelos arquivos; testes do plano por `→ caminho::nome`; G1 roda no commit red (`gate G1 --at`, também no modo completo); G7 acha a integração por merge, squash ou rebase.

### Como foi feito
Classificação de papel por `test_paths`, leitura do plano por regex e busca de integração por `git patch-id` na base; o modo completo segue com mensagens e tags (IT-09 de guarda).

### Prova de Correção
N/A

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | Dado `test_paths` padrão e commits com arquivos `[tests/a_test.py]`, `[src/a.py, tests/a_test.py]` e `[src/a.py]`, quando o papel é… | PASS | `test_private_mode.py::test_role_comes_from_the_files` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| UT-02 | Dado linhas de plano com ` | PASS | `test_private_mode.py::test_plan_line_target` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-01 | Dado o modo privado e uma branch com um commit só de teste ("adiciona teste") seguido de um commit de código ("implementa"), sem `Refs:`… | PASS | `test_private_mode.py::test_red_before_green_without_marks` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-02 | Dado o modo privado e o commit de código antes do commit de teste, quando roda `verify`, então G1 = FAIL apontando o commit fora de ordem. | PASS | `test_private_mode.py::test_green_before_red_fails` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-03 | Dado o plano apontando `tests/a_test.py::test_inexistente`, quando roda `verify`, então G1 = FAIL citando o ID do teste. | PASS | `test_private_mode.py::test_missing_planned_test_fails` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-04 | Dado uma branch já verde com um commit red anterior, quando roda `gate G1 --run --at <red>` (modo privado e modo completo), então G1 = PASS… | PASS | `test_private_mode.py::test_g1_at_red_commit_in_private_and_full_modes` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-05 | Dado a spec integrada na base por squash (`git merge --squash` + commit), quando roda `gate G7 --run` em modo privado, então a evidência… | PASS | `test_private_mode.py::test_squash` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-06 | Dado a spec integrada por rebase (commits reaplicados na base), quando roda `gate G7 --run`, então a evidência cita "rebase" e o intervalo. | PASS | `test_private_mode.py::test_rebase` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-07 | Dado a spec integrada com `git merge --no-ff`, quando roda `gate G7 --run`, então a evidência cita "merge"; e numa spec não integrada, G7 =… | PASS | `test_private_mode.py::test_merge_commit_and_missing_merge` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-08 | Dado o modo privado, quando roda `gate G1 --run` e depois `gate G2 --run`, então a spec no `spec_root` tem a seção "Commits" com papel,… | PASS | `test_private_mode.py::test_commits_are_recorded_in_the_spec_root` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| IT-09 | Dado o modo completo, quando roda `verify` com commits `test(...)`/`feat(...)` com `Refs:` e tags, então o resultado é o mesmo de hoje. | PASS | `test_private_mode.py::test_full_mode_verify_still_uses_messages_and_tags` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |
| CT-01 | Dado um `Project` em modo privado criado pela API da SPEC-0003@1, quando os comandos desta spec leem `project.private`, `project.spec_root`… | PASS | `test_private_mode.py::test_config_comes_from_the_spec_root` — CI do PR #3 em ee02ae2 (run 38677000910, ci 3.9 e 3.15) |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4) — modo solo (projeto de um mantenedor); merge aprovado por thomas (H2)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — conferidos pelos testes do plano e pela CI
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: pilar entrega dispensado; vale na `main` pelo link simbólico
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — rollback por revert do merge; ferramenta de linha de comando sem telemetria
- [x] Documentação raiz e CHANGELOG atualizados (G7)
- [x] Pendências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado): passa a valer na `main` com o merge do PR #3, pelo link simbólico `~/.claude/skills/sdd-management`. Versão da ferramenta 2026.10.8. Rollback: revert do merge.

### Pendências
Nenhuma. A cópia `tools/sdd` é atualizada em PR próprio depois do merge (ADR-0005).

## 15. Emendas
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
