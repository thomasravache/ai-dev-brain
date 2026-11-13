---
id: SPEC-0053
title: Plugin fermion e marketplace fermion-lab com as skills
tier: full
type: feature
user_facing: true
status: implemented
created: 2026-11-12
parent: SPEC-0031
depends_on: [SPEC-0055]
consumes_contract: []
contract_version: 4
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [.claude-plugin/**, tests/plugin/**, README.md, .github/workflows/ci.yml]
adrs: [ADR-0016]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-12
---

# SPEC-0053 — Plugin fermion e marketplace fermion-lab com as skills

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O repositório passa a ser um marketplace do Claude Code chamado `fermion-lab`, com um plugin `fermion` que traz as três skills (`gluon-spec`, `photon-brain`, `boson-atlas`, renomeadas pela SPEC-0055). Instalar vira um comando (`claude plugin marketplace add thomasravache/ai-dev-brain` e `claude plugin install fermion@fermion-lab`), e as skills aparecem como `/fermion:gluon-spec`, `/fermion:photon-brain` e `/fermion:boson-atlas`. A instalação por cópia da pasta continua funcionando.

## 2. Motivação & Escopo
**Motivação:** hoje cada skill é copiada à mão, uma por uma, e atualizar é copiar de novo. Um plugin instala e atualiza o conjunto de uma vez e é a base do servidor MCP (SPEC-0054) e do hook de início de sessão.

**Objetivos (dentro do escopo):**
- `.claude-plugin/marketplace.json` (marketplace `fermion-lab`, um plugin `fermion` com `"source": "./"`) e `.claude-plugin/plugin.json` (`name: fermion`, versão, descrição, repositório; sem `license`, porque o repositório ainda não tem licença).
- Testes que garantem o formato dos dois arquivos, que as três skills são achadas pelo scan padrão de `skills/` e que nenhuma skill depende de arquivo fora da própria pasta (o plugin é copiado para um cache na instalação).
- README com a instalação pelo plugin, mantendo a cópia da pasta como alternativa.

**Não-objetivos (fora do escopo):**
- Servidor MCP (SPEC-0054), hook `SessionStart` e comando de entrada única (filha seguinte).
- Renomear as skills ou o repositório; publicar o marketplace em diretórios de terceiros.
- Rodar `claude plugin validate` na CI (exigiria instalar o Claude Code no runner): roda no G4 e no E2E-01 local.

## 3. Dependências
- **Implementações necessárias:** SPEC-0055 — as três skills já com os nomes finais, que viram os comandos do plugin.
- **Contratos consumidos:** N/A.
- **Pré-requisitos externos:** formato de plugin e marketplace do Claude Code (code.claude.com/docs/en/plugins: manifest-reference, marketplace-reference, loading, cli-reference, lidos em 2026-11-12); Claude Code CLI instalado só para o E2E-01 e o `claude plugin validate`.

## 4. Decisão Arquitetural
**Contexto:** brownfield. As skills são pastas independentes com `SKILL.md` e CLI stdlib (ADR-0001, ADR-0007, ADR-0010) e já citam os scripts por `<skill-dir>/scripts/...`, sem caminho fixo. Referência para os testes: `skills/*/tests/test_architecture.py` (unittest stdlib, regra testada contra exemplo e contra o código real).

**Decisão:** o repositório inteiro é o plugin (ADR-0016): `.claude-plugin/` na raiz com os dois manifestos e o scan padrão de `skills/`. Os testes ficam em `tests/plugin/` (unittest, stdlib) e entram na CI e no `test` do `sdd-config.yml`.

**Justificativa:** caminhos fora da raiz do plugin são rejeitados pelo Claude Code; com a raiz do repositório como plugin, as skills entram sem cópia, link ou script de release, e a pasta de cada skill continua sendo a fonte da verdade.

**Desvio do padrão existente:** Nenhum nas skills. Arquivos novos na raiz (`.claude-plugin/`, `tests/plugin/`), cobertos pelo ADR-0016.

**Alternativas descartadas:** plugin numa subpasta (`plugins/fermion/`) apontando para `../../skills` (o Claude Code rejeita); cópia das skills gerada na release (duplica arquivos e pede um passo de build); symlinks (não documentados para a cópia ao cache).

**ADRs:** ADR-0016.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — só manifestos; o tamanho do cache é o do repositório.
- **Segurança:** o plugin não traz hooks nem servidores nesta spec; nenhum segredo nos manifestos (UT-01 confere só campos esperados). O conteúdo do repositório inteiro vai para o cache: `docs/` e `tools/` não têm segredo (o `secret-leak` da org-atlas e a revisão do G4 conferem).
- **Privacidade e dados pessoais:** o `owner` do marketplace é o login público do GitHub (`thomasravache`), sem e-mail.
- **Disponibilidade e resiliência:** N/A — sem processo em execução.
- **Acessibilidade (UI):** N/A — sem interface.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json` e a instalação `claude plugin install fermion@fermion-lab`

```text
.claude-plugin/marketplace.json
  {
    "name": "fermion-lab",
    "owner": {"name": "thomasravache"},
    "plugins": [
      {"name": "fermion", "source": "./", "description": "<uma frase: SDD, segundo cérebro e atlas da organização>"}
    ]
  }
  só essas chaves no topo (mais "metadata" opcional com description); um único plugin

.claude-plugin/plugin.json
  {"name": "fermion", "version": "<AAAA.MM.N>", "description": "...", "repository": "https://github.com/thomasravache/ai-dev-brain"}
  name em kebab-case e igual ao plugins[0].name do marketplace; version no formato AAAA.MM.N, a primeira 2026.11.1
  nenhum caminho de componente declarado: as skills vêm do scan padrão de skills/; a única chave de componente permitida é "mcpServers", com o servidor "fermion" da SPEC-0054 declarado inline   (v3)
  componentes por pasta padrão na raiz: só hooks/hooks.json, hooks/session_start.py (SPEC-0058) e commands/deliver.md (SPEC-0058); nenhum outro arquivo em hooks/, agents/, commands/, output-styles/, monitors/ nem .mcp.json   (v4)

skills/<pasta>/SKILL.md (as três)
  frontmatter com name igual ao nome da pasta e description não vazia
  nenhuma referência que a skill resolve a partir da própria pasta e que caia fora dela   (v2):
    links Markdown relativos ([x](caminho)) em SKILL.md, references/ e assets/ cujo destino, resolvido a partir do arquivo, sai de skills/<nome>/
    "<skill-dir>/.." em qualquer texto da skill
    nos scripts: Path(__file__) subindo além da pasta da skill, ou sys.path/caminho apontando para outra skill ou para o tools/ deste repositório
  caminhos citados como do projeto, vault ou atlas de quem usa (docs/specs/, tools/sdd/, ../{repo}.worktrees, ../ de vault) são permitidos   (v2)
  tests/ de cada skill fica fora da checagem (fixtures e exemplos de violação)   (v2)
  a pasta copiada sozinha para outro lugar continua funcionando (a CLI responde a --help e ao comando de diagnóstico)

instalação
  claude plugin marketplace add <owner/repo | caminho>  → marketplace fermion-lab
  claude plugin install fermion@fermion-lab              → skills /fermion:gluon-spec, /fermion:photon-brain, /fermion:boson-atlas
  claude plugin validate .                               → exit 0 (avisos aceitos: CLAUDE.md na raiz não é carregado)

erros
  manifesto inválido (JSON quebrado, nome fora de kebab-case, plugin.json e marketplace divergentes, source diferente de "./") → a suíte tests/plugin falha
  skill sem frontmatter válido ou com referência para fora da pasta → a suíte tests/plugin falha
```

**Design:** N/A — sem interface.

**Arquivos/módulos afetados:** ver `touches`. Criar `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`, `tests/plugin/test_plugin.py` (e helpers, se precisar); alterar `README.md` (instalação) e `.github/workflows/ci.yml` (passo da suíte `tests/plugin`).

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Manifestos válidos | marketplace.json e plugin.json do repositório | campos e nomes do contrato; plugin e marketplace coerentes | UT-01, UT-02 |
| Manifesto inválido | JSON quebrado, nome fora de kebab-case, nomes divergentes, source diferente de "./" | a checagem acusa cada caso | UT-03 |
| Skills achadas pelo scan | `skills/*/SKILL.md` | três skills, name igual à pasta, description não vazia | UT-04 |
| Skill autocontida | link relativo, `<skill-dir>/..` ou caminho de script que sai da pasta da skill | a checagem acusa; caminhos do projeto alvo não; as três skills reais passam | UT-05 |
| Plugin copiado para o cache | raiz copiada (só arquivos versionados) para uma pasta temporária | as três CLIs rodam a partir da cópia | IT-01 |
| Cópia da pasta continua funcionando | só `skills/<nome>` copiada para outra pasta | a CLI da skill roda | IT-01 |
| Instalação real | Claude Code CLI disponível | `validate` exit 0; marketplace e plugin instalados; três skills listadas | E2E-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — arquivos novos; as skills já têm suítes próprias.

### 7.2 Testes Unitários
- **UT-01** — Dado o `.claude-plugin/marketplace.json` do repositório, quando é lido, então tem `name: fermion-lab`, `owner.name` não vazio, um único plugin `fermion` com `source: "./"` e descrição, e nenhuma chave de topo fora de `name`, `owner`, `plugins`, `metadata`.
- **UT-02** — Dado o `.claude-plugin/plugin.json`, quando é lido, então `name` é `fermion` (igual ao do marketplace), `version` segue `AAAA.MM.N`, há `description` e `repository`, e nenhum caminho de componente é declarado; `mcpServers` só é aceito com o servidor `fermion` da SPEC-0054 (v3); nas pastas de componente da raiz só existem `hooks/hooks.json`, `hooks/session_start.py` e `commands/deliver.md` (v4).
- **UT-03** — Dados manifestos inválidos montados no teste (JSON quebrado, nome `Fermion_Lab`, plugin.json com `name` diferente, `source: "./plugins/x"`), quando a checagem roda, então cada um gera um achado próprio.
- **UT-04** — Dado `skills/`, quando o scan é simulado como o do Claude Code (`skills/<pasta>/SKILL.md`), então acha exatamente `gluon-spec`, `photon-brain` e `boson-atlas`, cada uma com `name` igual à pasta e `description` não vazia.
- **UT-05** — Dada uma skill de exemplo com `[x](../shared/a.md)`, `<skill-dir>/../tools/sdd/x` e um script com `sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))`, e com o texto "rode `docs/specs/INDEX.md`" e "`tools/sdd/spec_graph.py` do projeto", quando a checagem de autocontenção roda, então acusa os três primeiros e não os dois textos do projeto alvo; nas três skills reais (fora de `tests/`) não há achado (v2).

### 7.3 Testes de Integração
- **IT-01** — Dado o repositório, quando os arquivos versionados (`git ls-files`) são copiados para uma pasta temporária, como o cache do plugin, e, à parte, só `skills/<nome>` é copiada para outra pasta, então `spec_graph.py --help`, `brain.py --help` e `atlas.py --help` rodam com exit 0 a partir das duas cópias.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs; a SPEC-0054 depende desta implementação, não de um contrato versionado.

### 7.5 Testes E2E
- **E2E-01** — Com o Claude Code CLI disponível (pulado sem ele, com o motivo no resultado) e uma configuração isolada numa pasta temporária: `claude plugin validate .` sai com 0; `claude plugin marketplace add <repositório>` registra `fermion-lab`; `claude plugin install fermion@fermion-lab` instala; a listagem mostra o plugin `fermion` habilitado. [jornada: instalação do plugin]

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** manifestos inválidos montados em pasta temporária; cópias do repositório em pasta temporária.

**Ambiente de execução:** UT e IT locais e na CI (precisa de `git`), sem rede; E2E-01 local, com o Claude Code instalado, no G4 e no G5.

## 8. Plano de Rollout
- **Estratégia:** deploy direto: o marketplace existe quando o merge chega à `main`.
- **Dados/schema:** N/A.
- **Compatibilidade:** quem instalou por cópia continua igual; o plugin é opcional.
- **Observabilidade:** N/A — sem processo; `claude plugin validate` no G4.
- **Rollback:** reverter o merge; quem instalou roda `claude plugin uninstall fermion@fermion-lab`.
- **Etapas de migração/coexistência:** README mostra os dois caminhos de instalação.

## 9. Questões em Aberto
- [x] Nome do marketplace e do plugin — `fermion-lab` e `fermion`; `hadron`/`hadron-lab` ocupados (thomas, 2026-11-12)
- [x] O plugin aponta para `skills/` ou copia? — Aponta: o repositório é o plugin (`source: "./"`), ADR-0016 (thomas, 2026-11-12)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Manifestos e skills autocontidas**
- [x] Red: UT-01 a UT-05 e IT-01 em `tests/plugin/test_plugin.py` com a tag `SPEC-0053:<ID>`, falhando pelo motivo certo
- [x] Green: `.claude-plugin/marketplace.json` e `plugin.json` (as skills já passam na checagem de autocontenção v2)
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)

