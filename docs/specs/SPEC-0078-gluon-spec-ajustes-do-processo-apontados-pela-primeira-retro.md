---
id: SPEC-0078
title: "gluon-spec: ajustes do processo apontados pela primeira retrospectiva"
tier: lite
type: fix
user_facing: false
status: proposed
created: 2026-11-17
parent: SPEC-0066
depends_on: []
consumes_contract: []
touches: []
adrs: []
external: []
size: S
approved_by:
approved_at:
---

# SPEC-0078 — gluon-spec: ajustes do processo apontados pela primeira retrospectiva

> **Radar (2026-11-17), da primeira retrospectiva real (SPEC-0074) em 25 projetos.** A detalhar antes do G0; pode virar mais de uma spec.
> - **O `gate` apaga as reprovações:** havia 1 FAIL na tabela atual e 183 no histórico do git. Preservar o histórico na própria spec, por exemplo com uma coluna ou uma linha de tentativas no Registro de Gates, para que o rigor apareça sem o git (e no modo privado).
> - **Entregue sem fechar (R3 em 14 de 25 projetos):** specs com G5 PASS e sem G7. Fazer `status`, `next` e o hook de início de sessão apontarem isso como próximo passo obrigatório.
> - **Ferramenta "desconhecida" (R1 em 25 de 25):** os projetos privados nunca registraram `sdd_version`. Separar "versão desconhecida" de "desatualizada" no `retro` e fazer o `private init` gravar a versão.
> - **Resíduos da revisão da SPEC-0074:**
>   - um `spec_root` do registro com tipo errado ainda dá traceback (validar `isinstance(..., str)`);
>   - o rótulo "sem git" aparece também para histórico ilegível ou repositório sem commits (trocar por "sem histórico");
>   - o ID de impedimento vindo da tabela não é normalizado (usar `IMP-?`);
>   - duas specs sem `id` com o mesmo número aparecem duplicadas.

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
{{Comportamento atual vs. esperado. Para bug: passos de reprodução, ambiente e impacto.}}

## 2. Causa Raiz
{{Causa identificada no código (arquivo/trecho e por que falha). Corrija a causa, não o sintoma. Para melhoria pequena: contexto técnico.}}

## 3. Mudança Proposta
{{O que muda e o que explicitamente NÃO muda.}}

**Padrão seguido:** {{arquivos de referência do padrão existente que a correção respeita}}

**Rollback:** {{revert do commit | outro procedimento}}

**Outras ocorrências:** {{o mesmo defeito existe em outro lugar? liste como novas specs | Nenhuma}}

## 4. Plano de Testes (TDD)
<!-- Mínimo: um teste de regressão que reproduz o problema e FALHA antes da correção, no nível em que o defeito aparece (IT para fronteiras de I/O, E2E para jornadas de usuário). Código sem cobertura: primeiro CH-xx fixando o comportamento atual. Tag no código: `SPEC-0078:<ID>`. Modo privado: sem tag no código; aponte o teste no fim da linha com `→ caminho::nome` (ex.: `→ tests/test_soma.py::test_soma`). Categoria sem teste: "N/A — motivo" SEM ID. -->
- {{CH-01 — comportamento atual preservado | Caracterização: N/A — área já coberta}}
- **UT-01** — {{teste de regressão: Dado..., quando..., então...}}
- {{IT-01 ou E2E-01 — regressão no nível do defeito | Integração/E2E: N/A — motivo}}

## 5. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento (seção Registro de Impedimentos). -->
{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}

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
