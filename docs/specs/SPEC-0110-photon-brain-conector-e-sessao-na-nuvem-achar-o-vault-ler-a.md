---
id: SPEC-0110
title: "photon-brain: conector e sessão na nuvem — achar o vault, ler a config e conectar só a pasta"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-26
parent: SPEC-0093
depends_on: []
consumes_contract: []
contract_version: 2
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/assets/brain-config.yml, skills/photon-brain/references/connectors.md, skills/photon-brain/references/config.md, skills/photon-brain/SKILL.md, skills/photon-brain/CHANGELOG.md, skills/photon-brain/tests/test_connector_ids.py, skills/photon-brain/tests/test_connector_ids_cli.py, skills/photon-brain/tests/test_cloud_session_instructions.py, .claude-plugin/plugin.json]
adrs: [ADR-0013, ADR-0027]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-26
---

# SPEC-0110 — photon-brain: conector e sessão na nuvem — achar o vault, ler a config e conectar só a pasta

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
A sessão que só tem o conector (celular, navegador, sessão na nuvem) acha o vault e a inbox certos sem adivinhar: o vault guarda os IDs da pasta do vault e da inbox por provedor (`connectors.<provedor>` no `brain-config.yml`, gravados com `brain.py connector set`), e as instruções dizem como ler a configuração pelo conector do Drive, como escolher a inbox certa entre várias e, na nuvem, como conectar só a pasta do vault (pontos 3, 5, 6 e 7 da SPEC-0093).

## 2. Motivação & Escopo
**Motivação:** no uso real pelo conector do Google Drive, foi preciso procurar o `brain-config.yml` para descobrir o vault, havia várias pastas `inbox` antigas, o conector recusou ler o `.yml` (`application/octet-stream`), pedir acesso à pasta inteira da nuvem e à configuração local foi negado, e a sessão carregou a skill com o nome antigo `second-brain`.

**Objetivos (dentro do escopo):**
- Chave opcional `connectors.<provedor>` (provedores de `PROVIDERS`) com `vault_folder_id` e `inbox_folder_id`, texto opaco validado.
- `brain.py connector set PROVEDOR --vault-folder-id ID [--inbox-folder-id ID]` e `connector show [--json]`, com a pasta do vault montada; `connector set` grava no `brain-config.yml` e registra no `log.md`; `config --json` mostra os IDs.
- `references/connectors.md`:
  - como achar o vault: pelos IDs guardados; sem eles, buscar `brain-config.yml` pelo nome e conferir `index.md` e `log.md` na mesma pasta (`parentId`);
  - a inbox certa é a pasta `layout.inbox` cujo pai é a pasta do vault, nunca outra pasta `inbox` solta;
  - ler o `.yml` no Google Drive com `download_file_content` quando `read_file_content` recusar o tipo, e o que fazer se nenhum dos dois funcionar (seguir com `inbox` e sem contexto, avisando);
  - depois de achar as pastas numa máquina com a pasta montada, gravar os IDs com `connector set`.
- `SKILL.md`, sessão na nuvem:
  - pedir só a pasta do vault ("Add folder" na ferramenta), nunca a pasta inteira da nuvem nem a configuração local;
  - o `init --join` ali roda na máquina virtual da sessão, sem a configuração local do computador da pessoa;
  - se a skill aparecer como `second-brain`, a conta tem a skill antiga avulsa: removê-la e instalar o plugin `fermion`.

**Não-objetivos (fora do escopo):**
- O `brain.py` chamar a API do provedor (ADR-0008, ADR-0027).
- Descobrir os IDs automaticamente: quem os conhece é o agente, pelo conector.
- Um espelho `.md` da configuração (o `download_file_content` resolve a leitura; espelho seria mais uma coisa para ficar desatualizada).
- Remover a skill antiga da conta (é ação da pessoa no claude.ai).

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** conector do provedor na ferramenta do agente (ADR-0013); `download_file_content` do conector do Google Drive, observado no uso real (2026-11-23).

## 4. Decisão Arquitetural
**Contexto:** a configuração compartilhada é lida por `read_config`, validada por `check_shared` e escrita por funções como `add_context_text` (usada pelo `context add`), que altera o `brain-config.yml` preservando o resto. As instruções do modo só conector estão em `SKILL.md` e `references/connectors.md`, cobertas pelos testes de texto `test_connector_instructions.py` e `test_connector_session_instructions.py`.

**Decisão:** `connectors` entra em `SHARED_KEYS`; `connector set` segue o `context add` (edição pontual do `brain-config.yml`, com log); `connector show` segue o `config`. O texto novo segue o estilo dos testes de instruções existentes.

**Justificativa:** IDs no vault funcionam na sessão na nuvem, onde não há configuração local (ADR-0027); o `brain.py` só guarda texto, sem rede.