**Fase 2: Jornada de instalação**
- [x] Red: E2E-01 (pulado sem o Claude Code CLI) falhando pelo motivo certo localmente
- [x] Green: `claude plugin validate .`, `marketplace add` e `install fermion@fermion-lab` passando localmente
- [x] README com a instalação pelo plugin e o passo `tests/plugin` na CI

**Fase final: Integração, entrega e documentação**
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy via pipeline (G6) — N/A: o marketplace existe quando o merge chega à main
- [x] Relatório de Entrega e README (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 997634e (árvore suja) | 2026-11-12 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin` exit 1 (red: FAILED (failures=5)); nota: vermelho em 1962030: test_plugin.py 10 testes, 5 falhas (UT-01, UT-02, guarda do UT-03, IT-01 e E2E-01: manifestos inexistentes; E2E-01 rodou com CLAUDE_CONFIG_DIR/HOME temporários e falhou em marketplace add com manifest_missing); UT-04 e UT-05 já passam (skills reais autocontidas) — 1962030 | 2026-11-13 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — ea6f6d6 | 2026-11-13 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — ea6f6d6 | 2026-11-13 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: Reviewer (ea6f6d6): APPROVED — manifestos conforme o contrato v2, validate exit 0 (avisos author, CLAUDE.md na raiz, LICENSE/ICON do diretório), E2E isolado sem tocar ~/.claude; minors M2/M3/M4b e nits N2/N3/N4 corrigidos exatamente como sugerido em 3af8f52 (testes) e 5a70b3b (README), 18 testes OK; M1 e M4a viraram SPEC-0056 e SPEC-0057; N1 (author) fica para a SPEC-0056 — 5a70b3b | 2026-11-13 |
| G5 Integração & CI | PASS | test exit 0 (OK); arch_test exit 0 (OK); nota: CI do PR #25 em adc8663 verde (run 43459407968 ci Python 3.9/3.15; run 43459408198 sdd/pr-check) — 79df8b4 | 2026-11-13 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-13 |
| G6 Deploy | N/A | skills distribuídas por cópia e pelo plugin, sem deploy — mesmo critério da SPEC-0017 | 2026-11-13 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — c052ead | 2026-11-13 |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-11-12 | G1 | spec | SPEC_DEFECT do Test-writer: UT-05 manda acusar '../', 'tools/' e 'docs/' por texto, mas as três skills citam esses caminhos como caminhos do projeto, vault ou atlas de quem usa (gluon-spec: docs/specs, tools/sdd, ../{repo}.worktrees; photon-brain e boson-atlas: ../ de vault e páginas), e o UT-04 da SPEC-0055 exige tools/sdd/spec_graph.py | Test-writer contou as ocorrências e propôs a regra por links e <skill-dir>/..; nenhum teste escrito | thomas | Emenda v2 — autocontenção só para links relativos, <skill-dir>/.. e caminhos de script que saem da pasta da skill; caminhos do projeto alvo permitidos; tests/ fora (H1 thomas, 2026-11-13) | 2026-11-13 |

## 14. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Diz o que foi feito, como, e prova que foi resolvido. Para status implemented o validate exige todas as subseções preenchidas, todo teste do plano com PASS + evidência e a Definição de Pronto toda marcada. -->

### O que foi entregue
O repositório é o marketplace `fermion-lab` com um plugin `fermion` (`source: "./"`, versão 2026.11.1) que traz as três skills: `claude plugin marketplace add thomasravache/ai-dev-brain` e `claude plugin install fermion@fermion-lab` (ou `claude plugin install fermion --marketplace thomasravache/ai-dev-brain`) instalam `/fermion:gluon-spec`, `/fermion:photon-brain` e `/fermion:boson-atlas`. A instalação por cópia da pasta continua funcionando. README com instalação, atualização e desinstalação.

### Como foi feito
- `.claude-plugin/marketplace.json` e `plugin.json` (ADR-0016) em ea6f6d6; README em ea6f6d6 e 5a70b3b; testes em 1962030, 3af8f52 e 11636bb (`tests/plugin/test_plugin.py`).
- **Emenda v2 (IMP-01, H1 thomas 2026-11-13):** autocontenção das skills medida por links relativos, `<skill-dir>/..` e caminhos de script que saem da pasta, e não por texto (as skills citam `docs/specs/` e `tools/sdd/` do projeto de quem usa).
- **Emenda v3 (IMP-02 da SPEC-0054, H1 thomas 2026-11-13):** o `plugin.json` pode declarar `mcpServers` só com o servidor `fermion`.
- O E2E-01 roda o Claude Code de verdade com `HOME`, `CLAUDE_CONFIG_DIR` e `XDG_*` temporários e confere que a configuração real não muda.
- **Revisão G4:** APPROVED; minors de autocontenção (path com `/ ".."`, `os.path.join`, links de referência e `href`), guarda de componentes acidentais na raiz, casos do UT-03, isolamento do E2E e o comando de um passo corrigidos em 3af8f52 e 5a70b3b.
- `claude plugin validate .` sai com 0; avisos aceitos: falta `author`, `CLAUDE.md` na raiz não é carregado, falta LICENSE e ícone (só para o diretório de plugins).

### Prova de Correção
N/A — `type` não é `fix`.

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | marketplace.json `fermion-lab`, um plugin `fermion` com `source: "./"`, sem e-mail | PASS | `test_plugin.py::MarketplaceManifestTest` — CI do PR #25 em adc8663 (run 43459407968, Python 3.9 e 3.15) e suíte local no G5 |
| UT-02 | plugin.json coerente, versão AAAA.MM.N, só o `mcpServers` do `fermion`; nada de componente acidental na raiz | PASS | `PluginManifestTest` — CI do PR #25 em adc8663 (run 43459407968, Python 3.9 e 3.15) e suíte local no G5 |
| UT-03 | Cada manifesto inválido gera o seu achado | PASS | `ManifestCheckTest` — CI do PR #25 em adc8663 (run 43459407968, Python 3.9 e 3.15) e suíte local no G5 |
| UT-04 | Scan acha as três skills com `name` igual à pasta | PASS | `SkillScanTest` — CI do PR #25 em adc8663 (run 43459407968, Python 3.9 e 3.15) e suíte local no G5 |
| UT-05 | Autocontenção por links, `<skill-dir>/..` e scripts; caminhos do projeto alvo permitidos | PASS | `SelfContainmentTest` — CI do PR #25 em adc8663 (run 43459407968, Python 3.9 e 3.15) e suíte local no G5 |
| IT-01 | CLIs rodam a partir da cópia do cache e da pasta copiada sozinha | PASS | `PluginCopyTest` — CI do PR #25 em adc8663 (run 43459407968, Python 3.9 e 3.15) e suíte local no G5 |
| E2E-01 | `validate`, `marketplace add`, `install` e listagem com as três skills, em configuração isolada | PASS | `PluginInstallJourneyTest` (local, Claude Code 2.1.322; pulado na CI sem o CLI) — CI do PR #25 em adc8663 (run 43459407968, Python 3.9 e 3.15) e suíte local no G5 |

### Definição de Pronto
- [x] Todos os testes do plano passando e listados na Verificação
- [x] Todo comportamento do Mapa de Comportamentos coberto e verificado
- [x] Suíte completa, arquitetura e CI verdes no resultado integrado (G5) — CI do PR #25 em adc8663
- [x] Review independente sem achados blocker/major (G4) — revisão aprovada
- [x] Padrão arquitetural existente mantido, ou desvio coberto por ADR aprovado — ADR-0016
- [x] Requisitos não-funcionais medidos com evidência (ou N/A justificado) — N/A — só manifestos; privacidade: `owner` é o login público, sem e-mail (UT-01)
- [x] Disponível no ambiente-alvo via pipeline, com smoke/E2E passando no ambiente (G6) — N/A: skills distribuídas por cópia e pelo plugin; o marketplace existe quando o merge chega à `main`
- [x] Observabilidade e rollback prontos conforme o Plano de Rollout — rollback por revert; `claude plugin uninstall fermion@fermion-lab`
- [x] Documentação raiz e CHANGELOG atualizados (G7) — README (instalação pelo plugin e por cópia); sem CHANGELOG raiz no repositório, a versão do plugin fica no `plugin.json` (SPEC-0056)
- [x] Guia de jornadas e mapa do sistema atualizados quando a entrega muda uma jornada ou um componente (G7) — N/A: `living_docs` não habilitado neste repositório
- [x] Pendências registradas como novas specs (ou nenhuma) — SPEC-0056 (versão do plugin) e SPEC-0057 (hook do leak-check)

### Deploy
N/A — marketplace no próprio repositório; plugin `fermion` 2026.11.1 na branch `sdd/SPEC-0031`, PR #25.

### Pendências
- SPEC-0056 — a versão do plugin precisa subir quando as skills mudam, senão `claude plugin update` não traz as novidades; inclui o `author` no `plugin.json`.
- SPEC-0057 — o hook do leak-check grava o caminho absoluto da instalação, que some quando o cache do plugin muda de versão.

## 15. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0053`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-12 | Autocontenção (UT-05) passa a valer só para o que a skill resolve a partir da própria pasta: links Markdown relativos, `<skill-dir>/..` e caminhos de script (`Path(__file__)`, `sys.path`) que saem de `skills/<nome>/`; caminhos do projeto, vault ou atlas de quem usa (`docs/specs/`, `tools/sdd/`, `../` do vault) são permitidos; `tests/` fica fora | IMP-01: a regra por texto acusaria as três skills, que citam esses caminhos como do projeto alvo, e contradiria a SPEC-0055:UT-04 | nenhuma (sem consumidores) | thomas, 2026-11-13 |
| 3 | 2026-11-13 | `plugin.json` pode declarar `mcpServers` com o servidor `fermion` (inline, `${CLAUDE_PLUGIN_ROOT}/mcp/fermion_mcp.py`); as outras chaves de componente continuam proibidas; UT-02 ajustado | IMP-01 da SPEC-0054: o contrato v2 proibia toda chave de componente, inclusive a declaração do servidor MCP que a SPEC-0054 precisa | SPEC-0054 (consome a permissão) | thomas, 2026-11-13 |
| 4 | 2026-11-13 | Guarda da raiz: `hooks/hooks.json`, `hooks/session_start.py` e `commands/deliver.md` entram no contrato (lista exata); o resto das pastas de componente continua proibido; UT-02 ajustado | SPEC-0058 precisa do hook `SessionStart` e do comando `/fermion:deliver` por pasta padrão | SPEC-0058 (consome a permissão) | pendente — H1 junto com a SPEC-0058 |
