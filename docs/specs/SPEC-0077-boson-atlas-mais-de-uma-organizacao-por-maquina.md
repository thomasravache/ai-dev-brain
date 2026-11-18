---
id: SPEC-0077
title: "boson-atlas: mais de uma organização por máquina"
tier: epic
type: feature
status: proposed
created: 2026-11-17
depends_on: []
adrs: [ADR-0010, ADR-0020, ADR-0021]
external: []
approved_by:
approved_at:
---

# SPEC-0077 — boson-atlas: mais de uma organização por máquina (Épico)

> Origem: radar de 2026-11-17 (thomas); detalhado em 2026-11-18.

<!-- O épico não é executado: define visão, decisões, decomposição e entrega. As filhas executam (`parent: SPEC-0077`). -->

## 1. Visão
Uma pessoa que trabalha para mais de uma organização mantém, na mesma máquina, um atlas por organização. Cada atlas tem suas próprias credenciais (só pelo nome), e o atlas certo é usado sem trocar `ATLAS_CONFIG_HOME`:
- pelo nome, com `--atlas` e `ATLAS_NAME`;
- pelo remote git do projeto em que a sessão está;
- pelo `org_context` do projeto, no DISCOVER da `gluon-spec`.

Quem tem um atlas só não percebe mudança nenhuma: o arquivo, os comandos e as mensagens continuam iguais.

## 2. Escopo
**Objetivos (dentro do escopo):**
- Configuração local com vários atlas nomeados (`atlases:` e `default:`), lida junto com a forma de um atlas só (`atlas:` + `credentials:`). Enquanto houver um atlas só, o arquivo continua gravado na forma antiga (SPEC-0079).
- Ordem de escolha única, aplicada por todos os comandos: `--atlas`, `ATLAS_NAME`, remote do projeto, `default` e atlas único (ADR-0021; SPEC-0079 e SPEC-0080).
- `init` e `init --join` acrescentam um atlas sem apagar os outros. `config --list` e `config --set-default` mostram e trocam o padrão. O `doctor` mostra todos os atlas configurados (SPEC-0079).
- Chave `remotes:` no `atlas-config.yml` compartilhado. Ela liga um projeto ao atlas pelo remote git e entra na máquina nova pelo `init --join`, sem configuração extra (SPEC-0080).
- Tools MCP `atlas_*` com o parâmetro `atlas`. O hook de início de sessão diz qual atlas vale para o projeto e por quê (SPEC-0080).
- A `gluon-spec` passa o `org_context` do projeto ao `atlas.py` com `--atlas`, em vez de só avisar quando ele difere (SPEC-0081).

**Não-objetivos (fora do escopo):**
- Vários vaults na `photon-brain`, que é outra skill e outro pedido.
- Juntar dados de dois atlas num mesmo `context` ou grafo: cada atlas continua isolado.
- Migrar arquivos sozinho (ADR-0019): a forma nova só é gravada quando a pessoa acrescenta o segundo atlas.
- Guardar valores de credenciais: continua só o nome (ADR-0010).
- O mapa de acesso por ambiente (SPEC-0075), que vai usar o atlas escolhido por este épico.

## 3. Arquitetura Alvo
**Contexto:** projeto existente. Hoje a `boson-atlas` lê uma configuração local de duas camadas (ADR-0010). Essa configuração aponta um só atlas, com uma chave `atlas:` e um conjunto de `credentials` em `~/.config/boson-atlas/config.yml`, e o `org-atlas` é lido como reserva (ADR-0020). Todos os comandos encontram o atlas por `scan_config()`/`read_local()` (`skills/boson-atlas/scripts/atlas.py`), e o `lint` por `_lint_atlas()`. O `init` exige `--atlas` e regrava o ponteiro único. As tools MCP (`mcp/fermion_mcp.py`) e o hook (`hooks/session_start.py`) chamam a CLI sem dizer qual atlas usar.

**Como fica:**
- **Uma função de escolha (SPEC-0079):** `select_atlas(args, env, cwd)` em `atlas.py` devolve o nome, a entrada (`atlas`, `credentials`) e o motivo da escolha. Todos os comandos usam essa função no lugar do ponteiro único.
- **SPEC-0080** acrescenta à mesma ordem o passo do remote do projeto e leva o parâmetro `atlas` ao MCP e ao hook.
- **SPEC-0081** só muda a instrução da `gluon-spec`, que continua usando o atlas pela CLI (ADR-0010).
- **Contrato entre as filhas** (`SPEC-0079@1`): o formato da configuração local, a ordem de escolha, a opção `--atlas <nome|caminho>`, a variável `ATLAS_NAME` e os campos novos do `config --json` (`atlas_name`, `selected_by`, `atlases`).

**Decisões (ADRs):** ADR-0021 — vários atlas num só arquivo local, com ordem de escolha fixa (revisa a regra de "um atlas por máquina" do ADR-0010, que tem as demais regras mantidas). ADR-0020 — leitura dupla da forma antiga.

