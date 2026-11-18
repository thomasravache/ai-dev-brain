---
id: SPEC-0080
title: "boson-atlas: atlas escolhido pelo remote do projeto, nas tools MCP e no início da sessão"
tier: full
type: feature
user_facing: true
status: approved
created: 2026-11-18
parent: SPEC-0077
depends_on: [SPEC-0079]
consumes_contract: [SPEC-0079@1]
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/**, skills/boson-atlas/references/config.md, skills/boson-atlas/references/modes.md, skills/boson-atlas/assets/atlas-config.yml, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, mcp/fermion_mcp.py, mcp/tests/**, mcp/README.md, hooks/session_start.py, tests/plugin/test_session_start.py, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0021]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-18
---

# SPEC-0080 — boson-atlas: atlas escolhido pelo remote do projeto, nas tools MCP e no início da sessão

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
Um projeto passa a usar o atlas da sua organização sem nenhuma opção. O `atlas-config.yml` compartilhado declara em `remotes:` os prefixos dos repositórios da organização (ex.: `github.com/acme`). A CLI casa o remote git da pasta atual com esses prefixos, no passo 3 da ordem de escolha da SPEC-0079. As tools MCP `atlas_*` ganham o parâmetro `atlas` e rodam na pasta do projeto, e o hook de início de sessão diz qual atlas vale para o projeto e por quê.

## 2. Motivação & Escopo
**Motivação:**
- Com vários atlas (SPEC-0079), lembrar de `--atlas` em toda chamada é o mesmo atrito de hoje com `ATLAS_CONFIG_HOME`.
- O agente usa o atlas pelas tools MCP e pelo hook, que hoje não dizem qual atlas usar.
- O remote do projeto já diz a qual organização ele pertence.

**Objetivos (dentro do escopo):**
- Chave opcional `remotes:` no `atlas-config.yml`, com validação, opção `init --remote` e o modelo em `assets/atlas-config.yml`.
- Passo "remote do projeto" na ordem de escolha, com `selected_by: "remote"`.
- Aviso do `doctor` quando um remote casa com mais de um atlas no mesmo comprimento.
- Parâmetro `atlas` nas cinco tools `atlas_*`, que passam a rodar a CLI na pasta do projeto.
- Linha do hook com o nome do atlas e o motivo, ou o passo quando não há escolha.

**Não-objetivos (fora do escopo):**
- O `org_context` da `gluon-spec`: SPEC-0081.
- Preencher `remotes:` sozinho a partir dos coletores. Fica no onboarding, como sugestão do `init`, em spec futura se for pedido.
- Escolher por outro sinal que não o remote `origin`, como o nome da pasta ou um arquivo no repositório.

## 3. Dependências
- **Implementações necessárias:** SPEC-0079 — a função de escolha e os pontos que a usam, nos mesmos arquivos (`atlas.py`).
- **Contratos consumidos:** SPEC-0079@1 — formato da configuração local, ordem de escolha (passo 3 reservado), `--atlas`, `ATLAS_NAME` e campos `atlas_name`/`selected_by`/`atlases` do `config --json`.
- **Pré-requisitos externos:** `git` no `PATH` para ler o remote; sem ele, o passo é pulado.

## 4. Decisão Arquitetural
**Contexto:** segue estes padrões existentes:
- a validação do arquivo compartilhado em `atlas.py` (`absolute_values`, `render_atlas_config`, `validate_ci`);
- as chamadas de leitura ao `git` que o `atlas.py` já faz no `doctor`, com `GIT_OPTIONAL_LOCKS=0` e prazo;
- as tools `sdd_*` de `mcp/fermion_mcp.py`, que já rodam no `project_dir()`;
- as linhas do `hooks/session_start.py` (`configured_line`).

**Decisão:**
- `remotes:` fica no arquivo compartilhado, porque vale para toda a organização e chega à máquina nova pelo `init --join`.
- A CLI lê o `remote.origin.url` da pasta atual e o normaliza para `host/caminho` em minúsculas, sem esquema, credenciais, porta nem `.git`.
- Escolhe o atlas cujo prefixo casa por segmentos inteiros e é o mais longo.
- As tools MCP só repassam `--atlas` e o `cwd`.
- O hook chama `config --json` na pasta da sessão e monta a linha com `atlas_name` e `selected_by`.

**Justificativa:**
- A escolha fica num ponto só, na CLI, que é testada uma vez e é igual para terminal, MCP, hook e `gluon-spec`.
- O remote é o sinal mais estável do projeto e não exige arquivo novo no repositório do time.

**Desvio do padrão existente:** nenhum. O ADR-0021 define a ordem.

**Alternativas descartadas:**
- **`remotes:` na configuração local:** cada máquina teria de repetir o mesmo dado da organização.
- **Arquivo `.boson-atlas` no repositório:** mexe no repositório do time.
- **Escolha só no hook:** o MCP e a CLI no terminal ficariam sem ela.

**ADRs:** ADR-0021, ADR-0010.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** um `git config --get remote.origin.url` por comando (prazo de 5 s; se estourar, o passo é pulado) e a leitura do `atlas-config.yml` de cada atlas configurado. O hook continua dentro dos 10 s por CLI e 20 s no total.
- **Segurança:**
  - O remote nunca sai inteiro: a normalização tira as credenciais (`https://user:token@host/...`) antes de qualquer comparação ou mensagem.
  - `remotes:` rejeita `@`, esquema, caminho absoluto e espaço (exit 2).
  - O parâmetro `atlas` das tools segue o formato de nome ou caminho, com até 200 caracteres, e vira argumento sem shell.
- **Privacidade e dados pessoais:** a linha do hook mostra só nomes de atlas e o motivo, nunca caminhos, remotes nem credenciais. `selected_by` diz `remote`, sem o remote.
- **Disponibilidade e resiliência:** pasta sem git, sem remote, com `git` ausente ou com prazo estourado → o passo é pulado, sem erro. O hook sempre sai com 0 (padrão existente).
- **Acessibilidade (UI):** N/A — CLI e MCP.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** chave `remotes:` do `atlas-config.yml`, passo 3 da ordem de escolha, `init --remote`, `doctor`, parâmetro `atlas` das tools MCP `atlas_*` e linha do hook.

```text
atlas-config.yml (compartilhado)
  remotes:                       # opcional; lista de prefixos host/caminho
    - github.com/acme
    - gitlab.acme.interno/plataforma
  Cada item: minúsculas, sem esquema, "@", ":", espaço, "..", barra no início ou no fim → senão exit 2 com o item.
  init --atlas P --org O --mode M --remote github.com/acme [--remote ...] grava a lista no atlas novo.

Passo 3 da ordem de escolha (entre ATLAS_NAME e default):
  remote = git -C <cwd> config --get remote.origin.url (GIT_OPTIONAL_LOCKS=0, prazo 5 s)
  normalização: https://u:t@GitHub.com/Acme/API.git → github.com/acme/api ; git@github.com:Acme/API.git →
    github.com/acme/api ; ssh://git@host:2222/g/r.git → host/g/r
  casa quando um item de remotes é igual ao remote ou prefixo dele por segmentos inteiros
    (github.com/acme casa github.com/acme/api; não casa github.com/acme-labs/x)
  mais de um atlas casa: vale o prefixo mais longo; empate → passo pulado (cai no default)
  config --json: "selected_by": "remote"; texto: "escolhido por: remote do projeto"
  doctor: remote da pasta que casa com mais de um atlas no mesmo comprimento → AVISO com os nomes dos atlas

MCP (mcp/fermion_mcp.py) — atlas_config, atlas_doctor, atlas_context, atlas_lint, atlas_curate_list
  novo parâmetro opcional "atlas": string, 1–200 caracteres, sem caractere de controle → "--atlas <valor>"
  todas rodam a CLI com cwd = project_dir() (CLAUDE_PROJECT_DIR ou cwd do servidor)
  exit 2 da escolha (vários atlas sem escolha) → erro da tool com a mensagem da CLI; exit 3 → NOT_CONFIGURED de hoje

Hook de início de sessão (hooks/session_start.py), bloco do atlas, a partir de config --json na pasta da sessão:
  exit 0, 1 atlas configurado → linha atual, sem mudança
  exit 0, 2+ atlas → "Atlas da organização (boson-atlas) para este projeto: <nome> (escolhido por: remote do
    projeto|ATLAS_NAME|padrão). Outros nesta máquina: <nomes>. Use a skill boson-atlas ou a tool MCP atlas_context."
  exit 2 (vários sem escolha) → "Vários atlas nesta máquina (<nomes>) e nenhum escolhido para este projeto: use
    --atlas, o parâmetro atlas das tools MCP ou declare remotes: no atlas-config.yml."
  exit 3 → nada (como hoje)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:**
- `scripts/atlas.py`: `remotes:` (validação, `init --remote`), o passo 3, o `doctor` e `ATLAS_VERSION`.
- `assets/atlas-config.yml`: o modelo comentado.
- `references/config.md` e `references/modes.md`: o onboarding com `remotes:`.
- `mcp/fermion_mcp.py` e `mcp/README.md`.
- `hooks/session_start.py`.
- Os testes, o CHANGELOG e o `plugin.json`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Remote casa | pasta com remote `github.com/acme/api`, atlas `a` com `remotes: [github.com/acme]` | `a` escolhido, `selected_by: remote` | UT-01, IT-01, E2E-01 |
| Normalização | https com credenciais, scp-like, ssh com porta, `.git`, maiúsculas | mesmo remote normalizado; credenciais nunca aparecem | UT-02 |
| Segmento inteiro e prefixo mais longo | `github.com/acme` × `github.com/acme-labs/x`; `github.com/acme` e `github.com/acme/infra` | não casa; vale o mais longo | UT-03 |
| Empate | dois atlas com o mesmo prefixo | passo pulado (vale o `default`); `doctor` avisa | UT-03, UT-06 |
| Ordem | `--atlas` ou `ATLAS_NAME` com remote que casa outro atlas | opção e ambiente vencem o remote | UT-04 |
| Sem remote | pasta sem git, sem `origin`, `git` ausente | passo pulado sem erro | UT-05 |
| `remotes:` inválido | item com esquema, `@`, espaço, `..`, absoluto | exit 2 com o item | UT-07 |
| `init --remote` | atlas novo com dois `--remote` | lista gravada no `atlas-config.yml` | UT-07 |
| MCP com atlas | `atlas_context` com `atlas: "b"` | CLI chamada com `--atlas b` | UT-08, CT-01 |
| MCP no projeto | tools sem `atlas` num projeto cujo remote casa `b` | CLI roda em `project_dir()` e usa `b` | IT-02 |
| MCP sem escolha | vários atlas, nenhum casa, sem default | erro da tool com a mensagem da CLI | UT-08 |
| Hook | 1 atlas; 2+ com escolha; 2+ sem escolha; não configurado | linha atual; linha com nome e motivo; linha do passo; nada — sem caminhos | UT-09, E2E-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dado um atlas só, quando o hook roda e as tools `atlas_*` são chamadas sem `atlas`, então a linha do hook e os argumentos passados à CLI são os de hoje (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dado o atlas `a` com `remotes: [github.com/acme]` e `b` com `remotes: [github.com/globex]`, sem `default`, quando o comando roda numa pasta git com `origin` `https://github.com/Acme/api.git`, então `a` é escolhido com `selected_by: remote`.
- **UT-02** — Dados os remotes `https://u:tok@GitHub.com/Acme/API.git`, `git@github.com:Acme/API.git`, `ssh://git@host.interno:2222/g/r.git` e `https://host/g/r/`, quando são normalizados, então dão `github.com/acme/api`, `github.com/acme/api`, `host.interno/g/r` e `host/g/r`, e `tok`/`u` não aparecem em nenhuma saída.
- **UT-03** — Dados prefixos `github.com/acme` e `github.com/acme/infra` em atlas diferentes, quando o remote é `github.com/acme/infra/x`, então vale o segundo. `github.com/acme` não casa `github.com/acme-labs/x`. Dois atlas com o mesmo prefixo fazem o passo ser pulado, e vale o `default`.
- **UT-04** — Dado um remote que casa com `a`, quando o comando roda com `--atlas b` ou `ATLAS_NAME=b`, então `b` é escolhido (`option`/`env`).
- **UT-05** — Dada uma pasta sem git, um repositório sem `origin`, ou um `PATH` sem `git`, quando o comando roda com `default: b`, então `b` é escolhido sem erro nem aviso.
- **UT-06** — Dados dois atlas com o mesmo prefixo que casa o remote da pasta, quando o `doctor` roda, então há um AVISO com os dois nomes, sem o remote.
- **UT-07** — Dados itens de `remotes:` com `https://`, `@`, espaço, `..`, `/abs` e barra final, quando a configuração é lida, então exit 2 com o item. `init --remote github.com/acme --remote gitlab.acme.interno/plataforma` grava a lista.
- **UT-08** — Dado o servidor MCP, quando `atlas_context`, `atlas_config`, `atlas_doctor`, `atlas_lint` e `atlas_curate_list` recebem `atlas: "b"`, então a CLI recebe `--atlas b`. Um valor vazio, com mais de 200 caracteres ou com caractere de controle é recusado pelo esquema. O exit 2 da escolha vira erro da tool com a mensagem.
- **UT-09** — Dado o hook, quando `config --json` devolve 1 atlas, 2 atlas com `selected_by` `remote`, `env` ou `default`, exit 2 ou exit 3, então as linhas são as do contrato, e nenhuma contém caminho, remote ou credencial.

### 7.3 Testes de Integração
- **IT-01** — Com a CLI como processo, `HOME` temporário, dois atlas com `remotes:` e dois repositórios git locais com `origin` diferentes, `context` sem opção usa o grafo do atlas certo em cada repositório.
- **IT-02** — O servidor MCP como processo (stdio), com `CLAUDE_PROJECT_DIR` apontando para cada repositório: `atlas_context` sem `atlas` usa o atlas do remote, e com `atlas` usa o atlas pedido.

### 7.4 Testes de Contrato
- **CT-01** — Dado cada `selected_by` do contrato SPEC-0079@1 mais `remote`, quando o hook e o MCP leem o `config --json`, então interpretam `atlas_name`, `selected_by` e `atlases` como definido. Um campo desconhecido é ignorado.

### 7.5 Testes E2E
- **E2E-01** — Jornada da pessoa com duas organizações:
  1. com dois atlas configurados, cada um com `remotes:`, abre a sessão num repositório da organização B;
  2. o hook diz "para este projeto: b (escolhido por: remote do projeto)";
  3. `atlas_context` sem `atlas` responde com o grafo de B;
  4. a mesma jornada num repositório de A dá A;
  5. num repositório sem remote conhecido, vale o `default`.

### 7.6 Outros
- N/A

**Dublês e dados de teste:**
- `HOME`, `ATLAS_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários (helpers de `skills/boson-atlas/tests`, `mcp/tests` e `tests/plugin`).
- Repositórios git criados em pastas temporárias com `git init` e `git remote add origin <url fictícia>`.
- Atlas com coletor `generic`.
- Nunca rede, nunca o `~/.config` real.

**Ambiente de execução:** local e CI (suítes `skills/boson-atlas/tests`, `mcp/tests` e `tests/plugin`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto, por versão do plugin.
- **Dados/schema:** `remotes:` é opcional e só existe quando a pessoa declara. Atlas sem a chave se comportam como antes.
- **Compatibilidade:**
  - as tools ganham um parâmetro opcional;
  - com um atlas só, o hook e o MCP não mudam (CH-01);
  - numa máquina na versão anterior, os comandos ignoram `remotes:`, mas o `lint` antigo acusa `chave desconhecida: remotes`. O CHANGELOG avisa para atualizar todas as máquinas antes de declarar `remotes:` (mesmo cuidado da SPEC-0071).
- **Observabilidade:** `selected_by` no `config`, o aviso de empate no `doctor` e o motivo na linha do hook.
- **Rollback:** reverter o merge e tirar `remotes:` do `atlas-config.yml`.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] Prefixo casa por segmento inteiro ou por texto? — Segmento inteiro: `github.com/acme` não pode casar `github.com/acme-labs` (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-17: "beleza, segue no piloto automático até o merge"; revisável no H1)
- [x] Empate entre atlas: erro ou cai no default? — Cai no `default`, com aviso do `doctor`: o comando funciona e a pessoa vê o problema (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] Só o `origin` ou todos os remotes? — Só o `origin`, que é o sinal mais comum e não ambíguo; outros remotes ficam para spec futura se aparecer o caso (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] Máquinas na versão anterior com `remotes:` no atlas compartilhado? — A versão anterior ignora a chave nos comandos, mas o `lint` dela acusa `chave desconhecida: remotes`, então o CHANGELOG pede para atualizar todas as máquinas antes de declarar `remotes:`. Aceitar a chave em silêncio na versão anterior exigiria um release extra (recomendação do arquiteto, piloto automático; revisável no H1)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 7274c26 | 2026-11-18 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0080`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
