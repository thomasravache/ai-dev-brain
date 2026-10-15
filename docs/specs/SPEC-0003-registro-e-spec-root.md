---
id: SPEC-0003
title: Registro do usuário e spec_root
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-10-14
parent: SPEC-0002
depends_on: []
consumes_contract: []
contract_version: 1
touches: [skills/sdd-management/scripts/spec_graph.py, skills/sdd-management/tests/**, CHANGELOG.md]
adrs: [ADR-0006, ADR-0001]
external: []
size: M
approved_by: thomas
approved_at: 2026-10-14
---

# SPEC-0003 — Registro do usuário e spec_root

## 1. Visão Geral
Cria o liga/desliga do modo privado por repositório: um registro do usuário (`projects.json`, fora de qualquer repositório) e o comando `private`. Com o modo ligado, todos os comandos passam a ler e gravar specs, ADRs, sdd-config e INDEX numa pasta externa (`spec_root`) versionada por um git local próprio, e nada é escrito no repositório do time. Sem entrada no registro, nada muda.

## 2. Motivação & Escopo
**Motivação:** é a base do modo privado (ADR-0006): sem ela, a skill só sabe gravar dentro do repositório. As outras filhas consomem o modo e o `spec_root` definidos aqui.

**Objetivos (dentro do escopo):**
- Localização e formato do registro; normalização do remoto.
- `private init | status | off`.
- `Project` resolve os caminhos pelo modo; aviso de modo privado em todo comando.
- Commit automático no git do `spec_root` depois de cada comando que grava registros; push com `sync: push`.
- `vendor` e `pr-check` se recusam em modo privado; `init` se recusa num repositório que já versiona `docs/specs`.

**Não-objetivos (fora do escopo):**
- `leak-check` e hook (SPEC-0004); rastreio de commits (SPEC-0005); `pr` neutro e detecção das convenções do time (SPEC-0006).
- Migrar specs de um repositório em modo completo para o privado (ou o contrário).
- Apagar o `spec_root` no `private off`.

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A — só `git` e a biblioteca padrão.

## 4. Decisão Arquitetural
**Contexto:** projeto existente. `Project.__init__` (`spec_graph.py:459`) fixa `docs/specs` e `docs/adr`; `find_root` (`:573`) acha a raiz pelo `.git`; os comandos seguem o padrão `cmd_<nome>(project, ...)` despachado em `main()` (`:3140`). Testes seguem `Project` de `tests/test_spec_graph.py` (repositório git temporário + CLI por `subprocess`).

**Decisão:** uma função `resolve_mode(root)` lê o registro e devolve modo, `spec_root` e `sync`; `Project` usa o resultado para `specs_dir`, `adr_dir` e o caminho do sdd-config. Um helper `commit_records(project, mensagem)` é chamado no fim dos comandos que gravam. `cmd_private` segue o padrão dos outros comandos.

**Justificativa:** concentra a decisão de modo num ponto só (`Project`), então os comandos existentes continuam iguais e passam a funcionar nos dois modos.

**Desvio do padrão existente:** Nenhum. Registro em JSON (biblioteca padrão) conforme ADR-0006.

**Alternativas descartadas:** passar `--spec-root` em cada comando (fácil de esquecer — vazaria na primeira vez); variável de ambiente por sessão (não sobrevive a nova sessão).

**ADRs:** ADR-0006, ADR-0001.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** resolver o modo custa uma leitura de arquivo e um `git remote get-url`; sem medição dedicada — a suíte não pode ficar mais de 20% mais lenta (medido no G2).
- **Segurança:** o registro não guarda credenciais; caminhos com `~` são expandidos, nunca executados; `sync: push` usa a autenticação do próprio git.
- **Privacidade e dados pessoais:** o `spec_root` guarda conteúdo do time: só local por padrão (`sync: none`).
- **Disponibilidade e resiliência:** registro ausente ou JSON inválido → modo completo com aviso (nunca grava no repositório em silêncio quando o registro está ilegível — ver Mapa); falha de push → aviso, sem falhar o comando.
- **Acessibilidade (UI):** N/A — CLI sem interface gráfica.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** registro do usuário, comando `private`, resolução de modo no `Project`.

```text
Registro: <dir>/projects.json, <dir> = $SDD_CONFIG_HOME | $XDG_CONFIG_HOME/sdd | ~/.config/sdd
{
  "default_root": "~/dev/sdd",                         (opcional; padrão: $XDG_DATA_HOME/sdd ou ~/.local/share/sdd)
  "projects": {
    "github.com/org/repo": {"mode": "private", "spec_root": "~/dev/sdd/org/repo", "sync": "none"},
    "/abs/caminho/do/repo": {...}                      (repositório sem remoto)
  }
}
Chave: remoto "origin" normalizado — sem protocolo, usuário, porta e ".git"; host em minúsculas.
  git@github.com:Org/Repo.git | https://user@github.com/Org/Repo | ssh://git@github.com:22/Org/Repo.git → github.com/Org/Repo

spec_graph.py private init [--spec-root PATH] [--sync none|push]
  cria/atualiza a entrada; padrão do spec_root: <default_root>/<dois últimos segmentos da chave>
  cria spec_root/{specs/, adr/, sdd-config.yml (do template)}, roda git init e faz o commit inicial
  saída: "modo privado ativado para <chave>" + spec_root + sync
  erro (exit 2): repositório já versiona docs/specs → "este repositório usa o SDD versionado (modo completo)"
  erro (exit 2): fora de um repositório git
spec_graph.py private status   → modo, chave, spec_root, sync, mudanças sem commit e commits sem push no spec_root
spec_graph.py private off      → remove a entrada; o spec_root fica onde está (exit 0, informa o caminho)

Em modo privado (todos os comandos):
  stderr, 1ª linha: "MODO PRIVADO — nada de SDD no repositório (specs em <spec_root>)"
  specs_dir = spec_root/specs; adr_dir = spec_root/adr; config = spec_root/sdd-config.yml; INDEX em spec_root/specs
  new, new-adr, set, gate, impede, resolve, index, upgrade --apply → commit no git do spec_root ("sdd: <comando> <ids>")
    sync: push e remoto configurado no spec_root → git push; falha → aviso em stderr, exit do comando inalterado
  vendor, pr-check → exit 2: "<comando> não se aplica em modo privado"
  status → acrescenta avisos de mudanças sem commit / commits sem push no spec_root
Registro ilegível (JSON inválido) → exit 2 em qualquer comando: "registro inválido: <caminho>: <erro>" (nunca cai para o modo completo em silêncio)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. `spec_graph.py`: `resolve_mode`, `normalize_remote`, `Project`, `cmd_private`, `commit_records`, guardas em `cmd_vendor`/`cmd_pr_check`, aviso em `main()`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Normalização do remoto | URLs SSH, HTTPS e ssh:// do mesmo repositório | mesma chave `host/caminho` | UT-01 |
| Busca no registro | remoto registrado; sem remoto (caminho); arquivo ausente | entrada certa; entrada pelo caminho; modo completo | UT-02 |
| Ativação | `private init` num repositório git sem `docs/specs` | entrada no registro, `spec_root` com git e config, repositório intocado | IT-01 |
| Trabalho em modo privado | `new`, `set`, `gate`, `index` com o modo ligado | arquivos só no `spec_root`, commit no git dele, `git status` do repositório limpo, aviso em stderr | IT-02 |
| Comandos do repositório | `vendor` ou `pr-check` em modo privado | exit 2 com mensagem | IT-03 |
| Sem registro | nenhuma entrada para o repositório | comportamento idêntico ao de hoje | IT-04 |
| Worktree | comando rodado numa worktree do repositório registrado | mesmo `spec_root` | IT-05 |
| Sincronização | `sync: push` com remoto no `spec_root`; `sync: none`; push falha | push feito; nenhum push; aviso sem falhar | IT-06 |
| Repositório com SDD versionado | `private init` onde `docs/specs` está no git | exit 2 com mensagem | IT-07 |
| Registro inválido | `projects.json` com JSON quebrado | exit 2 com caminho e erro | IT-08 |
| Desativar | `private off` | entrada removida, `spec_root` preservado | IT-09 |
| Pendências no spec_root | arquivo alterado no `spec_root` sem commit | `status` e `private status` avisam | IT-06 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — o comportamento atual do modo completo já é fixado pela suíte existente (61 testes), que deve passar sem alteração; IT-04 cobre explicitamente o caso "registro existe, mas sem entrada para este repositório".

### 7.2 Testes Unitários
- **UT-01** — Dado `git@github.com:Org/Repo.git`, `https://user@github.com/Org/Repo`, `ssh://git@GitHub.com:22/Org/Repo.git` e `https://gitlab.example.com/grupo/sub/repo.git`, quando `normalize_remote` roda, então as três primeiras dão `github.com/Org/Repo` e a última `gitlab.example.com/grupo/sub/repo`.
- **UT-02** — Dado um registro com uma entrada por remoto e outra por caminho, quando `resolve_mode` consulta um repositório com aquele remoto, um sem remoto naquele caminho e um terceiro sem entrada, então devolve a entrada do remoto, a do caminho e modo completo; com o arquivo ausente, modo completo.

### 7.3 Testes de Integração
<!-- CLI real sobre git real em diretório temporário; HOME, SDD_CONFIG_HOME e XDG_* apontam para o diretório do teste. -->
- **IT-01** — Dado um repositório temporário com remoto, quando roda `private init --spec-root <tmp>/sdd/org/repo`, então o registro tem a entrada, o `spec_root` tem `specs/`, `adr/`, `sdd-config.yml` e um commit inicial, e `git status --porcelain` do repositório é vazio.
- **IT-02** — Dado o modo privado ligado, quando roda `new --tier lite`, `set`, `gate SPEC-0001 G0 --run` e `index`, então os arquivos existem só no `spec_root`, cada comando gerou um commit no git do `spec_root`, o repositório continua limpo e o stderr começa com "MODO PRIVADO".
- **IT-03** — Dado o modo privado ligado, quando roda `vendor --ci generic` e `pr-check`, então ambos saem com 2 e mensagem "não se aplica em modo privado", e nenhum arquivo é criado no repositório.
- **IT-04** — (guarda: passa antes da mudança) Dado um registro que só tem entrada para outro repositório, quando roda `new`, `validate`, `index` e `status`, então tudo vai para `docs/specs` do repositório como hoje e nada é escrito fora dele.
- **IT-05** — Dado o modo privado ligado e uma worktree do repositório, quando roda `status` dentro da worktree, então usa o mesmo `spec_root`.
- **IT-06** — Dado o `spec_root` com um remoto bare e `sync: push`, quando roda `new`, então o commit chega ao remoto; com `sync: none`, não chega; com o remoto inacessível, o comando sai com 0 e avisa; e com um arquivo alterado sem commit no `spec_root`, `status` e `private status` avisam.
- **IT-07** — Dado um repositório que versiona `docs/specs/`, quando roda `private init`, então sai com 2, a mensagem cita o modo completo e o registro não muda.
- **IT-08** — Dado `projects.json` com JSON inválido, quando roda `status`, então sai com 2 citando o caminho do registro.
- **IT-09** — Dado o modo privado ligado, quando roda `private off`, então a entrada sai do registro, o `spec_root` continua existindo e o próximo `status` volta ao modo completo.

### 7.4 Testes de Contrato
- **CT-01** — Dado o modo privado e o modo completo, quando um `Project` é criado, então expõe a API consumida por SPEC-0004/0005/0006: `project.private` (bool), `project.spec_root` (Path ou None), `project.sync` ("none"|"push"), `project.specs_dir`, `project.adr_dir`, `project.config_path` e `commit_records(project, mensagem)` — com os valores do registro no privado e os caminhos de hoje no completo.

### 7.5 Testes E2E
- N/A — a jornada do usuário é a CLI e, conforme o ADR-0002, é coberta por testes de integração; a jornada privada completa é o IT-05 da SPEC-0006.

### 7.6 Outros
- Tempo da suíte medido no G2 contra o tempo antes da mudança (RNF de desempenho).

**Dublês e dados de teste:** repositórios git temporários com remotos bare locais; registro e `spec_root` dentro do diretório do teste.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** merge direto; o modo só se ativa com `private init`.
- **Dados/schema:** registro novo, criado sob demanda; nada é migrado.
- **Compatibilidade:** sem entrada no registro, comportamento idêntico (IT-04 + suíte existente).
- **Observabilidade:** aviso "MODO PRIVADO" em stderr; `private status`.
- **Rollback:** `git revert` do merge; `private off` desliga por repositório.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Formato do registro? — JSON (`projects.json`), porque o parser de YAML da ferramenta só aceita chaves simples (ADR-0006) (proposta do Architect, confirmada no H1 por thomas, 2026-10-14)
- [x] Registro ilegível cai para o modo completo? — Não: exit 2, para nunca gravar no repositório do time por engano (proposta do Architect, confirmada no H1 por thomas, 2026-10-14)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação

**Fase 1: Registro e normalização**
- [ ] Red: UT-01, UT-02 e CT-01 com a tag `SPEC-0003:<ID>`, falhando pelo motivo certo
- [ ] Green: `normalize_remote`, `resolve_mode`, atributos do modo no `Project`

**Fase 2: Comando private e spec_root**
- [ ] Red: IT-01, IT-07, IT-08, IT-09; IT-04 (guarda) passando no código atual
- [ ] Green: `private init|status|off`, recusa com `docs/specs` versionado, registro inválido = exit 2

**Fase 3: Comandos em modo privado**
- [ ] Red: IT-02, IT-03, IT-05, IT-06
- [ ] Green: caminhos pelo modo, aviso em stderr, `commit_records` + sync, recusa de `vendor`/`pr-check`, avisos no `status`
- [ ] Refactor mantendo tudo verde; validar: suíte completa + lint + arquitetura (G2/G3); tempo da suíte ≤ +20%

**Fase final: Integração, entrega e documentação**
- [ ] `SDD_TOOL_VERSION` e CHANGELOG atualizados (ADR-0005)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e aprovação (H2)
- [ ] Deploy: N/A — pilar entrega dispensado
- [ ] Relatório de Entrega, docs raiz e CHANGELOG (G7)

## 12. Registro de Gates
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 7911562 | 2026-10-14 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests` exit 1 (red: FAILED (failures=9, errors=2, skipped=1)) — 69043a1 | 2026-10-14 |
| G2 Green | PASS | test exit 0 (OK (skipped=1)); lint exit 0 (All checks passed!) — f4b6f58 | 2026-10-14 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — f4b6f58 | 2026-10-14 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: APPROVED (modo solo) — 0 blocker/major; minor: private init aceita --spec-root dentro do repositório (fora do contrato; pendência), gravação do registro não atômica; scaffold f3c1da2 sem lógica; TEST_DEFECT do IT-02 corrigido em commit test próprio (099d22d) — 03768b0 | 2026-10-14 |
| G5 Integração & CI | PASS | MANUAL: BYPASS LOCAL (autorizado por thomas em 2026-10-14; GitHub Actions bloqueado por cobrança, IMP-02): test exit 0 e arch_test exit 0 em 5d0456d — refazer na CI do GitHub em 2026-10-15 | 2026-10-14 |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

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