**Regras de arquitetura a garantir (G3):**
- `atlas.py` continua um arquivo só, stdlib e compatível com o Python 3.9 (`tests/test_architecture.py`).
- Nenhuma importação entre skills: a `gluon-spec` só chama a CLI (`test_architecture.py` das duas skills).
- Nenhum caminho absoluto no `atlas-config.yml`, inclusive em `remotes:` (validação existente, estendida na SPEC-0080).

## 4. Decomposição
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0079 | boson-atlas: vários atlas na configuração local e escolha por --atlas | full | feature | M | — | — |
| SPEC-0080 | boson-atlas: atlas escolhido pelo remote do projeto, nas tools MCP e no início da sessão | full | feature | M | SPEC-0079 | SPEC-0079@1 |
| SPEC-0081 | gluon-spec: org_context escolhe o atlas no DISCOVER | lite | feature | S | — | SPEC-0079@1 |

## 5. Estratégia de Entrega
- **Ambientes:** N/A — as skills são distribuídas por cópia e pelo plugin, sem deploy (mesmo critério da SPEC-0017).
- **Entrega por onda:**
  - onda 1: SPEC-0079 e SPEC-0081, em paralelo porque não tocam os mesmos arquivos e a 0081 só consome o contrato;
  - onda 2: SPEC-0080.

  Cada onda é uma versão do plugin.
- **Feature flags:** N/A — o comportamento novo só aparece quando há mais de um atlas, ou com `--atlas` ou `remotes:`.
- **Rollback:**
  - com um atlas só, voltar à versão anterior não exige nada, porque o arquivo continua na forma antiga;
  - com vários, a versão anterior não lê `atlases:` e para com exit 3. O `.bak` gravado ao acrescentar o segundo atlas restaura a forma antiga, e o CHANGELOG mostra o passo.
- **Métricas de sucesso pós-release:** uso real com dois atlas na máquina do autor:
  - o `context` de um projeto de cada organização usa o atlas certo, sem `ATLAS_CONFIG_HOME`;
  - o `doctor` fica sem ERRO.

## 6. Riscos & Mitigações
- **Usar o atlas ou a credencial da organização errada:** a ordem de escolha é fixa e explicada em toda saída (`selected_by`). A credencial de um atlas nunca é usada por outro (IT da SPEC-0079). Com vários atlas e nenhuma escolha, o comando para com exit 2 em vez de adivinhar.
- **Quebrar quem tem um atlas só:** o arquivo continua gravado na forma antiga enquanto houver um atlas, e há um teste de caracterização da forma antiga (SPEC-0079).
- **Vazar organizações na saída do hook:** o hook mostra só os nomes dos atlas, nunca caminhos nem credenciais (SPEC-0080).
- **Remote de um projeto casar com dois atlas:** vale o prefixo mais longo. Se houver empate, não há escolha automática (cai no `default`), e o `doctor` avisa (SPEC-0080).

## 7. Critérios de Aceite do Épico
- [ ] Numa máquina com dois atlas, `--atlas` e `ATLAS_NAME` escolhem o atlas, e cada um usa só as próprias credenciais — SPEC-0079:E2E-01
- [ ] A configuração de um atlas só, gravada pela versão anterior, funciona igual e continua na forma antiga depois de `init --join` no mesmo atlas — SPEC-0079:IT-01
- [ ] Num projeto cujo remote casa com o `remotes:` de um atlas, a CLI, as tools MCP e o hook usam esse atlas sem nenhuma opção — SPEC-0080:E2E-01
- [ ] O DISCOVER da `gluon-spec` passa o `org_context` ao `atlas.py` com `--atlas` — SPEC-0081:UT-01

## 8. Questões em Aberto
- [x] Um arquivo com vários atlas, um arquivo por atlas (vários `ATLAS_CONFIG_HOME`) ou um arquivo no repositório do projeto? — Um arquivo local com `atlases:`. O `ATLAS_CONFIG_HOME` continua valendo para quem quer separar tudo, e um arquivo no repositório levaria caminhos da máquina para o repositório do time (ADR-0021; recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-17: "beleza, segue no piloto automático até o merge"; revisável no H1)
- [x] Onde fica a ligação entre projeto e atlas? — Na chave `remotes:` do `atlas-config.yml` compartilhado (ex.: `github.com/acme`). Ela vale para toda a organização, chega à máquina nova pelo `init --join` e não contém segredo nem caminho (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] O que acontece com vários atlas e nenhuma escolha? — Exit 2 com a lista de nomes e o passo (`--atlas`, `ATLAS_NAME` ou `config --set-default`). Não se adivinha (recomendação do arquiteto, piloto automático; revisável no H1)
- [x] Quando o arquivo muda de forma? — Só quando a pessoa acrescenta o segundo atlas (`init` ou `init --join` com outro caminho), com `.bak` da forma antiga. Com um atlas só ele continua igual, o que mantém o rollback trivial (recomendação do arquiteto, piloto automático; revisável no H1)
## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0077` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
