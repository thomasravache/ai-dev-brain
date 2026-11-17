---
id: SPEC-0069
title: "photon-brain: configuração, mensagens e backups com o nome novo e leitura dupla"
tier: full
type: migration
user_facing: false
status: implemented
created: 2026-11-16
parent: SPEC-0067
depends_on: []
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/photon-brain/scripts/brain.py, skills/photon-brain/tests/**, skills/photon-brain/references/**, skills/photon-brain/assets/brain-config.yml, skills/photon-brain/SKILL.md, skills/photon-brain/CHANGELOG.md, .claude-plugin/plugin.json, tests/plugin/test_skill_names.py]
adrs: [ADR-0008, ADR-0018, ADR-0019, ADR-0020]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0069 — photon-brain: configuração, mensagens e backups com o nome novo e leitura dupla

## 1. Visão Geral
A `photon-brain` passa a usar o próprio nome em tudo o que é técnico: a pasta de configuração da máquina vira `~/.config/photon-brain`, as mensagens e a `--version` dizem `photon-brain`, e os backups novos se chamam `photon-brain-<data>.zip`. Quem já tem `~/.config/second-brain` continua funcionando sem fazer nada: a configuração antiga é lida como reserva, a gravação vai só para a pasta nova e o `doctor` mostra o comando para copiar.

## 2. Motivação & Escopo
**Motivação:** depois da SPEC-0055 a skill se chama `photon-brain`, mas a máquina ainda mostra `second-brain` na pasta de configuração, nas mensagens, na versão e nos backups. Dois nomes para a mesma coisa confundem quem usa e quem dá suporte (épico SPEC-0067, ADR-0020).

**Objetivos (dentro do escopo):**
- Resolução da configuração local: `--config-home`/`BRAIN_CONFIG_HOME` (sem mudança) → `~/.config/photon-brain/config.yml` se existir → `~/.config/second-brain/config.yml` se existir → `~/.config/photon-brain/config.yml`.
- Toda gravação da configuração local (`init`, `init --join`, `config set`, `context add`, `backup target add` e afins) vai para a pasta nova, com o conteúdo completo; a antiga nunca é gravada, movida nem apagada.
- `doctor`: AVISO quando só a pasta antiga existe (com o comando de cópia) e quando as duas existem (a antiga é ignorada e pode ser apagada).
- Textos: `NOT_CONFIGURED`, cabeçalho do `config.yml` local, `--version`, descrição do `--help`, cabeçalho do `assets/brain-config.yml` (só vaults novos).
- Backups: nome novo `photon-brain-AAAA-MM-DD-HHMMSS[-files].zip`; rotação e `restore` reconhecem os dois prefixos, contando os dois juntos no limite de retenção.
- Referências (`config.md`, `backup.md`, `vault-layout.md`) e `SKILL.md` com os nomes novos; os exemplos de cron/launchd usam o nome novo (agendamentos existentes continuam funcionando, porque chamam o `brain.py`).
- `BRAIN_VERSION` e CHANGELOG, com a data de remoção do caminho antigo (SPEC-0073).

**Não-objetivos (fora do escopo):**
- Mover, renomear ou apagar `~/.config/second-brain`, backups ou agendamentos existentes (ADR-0019).
- Mudar o `brain-config.yml` de vaults existentes ou o layout do vault.
- O aviso no `fermion_doctor` e a guarda de nomes do repositório (SPEC-0072); a remoção da leitura antiga (SPEC-0073).

## 3. Dependências
- **Implementações necessárias:** N/A
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** brownfield; `local_config_path` em `skills/photon-brain/scripts/brain.py` já resolve `config_home` → `BRAIN_CONFIG_HOME` → pasta padrão, e `write_local_config` grava; a rotação de backup usa `BACKUP_NAME_RE`. O `doctor` já devolve linhas OK/AVISO/ERRO (`doctor_items`).

**Decisão:** separar leitura e gravação: `local_config_path` (leitura) devolve o primeiro caminho existente da ordem do objetivo; um novo `local_config_write_path` devolve sempre a pasta nova (ou a sobrescrita por `--config-home`/variável). `BACKUP_NAME_RE` aceita os dois prefixos; `backup_name` grava só o novo.

**Justificativa:** é a leitura dupla com remoção anunciada do ADR-0020, que respeita o ADR-0019 (nada é movido sozinho) e o ADR-0008 (configuração local fora do vault).

**Desvio do padrão existente:** muda a pasta padrão definida na configuração da skill (ADR-0008) — coberto pelo ADR-0020 e pelo `type: migration` do épico.

**Alternativas descartadas:** migrar na primeira execução (move arquivos da pessoa, contra o ADR-0019); gravar no caminho que foi lido (a pasta antiga continuaria crescendo e nunca seria aposentada).

**ADRs:** ADR-0008, ADR-0018, ADR-0019, ADR-0020.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — duas checagens de existência de arquivo a mais.
- **Segurança:** a configuração local guarda só nomes de segredo (`secret-ref`), nunca valores; a cópia sugerida preserva permissões (`cp -p`) — verificado no UT-05.
- **Privacidade e dados pessoais:** N/A — nenhum dado novo.
- **Disponibilidade e resiliência:** máquina com só a pasta antiga funciona sem ação (IT-01).
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** `brain.py` (CLI) e as funções `local_config_path`, `local_config_write_path`, `backup_name`, `BACKUP_NAME_RE`

```text
Leitura da configuração local (primeiro que existir):
  --config-home DIR | $BRAIN_CONFIG_HOME   → DIR/config.yml (sem reserva)
  ~/.config/photon-brain/config.yml
  ~/.config/second-brain/config.yml        (reserva até a SPEC-0073)
  nenhum → ~/.config/photon-brain/config.yml (não configurado)
Gravação: sempre ~/.config/photon-brain/config.yml (ou DIR/config.yml), conteúdo completo; a pasta antiga nunca é gravada.
Mensagens: "photon-brain não configurado nesta máquina — rode init (ou init --join)"; --version → "photon-brain <BRAIN_VERSION>".
doctor (texto e --json, sem mudar o formato):
  só a antiga existe  → AVISO "configuração no caminho antigo ~/.config/second-brain — copie com: mkdir -p ~/.config/photon-brain && cp -p ~/.config/second-brain/config.yml ~/.config/photon-brain/"
  as duas existem     → AVISO "~/.config/second-brain é ignorada (vale ~/.config/photon-brain) — pode apagá-la"
  com BRAIN_CONFIG_HOME/--config-home → nenhum aviso de caminho antigo
Backups: grava photon-brain-AAAA-MM-DD-HHMMSS[-files].zip; rotação e restore aceitam também second-brain-…zip; a retenção conta os dois prefixos juntos, apagando os mais antigos pela data do nome.
Exit codes: sem mudança.
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. `brain.py` (config, doctor, backup, textos), `assets/brain-config.yml`, `references/config.md`, `references/backup.md`, `references/vault-layout.md`, `SKILL.md`, `CHANGELOG.md`, versão do plugin.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Máquina antiga sem ação | só `~/.config/second-brain/config.yml` | todos os comandos leem a configuração antiga e funcionam | UT-01, IT-01 |
| Máquina nova | nenhuma pasta | `init` grava só em `~/.config/photon-brain`; mensagem "photon-brain não configurado" antes | UT-02, IT-02 |
| Gravação com só a antiga | `config set` (ou outro comando que grava) | grava a configuração completa na pasta nova; a antiga fica idêntica byte a byte | UT-03 |
| As duas existem | ambas com `config.yml` | vale a nova; `doctor` avisa que a antiga é ignorada | UT-01, UT-05 |
| Sobrescrita | `BRAIN_CONFIG_HOME` ou `--config-home` | usa só essa pasta, sem reserva nem aviso de caminho antigo | UT-04 |
| doctor com só a antiga | — | AVISO com o comando de cópia (`cp -p`), exit sem mudança | UT-05 |
| Textos | `--version`, `--help`, não configurado, cabeçalho local, `assets/brain-config.yml` | dizem `photon-brain`; nenhum texto de saída com `second-brain` fora dos avisos de compatibilidade | UT-06, CH-01 |
| Backup novo | `backup` | arquivo `photon-brain-<data>.zip` | UT-07 |
| Rotação mista | destino com backups `second-brain-…` e `photon-brain-…` acima do limite | apaga os mais antigos pela data, dos dois prefixos; nunca outro arquivo | UT-08 |
| Restore de backup antigo | `restore --from …/second-brain-….zip` | restaura como hoje | UT-09 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Dados os testes atuais de config, backup e CLI da `photon-brain` (guarda: passa antes da mudança), quando rodados depois da mudança com as expectativas de texto atualizadas, então nenhum outro comportamento muda (exit codes, formato do `--json`, layout do vault).

### 7.2 Testes Unitários
- **UT-01** — Dado `HOME` temporário com só a pasta antiga, ou com as duas, quando `local_config_path()` resolve, então devolve a antiga no primeiro caso e a nova no segundo.
- **UT-02** — Dado `HOME` temporário sem nenhuma pasta, quando `local_config_path()` e `local_config_write_path()` resolvem, então os dois devolvem `~/.config/photon-brain/config.yml`.
- **UT-03** — Dado só a pasta antiga, quando um comando grava a configuração local, então o arquivo novo tem a configuração completa com a mudança e o antigo fica idêntico byte a byte.
- **UT-04** — Dado `BRAIN_CONFIG_HOME` (ou `--config-home`) e as duas pastas padrão presentes, quando a configuração é lida e gravada, então só a pasta da sobrescrita é usada e o `doctor` não avisa caminho antigo.
- **UT-05** — Dado só a pasta antiga, e depois as duas, quando `doctor` (texto e `--json`) roda, então há um AVISO com o comando de cópia com `cp -p` no primeiro caso e o de pasta ignorada no segundo, sem mudar exit code nem formato.
- **UT-06** — Quando `--version`, `--help`, um comando sem configuração e o `init` rodam, então as saídas e o cabeçalho do `config.yml` dizem `photon-brain`, e `assets/brain-config.yml` começa com `# photon-brain`.
- **UT-07** — Dado um relógio fixo, quando `backup_name()` gera o nome, então é `photon-brain-AAAA-MM-DD-HHMMSS.zip` (e `-files.zip` com arquivos).
- **UT-08** — Dado um destino com backups dos dois prefixos acima do limite de retenção e um arquivo alheio, quando a rotação roda, então apaga os mais antigos pela data do nome, de qualquer prefixo, e nunca o alheio.
- **UT-09** — Dado um backup `second-brain-….zip`, quando `restore` lê uma nota dele, então restaura como hoje.

### 7.3 Testes de Integração
- **IT-01** — Dada uma máquina simulada (`HOME` temporário) configurada pela versão anterior em `~/.config/second-brain` e um vault real temporário, quando `search`, `context`, `doctor` e `backup` rodam pela CLI, então funcionam sem ação, e o backup sai com o nome novo.
- **IT-02** — Dada uma máquina simulada sem configuração, quando `init` roda pela CLI com um vault temporário, então só `~/.config/photon-brain/config.yml` é criado.

### 7.4 Testes de Contrato
- N/A — nenhuma spec consome a CLI da `photon-brain` por contrato versionado; o MCP (SPEC-0059) só repassa a saída e tem a própria suíte, que roda no G5.

### 7.5 Testes E2E
- N/A — nenhuma jornada muda de passos: os mesmos comandos funcionam com a pasta antiga ou a nova (IT-01 e IT-02 rodam o `brain.py` como processo, como a pessoa usa).

### 7.6 Outros
- N/A

**Dublês e dados de teste:** `HOME`, `BRAIN_CONFIG_HOME` e `XDG_CONFIG_HOME` temporários (helpers de `skills/photon-brain/tests/brain_support.py`); relógio fixo para nomes de backup; nunca o `~/.config` real.

**Ambiente de execução:** local e CI (`python3 -m unittest discover -s skills/photon-brain/tests`, Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin (versão nova) e pela cópia da skill.
- **Dados/schema:** N/A — a configuração não muda de formato; só de pasta, com leitura dupla.
- **Compatibilidade:** máquinas com `~/.config/second-brain` seguem funcionando até a SPEC-0073; backups antigos seguem restauráveis e entram na rotação.
- **Observabilidade:** AVISO do `doctor` (e, na SPEC-0072, do `fermion_doctor` no início de sessão).
- **Rollback:** reverter a versão; a pasta antiga nunca foi tocada, e uma pasta nova criada pela versão nova fica sem uso (a versão anterior lê só a antiga).
- **Etapas de migração/coexistência:** leitura dupla agora; o `doctor` mostra a cópia; a SPEC-0073 remove a reserva na versão anunciada no CHANGELOG.

## 9. Questões em Aberto
- [x] A gravação com só a pasta antiga presente grava na nova (e a antiga para de valer) ou na antiga? — Na nova, com a configuração completa; a antiga vira reserva ignorada e o `doctor` avisa (thomas, 2026-11-16: piloto automático com o recomendado)
- [x] O onboarding passa a sugerir `~/photon-brain/vault` em vez de `~/second-brain/vault`? — Sim, só para vaults novos; vaults existentes não mudam (thomas, 2026-11-16: piloto automático com o recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Configuração e textos**
- [x] Red: CH-01 (guarda), UT-01 a UT-06, IT-01, IT-02 com a tag `SPEC-0069:<ID>`, falhando pelo motivo certo
- [x] Green: `local_config_path`/`local_config_write_path`, avisos do `doctor`, textos e `assets/brain-config.yml`

**Fase 2: Backups**
- [x] Red: UT-07 a UT-09
- [x] Green: `backup_name`, `BACKUP_NAME_RE` com os dois prefixos e retenção conjunta
- [x] Validar: suítes da photon-brain, tests/plugin e mcp, arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e aprovação (H2)
- [x] Deploy via pipeline (G6) — N/A: skill distribuída pelo plugin e por cópia
- [x] Relatório de Entrega, references, SKILL.md, CHANGELOG com a data de remoção, versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3ec7d76 | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=30)) — 392393e | 2026-11-17 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 524a3a2 | 2026-11-17 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — e1198bf | 2026-11-17 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (rodada 1; leitura dupla, gravações, backups e textos conferidos por experimento; 2 minors: permissão não preservada na gravação a partir da pasta antiga e comando de cópia só POSIX; 2 nits) — 12c9f78 | 2026-11-17 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK) — 5339099 | 2026-11-17 |
| H2 Integração aprovada | PASS | aprovado por política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-17 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-17 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 9e6772f | 2026-11-17 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
- A `photon-brain` usa o próprio nome no que é técnico: configuração em `~/.config/photon-brain`, mensagens, `--version`, `--help`, cabeçalhos e backups `photon-brain-<data>.zip`. Máquinas com `~/.config/second-brain` funcionam sem ação (leitura dupla), toda gravação vai para a pasta nova e o `doctor` mostra o comando de cópia ou avisa que a antiga é ignorada. Backups antigos entram na rotação e seguem restauráveis. photon-brain 2026.11.8, plugin 2026.11.15.

### Como foi feito
- `local_config_path` (leitura com reserva) e `local_config_write_path` (gravação) em `brain.py`; `old_config_items` no `doctor`; `BACKUP_NAME_RE` com os dois prefixos (grupo não capturante); textos, assets, references, SKILL.md e CHANGELOG (remoção da leitura antiga não antes de 2027-03, SPEC-0073).
- Testes em 0613196 e 392393e (Emenda: a guarda de nomes da SPEC-0055 passou a exigir os identificadores novos), lint em 524a3a2; implementação em 42d236a.
- **Revisão G4:** APPROVED na rodada 1, com experimentos (14 comandos de leitura sem criar a pasta nova, rotação com 18 nomes mistos, `shasum` da pasta antiga inalterado).

### Prova de Correção
N/A — `type: migration`.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| CH-01 | Suíte atual sem outra mudança além de textos e prefixo | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-01 | Leitura: só a antiga → antiga; as duas → nova | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-02 | Sem pastas: leitura e gravação na nova | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-03 | Gravação com só a antiga: configuração completa na nova, antiga idêntica | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-04 | Sobrescrita sem reserva nem aviso | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-05 | doctor: AVISO com `cp -p` e de pasta ignorada | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-06 | Textos dizem `photon-brain` | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-07 | Backup `photon-brain-<data>.zip` | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-08 | Regex e retenção com os dois prefixos, nunca arquivo alheio | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| UT-09 | Restore e `backup list` com backup antigo | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| IT-01 | Máquina configurada pela versão anterior funciona sem ação | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |
| IT-02 | `init` cria só a pasta nova | PASS | `skills/photon-brain/tests/test_rename.py` e suítes da photon-brain e `tests/plugin` — suíte local no G5 (5339099) e CI do PR |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado — ADR-0020
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skill distribuída pelo plugin e por cópia
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — AVISOs do `doctor`; pasta antiga nunca tocada
- [x] Documentação raiz e CHANGELOG atualizados (G7) — CHANGELOG da photon-brain 2026.11.8; o README entra na SPEC-0072
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: o projeto não define `living_docs`
- [x] Pendências registradas como novas specs (ou nenhuma) — ver Pendências

### Deploy
N/A — plugin 2026.11.15, PR desta spec.

### Pendências
- Minor da revisão: a gravação a partir da pasta antiga não preserva o modo do arquivo (sai com o umask, como antes); o arquivo só guarda caminhos. Candidato a ajuste junto da SPEC-0073.
- Minor da revisão: o comando de cópia do `doctor` é POSIX; no Windows a pessoa copia à mão. Candidato a ajuste junto da SPEC-0073.
- Nits: `BACKUP_NAME_RE` com `$` aceita `\n` no fim do nome; o `init` normal regrava só as quatro chaves conhecidas.
- Cobertura do MCP: `mcp/tests/test_brain_server.py` confere que o servidor não toca a pasta antiga, mas não a nova — ajustar na SPEC-0072.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0069`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| v1 (sem mudança de contrato) | 2026-11-17 | `touches` ganha `tests/plugin/test_skill_names.py`: o `KeptIdentifiersTest` (SPEC-0055:UT-04) passa a exigir os identificadores novos da `photon-brain` (pasta padrão sem nenhuma configuração e `--version`), mantendo a checagem de `BACKUP_NAME_RE` com o prefixo antigo | o teste da SPEC-0055 fixava os nomes que esta spec troca; achado pelo test-writer no G1 | SPEC-0070 (mesmo ajuste para a `boson-atlas`), SPEC-0072 | thomas, 2026-11-17 (piloto automático com o recomendado) |