**Desvio do padrão existente:** Nenhum.

**Alternativas descartadas:** IDs na configuração local (não existe na nuvem); um arquivo `.md` espelhando a configuração; o `brain.py` consultar o Drive (ADR-0008).

**ADRs:** ADR-0013, ADR-0027.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — configuração pequena.
- **Segurança:** os IDs são validados como `^[A-Za-z0-9_-]{8,128}$` e nunca são credenciais; um valor que pareça segredo (detector da SPEC-0050) é recusado; o `connector set` só escreve no `brain-config.yml` do vault — UT-02.
- **Privacidade e dados pessoais:** os IDs identificam pastas da conta da pessoa e ficam no vault dela; o log registra só o provedor, nunca os IDs — UT-03.
- **Disponibilidade e resiliência:** sem a chave, tudo funciona como hoje (busca pelo nome); IDs velhos só fazem o agente cair na busca pelo nome, conforme as instruções.
- **Acessibilidade (UI):** N/A — sem interface gráfica.
- **Custo:** N/A — local.

## 6. Artefato A — Contrato
**Interface:** chave `connectors`; `brain.py connector set|show`; instruções

```text
brain-config.yml (compartilhada, opcional)
  connectors:
    google-drive:
      vault_folder_id: <ID>
      inbox_folder_id: <ID>        # opcional

brain.py connector set PROVEDOR --vault-folder-id ID [--inbox-folder-id ID]
  PROVEDOR em PROVIDERS (google-drive, onedrive, icloud, local)
  sucesso (exit 0): "ids do conector google-drive gravados"; o resto do brain-config.yml não muda
    log.md: "- <agora> connector set google-drive"
  erros (exit 2, nada gravado): provedor desconhecido | ID fora da regra ou com cara de segredo
  erro (exit 3): sem configuração

brain.py connector show [--json]
  "google-drive: vault <ID>, inbox <ID>" por provedor | {"google-drive": {"vault_folder_id", "inbox_folder_id"}}
  sem a chave: "nenhum id de conector gravado" (exit 0)

brain.py config --json
  ganha "connectors" com os IDs gravados ({} sem a chave)

doctor
  AVISO "connectors.<x>: provedor desconhecido" | ERRO "connectors.<p>.<campo>: id inválido"
```

