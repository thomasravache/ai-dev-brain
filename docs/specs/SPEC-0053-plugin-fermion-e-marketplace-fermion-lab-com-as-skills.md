---
id: SPEC-0053
title: Plugin fermion e marketplace fermion-lab com as skills
tier: full
type: feature
user_facing: true
status: proposed
created: 2026-11-12
parent: SPEC-0031
depends_on: [SPEC-0029]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [.claude-plugin/**, tests/plugin/**, README.md, .github/workflows/ci.yml]
adrs: [ADR-0016]
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0053 — Plugin fermion e marketplace fermion-lab com as skills

<!-- type: feature | fix | refactor | migration | foundation. user_facing: true quando a mudança altera uma jornada do usuário (UI ou API pública) — exige teste E2E. Substitua todos os marcadores com chaves duplas: o G0 (`spec_graph.py validate`) reprova a spec enquanto restar algum. As seções de Checklist em diante são preenchidas depois da aprovação, sem marcadores. -->

## 1. Visão Geral
O repositório passa a ser um marketplace do Claude Code chamado `fermion-lab`, com um plugin `fermion` que traz as três skills (`sdd-management`, `second-brain`, `org-atlas`). Instalar vira um comando (`claude plugin marketplace add thomasravache/ai-dev-brain` e `claude plugin install fermion@fermion-lab`), e as skills aparecem como `/fermion:sdd-management`, `/fermion:second-brain` e `/fermion:org-atlas`. A instalação por cópia da pasta continua funcionando.

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
- **Implementações necessárias:** SPEC-0029 — as três skills que o plugin empacota já estão entregues.
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
  nenhum caminho de componente declarado: as skills vêm do scan padrão de skills/

skills/<pasta>/SKILL.md (as três)
  frontmatter com name igual ao nome da pasta e description não vazia
  nenhuma referência a arquivo fora da própria pasta da skill (nem "../", nem caminho do repositório como tools/ ou docs/)
  a pasta copiada sozinha para outro lugar continua funcionando (a CLI responde a --help e ao comando de diagnóstico)

instalação
  claude plugin marketplace add <owner/repo | caminho>  → marketplace fermion-lab
  claude plugin install fermion@fermion-lab              → skills /fermion:sdd-management, /fermion:second-brain, /fermion:org-atlas
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
| Skill autocontida | referência a `../`, `tools/` ou `docs/` num SKILL.md, script ou referência da skill | a checagem acusa; as três skills reais passam | UT-05 |
| Plugin copiado para o cache | raiz copiada (só arquivos versionados) para uma pasta temporária | as três CLIs rodam a partir da cópia | IT-01 |
| Cópia da pasta continua funcionando | só `skills/<nome>` copiada para outra pasta | a CLI da skill roda | IT-01 |
| Instalação real | Claude Code CLI disponível | `validate` exit 0; marketplace e plugin instalados; três skills listadas | E2E-01 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- N/A — arquivos novos; as skills já têm suítes próprias.

### 7.2 Testes Unitários
- **UT-01** — Dado o `.claude-plugin/marketplace.json` do repositório, quando é lido, então tem `name: fermion-lab`, `owner.name` não vazio, um único plugin `fermion` com `source: "./"` e descrição, e nenhuma chave de topo fora de `name`, `owner`, `plugins`, `metadata`.
- **UT-02** — Dado o `.claude-plugin/plugin.json`, quando é lido, então `name` é `fermion` (igual ao do marketplace), `version` segue `AAAA.MM.N`, há `description` e `repository`, e nenhum caminho de componente é declarado.
- **UT-03** — Dados manifestos inválidos montados no teste (JSON quebrado, nome `Fermion_Lab`, plugin.json com `name` diferente, `source: "./plugins/x"`), quando a checagem roda, então cada um gera um achado próprio.
- **UT-04** — Dado `skills/`, quando o scan é simulado como o do Claude Code (`skills/<pasta>/SKILL.md`), então acha exatamente `sdd-management`, `second-brain` e `org-atlas`, cada uma com `name` igual à pasta e `description` não vazia.
- **UT-05** — Dado um `SKILL.md` de exemplo com `../shared`, `tools/sdd/` e `docs/specs/`, quando a checagem de autocontenção roda, então acusa os três; nas três skills reais não há achado.

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

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3beae75 (árvore suja) | 2026-11-12 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0053`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
