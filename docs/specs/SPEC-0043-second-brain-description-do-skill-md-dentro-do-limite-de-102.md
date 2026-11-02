---
id: SPEC-0043
title: "second-brain: description do SKILL.md dentro do limite de 1024 caracteres"
tier: lite
type: fix
user_facing: false
status: implemented
created: 2026-11-02
parent:
depends_on: []
consumes_contract: []
touches: [skills/second-brain/SKILL.md, skills/second-brain/tests/test_instructions.py, skills/second-brain/scripts/brain.py, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-02
---

# SPEC-0043 — second-brain: description do SKILL.md dentro do limite de 1024 caracteres

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Ao subir a skill no claude.ai (Settings → Skills → Upload a skill, com `second-brain.zip`), o upload é recusado com "field 'description' in SKILL.md must be at most 1024 characters". A `description` do `skills/second-brain/SKILL.md` tem 1149 caracteres.

- **Reprodução:** zipar `skills/second-brain/` e subir no claude.ai.
- **Esperado:** o upload passa na validação e a skill fica disponível na conta, para usar em outros projetos (ex.: o projeto de inglês do usuário).
- **Impacto:** a skill não pode ser usada no claude.ai; só funciona copiada para `~/.claude/skills/`, onde o limite não é verificado.

## 2. Causa Raiz
A `description` foi crescendo a cada spec (SPEC-0018 search/related/links, SPEC-0019 ingest, processadores, inbox, lint…) sem nenhum limite. O formato de skills limita `description` a 1024 caracteres e `name` a 64 (minúsculas, dígitos e hífen), mas o teste `test_instructions.py` (`test_skill_md_describes_onboarding_join_and_direct_use`, SPEC-0017) só confere que o campo existe. Nada impede a regressão.

## 3. Mudança Proposta
- `test_instructions.py` ganha um teste que lê a `description` do frontmatter (escalar dobrado `>-`, juntando as linhas) e exige no máximo 1024 caracteres, e exige `name` com no máximo 64 caracteres em `[a-z0-9-]`.
- A `description` do `SKILL.md` é reescrita mais curta (≈840 caracteres), mantendo todos os gatilhos e comandos citados hoje: configurar (onboarding de vault novo ou existente, máquina nova), ver a configuração, criar contexto, `doctor`; `search`, `related`, `links`; `ingest`, `new-note`, `relate`, `index`; `process` (YouTube, vídeo, áudio, PDF); perguntar ("o que eu sei sobre X", "me prepara para a prova": `context`, nota `answer`); inbox (`capture`, `inbox list`, `ingest --move`, `inbox done`, inclusive do celular); `lint`.
- `BRAIN_VERSION` vai para 2026.11.1 e o `CHANGELOG.md` da skill ganha a seção correspondente (ADR-0007).

NÃO muda: o corpo do `SKILL.md`, o `brain.py` (além da versão) e o `name`.

**Padrão seguido:** `test_instructions.py::InstructionsTest.test_skill_md_describes_onboarding_join_and_direct_use` (leitura do frontmatter com `read` e `split("---", 2)`)

**Rollback:** `git revert` do merge

**Outras ocorrências:** Nenhuma — a outra skill do repositório (`skills/sdd-management/SKILL.md`) tem `description` com 769 caracteres.

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0043:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- Caracterização: N/A — o teste `test_skill_md_describes_onboarding_join_and_direct_use` (SPEC-0017) já cobre o restante do `SKILL.md` e continua valendo.
- **UT-01** — Dado o `skills/second-brain/SKILL.md`, quando o teste lê o frontmatter, então a `description` (linhas do escalar dobrado juntadas com espaço) tem no máximo 1024 caracteres e o `name` tem no máximo 64 caracteres, só com `[a-z0-9-]`. Falha hoje (1149).
- Integração/E2E: N/A — o defeito está num arquivo estático; o upload no claude.ai é manual e fica como verificação no Relatório de Entrega.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [x] Red: UT-01 com a tag `SPEC-0043:UT-01`, falhando pela description com 1149 caracteres
- [x] Green: description reescrita, `BRAIN_VERSION` 2026.11.1 e CHANGELOG da skill
- [x] Refactor mantendo tudo verde
- [x] Validar: suíte completa + lint + arquitetura (G2/G3)
- [x] Review independente (G4)
- [x] Integração + CI verde (G5) e H2
- [x] Deploy (G6) — N/A: pilar entrega dispensado
- [x] Relatório de Entrega, CHANGELOG e upload manual no claude.ai (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3607a19 | 2026-11-02 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/sdd-management/tests && python3 -m unittest discover -s skills/second-brain/tests` exit 1 (red: FAILED (failures=1)) — 09281d9 | 2026-11-02 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 7a75b81 | 2026-11-02 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 14d0c16 | 2026-11-02 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED na revisão de fb6476b; achado minor (description vazia passava) corrigido em 7a75b81; 4 nits sem ação — cf208f5 | 2026-11-02 |
| G5 Integração & CI | PASS | MANUAL: CI do PR #21 verde em 39988cb: ci (3.9) e ci (3.15) com a suíte completa (run 41424652684), pr-check sdd (run 41424652699); a suíte local falhou só em testes de desempenho de 2 s fora do escopo (máquina com carga 5–7; test_fifty_commits levou 4,06 s isolado); thomas aceitou a evidência do CI | 2026-11-02 |
| H2 Integração aprovada | PASS | política auto-on-green (aprovada por thomas em 2026-10-26); G5 PASS | 2026-11-02 |
| G6 Deploy | N/A | pilar entrega dispensado (pillars.waived): skill distribuída por cópia da pasta, sem deploy | 2026-11-02 |
| G7 Pronto & Docs | PASS | Relatório de Entrega e Definição de Pronto: ok — 250c7b4 | 2026-11-02 |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue
A `description` do `skills/second-brain/SKILL.md` caiu de 1149 para 841 caracteres, mantendo todos os gatilhos e comandos, e o upload da skill no claude.ai passou: a skill já aparece no projeto Idiomas do usuário com a description nova. Um teste novo reprova `description` vazia ou com mais de 1024 caracteres e `name` fora de `[a-z0-9-]` ou com mais de 64, para o defeito não voltar. Versão da skill: 2026.11.1.

### Como foi feito
Teste primeiro (806e16d, falhando com "description com 1149 caracteres"), depois a description nova, `BRAIN_VERSION` 2026.11.1 e a seção no CHANGELOG da skill (fb6476b). A revisão G4 aprovou e apontou um achado minor (description vazia passava), corrigido com um teste a mais (7a75b81). Antes do G1, a spec passou a citar o teste da SPEC-0017 pelo nome do método, porque a ferramenta lia "SPEC-0017:UT-05" como teste desta spec; o plano de testes não mudou. O G5 usa a evidência do CI, por decisão do thomas: a suíte local falhou só em testes de desempenho de 2 s, fora do escopo, com a máquina carregada.

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->
- **Antes:** em 806e16d, `test_skill_md_frontmatter_fits_the_skill_upload_limits` falhou com `AssertionError: 1149 not less than or equal to 1024 : description com 1149 caracteres; o upload aceita no máximo 1024` (G1 em 09281d9).
- **Depois:** em fb6476b o teste passa (G2 em 7a75b81, suíte completa OK) e no CI do PR #21 (run 41424652684, Python 3.9 e 3.15).

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|
| UT-01 | description ≤ 1024 e não vazia; name ≤ 64 em `[a-z0-9-]` | PASS | `test_instructions.py::InstructionsTest.test_skill_md_frontmatter_fits_the_skill_upload_limits` — CI do PR #21 em 39988cb (run 41424652684, Python 3.9 e 3.15; pr-check no run 41424652699) e suíte local (G2) |

### Definição de Pronto
- [x] Teste de regressão falhou antes e passa depois da correção
- [x] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [x] Review independente sem achados blocker/major (G4)
- [x] Padrão existente mantido
- [x] Disponível no ambiente-alvo via pipeline (G6)
- [x] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [x] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy
Sem deploy próprio (pilar entrega dispensado). Passa a valer na `main` com o merge do PR #21; o zip já foi subido no claude.ai e funciona. Para as máquinas locais, copiar a skill de novo para `~/.claude/skills/`. Rollback: revert do merge.

### Pendências
Nenhuma. Observação: os testes de desempenho com limite de 2 s (`test_fifty_commits_in_under_two_seconds`, `test_context_with_two_hops_takes_under_2_seconds_on_5000_notes`) falham numa máquina carregada; vale avaliar uma margem ou um jeito de pular esses testes localmente.

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
