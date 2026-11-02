---
id: SPEC-0043
title: "second-brain: description do SKILL.md dentro do limite de 1024 caracteres"
tier: lite
type: fix
user_facing: false
status: approved
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
A `description` foi crescendo a cada spec (SPEC-0018 search/related/links, SPEC-0019 ingest, processadores, inbox, lint…) sem nenhum limite. O formato de skills limita `description` a 1024 caracteres e `name` a 64 (minúsculas, dígitos e hífen), mas o teste `test_instructions.py` (SPEC-0017:UT-05) só confere que o campo existe. Nada impede a regressão.

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
- Caracterização: N/A — o teste SPEC-0017:UT-05 já cobre o restante do `SKILL.md` e continua valendo.
- **UT-01** — Dado o `skills/second-brain/SKILL.md`, quando o teste lê o frontmatter, então a `description` (linhas do escalar dobrado juntadas com espaço) tem no máximo 1024 caracteres e o `name` tem no máximo 64 caracteres, só com `[a-z0-9-]`. Falha hoje (1149).
- Integração/E2E: N/A — o defeito está num arquivo estático; o upload no claude.ai é manual e fica como verificação no Relatório de Entrega.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01 com a tag `SPEC-0043:UT-01`, falhando pela description com 1149 caracteres
- [ ] Green: description reescrita, `BRAIN_VERSION` 2026.11.1 e CHANGELOG da skill
- [ ] Refactor mantendo tudo verde
- [ ] Validar: suíte completa + lint + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Deploy (G6) — N/A: pilar entrega dispensado
- [ ] Relatório de Entrega, CHANGELOG e upload manual no claude.ai (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3607a19 | 2026-11-02 |
| G1 Red | PENDING | | |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 9. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-NNNN nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 10. Relatório de Entrega
<!-- Preenchido no CLOSE (G7). Para status implemented o validate exige tudo preenchido, todo teste do plano com PASS + evidência e a Definição de Pronto marcada. -->

### O que foi entregue

### Como foi feito

### Prova de Correção
<!-- type fix: teste de regressão falhou antes (commit red + saída) e passa depois (commit green + execução). Outros tipos: "N/A". -->

### Verificação
| Teste | Comportamento | Resultado | Evidência |
|---|---|---|---|

### Definição de Pronto
- [ ] Teste de regressão falhou antes e passa depois da correção
- [ ] Suíte completa, arquitetura e CI verdes (G2, G3, G5)
- [ ] Review independente sem achados blocker/major (G4)
- [ ] Padrão existente mantido
- [ ] Disponível no ambiente-alvo via pipeline (G6)
- [ ] Documentação/CHANGELOG atualizados quando aplicável (G7)
- [ ] Outras ocorrências registradas como novas specs (ou nenhuma)

### Deploy

### Pendências

## 11. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