**Esclarecimentos (Emenda v2):**
- `connector set` num `brain-config.yml` que já tem `connectors` com vários provedores (e comentários) muda só os campos do provedor pedido; os outros provedores ficam byte a byte iguais. Acrescentar `--inbox-folder-id` depois de gravar só o vault, num provedor que não é o último, funciona (UT-01).
- `connector show` e `config --json` mostram `(inválido)` no lugar de um ID escrito à mão que não passe na regra ou pareça segredo; o valor nunca aparece (UT-04).
- `connector set` com `timezone` inválido sai com 2 sem gravar, como os outros comandos que gravam (UT-02).
- `SKILL.md`, na parte de localizar o vault, também diz para usar primeiro os IDs de `connectors.<provedor>` quando o agente já os tiver (lidos do `brain-config.yml` numa sessão anterior ou dados pela pessoa) e que, só com o conector, o ganho principal dos IDs é escolher a inbox certa (UT-06).

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** `scripts/brain.py` (`SHARED_KEYS`, `check_shared`, `cmd_connector_set`, `cmd_connector_show`, `config --json`, `doctor`); `assets/brain-config.yml` (chave comentada); `references/connectors.md`, `references/config.md` e `SKILL.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Gravar IDs | `connector set google-drive --vault-folder-id A --inbox-folder-id B` | chave gravada, resto do arquivo igual, log sem os IDs | UT-01, UT-03, IT-01 |
| ID inválido | ID curto, com `/`, com espaço ou com cara de segredo; provedor fora de `PROVIDERS` | exit 2, nada muda | UT-02 |
| Mostrar | `connector show` e `config --json` | IDs por provedor; sem a chave, mensagem e `{}` | UT-04 |
| Config com a chave | `doctor` e `read_config` | sem AVISO de chave desconhecida; ID inválido vira ERRO | UT-05 |
| Achar o vault pelo conector | `references/connectors.md` | IDs primeiro; sem eles, `brain-config.yml` + `index.md`/`log.md` no mesmo pai; inbox com pai no vault | UT-06 |
| Ler o `.yml` no Drive | `references/connectors.md` | `download_file_content` quando `read_file_content` recusa; plano se os dois falham | UT-06 |
| Sessão na nuvem | `SKILL.md` | só a pasta do vault ("Add folder"); `init --join` na máquina virtual; nome antigo `second-brain` | UT-07 |
| Sem a chave | vault de hoje | comandos e instruções de hoje seguem válidos | CH-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Dado um vault sem `connectors`, quando `config --json`, `doctor` e `capture --print` rodam, então a saída é a de hoje, a menos da chave `connectors: {}` no `config --json` (guarda: passa antes da mudança nas partes que não mudam).

### 7.2 Testes Unitários
- **UT-01** — Quando `connector set google-drive --vault-folder-id 1AbCdEfGhIj --inbox-folder-id 2KlMnOpQrSt` roda, então o `brain-config.yml` ganha `connectors.google-drive` com os dois IDs, as outras chaves e os comentários do arquivo ficam iguais, e rodar de novo com outro ID só troca o valor.
- **UT-02** — Quando o provedor não está em `PROVIDERS`, ou um ID tem menos de 8 caracteres, `/`, espaço, quebra de linha ou cara de segredo, então sai com 2 e o arquivo não muda.
- **UT-03** — A linha do `log.md` do `connector set` cita o provedor e não contém nenhum dos IDs.
- **UT-04** — `connector show` lista os IDs por provedor e, sem a chave, diz "nenhum id de conector gravado" com exit 0; `config --json` traz `connectors` (`{}` sem a chave).
- **UT-05** — Um `brain-config.yml` com `connectors` válido não gera AVISO de chave desconhecida; com um ID inválido escrito à mão, o `doctor` mostra o ERRO do campo.
- **UT-06** — `references/connectors.md` diz para usar primeiro os IDs de `connectors.<provedor>`; sem eles, buscar `brain-config.yml` e conferir `index.md` e `log.md` na mesma pasta; usar como inbox só a pasta `layout.inbox` cujo pai é a pasta do vault; ler o `.yml` com `download_file_content` quando `read_file_content` recusar o tipo; se nada ler a configuração, seguir com `inbox` e sem contexto, avisando a pessoa; e gravar os IDs com `connector set` numa máquina com a pasta montada.
- **UT-07** — O `SKILL.md`, na parte de sessão na nuvem, diz para pedir só a pasta do vault ("Add folder"), nunca a pasta inteira da nuvem nem a configuração local; que o `init --join` ali roda na máquina virtual da sessão, sem a configuração local do computador da pessoa; e que a skill com o nome `second-brain` indica a skill antiga avulsa na conta, a remover, com o plugin `fermion` instalado.

### 7.3 Testes de Integração
- **IT-01** — Num vault do `init`, quando `connector set`, `context add` e `connector show` rodam em sequência, então os dois blocos convivem no `brain-config.yml`, o `doctor` fica sem ERRO e o `log.md` tem as duas linhas.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs.

### 7.5 Testes E2E
- N/A — CLI e instruções de uso do agente; `user_facing: false` e sem jornada crítica declarada.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `Sandbox`; IDs fictícios no formato dos do Drive.

**Ambiente de execução:** local e CI, suíte da photon-brain.

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin.
- **Dados/schema:** chave opcional; nada muda nos vaults sem ela.
- **Compatibilidade:** comandos novos; `config --json` ganha uma chave.
- **Observabilidade:** `connector show` e as linhas do `doctor`.
- **Rollback:** reverter o merge; a chave fica no arquivo e o `doctor` antigo só avisa que é desconhecida.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Os IDs ficam na configuração local ou no vault? — No vault, por provedor: a sessão na nuvem não tem a configuração local (ADR-0027; sugestão do terceiro feedback, thomas, 2026-11-25)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato e implementação**
- [ ] Red: CH-01, UT-01, UT-02, UT-03, UT-04, UT-05, UT-06, UT-07, IT-01 com a tag `SPEC-0110:<ID>`, falhando pelo motivo certo (CH passando)
- [ ] Green: implementar o mínimo para passar, seguindo o padrão de referência da seção 4
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6): N/A — skills distribuídas por cópia e pelo plugin
- [ ] Relatório de Entrega, CHANGELOG e versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 7c6da0c (árvore suja) | 2026-11-26 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=20)) — 38e9568 | 2026-11-26 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — aecba24 | 2026-11-27 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — d6a68c8 | 2026-11-27 |
| G4 Review | FAIL | CHANGES_REQUESTED: connector set acrescenta campo no provedor seguinte quando há mais de um em connectors (_children não para no irmão); sai com 1, fora do contrato | 2026-11-27 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G4 FAIL 2026-11-27 — CHANGES_REQUESTED: connector set acrescenta campo no provedor seguinte quando há mais de um em connectors (_children não para no irmão); sai com 1, fora do contrato — ea40dfd

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0110`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-27 | `connector set` com vários provedores muda só o pedido; `(inválido)` no lugar de ID inválido em `show` e `config --json`; fuso inválido sai com 2; IDs primeiro também no `SKILL.md` | G4 da SPEC-0110: campo gravado no provedor seguinte e ID inválido exibido | nenhuma | thomas, 2026-11-27 (piloto automático com o recomendado) |
