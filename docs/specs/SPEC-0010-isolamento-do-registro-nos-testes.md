---
id: SPEC-0010
title: Testes antigos isolados do registro do usuário
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-10-14
parent:
depends_on: []
consumes_contract: []
touches: [skills/sdd-management/tests/**]
adrs: []
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0010 — Testes antigos isolados do registro do usuário

## 1. Problema
Desde a SPEC-0003, todo `Project` consulta o registro do usuário (`projects.json`) para saber se o repositório está em modo privado. Os testes de `tests/test_spec_graph.py` não isolam esse registro: tanto `sg.Project(...)` quanto a CLI chamada pelo helper `Project.run` leem o `~/.config/sdd/projects.json` real de quem roda a suíte. Um registro inválido na máquina faz a suíte antiga falhar com "registro inválido" em testes que nada têm a ver com o modo privado; um registro válido não muda nada hoje, mas deixa o resultado dos testes dependente da máquina. Achado na revisão (G4) da SPEC-0009.

## 2. Causa Raiz
`test_spec_graph.py` foi escrito antes do registro existir e usa o ambiente do processo como está. `tests/test_private_mode.py` já isola (`PrivateEnv` aponta `HOME`, `SDD_CONFIG_HOME` e `XDG_*` para um diretório temporário), mas o padrão não foi levado para a suíte antiga.

## 3. Mudança Proposta
`test_spec_graph.py` ganha um `setUpModule`/`tearDownModule` que aponta `SDD_CONFIG_HOME` para um diretório temporário vazio durante o módulo inteiro (o processo dos testes e os subprocessos da CLI herdam o valor), e restaura o ambiente no fim. Não muda: código da ferramenta, `test_private_mode.py` (já isolado), `test_architecture.py` (não usa o registro).

**Padrão seguido:** isolamento de `PrivateEnv` em `tests/test_private_mode.py`.

**Rollback:** revert do commit.

**Outras ocorrências:** Nenhuma — `test_architecture.py` só lê arquivos-fonte.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — a suíte antiga continua passando sem alteração de asserções.
- **UT-01** — Dado `XDG_CONFIG_HOME` e `HOME` apontando para um diretório cujo `sdd/projects.json` é JSON inválido (simulando o registro quebrado de quem roda a suíte), quando um teste da suíte antiga cria um projeto temporário e roda `validate` pela CLI e `sg.Project(...)` no processo, então os dois funcionam em modo completo.
- Integração/E2E: N/A — UT-01 já roda a CLI num repositório temporário.

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
Nenhuma

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
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
