---
id: SPEC-0058
title: Hook de início de sessão e comando de entrada única do plugin
tier: full
type: feature
user_facing: true
status: proposed
created: 2026-11-13
parent: SPEC-0031
depends_on: [SPEC-0053, SPEC-0054]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [hooks/**, commands/**, tests/plugin/test_session_start.py, tests/plugin/test_plugin.py, tests/plugin/check_plugin_version.py, tests/plugin/test_plugin_version.py, .claude-plugin/plugin.json, README.md]
adrs: [ADR-0016, ADR-0017]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0058 — Hook de início de sessão e comando de entrada única do plugin

## 1. Visão Geral
O plugin `fermion` passa a fazer duas coisas sozinho no Claude Code. Um hook `SessionStart` (`hooks/hooks.json` → `hooks/session_start.py`, stdlib) coloca no contexto, ao abrir, retomar, limpar ou compactar a sessão:
- o `status` do SDD, quando o projeto usa a `gluon-spec`;
- uma linha dizendo que o atlas da organização (`boson-atlas`) está configurado, quando está;
- uma linha dizendo que o segundo cérebro (`photon-brain`) está configurado, quando está.

O comando `/fermion:deliver <tarefa>` (`commands/deliver.md`) encadeia o fluxo: contexto do atlas, depois spec e aprovação, implementação e PR pela `gluon-spec`. O usuário pede a tarefa uma vez, sem chamar cada skill.

## 2. Motivação & Escopo
**Motivação:** frente 2 do épico SPEC-0031. Hoje o agente só sabe do SDD e do atlas se alguém carregar a skill; depois de um resumo de contexto, o processo depende da memória do modelo. Um hook de início de sessão põe o estado real (o `status`) no contexto todo começo de sessão, que é a regra "rode `status` antes de cada passo" aplicada fora do modelo. O comando de entrada única é atalho: a lógica continua nas skills.

**Objetivos (dentro do escopo):**
- `hooks/hooks.json` com um hook `SessionStart` (matcher `startup|resume|clear|compact`), forma exec: `python3` com `${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py`.
- `hooks/session_start.py`: lê o JSON do stdin (`cwd`), roda só comandos de leitura das CLIs do próprio plugin e imprime `hookSpecificOutput.additionalContext`.
- `commands/deliver.md`: comando `/fermion:deliver` com `argument-hint` e o roteiro de encadeamento.
- A guarda de componentes na raiz (SPEC-0053:UT-02) passa a aceitar exatamente `hooks/hooks.json`, `hooks/session_start.py` e `commands/deliver.md`, e passa a vigiar também `bin/`.
- A regra de versão do plugin (SPEC-0056, `tests/plugin/check_plugin_version.py`) passa a valer para mudanças em `hooks/`, `commands/`, `mcp/` e `scripts/`, além de `skills/`: sem isso, `claude plugin update` não entregaria hook, comando nem tools novas.

**Não-objetivos (fora do escopo):**
- Avisos de instalação antiga no hook (SPEC-0061, que reaproveita este hook).
- Índice completo do atlas no contexto: pode passar de 10.000 caracteres; o agente busca com a skill ou com `atlas_context`.
- Hooks em outros eventos (`PreToolUse`, `Stop`) e qualquer hook que bloqueie ou grave.
- Entrada única em outros agentes (Gemini CLI, Codex): eles usam o bloco `sdd:start` do `AGENTS.md`, como hoje.
- Projetos em modo privado (specs fora do repositório, sem `docs/specs/sdd-config.yml`): o bloco SDD não aparece; a detecção do modo privado fica para quando houver pedido.

## 3. Dependências
- **Implementações necessárias:** SPEC-0053 (o repositório é o plugin; `${CLAUDE_PLUGIN_ROOT}`), SPEC-0054 (padrão de chamada das CLIs por `subprocess`, sem shell, com timeout, que o hook copia).
- **Contratos consumidos:** N/A — o hook repassa o texto do `status` e só lê o exit code de `config --json` das outras CLIs.
- **Pré-requisitos externos:** documentação oficial do Claude Code lida em 2026-11-13: code.claude.com/docs/en/plugins-reference (`hooks/hooks.json` com o invólucro `"hooks"`, `commands/` como pasta padrão, `${CLAUDE_PLUGIN_ROOT}` em `command` e `args`) e code.claude.com/docs/en/hooks (`SessionStart` com matchers `startup`, `resume`, `clear`, `compact` e `fork`; `hookSpecificOutput.additionalContext`; limite de 10.000 caracteres por valor; seção "Exec form and shell form": com `args` presente, `command` é resolvido no PATH e executado sem shell, cada item de `args` é um argumento e `${CLAUDE_PLUGIN_ROOT}` é substituído; exit diferente de 0 e de 2 não bloqueia).

## 4. Decisão Arquitetural
**Contexto:** brownfield. Referências: `mcp/fermion_mcp.py` (`run_cli`: lista de argumentos, sem shell, timeout, `check=False`; raiz do plugin por `Path(__file__)`, nunca pelo cwd) e `mcp/tests/test_architecture.py` (regras do ADR-0017 testadas contra exemplo e contra o código real).

**Decisão:** um script stdlib por evento em `hooks/`, chamado em forma exec. O script nunca importa código das skills: chama `skills/gluon-spec/scripts/spec_graph.py status`, `skills/boson-atlas/scripts/atlas.py config --json` e `skills/photon-brain/scripts/brain.py config --json` como processos, com `cwd` igual ao `cwd` recebido no stdin (o `status` usa a pasta do projeto). É a regra do ADR-0017 (camada fina sobre as CLIs) aplicada ao hook. O comando é Markdown puro em `commands/`, sem script.

**Justificativa:** a CLI continua a fonte da verdade (ADR-0001); exec sem shell evita problemas de aspas em caminhos com espaço; um hook que nunca falha (exit 0 sempre) não atrapalha o início da sessão.

**Desvio do padrão existente:** a SPEC-0053 proibia `hooks/` e `commands/` na raiz para nada ser carregado fora do contrato. Esta spec põe os dois no contrato, com a lista exata de arquivos (Emenda v4 da SPEC-0053, aprovada junto com esta spec).

**Alternativas descartadas:** shell script com `jq` (dependência externa e quebra no Windows); skill nova `fermion-deliver` em `skills/` (a SPEC-0055 fixa exatamente três skills, e a entrada única é atalho, não capacidade nova); hook do tipo `mcp_tool` chamando o servidor `fermion` (a documentação diz que hooks `mcp_tool` no `SessionStart` de abertura são ignorados porque o MCP ainda não subiu); colocar o índice do atlas inteiro (passa do limite de 10.000 caracteres e gasta contexto à toa).

**ADRs:** ADR-0016 (o repositório é o plugin), ADR-0017 (camada fina sobre as CLIs).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** timeout de 10 s por CLI e de 20 s no total; medido no IT-01 (hook completo em menos de 5 s num projeto de fixture).
- **Segurança:** só comandos de leitura; nada do ambiente, nenhum argumento vindo do stdin além do `cwd` (que só vira `cwd` do processo, nunca argumento); sem shell; nenhum valor de credencial no contexto (o `status` e o `config --json` não mostram segredo, e do `config` só o exit code é usado).
- **Privacidade e dados pessoais:** N/A — só o estado das specs do projeto aberto entra no contexto.
- **Disponibilidade e resiliência:** o hook sempre sai com 0; CLI ausente, timeout, JSON inválido no stdin ou `cwd` inexistente viram uma linha omitida e uma linha de diagnóstico no stderr.
- **Acessibilidade (UI):** N/A — sem interface.
- **Custo:** contexto limitado a 8.000 caracteres (abaixo do limite de 10.000 do Claude Code).

## 6. Artefato A — Contrato
**Interface:** `hooks/hooks.json`, `hooks/session_start.py` (stdin/stdout do hook `SessionStart`) e o comando `/fermion:deliver`

```text
hooks/hooks.json
  {"hooks": {"SessionStart": [{"matcher": "startup|resume|clear|compact",
     "hooks": [{"type": "command", "command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py"], "timeout": 30}]}]}}

hooks/session_start.py
  stdin: JSON do hook (usa só "cwd"; JSON inválido ou sem "cwd" → usa o cwd do processo)
  raiz do plugin: a pasta acima de hooks/ (Path(__file__)), nunca o cwd
  projeto: a primeira pasta, do cwd para cima, que contém .git (arquivo ou pasta), como o find_root da gluon-spec; sem .git, o próprio cwd (nenhum processo além das três CLIs)
  blocos, nesta ordem, cada um só quando a condição vale:
    SDD    projeto tem docs/specs/sdd-config.yml
           → "## SDD (gluon-spec)\n" + stdout de `spec_graph.py status` (cwd = projeto), cortado em 6.000 caracteres com "… (cortado; rode `status`)"
    Atlas  `atlas.py config --json` sai com 0
           → "Atlas da organização (boson-atlas) configurado nesta máquina: para contexto de sistemas, use a skill boson-atlas ou a tool MCP atlas_context."
    Brain  `brain.py config --json` sai com 0
           → "Segundo cérebro (photon-brain) configurado nesta máquina: para notas e decisões do usuário, use a skill photon-brain."
  stdout: sem bloco → nada (exit 0); com bloco →
    {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<blocos separados por linha em branco, no máximo 8.000 caracteres>"}}
  exit: sempre 0. Falha de uma CLI (ausente, timeout de 10 s, exit fora do esperado) → bloco omitido + uma linha "session_start: <bloco> indisponível (<motivo curto>)" no stderr
  `status` com exit diferente de 0 → bloco SDD com a primeira linha do stderr ("status falhou: …"), porque a spec quebrada é informação útil

commands/deliver.md   (/fermion:deliver)
  frontmatter: description (uma linha), argument-hint: "<tarefa>"
  corpo, em ordem:
    1. tarefa = $ARGUMENTS; vazio → pedir a tarefa e parar
    2. se o atlas estiver configurado: carregar a skill boson-atlas e montar o contexto da tarefa (`context`)
    3. carregar a skill gluon-spec e seguir o `status`: DISCOVER → SPEC (G0) → parar no H1 e pedir "Aprovado" → executar → PR
    4. nunca aprovar H1/H2 nem fazer merge sem o "sim" explícito do usuário
```

**Design:** N/A — sem interface gráfica; o comando aparece no menu `/` do Claude Code.

**Arquivos/módulos afetados:** ver `touches`. Criar `hooks/hooks.json`, `hooks/session_start.py`, `commands/deliver.md`, `tests/plugin/test_session_start.py`; alterar `tests/plugin/test_plugin.py` (guarda da raiz: lista exata), `.claude-plugin/plugin.json` (versão) e `README.md` (seção do plugin).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Projeto com SDD | `docs/specs/sdd-config.yml` presente | bloco SDD com o stdout do `status` | UT-01, IT-01 |
| Projeto sem SDD, nada configurado | sem `sdd-config.yml`; `config` sai com 3 | stdout vazio, exit 0 | UT-02 |
| Atlas e cérebro configurados | `config --json` sai com 0 | as duas linhas fixas, nessa ordem | UT-03 |
| Corte de tamanho | `status` com 20.000 caracteres | bloco SDD com 6.000 e o aviso; total até 8.000 | UT-04 |
| Falha de CLI | CLI ausente, timeout, exit inesperado; `status` com exit 1 | bloco omitido e linha no stderr, exit 0; `status` com erro vira a primeira linha do stderr | UT-05 |
| Stdin ruim | JSON inválido, sem `cwd`, `cwd` inexistente | usa o cwd do processo ou omite o SDD; exit 0 | UT-06 |
| Fronteira com as CLIs | código do hook | só stdlib; nenhum import de `skills/`; processos só das três CLIs, sem shell | UT-07 |
| Contrato do plugin | `hooks/hooks.json`, `commands/deliver.md` e guarda da raiz | forma exec com `${CLAUDE_PLUGIN_ROOT}`; frontmatter e roteiro do comando; só os arquivos do contrato na raiz | UT-08 |
| Versão do plugin | mudança em `hooks/`, `commands/`, `mcp/` ou `scripts/` sem subir a versão | achado na CI, como para `skills/` | UT-09 |
| Instalação com hook e comando | plugin instalado numa configuração isolada | cópia instalada traz hook e comando; o hook rodado como o `hooks.json` declara devolve o `status` | E2E-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — código novo; a guarda da raiz (SPEC-0053:UT-02) já está coberta e muda junto com o contrato.

### 7.2 Testes Unitários
- **UT-01** — Dado um projeto temporário com `docs/specs/sdd-config.yml` e um executor falso cujo `status` devolve `SPEC-0001 proposed`, quando o hook monta a saída, então o JSON tem `hookEventName: "SessionStart"` e `additionalContext` começando por `## SDD (gluon-spec)` com esse texto, e o `status` foi chamado com `cwd` igual à raiz do projeto.
- **UT-02** — Dado um projeto sem `sdd-config.yml` e as duas `config` saindo com 3, quando o hook roda, então o stdout é vazio e o exit é 0.
- **UT-03** — Dado `atlas.py config --json` e `brain.py config --json` saindo com 0, quando o hook roda, então o contexto traz as duas linhas fixas do contrato, a do atlas antes da do cérebro, e nenhum texto do stdout dessas CLIs.
- **UT-04** — Dado um `status` com 20.000 caracteres, quando o hook monta o contexto, então o bloco SDD tem no máximo 6.000 caracteres e termina com o aviso de corte, e o `additionalContext` inteiro tem no máximo 8.000.
- **UT-05** — Dados um executor que levanta `FileNotFoundError`, um que levanta `TimeoutExpired`, `config` saindo com 2 e `status` saindo com 1 e stderr `erro: x`, quando o hook roda, então os blocos das duas primeiras e da `config` somem com uma linha `session_start: … indisponível` no stderr, o bloco SDD traz `status falhou: erro: x`, e o exit é sempre 0.
- **UT-06** — Dados stdin `{`, stdin `{}` e `{"cwd": "/nao/existe"}`, quando o hook roda, então não levanta exceção, sai com 0 e, no último caso, não tem bloco SDD.
- **UT-07** — Dados o código de `hooks/session_start.py` e exemplos que violam as regras, quando as regras rodam, então acusam import fora da stdlib ou de `skills/`, `shell=True` e processo que não seja uma das três CLIs (inclusive `git`); o código real não tem achado. As regras ficam em `tests/plugin/` e o Architect inclui o arquivo no `arch_test` do `sdd-config.yml` no G1, para o G3 rodá-las.
- **UT-08** — Dado o repositório, quando o contrato do plugin é conferido, então `hooks/hooks.json` é exatamente o do contrato (invólucro `hooks`, matcher, forma exec, `${CLAUDE_PLUGIN_ROOT}`); `commands/deliver.md` tem `description` e `argument-hint`, cita `$ARGUMENTS`, `boson-atlas`, `gluon-spec` e a parada no H1; e na raiz só existem `hooks/hooks.json`, `hooks/session_start.py` e `commands/deliver.md` entre as pastas de componente, agora com `bin/` vigiada (guarda da SPEC-0053:UT-02 com a lista exata).
- **UT-09** — Dado um repositório temporário com uma mudança só em `hooks/`, outra só em `commands/`, outra só em `mcp/` e outra só em `scripts/`, todas sem subir a versão do `plugin.json`, quando `check_plugin_version.py --base` roda, então cada uma tem o achado de versão; uma mudança só em `docs/` não tem achado.

### 7.3 Testes de Integração
- **IT-01** — Dado um projeto temporário criado com a CLI real da `gluon-spec` (`git init` e uma spec criada com `new`) e `ATLAS_CONFIG_HOME` e a configuração do cérebro apontando para pastas vazias, quando `hooks/session_start.py` roda como processo real com o JSON do hook no stdin, então o `additionalContext` contém o stdout do `spec_graph.py status` rodado na mesma pasta, não tem as linhas do atlas e do cérebro, e o processo termina com 0 em menos de 5 s.

### 7.4 Testes de Contrato
- N/A — o hook repassa o texto do `status` sem interpretar; a igualdade com a CLI é provada no IT-01.

### 7.5 Testes E2E
- **E2E-01** — [jornada: início de sessão com o plugin] Dado o Claude Code CLI no PATH e uma configuração isolada (mesmo isolamento do SPEC-0053:E2E-01: `HOME`, `CLAUDE_CONFIG_DIR` e `XDG_CONFIG_HOME` temporários), quando o marketplace é adicionado e o plugin `fermion` instalado, então `claude plugin validate .` passa, a cópia instalada contém `hooks/hooks.json` e `commands/deliver.md`, e o comando declarado no `hooks.json` instalado, com `${CLAUDE_PLUGIN_ROOT}` trocado pelo `installPath`, rodado num projeto de fixture com SDD, devolve o `additionalContext` com o `status`. Sem `claude` no PATH o teste é pulado com o motivo (como o SPEC-0053:E2E-01).

### 7.6 Outros
- G4 manual (obrigatório, porque o E2E-01 roda o comando do hook mas não prova que o Claude Code o executa): numa sessão real do Claude Code com o plugin instalado, `claude --debug` mostra o hook `SessionStart` do `fermion` terminando com 0, o contexto inicial traz o bloco SDD e `/fermion:deliver` aparece no menu `/`. Se o Claude Code instalado não aceitar `args`, o `hooks.json` volta para a forma de texto `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py"` por emenda.

**Dublês e dados de teste:** executor de processo substituível nos UT (como `Server(runner=...)` do `mcp/fermion_mcp.py`); projetos e configurações em pastas temporárias; nunca o `~/.claude`, o `~/.claude.json` nem as configurações reais do atlas e do cérebro.

**Ambiente de execução:** local e CI, sem rede; o E2E-01 roda onde houver `claude` no PATH (local no G4 e no G5).

## 8. Plano de Rollout
- **Estratégia:** deploy direto: hook e comando chegam com `claude plugin update` (versão do plugin sobe, regra da SPEC-0056).
- **Dados/schema:** N/A.
- **Compatibilidade:** quem usa as skills por cópia não é afetado; agentes sem hooks ignoram as pastas.
- **Observabilidade:** stderr do hook (log de debug do Claude Code) com uma linha por bloco indisponível.
- **Rollback:** reverter o merge; o usuário pode desligar o plugin em `/plugin` sem perder as skills por cópia.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] O hook põe o índice do atlas no contexto? — Não: só a linha de que o atlas está configurado; o índice pode passar de 10.000 caracteres e o agente busca com `atlas_context` (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)
- [x] Entrada única como comando (`commands/`) ou como skill nova? — Comando `/fermion:deliver`: a SPEC-0055 fixa três skills e a entrada única é atalho (recomendação do arquiteto, aceita no piloto automático, thomas, 2026-11-13; revisável no H1)
- [x] O E2E precisa de uma sessão real com o modelo? — Não: o E2E-01 prova instalação e o hook como o Claude Code o chama; a sessão real com o modelo é conferida no G4, porque depende de credencial e não é determinística (recomendação do arquiteto, aceita no piloto automático, thomas, 2026-11-13; revisável no H1)

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0058`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
