---
id: SPEC-0004
title: Checagem de vazamento
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-14
parent: SPEC-0002
depends_on: []
consumes_contract: [SPEC-0003@1]
contract_version: 2
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, skills/sdd-management/assets/hooks/**, CHANGELOG.md]
adrs: [ADR-0006]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0004 — Checagem de vazamento

## 1. Visão Geral
Cria o `leak-check`: procura marcas do SDD (IDs de spec e ADR, tags de teste, títulos das seções dos templates, o caminho do `spec_root` e padrões do usuário) em tudo o que vai para o time — linhas adicionadas no diff, mensagens de commit, nome da branch. Em modo privado, ele roda dentro de `worktree --create` (que passa a gerar nomes de branch neutros) e dos gates G4/G5, e um hook local de pre-push o executa antes de cada push quando o time não usa gerenciador de hooks.

## 2. Motivação & Escopo
**Motivação:** sem uma checagem automática, uma única linha `// ver SPEC-0003` escrita por um agente expõe o processo (ADR-0006). O controle não pode depender de o modelo lembrar.

**Objetivos (dentro do escopo):**
- Comando `leak-check` com as fontes: staged, intervalo de commits, arquivo de mensagem, nome de branch.
- Padrões padrão + `leak_patterns` e `leak_allow` no sdd-config do `spec_root`.
- Hook local `pre-push` instalado pelo `private init` só quando seguro; aviso quando não.
- `worktree --create` em modo privado: branch `<tipo>/<slug>` e pasta `<worktree_dir>/<slug>`, sem ID de spec.
- `gate G4 --run` e `gate G5 --run` em modo privado incluem o `leak-check` da branch; vazamento = FAIL.

**Não-objetivos (fora do escopo):**
- Checar o corpo do PR (fica no `pr` da SPEC-0006, que chama este `leak-check`).
- Reescrever histórico com vazamento (o comando aponta; corrigir é do usuário).
- Detectar uso de IA (ADR-0006).

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** SPEC-0003@1 — modo do `Project` (privado ou completo), `spec_root` e o sdd-config dele.
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** projeto existente. Segue o padrão `cmd_<nome>` e o estilo de achados de `verify`/`pr-check` (linhas `[GRUPO] NÍVEL mensagem` e resultado no fim, `spec_graph.py:1997`, `:2714`). Hooks vivem em `assets/hooks/` e são escritos pelo `vendor` (`:2850`).

**Decisão:** uma função pura `leak_findings(texto, origem, padrões, permitidos)` e um `cmd_leak_check` que coleta as fontes com `git`. O hook novo `assets/hooks/pre-push-leak` só chama `spec_graph.py leak-check --range` com o intervalo recebido do git. A instalação usa `git rev-parse --git-path hooks` (funciona em worktrees).

**Justificativa:** função pura testável sem git; o hook não tem lógica própria, só repassa ao script (mesma regra do resto da skill).

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** hook `commit-msg` (também bloquearia commits locais de trabalho, e o time pode ter o seu); checar só no push (tarde demais para o nome da branch e os gates).

**ADRs:** ADR-0006.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `leak-check` de um intervalo de 50 commits em menos de 2 s — medido num teste de integração com 50 commits.
- **Segurança:** o hook só chama o script com argumentos vindos do git; padrões do usuário são regex compiladas, nunca executadas como comando.
- **Privacidade e dados pessoais:** os achados citam arquivo, linha e trecho curto (até 80 caracteres); nada é gravado fora do terminal.
- **Disponibilidade e resiliência:** regex inválida em `leak_patterns` → exit 2 citando o padrão (nunca ignora em silêncio).
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** comando `leak-check`, chaves `leak_patterns`/`leak_allow`, hook `pre-push`, nomes de branch em modo privado, achado nos gates.

```text
spec_graph.py leak-check [--staged] [--range A..B] [--message FILE] [--branch NOME]
  sem fonte: --staged + branch atual + intervalo <base_branch>..HEAD
  modo completo: exit 0, "modo completo: nada a checar"
  achado:  [LEAK] FAIL <origem>:<linha> — <padrão> — "<trecho>"
           origem = arquivo (linhas adicionadas no diff) | commit <sha7> (assunto/corpo) | branch | mensagem
  exit 0 sem achados; 1 com achados; 2 em erro (regex inválida, intervalo inexistente)

Padrões padrão (sempre ativos em modo privado):
  \bSPEC-\d{4,}\b   \bSPEC-\d{4,}:[A-Z0-9]+-\d+\b
  IDs de ADR que existem no spec_root (ADR-NNNN do time, fora do spec_root, não é achado)  [emenda v2]
  títulos dos templates: "Mapa de Comportamentos", "Registro de Gates", "Relatório de Entrega",
    "Registro de Impedimentos", "Questões em Aberto", "Definição de Pronto"
  "sdd-config", e o caminho do spec_root (absoluto e com ~)
sdd-config do spec_root:
  leak_patterns: [regex, ...]   (extras do usuário, ex.: codinomes internos)
  leak_allow:    [regex, ...]   (trechos que casam com um padrão mas são legítimos; testado contra o trecho achado)

Hook (private init): <git-path hooks>/pre-push → "spec_graph.py leak-check --range <remoto>..<local>" por ref empurrada
  instalado só se: não há core.hooksPath, .husky/, lefthook.yml/.lefthook.yml, .pre-commit-config.yaml, nem pre-push existente
  senão: aviso "hooks do time detectados (<qual>): o leak-check roda dentro de worktree/gate/pr"
  push com achado → exit 1 (o git cancela); escape do próprio git: --no-verify

worktree SPEC-X [--create] em modo privado:
  branch "<tipo convencional da spec>/<slug>" (ex.: feat/multiplos-cartoes); pasta "<worktree_dir>/<slug>"
  conflito de nome → sufixo "-2", "-3"
gate G4|G5 --run em modo privado: roda leak-check do intervalo da branch; achado → FAIL "vazamento: <n> achado(s)"
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. Novo: `assets/hooks/pre-push-leak`. `spec_graph.py`: `leak_findings`, `cmd_leak_check`, instalação do hook em `cmd_private`, nomes em `cmd_worktree`, achado em `cmd_gate`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Padrões padrão | texto com ID de spec, tag, título de seção, caminho do spec_root | um achado por ocorrência, com linha | UT-01 |
| Padrões do usuário e permitidos | `leak_patterns` com codinome; `leak_allow` cobrindo um trecho | codinome achado; trecho permitido ignorado | UT-02 |
| Texto limpo | código comum, inclusive `IT-01` isolado ou "spec" em minúscula | nenhum achado | UT-03 |
| ADR do time | `ADR-0001` que não existe no spec_root; `ADR-0001` que existe | não é achado; é achado | IT-11 |
| Regex inválida | `leak_patterns` com regex quebrada | exit 2 citando o padrão | IT-08 |
| Diff staged | comentário com ID de spec num arquivo staged | exit 1, achado `arquivo:linha` | IT-01 |
| Mensagem de commit | commit com `Refs: SPEC-0003` no intervalo | exit 1, achado `commit <sha7>` | IT-02 |
| Nome de branch | branch `sdd/SPEC-0003-x` | exit 1, achado `branch` | IT-03 |
| Push | hook instalado, push com vazamento / push limpo | push recusado / push aceito | IT-04 |
| Hooks do time | `core.hooksPath` definido ou `.husky/` presente | hook não instalado, aviso | IT-05 |
| Worktree neutra | `worktree --create` em modo privado | branch `feat/<slug>`, sem ID | IT-06 |
| Gate com vazamento | `gate G4 --run` com commit vazado | G4 = FAIL citando vazamento | IT-07 |
| Modo completo | `leak-check` sem modo privado | exit 0, mensagem informativa | IT-09 |
| Desempenho | 50 commits no intervalo | menos de 2 s | IT-10 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — comportamento novo; `worktree` no modo completo continua coberto pelos testes existentes (`test_default_path_is_outside_repo_and_create_works`).

### 7.2 Testes Unitários
- **UT-01** — Dado um texto com `SPEC-0003`, `ADR-0006` (existente no spec_root), `SPEC-0003:UT-01`, "Mapa de Comportamentos" e o caminho do `spec_root`, quando `leak_findings` roda com os padrões padrão, então há um achado por linha, cada um com a linha certa.
- **UT-02** — Dado `leak_patterns: ["\\bProjetoFenix\\b"]` e `leak_allow: ["SPEC-0000-exemplo"]`, quando `leak_findings` roda sobre um texto com "ProjetoFenix" e "SPEC-0000-exemplo", então acha só "ProjetoFenix".
- **UT-03** — (guarda: passa antes da mudança) Dado um trecho de código comum com `IT-01`, "spec" em minúscula e `ADR` sem número, quando `leak_findings` roda, então não há achados.

### 7.3 Testes de Integração
- **IT-01** — Dado o modo privado ligado e um arquivo staged com `// ver SPEC-0003`, quando roda `leak-check --staged`, então sai com 1 e o achado cita `arquivo:linha`.
- **IT-02** — Dado um commit com `Refs: SPEC-0003` no intervalo, quando roda `leak-check --range main..HEAD`, então sai com 1 citando `commit <sha7>`.
- **IT-03** — Dado a branch atual `sdd/SPEC-0003-x`, quando roda `leak-check --branch sdd/SPEC-0003-x`, então sai com 1 citando `branch`.
- **IT-04** — Dado o modo privado ligado com o hook instalado e um remoto bare, quando faz `git push` de um commit com `SPEC-0003` na mensagem, então o push é recusado; e um push limpo é aceito.
- **IT-05** — Dado um repositório com `core.hooksPath` definido (e outro com `.husky/`), quando roda `private init`, então nenhum hook é escrito e a saída avisa qual gerenciador foi detectado.
- **IT-06** — Dado o modo privado ligado e uma spec com título "Múltiplos cartões" e `type: feature`, quando roda `worktree SPEC-0001 --create`, então a branch é `feat/multiplos-cartoes` e nem a branch nem a pasta contêm "SPEC".
- **IT-07** — Dado o modo privado ligado e uma branch com um commit que cita `SPEC-0001`, quando roda `gate SPEC-0001 G4 --run`, então G4 = FAIL com "vazamento" na evidência.
- **IT-08** — Dado `leak_patterns: ["(quebrada"]`, quando roda `leak-check`, então sai com 2 citando o padrão.
- **IT-09** — (guarda: passa antes da mudança) Dado o modo completo, quando roda `leak-check`, então sai com 0 e informa "modo completo".
- **IT-10** — Dado um intervalo com 50 commits limpos, quando roda `leak-check --range`, então termina em menos de 2 s.
- **IT-11** — Dado o modo privado com `ADR-0001` criado no spec_root, quando um arquivo staged cita `ADR-0002` (ADR do time) e outro cita `ADR-0001`, então só `ADR-0001` é achado.

### 7.4 Testes de Contrato
- **CT-01** — Dado um `Project` em modo privado criado pela API da SPEC-0003@1, quando os comandos desta spec leem `project.private`, `project.spec_root` e `project.config_path`, então usam esses valores (e não caminhos fixos) — verificado com um registro de teste e um `spec_root` fora do repositório.

### 7.5 Testes E2E
- N/A — a jornada do usuário é a CLI e, conforme o ADR-0002, é coberta por testes de integração; a jornada privada completa é o IT-05 da SPEC-0006.

### 7.6 Outros
- Desempenho: IT-10.

**Dublês e dados de teste:** repositórios temporários com remoto bare; registro e `spec_root` no diretório do teste (como na SPEC-0003).

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** merge direto; só atua em modo privado.
- **Dados/schema:** chaves opcionais novas no sdd-config do `spec_root` (`leak_patterns`, `leak_allow`).
- **Compatibilidade:** modo completo inalterado (IT-09 e suíte existente); `worktree` no modo completo mantém `sdd/<spec>-<slug>`.
- **Observabilidade:** achados no terminal; FAIL registrado no gate.
- **Rollback:** `git revert` do merge; hook removível apagando `.git/hooks/pre-push`.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Checar também `IT-01`, `UT-01` soltos? — Não: são comuns em código de qualquer time; só a tag completa `SPEC-NNNN:<ID>` (proposta do Architect, confirmada no H1 por thomas, 2026-10-14)
- [x] Hook `commit-msg` além do `pre-push`? — Não: só pre-push, para não bloquear commits locais de trabalho nem disputar com o hook do time (proposta do Architect, confirmada no H1 por thomas, 2026-10-14)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação

**Fase 1: Padrões**
- [ ] Red: UT-01, UT-02 e CT-01 com a tag `SPEC-0004:<ID>`; UT-03 (guarda) passando
- [ ] Green: `leak_findings` com padrões padrão, `leak_patterns` e `leak_allow`

**Fase 2: Comando e fontes**
- [ ] Red: IT-01, IT-02, IT-03, IT-08, IT-10; IT-09 (guarda) passando
- [ ] Green: `leak-check` (staged, range, message, branch), regex inválida = exit 2

**Fase 3: Integrações**
- [ ] Red: IT-04, IT-05, IT-06, IT-07
- [ ] Green: hook `assets/hooks/pre-push-leak` e instalação segura no `private init`, branch neutra no `worktree`, leak-check no G4/G5
- [ ] Refactor mantendo tudo verde; validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] `SDD_TOOL_VERSION` e CHANGELOG atualizados (ADR-0005)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e aprovação (H2)
- [ ] Deploy: N/A — pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 5c7f2c8 | 2026-10-14 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=13, skipped=1)) — ab5c4d3 | 2026-10-14 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — 683519f | 2026-10-14 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 683519f | 2026-10-14 |
| G4 Review | FAIL | verify G1+G4: PASS; revisão: CHANGES_REQUESTED (modo solo) — major: padrão padrão ADR-\d{4,} reprova as ADRs do próprio time (comuns em repositórios corporativos) e bloquearia pushes legítimos; minor: leak_scan valida leak_allow chamando leak_findings vazio; minor: IT-09 marcado como guarda mas o comando é novo — 683519f | 2026-10-14 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-14 | G4 | spec | Contrato manda reprovar qualquer ADR-NNNN; times com ADRs próprias teriam falso positivo em todo push. Proposta: ID de ADR só reprova se o ADR existir no spec_root (ADRs do SDD do usuário); ID de spec continua genérico (SPEC-NNNN raramente é usado por times) | revisão do diff e do contrato; leak_allow resolveria caso a caso, mas o padrão precisa ser seguro por omissão | Architect + thomas | Emenda v2 — ID de ADR só é achado se existir no spec_root; aprovada por thomas em 2026-10-14 | 2026-10-14 |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). -->

### O que foi entregue

### Como foi feito

### Prova de Correção

### Verificação
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
- [ ] Pendências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 15. Emendas
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-10-14 | ID de ADR só é achado se o ADR existir no spec_root; UT-01 ajustado, IT-11 novo | IMP-01: times com ADRs próprias teriam falso positivo em todo push | Nenhuma | thomas, 2026-10-14 |
