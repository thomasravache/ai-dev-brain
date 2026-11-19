---
id: SPEC-0080
title: "boson-atlas: atlas escolhido pelo remote do projeto, nas tools MCP e no início da sessão"
tier: full
type: feature
user_facing: true
status: in-progress
created: 2026-11-18
parent: SPEC-0077
depends_on: [SPEC-0079]
consumes_contract: [SPEC-0079@1]
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/tests/**, skills/boson-atlas/references/config.md, skills/boson-atlas/references/modes.md, skills/boson-atlas/assets/atlas-config.yml, skills/boson-atlas/SKILL.md, skills/boson-atlas/CHANGELOG.md, mcp/fermion_mcp.py, mcp/tests/**, mcp/README.md, hooks/session_start.py, tests/plugin/**, .claude-plugin/plugin.json]
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

**Esclarecimentos (Emenda v2, achados do test-writer no G1):**
1. **Hook com exit 2:** os `<nomes>` vêm de uma segunda chamada de leitura, `config --list --json`, que nunca falha com vários atlas e fica dentro do prazo do hook. Com 0 atlas ou `config --json` ilegível, o hook mantém a linha atual.
2. **Formato dos nomes:** na ordem de `atlases` (por nome), separados por `, `.
3. **Motivo no hook para `option` e `single`:** usa o texto da CLI: `--atlas` e `único`. `env` vira `ATLAS_NAME`, `default` vira `padrão` e `remote` vira `remote do projeto`.
4. **Parâmetro `atlas` das tools:** recusa qualquer caractere de controle, inclusive TAB, LF e CR, porque o valor vira argv.
5. **Passagem à CLI:** colada, `--atlas=<valor>`, para que um valor começando com `-` não vire opção, como as tools `brain_*` já fazem.
6. **Validação de `remotes:` no UT-07:** acontece ao ler a configuração (`config --json` e os demais comandos), que sai com exit 2 e cita o item. Itens com `:` ou maiúsculas também são recusados, e o `lint` aceita `remotes` como chave conhecida.

**Correções do G4 (Emenda v3):**
7. **Item inválido de `remotes:` nas mensagens:** toda mensagem que cita um item inválido (CLI, `doctor`, `lint` e, por consequência, MCP) mostra o item com as credenciais trocadas por `***` (`https://***@host/...`). Nenhum token sai.
8. **Um atlas com `remotes:` inválido não derruba os outros:**
   - no passo do remote, um atlas cujo `remotes:` é inválido conta como sem `remotes`;
   - o exit 2 por `remotes:` inválido só acontece quando esse atlas é o escolhido;
   - o `config --list` nunca falha por isso;
   - o `doctor` mostra um AVISO com o nome do atlas, sem o item.
9. **Hook com exit 2:** a linha "nenhum escolhido" só aparece quando o `config --list --json` traz `atlas_name` nulo. Outro exit 2 (credenciais ou `ci:` inválidos no atlas escolhido) tira o bloco do atlas e manda uma linha ao stderr, como qualquer falha da CLI.
10. **`mcp/README.md`:** o parágrafo do parâmetro `atlas` fica abaixo da tabela de tools.
11. **`CLAUDE_PROJECT_DIR` inexistente:** as tools `atlas_*` usam a pasta do projeto como `cwd` só quando ela existe; senão usam o `cwd` do servidor, e o passo do remote usa o remote dessa pasta, se houver.
12. **Pasta atual removida:** o passo do remote é pulado sem erro.
13. **`remotes:` com caractere de controle:** o item é recusado (abaixo de 0x20 e de 0x7f a 0x9f).

**Correções da rodada 2 do G4 (Emenda v4):**
14. **Máscara sempre aplicada:** toda mensagem que cita um item de `remotes:` mostra `***@` no lugar de tudo o que vem antes do último `@` (depois do esquema), com ou sem esquema e com ou sem `:` (`TOK@github.com/acme` → `***@github.com/acme`, `git@host:g/r` → `***@host:g/r`). Também troca o que vem depois de `?` ou `#` por `***`. O UT-07 deixa de esperar `user@github.com/acme` sem máscara.
15. **Item com `?`, `#` ou `=`:** é recusado (exit 2), porque nunca casaria com um remote normalizado e poderia carregar um token.

**Decisão do impedimento IMP-01 (Emenda v5, thomas, 2026-11-19):**
16. **Mensagens sobre `remotes:` não citam o item.** Toda mensagem sobre um item inválido diz só a posição (a partir de 1) e o motivo, por exemplo `remotes: item 2 inválido — tem esquema (ex.: https://); use host/caminho, como github.com/acme`. Isso vale para CLI, `doctor`, `lint` e, por consequência, MCP. Nenhum texto do item aparece em nenhuma saída, mascarado ou não. Esta regra substitui os itens 7 e 14: a máscara deixa de existir nas mensagens de `remotes:`.
17. **Motivos, um por item (o primeiro que se aplica):**
    - `tem esquema`
    - `tem credenciais (@)`
    - `tem ? , # ou =`
    - `tem : (porta ou formato scp)`
    - `tem espaço ou caractere de controle`
    - `tem maiúsculas`
    - `tem barra no início ou no fim, // ou segmento . ou ..` (inclui `~` no início e `\`)
    - `vazio`
    - `não é texto`

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
- **UT-07** — Dados itens de `remotes:` com `https://`, `@`, espaço, `..`, `/abs` e barra final, quando a configuração é lida, então exit 2 com `item N inválido` e o motivo, sem o texto do item (Emenda v5). `init --remote github.com/acme --remote gitlab.acme.interno/plataforma` grava a lista.
- **UT-08** — Dado o servidor MCP, quando `atlas_context`, `atlas_config`, `atlas_doctor`, `atlas_lint` e `atlas_curate_list` recebem `atlas: "b"`, então a CLI recebe `--atlas b`. Um valor vazio, com mais de 200 caracteres ou com caractere de controle é recusado pelo esquema. O exit 2 da escolha vira erro da tool com a mensagem.
- **UT-09** — Dado o hook, quando `config --json` devolve 1 atlas, 2 atlas com `selected_by` `remote`, `env` ou `default`, exit 2 ou exit 3, então as linhas são as do contrato, e nenhuma contém caminho, remote ou credencial.
- **UT-10** — Dado um `remotes:` com `https://u:SECRETTOK@github.com/globex`, quando `config --json`, `config --list --json`, `doctor --json`, `lint --json` e a tool `atlas_config` rodam, então `SECRETTOK` não aparece em nenhuma saída. Nas saídas de erro (`config --json` com `globex` escolhido, `lint --json` e a tool `atlas_config`), aparecem só `item 1 inválido` e o motivo `tem esquema`, sem nenhum texto do item (Emenda v5).
- **UT-11** — Dados os atlas `acme` (default) e `globex` com `remotes:` inválido, quando `config --json`, `context`, `lint` e `config --list --json` rodam fora e dentro de um repositório git, então `acme` funciona (exit 0) e `config --list` sai 0. Com `--atlas globex`, exit 2 com a posição e o motivo, sem o item (Emenda v5). O `doctor` mostra um AVISO citando `globex` (Emenda v3, item 8).
- **UT-13** — Dados os itens `TOK@github.com/acme`, `ghp_TOK@github.com:acme/x`, `https://github.com/acme?access_token=TOK`, `https://github.com/acme#TOK` e `https:/u:TOK@h/x`, quando a configuração é lida (CLI, `doctor`, `lint` e tool `atlas_config`), então nenhum pedaço do item (token, userinfo, texto depois do `@`) aparece em nenhuma saída, e o erro diz a posição e o motivo. Emenda v5 acrescenta `https://u:TO?K@host/x` e `https://u:ab#TOK@host/x`, e `https:/u:TOK@h/x` tem o motivo `tem credenciais (@)`, porque `https:/` não é esquema. `github.com/acme?token=x`, `github.com/acme#x` e `github.com/a=b` dão exit 2 (Emenda v4).
- **UT-12** — Casos de borda da Emenda v3:
  - hook com `config --json` em exit 2 e `config --list --json` com `atlas_name: "acme"`: não mostra "nenhum escolhido" (item 9);
  - `atlas_config` com `CLAUDE_PROJECT_DIR=/inexistente`: responde com o atlas `default` (item 11);
  - `config --json` numa pasta atual removida: sai 0 pelo `default` (item 12);
  - item `github.com/acme\x1b[31m`: exit 2 (item 13).

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
- [x] Fase 0: CH-01 escrito e passando no código atual, commitado antes de qualquer mudança
- [x] Red: UT-01 a UT-09, IT-01, IT-02, CT-01 e E2E-01 com a tag `SPEC-0080:<ID>`, falhando pelo motivo certo
- [x] Green: `remotes:` (validação, `init --remote`, modelo), passo do remote em `project_remote_choice`, aviso de empate no `doctor`; parâmetro `atlas` e `cwd` do projeto nas tools `atlas_*`; linha do hook; docs, CHANGELOG, `ATLAS_VERSION` e `plugin.json`
- [x] Validar: suíte completa + arquitetura (G2/G3)
- [x] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega, docs e CHANGELOG (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 7274c26 | 2026-11-18 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=4)) — ffa2016 | 2026-11-18 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 46c53c8 | 2026-11-19 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — b318cd8 | 2026-11-19 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer (subagente), rodada 4: APPROVED — 0 blocker, 0 major, 2 minor (fixture de teste com o formato antigo; redação do CHANGELOG) — f50b089 | 2026-11-19 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G2 FAIL 2026-11-18 — test exit 1 (FAILED (failures=7)); lint exit 0 (All checks passed!) — fb2ee85
- G2 PASS 2026-11-18 — depois de 1 reprovação(ões)
- G4 FAIL 2026-11-18 — rodada 1: CHANGES_REQUESTED — 1 blocker de processo (arquivo fora de touches), 2 major (item de remotes com token sem máscara; remotes inválido num atlas derruba os outros), 5 minor — f95ff16
- G4 FAIL 2026-11-18 — rodada 2: CHANGES_REQUESTED — 1 major (userinfo sem esquema e query/fragment não mascarados), 1 minor (item válido aceita ?, # e =) — 89bb1a5
- G4 FAIL 2026-11-18 — rodada 3: CHANGES_REQUESTED — 1 major (? ou # dentro da senha deixa sair parte dela na máscara) — 7eac523
- G4 PASS 2026-11-19 — depois de 3 reprovação(ões)

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-18 | G4 | falha | 3 reprovações seguidas do G4, todas na máscara de itens inválidos de remotes: cada regra de máscara nova deixa outra forma de token passar | Emendas v3 (máscara com esquema) e v4 (máscara sempre, query e fragment); rodada 3 achou ? ou # dentro da senha | thomas | Emenda v5 — decisão de thomas em 2026-11-19: as mensagens de remotes citam só a posição e o motivo, nunca o item | 2026-11-19 |

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
| 1 (sem mudança de versão) | 2026-11-19 | Emenda v5: as mensagens sobre `remotes:` citam só a posição e o motivo, nunca o item; a máscara (itens 7 e 14) sai; UT-07, UT-10 e UT-13 passam a conferir a posição e o motivo e a ausência de qualquer texto do item | IMP-01 (falha): 3 reprovações seguidas do G4, cada regra de máscara deixava outra forma de token passar; decisão de thomas em 2026-11-19 ("Não citar o item") | nenhuma | thomas, 2026-11-19 |
| 1 (sem mudança de versão) | 2026-11-18 | Emenda v4: a máscara de userinfo vale sempre (com e sem esquema), e query/fragment também viram `***`; itens com `?`, `#` ou `=` são recusados; UT-07 ajustado; UT-13 novo | G4 rodada 2 (1 major, 1 minor): `TOK@github.com/acme` e `?access_token=` ainda saíam sem máscara | nenhuma | thomas, 2026-11-18 (piloto automático com o recomendado) |
| 1 (sem mudança de versão) | 2026-11-18 | Emenda v3: item inválido de `remotes:` mascarado; atlas com `remotes:` inválido não derruba os outros (AVISO no `doctor`); hook só diz "nenhum escolhido" com `atlas_name` nulo; README; `CLAUDE_PROJECT_DIR` inexistente e pasta removida pulam o passo; caractere de controle recusado; `touches` ganha `tests/plugin/**`; UT-10 a UT-12 novos | G4 rodada 1 (1 blocker de processo, 2 major, 5 minor) | nenhuma | thomas, 2026-11-18 (piloto automático com o recomendado) |
| 1 (sem mudança de versão) | 2026-11-18 | Emenda v2: esclarece de onde o hook tira os nomes no exit 2 (`config --list --json`), o formato e os textos do motivo, a recusa de qualquer caractere de controle no parâmetro `atlas`, o `--atlas=<valor>` colado e onde `remotes:` é validado | G1 (test-writer): seis pontos sem definição no contrato | nenhuma | thomas, 2026-11-18 (piloto automático com o recomendado) |
