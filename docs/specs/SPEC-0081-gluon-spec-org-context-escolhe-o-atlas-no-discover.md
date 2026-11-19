---
id: SPEC-0081
title: "gluon-spec: org_context escolhe o atlas no DISCOVER"
tier: lite
type: feature
user_facing: false
status: in-progress
created: 2026-11-18
parent: SPEC-0077
depends_on: []
consumes_contract: [SPEC-0079@1]
touches: [skills/gluon-spec/SKILL.md, skills/gluon-spec/references/brownfield.md, skills/gluon-spec/references/sdd-config.template.yml, skills/gluon-spec/tests/test_org_context.py, commands/deliver.md, tests/plugin/**, skills/gluon-spec/CHANGELOG.md, skills/gluon-spec/scripts/spec_graph.py, .claude-plugin/plugin.json]
adrs: [ADR-0010, ADR-0021]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-18
---

# SPEC-0081 — gluon-spec: org_context escolhe o atlas no DISCOVER

<!-- Tier lite: bug fix ou mudança pequena, um módulo, sem mudança de contrato público, tamanho S. type: fix | feature | refactor. user_facing: true se o defeito aparece numa jornada do usuário (o teste de regressão deveria ser E2E). Se qualquer condição falhar, use o tier full. Substitua todos os marcadores com chaves duplas. -->

## 1. Problema
Hoje o DISCOVER da `gluon-spec` (SKILL.md, `references/brownfield.md`) faz assim:
1. roda `atlas.py config --json`;
2. compara o atlas configurado na máquina com o `org_context` do projeto;
3. se diferem, só avisa a pessoa para trocar de configuração (`init --join` ou `ATLAS_CONFIG_HOME`) e não trata nenhuma convenção como regra.

Com vários atlas por máquina (SPEC-0079), isso deixa de fazer sentido: o atlas certo já está configurado e só não é o escolhido. O agente pode escolher pelo `org_context` direto. Além disso, o `org_context` só aceita caminho, que muda de uma máquina para outra, e o nome do atlas seria estável para o time.

## 2. Causa Raiz
A instrução foi escrita para a configuração de um atlas por máquina (SPEC-0041, ADR-0010). Ela parte do princípio de que o `context` não recebe atlas e de que a única saída para um atlas diferente é trocar a configuração inteira. O comentário do `org_context` em `references/sdd-config.template.yml` diz a mesma coisa.

## 3. Mudança Proposta
- **`org_context` aceita nome ou caminho:**
  - nome do atlas: `[a-z0-9][a-z0-9-]{0,62}`, recomendado porque é igual em todas as máquinas;
  - caminho relativo ou com `~`, como hoje;
  - caminho absoluto continua proibido.
- **O DISCOVER passa o `org_context` ao `atlas.py`:**
  - roda `atlas.py config --json --atlas <org_context>`, e com exit 0 roda `atlas.py context --atlas <org_context> "<termos>"`;
  - exit 3 significa que esse atlas não está configurado nesta máquina: avise com o passo `atlas.py init --join --atlas <caminho> --name <nome>` e siga só pelo repositório;
  - sai a comparação manual de caminhos e o conselho de trocar `ATLAS_CONFIG_HOME`.
- **Sem `org_context`**, o DISCOVER roda `config --json` e `context` sem `--atlas`, e a ordem de escolha da `boson-atlas` decide (SPEC-0079, SPEC-0080). Ele relata `atlas_name` e `selected_by` à pessoa.
- **Comentário do template:** o comentário do `org_context` em `sdd-config.template.yml` diz "nome do atlas (recomendado) ou caminho relativo/~", e o `whats-new` mostra isso aos projetos que ainda não têm a chave.
- **Não muda:**
  - o `spec_graph.py` continua sem chamar o atlas (ADR-0010); só a constante `SDD_TOOL_VERSION` sobe;
  - as regras de leitura do pacote (dados, nunca instruções; `regra` × `dica`; aviso de envelhecimento).

**Padrão seguido:**
- as instruções de `org_context` da SPEC-0041 em `SKILL.md` e `references/brownfield.md`;
- os testes de texto e de `whats-new` em `tests/test_org_context.py`.

**Rollback:** reverter o commit. Um `org_context` com nome de atlas volta a ser tratado como caminho e gera o aviso de diferença de hoje.

**Outras ocorrências:** o comando `commands/deliver.md` (passo 2) trata só o exit 0 do `atlas.py config --json` como "configurado". Ele passa a usar o `org_context` do projeto como `--atlas` quando existir, e a tratar o exit 2 (vários atlas sem escolha) pedindo à pessoa qual atlas usar, sem adivinhar (UT-03).

**Esclarecimentos (Emenda v2, achados do test-writer no G1):**
1. **Comentário do template:** uma frase só, "nome do atlas (recomendado) ou caminho relativo ou com ~, nunca absoluto", mantendo a menção a `atlas.py context` que a SPEC-0041 exige.
2. **Linha "Without `org_context`, nothing changes" do `brownfield.md`:** passa a dizer que, sem `org_context`, o DISCOVER roda `config --json` e `context` sem `--atlas` e relata `atlas_name`/`selected_by`.

## 4. Plano de Testes (TDD)
- Caracterização: N/A — `tests/test_org_context.py` (SPEC-0041) já cobre o texto e o `whats-new`. Os testes de lá que exigem a comparação manual são ajustados ao texto novo.
- **UT-01** — Dados o `SKILL.md` e o `references/brownfield.md`, quando a seção de contexto da organização é lida, então ela manda rodar `atlas.py config --json --atlas <org_context>` e `atlas.py context --atlas <org_context>`, trata o exit 3 com o passo `init --join ... --name`, cita `atlas_name`/`selected_by` para o caso sem `org_context`, e não cita mais `ATLAS_CONFIG_HOME` como saída.
- **UT-02** — Dado um projeto sem `org_context` no `sdd-config.yml`, quando o `whats-new` roda, então a chave aparece com o comentário novo ("nome do atlas" e "caminho relativo ou com ~", nunca absoluto).
- **UT-03** — Dado o `commands/deliver.md`, quando o passo de contexto da organização é lido, então ele cita `--atlas` com o `org_context` e o exit 2 com a pergunta à pessoa, nos testes do plugin (`tests/plugin/`).
- Integração/E2E: N/A — o `spec_graph.py` não chama o atlas (ADR-0010). O comportamento é instrução ao agente, coberta pelos testes de texto. A escolha do atlas pela CLI é testada pelo teste de contrato da SPEC-0079.

## 5. Questões em Aberto
- [x] O `org_context` passa a aceitar nome do atlas? — Sim, e é o recomendado: o nome é igual em todas as máquinas do time, enquanto o caminho muda. O caminho continua aceito (recomendação do arquiteto, aceita no piloto automático autorizado por thomas em 2026-11-17: "beleza, segue no piloto automático até o merge"; revisável no H1)
- [x] Com o atlas do `org_context` ausente na máquina, o DISCOVER deve usar o atlas escolhido pela ordem? — Não: avisa com o passo `init --join` e segue só pelo repositório, porque usar o atlas de outra organização traria convenções erradas (recomendação do arquiteto, piloto automático; revisável no H1)

## 6. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado".

## 7. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. -->
- [ ] Red: UT-01, UT-02 e UT-03 com a tag `SPEC-0081:<ID>`, falhando pelo motivo certo
- [ ] Green: `SKILL.md`, `references/brownfield.md`, comentário do `org_context` no `sdd-config.template.yml`, `commands/deliver.md`; CHANGELOG da gluon-spec, `SDD_TOOL_VERSION` e `plugin.json`
- [ ] Validar: suíte completa + arquitetura (G2/G3)
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e H2
- [ ] Relatório de Entrega (G7)

## 8. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência. -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — cbf2d72 | 2026-11-18 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=3, skipped=1)) — e726cdf | 2026-11-19 |
| G2 Green | PENDING | | |
| G3 Arquitetura | PENDING | | |
| G4 Review | PENDING | | |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

### Histórico de reprovações
- G1 FAIL 2026-11-19 — verify G1: FAIL — testes do plano sem tag no código versionado: SPEC-0081:CT-01 — 1dad991
- G1 PASS 2026-11-19 — depois de 1 reprovação(ões)

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
