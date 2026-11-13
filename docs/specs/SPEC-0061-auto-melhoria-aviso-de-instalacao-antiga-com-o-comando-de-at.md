---
id: SPEC-0061
title: "Auto-melhoria: aviso de instalação antiga com o comando de atualização"
tier: full
type: feature
user_facing: true
status: proposed
created: 2026-11-13
parent: SPEC-0031
depends_on: [SPEC-0058, SPEC-0060]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [scripts/fermion_doctor.py, hooks/session_start.py, mcp/**, tests/plugin/test_fermion_doctor.py, tests/plugin/test_session_start.py, .claude-plugin/plugin.json, README.md]
adrs: [ADR-0017, ADR-0019]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0061 — Auto-melhoria: aviso de instalação antiga com o comando de atualização

## 1. Visão Geral
O plugin `fermion` passa a conferir, sempre que é usado, se há instalação antiga ao lado dele e a dizer como atualizar. É o item de radar pedido pelo thomas em 2026-11-12. Um script só de leitura (`scripts/fermion_doctor.py`, stdlib) encontra:
- cópias das skills com o nome antigo (`sdd-management`, `second-brain`, `org-atlas`) na pasta de skills do usuário ou do projeto;
- cópias com o nome novo mais velhas que o plugin;
- `tools/sdd/` do projeto mais velho que a `gluon-spec` do plugin;
- bloco `sdd:start` que ainda manda carregar a `sdd-management`;
- atlas vendorizado (`.org-atlas/skill/`) mais velho que a `boson-atlas`, quando o projeto aberto é o repositório do atlas.

Cada achado vira um aviso com o comando de atualização, no início da sessão (hook da SPEC-0058) e na tool MCP `fermion_doctor`. Nada é atualizado sozinho.

## 2. Motivação & Escopo
**Motivação:** frente 4 do épico SPEC-0031. Depois da troca de nomes (SPEC-0055) e do plugin (SPEC-0053), quem instalou antes fica com duas versões das mesmas skills: o agente pode carregar a cópia velha e o usuário não percebe. Hoje só o `whats-new` da `gluon-spec` olha o `tools/sdd/`, e só quando alguém roda. A checagem automática garante que o usuário sempre tenha a versão melhor sem decorar comandos.

**Objetivos (dentro do escopo):**
- `scripts/fermion_doctor.py [--project PASTA] [--json]`: as cinco checagens, só leitura.
- Hook `SessionStart` (SPEC-0058): bloco "Instalação desatualizada" quando houver achado.
- Tool MCP `fermion_doctor` (sem argumentos, `readOnlyHint`).
- ADR-0019: a política de auto-melhoria (só ler, avisar, nunca atualizar sozinho) e a extensão da regra do ADR-0017 para o script do plugin.

**Não-objetivos (fora do escopo):**
- Atualizar, apagar ou mover qualquer coisa (o aviso traz o comando; quem roda é a pessoa).
- Conferir se há versão nova do plugin no marketplace (exige rede; `claude plugin update` já faz).
- Política de versão mínima do Python e migração do ADR-0001/ADR-0007 (spec própria, `type: migration`).
- Agente mantenedor que abre a spec de atualização sozinho (fica como pendência do épico).
- Pastas de skills de outros agentes (`~/.gemini`, `~/.codex`): cada um tem layout próprio; entram quando houver pedido.

## 3. Dependências
- **Implementações necessárias:** SPEC-0058 (o hook onde o bloco entra), SPEC-0054 e SPEC-0060 (servidor MCP e a pasta do projeto por `CLAUDE_PROJECT_DIR`, que a tool reaproveita), SPEC-0055 (nomes novos e antigos), e as constantes de versão `SDD_TOOL_VERSION`, `BRAIN_VERSION` e `ATLAS_VERSION` nos scripts das skills (formato `AAAA.MM.N`).
- **Contratos consumidos:** N/A — lê arquivos e constantes de versão por expressão regular, como o `whats-new` faz com o `tools/sdd/`.
- **Pré-requisitos externos:** code.claude.com/docs/en/skills e plugins-reference, lidas em 2026-11-13: skills do usuário em `~/.claude/skills/<nome>/SKILL.md` (ou `$CLAUDE_CONFIG_DIR/skills`), do projeto em `.claude/skills/<nome>/SKILL.md`.

## 4. Decisão Arquitetural
**Contexto:** brownfield. Referências: `whats-new` da `gluon-spec` (`spec_graph.py`, leitura de `SDD_TOOL_VERSION` do `tools/sdd/` por regex e comparação de versão) e o formato de linha do `doctor` das skills (`OK|AVISO|ERRO <item> — <detalhe>`).

**Decisão:** um script do plugin, fora das skills (é uma checagem entre skills, e cada skill continua instalável sozinha por cópia). Lê só arquivos; nunca abre processo, nunca grava, nunca usa rede. O hook e o servidor MCP chamam o script como processo, como fazem com as CLIs (ADR-0019 estende a regra do ADR-0017 a ele). Versões comparadas como tupla de inteiros `(AAAA, MM, N)`.

**Justificativa:** a checagem precisa saber do plugin inteiro (as três versões), então não cabe numa skill; ser só leitura deixa rodar a cada início de sessão sem risco.

**Desvio do padrão existente:** pasta nova `scripts/` na raiz do plugin, que não é pasta de componente do Claude Code (só `hooks/`, `agents/`, `commands/`, `output-styles/`, `monitors/` e `bin/` são), coberta pelo ADR-0019.

**Alternativas descartadas:** comando novo dentro da `gluon-spec` (ela não deveria saber da `photon-brain` nem da `boson-atlas`); atualizar sozinho (apagar uma cópia que a pessoa editou perde trabalho; ADR-0019); checar o marketplace na rede (lento no início da sessão e já coberto pelo `claude plugin update`).

**ADRs:** ADR-0017, ADR-0019 (novo, proposto junto com esta spec).

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** só leitura de poucos arquivos; medido no IT-01 (menos de 1 s); o hook não passa dos 20 s da SPEC-0058.
- **Segurança:** nunca grava, nunca apaga, sem processo, sem rede; links simbólicos não são seguidos para fora das pastas conferidas; o aviso mostra caminho e versão, nunca conteúdo de arquivo.
- **Privacidade e dados pessoais:** N/A — caminhos de pastas de skills e versões.
- **Disponibilidade e resiliência:** pasta ausente, sem permissão ou versão ilegível vira aviso próprio ou é ignorada; o script sempre sai com 0.
- **Acessibilidade (UI):** N/A — sem interface.
- **Custo:** bloco do hook limitado a 1.500 caracteres, dentro dos 8.000 da SPEC-0058.

## 6. Artefato A — Contrato
**Interface:** `scripts/fermion_doctor.py`, bloco do hook `SessionStart`, tool MCP `fermion_doctor`

```text
python3 scripts/fermion_doctor.py [--project PASTA] [--json]
  plugin: a pasta acima de scripts/ (Path(__file__)); versões do plugin lidas de skills/gluon-spec/scripts/spec_graph.py (SDD_TOOL_VERSION),
          skills/photon-brain/scripts/brain.py (BRAIN_VERSION) e skills/boson-atlas/scripts/atlas.py (ATLAS_VERSION)
  pastas de skills: usuário = $CLAUDE_CONFIG_DIR/skills, senão $HOME/.claude/skills; projeto = <projeto>/.claude/skills
  projeto: --project, senão o cwd
  checagens (cada achado = uma linha AVISO; sem achado = uma linha OK por checagem):
    old-name-copy   <pasta de skills>/{sdd-management|second-brain|org-atlas}/SKILL.md existe
                    → "AVISO old-name-copy <caminho> — cópia com o nome antigo; o plugin fermion já traz <nome novo> (remova a pasta)"
    stale-copy      <pasta de skills>/{gluon-spec|photon-brain|boson-atlas}/scripts/<script> com versão menor que a do plugin
                    → "AVISO stale-copy <caminho> — <versão da cópia> < <versão do plugin> (copie de novo de <plugin>/skills/<nome> ou remova a pasta)"
    stale-sdd-tool  <projeto>/tools/sdd/spec_graph.py com SDD_TOOL_VERSION menor que a do plugin
                    → "AVISO stale-sdd-tool tools/sdd/spec_graph.py — <v> < <v plugin> (rode: python3 <plugin>/skills/gluon-spec/scripts/spec_graph.py whats-new, depois vendor)"
    old-sdd-block   <projeto>/{AGENTS.md|CLAUDE.md|GEMINI.md} com bloco sdd:start que cita sdd-management e não cita gluon-spec
                    → "AVISO old-sdd-block <arquivo> — bloco SDD com o nome antigo (rode: … spec_graph.py vendor --agents)"
    stale-atlas     <projeto>/.org-atlas/skill/scripts/atlas.py com ATLAS_VERSION menor que a do plugin (só existe quando o projeto aberto é o repositório do atlas, modo repo)
                    → "AVISO stale-atlas .org-atlas/skill — <v> < <v plugin> (rode no repositório do atlas: python3 <plugin>/skills/boson-atlas/scripts/atlas.py vendor --ci <github|generic>, o mesmo --ci da instalação)"
    versão ilegível numa cópia → "AVISO unreadable-version <caminho> — versão não encontrada" (a checagem segue)
  --json → {"plugin_versions": {"gluon-spec": v, "photon-brain": v, "boson-atlas": v},
            "findings": [{"check": id, "level": "warn", "path": caminho, "detail": texto, "fix": comando ou instrução}]}
  exit: sempre 0; nada é gravado

hook SessionStart (SPEC-0058) → com achado, bloco depois dos da SPEC-0058:
  "## Instalação desatualizada (fermion)\n" + uma linha por achado "- <detail> → <fix>", no máximo 1.500 caracteres ("… e mais N")
  sem achado → nenhum bloco

tool MCP fermion_doctor {} (readOnlyHint) → fermion_doctor.py --project <CLAUDE_PROJECT_DIR ou cwd> --json; exit 0 → isError: false com structuredContent
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`. Criar `scripts/fermion_doctor.py` e `tests/plugin/test_fermion_doctor.py`; alterar `hooks/session_start.py` e seu teste, `mcp/fermion_mcp.py` e `mcp/tests/` (tool e regra de arquitetura), `.claude-plugin/plugin.json` (versão) e `README.md`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Tudo em dia | nenhuma cópia, `tools/sdd` igual, bloco novo | só linhas OK; `findings` vazio | UT-01 |
| Cópia com nome antigo | `sdd-management/SKILL.md` na pasta do usuário e `org-atlas/SKILL.md` na do projeto | um `old-name-copy` para cada | UT-02 |
| Cópia nova mais velha | `gluon-spec` copiada com versão menor; outra com versão igual | `stale-copy` só na menor | UT-03 |
| Projeto desatualizado | `tools/sdd` menor, bloco `sdd:start` antigo, `.org-atlas/skill` menor | `stale-sdd-tool`, `old-sdd-block`, `stale-atlas` com os comandos | UT-04 |
| Versão ilegível ou pasta inacessível | script sem constante; pasta sem permissão; link simbólico para fora | `unreadable-version` ou checagem ignorada; exit 0 | UT-05 |
| Só leitura | qualquer execução | nenhum arquivo muda; sem processo, sem rede | UT-06, IT-01 |
| Aviso no início da sessão | hook com achados; sem achados; muitos achados | bloco com até 1.500 caracteres; nenhum bloco | UT-07 |
| Tool MCP | `fermion_doctor` | `structuredContent` com `findings`; `readOnlyHint` | UT-08 |
| Jornada de atualização | instalação antiga e plugin instalado | o aviso aparece no contexto e some depois do comando sugerido | E2E-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — código novo; o hook da SPEC-0058 tem suíte própria que continua passando.

### 7.2 Testes Unitários
- **UT-01** — Dado `HOME` e `CLAUDE_CONFIG_DIR` temporários sem pasta de skills e um projeto com `tools/sdd/spec_graph.py` na mesma versão do plugin e bloco `sdd:start` citando `gluon-spec`, quando o doctor roda com `--json`, então `findings` é vazio, `plugin_versions` traz as três versões das skills do repositório e o texto tem só linhas `OK`.
- **UT-02** — Dado `<config>/skills/sdd-management/SKILL.md` e `<projeto>/.claude/skills/org-atlas/SKILL.md`, quando o doctor roda, então há dois achados `old-name-copy`, com os caminhos e os nomes novos `gluon-spec` e `boson-atlas`.
- **UT-03** — Dado `<config>/skills/gluon-spec/scripts/spec_graph.py` com `SDD_TOOL_VERSION = "2026.10.1"` e `<config>/skills/photon-brain/scripts/brain.py` com a versão do plugin, quando o doctor roda, então há um `stale-copy` só para a `gluon-spec`, citando `2026.10.1` e a versão do plugin; `2026.10.10` é tratada como maior que `2026.10.9`.
- **UT-04** — Dado um projeto com `tools/sdd/spec_graph.py` em versão menor, `AGENTS.md` com bloco `sdd:start` citando só `sdd-management` e `.org-atlas/skill/scripts/atlas.py` em versão menor, quando o doctor roda, então há `stale-sdd-tool` (com `whats-new` e `vendor`), `old-sdd-block` (com `vendor --agents`) e `stale-atlas` (com `atlas.py vendor --ci <github|generic>`).
- **UT-05** — Dados um `spec_graph.py` copiado sem constante de versão, uma pasta de skills sem permissão de leitura e `<config>/skills/gluon-spec` como link simbólico para fora da pasta, quando o doctor roda, então há `unreadable-version` para o primeiro, os outros dois são ignorados sem exceção, e o exit é 0 (o caso sem permissão é pulado com o motivo quando o teste roda como root, `os.geteuid() == 0`, porque root lê tudo).
- **UT-06** — Dados o código de `scripts/fermion_doctor.py` e exemplos que violam as regras, quando as regras do ADR-0019 rodam, então acusam import fora da stdlib, `subprocess`, `socket`/`urllib`, e escrita em arquivo (`open` com modo de escrita, `write_text`, `unlink`, `rmtree`, `rename`); o código real não tem achado. As regras ficam em `tests/plugin/` e o Architect inclui o arquivo no `arch_test` do `sdd-config.yml` no G1.
- **UT-07** — Dado um executor falso do doctor com dois achados, com zero e com 40 achados, quando o hook monta o contexto, então há o bloco `## Instalação desatualizada (fermion)` com as duas linhas, nenhum bloco, e um bloco de até 1.500 caracteres terminado em `… e mais N`, respectivamente.
- **UT-08** — Dado o servidor MCP com executor falso, quando recebe `tools/list` e `tools/call` de `fermion_doctor`, então a tool tem `inputSchema` vazio e fechado e `readOnlyHint: true`, a linha de comando é `fermion_doctor.py --project <projeto> --json` e o resultado traz `structuredContent` com `findings`.

### 7.3 Testes de Integração
- **IT-01** — Dado um projeto temporário com `tools/sdd/spec_graph.py` copiado do plugin com `SDD_TOOL_VERSION` reduzido no teste e uma pasta de skills temporária com `second-brain/SKILL.md`, quando `scripts/fermion_doctor.py --json` roda como processo real, então os achados `stale-sdd-tool` e `old-name-copy` aparecem, o processo termina com 0 em menos de 1 s, e o conteúdo e a data de modificação de todos os arquivos do projeto e da pasta de skills ficam iguais.

### 7.4 Testes de Contrato
- N/A — sem contrato entre módulos além do JSON do próprio script, coberto nos UT-01 e UT-08.

### 7.5 Testes E2E
- **E2E-01** — [jornada: atualização de instalação antiga] Dado o Claude Code CLI no PATH e uma configuração isolada (isolamento do SPEC-0053:E2E-01) com `skills/org-atlas/SKILL.md` na pasta de skills do usuário, quando o plugin `fermion` é instalado e o hook `SessionStart` instalado roda como o `hooks.json` declara num projeto de fixture, então o `additionalContext` traz o aviso `old-name-copy` com a instrução; depois de seguir a instrução (remover a pasta) e rodar o hook de novo, o aviso some. Sem `claude` no PATH o teste é pulado com o motivo.

### 7.6 Outros
- Tempo do doctor no IT-01 (menos de 1 s).

**Dublês e dados de teste:** pastas temporárias para `HOME`, `CLAUDE_CONFIG_DIR` e projetos; cópias de scripts das skills com a constante de versão trocada no teste; nunca o `~/.claude` real.

**Ambiente de execução:** local e CI, sem rede; o E2E-01 onde houver `claude` no PATH.

## 8. Plano de Rollout
- **Estratégia:** deploy direto com `claude plugin update`.
- **Dados/schema:** N/A.
- **Compatibilidade:** só acrescenta um bloco opcional ao contexto e uma tool; quem usa as skills por cópia não é afetado.
- **Observabilidade:** o próprio aviso; stderr do hook se o doctor falhar.
- **Rollback:** reverter o merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [x] O aviso só mostra o comando ou também atualiza? — Só mostra: atualizar ou apagar sozinho pode perder edição da pessoa (ADR-0019) (decidido pelo thomas no radar de 2026-11-12: "nunca atualiza sozinha", registrado na SPEC-0031)
- [x] Onde o aviso aparece? — No início da sessão (hook) e na tool MCP `fermion_doctor` (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-13: "pode seguir no piloto automático com o recomendado"; revisável no H1)
- [x] O agente mantenedor que abre a spec de atualização entra aqui? — Não: fica como pendência do épico; esta spec entrega a detecção (recomendação do arquiteto, aceita no piloto automático, thomas, 2026-11-13; revisável no H1)

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0061`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
