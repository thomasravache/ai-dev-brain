---
id: SPEC-0071
title: "boson-atlas: contrato do coletor com o nome boson-atlas, org-atlas aceito"
tier: full
type: migration
user_facing: false
status: in-progress
created: 2026-11-16
parent: SPEC-0067
depends_on: [SPEC-0070]
consumes_contract: []
contract_version: 1
# breaking: "o que quebra para consumidores e como migrar"   # só se houver quebra; vai para o PR e pede `!` no título
touches: [skills/boson-atlas/scripts/atlas.py, skills/boson-atlas/assets/collectors/**, skills/boson-atlas/tests/**, skills/boson-atlas/references/collector-contract.md, skills/boson-atlas/references/collectors/**, skills/boson-atlas/CHANGELOG.md, mcp/tests/fixtures/collector.py, .claude-plugin/plugin.json, tests/plugin/test_skill_names.py, skills/boson-atlas/references/modes.md]
adrs: [ADR-0011, ADR-0020]
external: []
size: S
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0071 — boson-atlas: contrato do coletor com o nome boson-atlas, org-atlas aceito

## 1. Visão Geral
O contrato dos coletores passa a se chamar `boson-atlas/collector@1`. O formato não muda, por isso a versão continua `@1`. O validador aceita os dois nomes, os coletores de referência (generic, GitHub, Argo CD) passam a emitir o nome novo, e snapshots já gravados com `org-atlas/collector@1` continuam válidos no `build` e no `lint`.

## 2. Motivação & Escopo
**Motivação:** o identificador do contrato publicado é o último nome técnico antigo da `boson-atlas` que aparece para quem escreve coletores (épico SPEC-0067, ADR-0020).

**Objetivos (dentro do escopo):**
- `CONTRACT = "boson-atlas/collector@1"`; `SUPPORTED_CONTRACTS` aceita também `org-atlas/collector@1` até a SPEC-0073.
- Coletores de referência em `assets/collectors/` emitem o nome novo; mensagens do `scan` citam o nome novo.
- `build`, `lint` e `context` aceitam snapshots com qualquer dos dois nomes.
- `references/collector-contract.md` e as páginas dos coletores com o nome novo e a nota de compatibilidade (até quando o antigo é aceito).
- Fixture de coletor do MCP (`mcp/tests/fixtures/collector.py`) emitindo o nome novo.

**Não-objetivos (fora do escopo):**
- Qualquer mudança de campo ou de regra do contrato (seria `@2`, ADR-0011).
- Regravar snapshots existentes com o nome novo (são reescritos naturalmente no próximo `scan`).
- Remover o nome antigo (SPEC-0073).

## 3. Dependências
- **Implementações necessárias:** SPEC-0070 — as duas mexem em `atlas.py` e nos testes da `boson-atlas`; em sequência, sem conflito.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:** brownfield; `CONTRACT` e `SUPPORTED_CONTRACTS` em `skills/boson-atlas/scripts/atlas.py` já foram desenhados para aceitar mais de um valor (comentário do ADR-0011); `validate_output` rejeita `contract` fora da lista.

**Decisão:** mudar o namespace sem mudar a versão: `boson-atlas/collector@1` e `org-atlas/collector@1` são o mesmo contrato com dois nomes; os coletores de referência emitem o novo.

**Justificativa:** o ADR-0011 sobe a versão quando o formato quebra; aqui o formato é idêntico, e um `@2` faria terceiros acharem que precisam mudar algo além do nome.

**Desvio do padrão existente:** muda o identificador publicado do ADR-0011 — coberto pelo ADR-0020 e pelo `type: migration` do épico; o ADR-0011 ganha a nota do apelido.

**Alternativas descartadas:** `boson-atlas/collector@2` (sugere quebra de formato que não existe; foi o rascunho do épico, revisto aqui); manter só o nome antigo (deixa o nome velho no contrato público para sempre).

**ADRs:** ADR-0011, ADR-0020.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A.
- **Segurança:** a validação continua rejeitando qualquer outro valor de `contract` e mascarando segredos como hoje (UT-02).
- **Privacidade e dados pessoais:** N/A.
- **Disponibilidade e resiliência:** coletores de terceiros com o nome antigo continuam funcionando (UT-01, IT-01).
- **Acessibilidade (UI):** N/A.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** campo `contract` da saída dos coletores (`references/collector-contract.md`) e validação do `scan`

```text
contract aceito: "boson-atlas/collector@1" | "org-atlas/collector@1" (até a SPEC-0073); mesmo formato, mesmas regras.
outro valor → violação "contract não suportado: <valor>"; saída não gravada (sem mudança).
mensagem de falha do scan: "saída fora do contrato boson-atlas/collector@1 (N violação(ões))".
coletores de referência (generic, github, argocd) → emitem "boson-atlas/collector@1".
snapshots gravados com qualquer dos dois nomes → aceitos por build, lint e context.
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Coletor com nome novo | saída com `boson-atlas/collector@1` | aceita e gravada | UT-01 |
| Coletor de terceiro antigo | saída com `org-atlas/collector@1` | aceita e gravada como hoje | UT-01, IT-01 |
| Contrato desconhecido | `contract` com outro valor (ex.: `boson-atlas/collector@2`) | violação "contract não suportado", saída descartada | UT-02 |
| Coletores de referência | generic, github, argocd | emitem o nome novo | UT-03 |
| Snapshots antigos | atlas com snapshots `org-atlas/collector@1` | `build`, `lint` e `context` funcionam sem ação | IT-01 |
| Mensagens e docs | falha de contrato no `scan` | mensagem cita `boson-atlas/collector@1` | UT-04 |
| CI que não cita nenhuma pasta (Emenda v2) | arquivo de CI mantido sem `.boson-atlas/skill` nem `.org-atlas/skill`, com `.org-atlas/` no atlas | não conta como migrado: `vendor` atualiza as duas cópias e mostra o passo de migração; `doctor` não manda apagar | UT-05 |
| Dois tipos de CI (Emenda v2) | workflow do GitHub roda `.boson-atlas/skill`, `ci/atlas-scan.sh` personalizado roda `.org-atlas/skill`, `vendor --ci generic` | as duas cópias ficam atualizadas | UT-06 |
| Descrição dos coletores (Emenda v2) | `--help` de generic, github e argocd | diz `boson-atlas` | UT-03 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- **CH-01** — Dados os fixtures de contrato válidos e inválidos atuais (guarda: passa antes da mudança), quando validados depois da mudança, então as violações são as mesmas, exceto o texto do nome do contrato nas mensagens.

### 7.2 Testes Unitários
- **UT-01** — Dadas duas saídas iguais, uma com cada nome de contrato, quando validadas, então as duas são aceitas sem violação.
- **UT-02** — Dada uma saída com `contract` `boson-atlas/collector@2` ou `outro/collector@1`, quando validada, então há a violação "contract não suportado" e nada é gravado.
- **UT-03** — Quando os coletores de referência (generic, github, argocd) rodam com os fixtures atuais, então emitem `boson-atlas/collector@1`, e o `--help` de cada um diz `boson-atlas` e não `org-atlas`; o `KeptIdentifiersTest` (SPEC-0055:UT-04) passa a exigir `CONTRACT == "boson-atlas/collector@1"`.
- **UT-04** — Dada uma saída fora do contrato, quando o `scan` roda, então a mensagem cita `boson-atlas/collector@1`.
- **UT-05** — (Emenda v2) Dado um atlas com `.org-atlas/skill` velha e `ci/atlas-scan.sh` mantido que roda a ferramenta por um script intermediário, sem citar nenhuma das duas pastas, quando `vendor --ci generic` e `doctor` rodam, então `.org-atlas/skill` e `.boson-atlas/skill` ficam atualizadas, "pode apagar" não aparece e o `doctor` mostra o passo de migração em vez de "apague com".
- **UT-06** — (Emenda v2) Dado um atlas com o workflow do GitHub rodando `.boson-atlas/skill` desatualizada e `ci/atlas-scan.sh` personalizado rodando `.org-atlas/skill`, quando `vendor --ci generic` roda, então as duas cópias ficam iguais ao `atlas.py` instalado.

### 7.3 Testes de Integração
- **IT-01** — Dado um atlas temporário com snapshots gravados pela versão anterior (`org-atlas/collector@1`) e um coletor de terceiro que ainda emite o nome antigo, quando `scan`, `build`, `lint` e `context` rodam pela CLI, então tudo funciona e o grafo é o mesmo de antes.

### 7.4 Testes de Contrato
- **CT-01** — Dados os fixtures de contrato da skill e o fixture de coletor do MCP, quando validados com `validate_output`, então os válidos com qualquer dos dois nomes passam e os inválidos falham pelas mesmas violações.

### 7.5 Testes E2E
- N/A — nenhuma jornada de usuário muda; quem escreve coletor só ganha um nome aceito a mais.

### 7.6 Outros
- N/A

**Dublês e dados de teste:** fixtures de `skills/boson-atlas/tests/fixtures/contract/`; atlas temporários; nunca rede.

**Ambiente de execução:** local e CI (suítes da `boson-atlas` e do `mcp`).

## 8. Plano de Rollout
- **Estratégia:** deploy direto pelo plugin e pela cópia da skill (e pelo `vendor` nos atlas).
- **Dados/schema:** snapshots não são reescritos; o próximo `scan` grava o nome novo.
- **Compatibilidade:** coletores de terceiros com o nome antigo aceitos até a SPEC-0073; máquina com versão antiga lendo snapshot com o nome novo rejeitaria a saída de um coletor novo — por isso o CHANGELOG pede atualizar a skill em todas as máquinas e o `vendor` do atlas antes de trocar coletores próprios.
- **Observabilidade:** mensagens do `scan`.
- **Rollback:** reverter a versão e rodar o próximo `scan` com os coletores antigos.
- **Etapas de migração/coexistência:** dois nomes aceitos agora; remoção do antigo na SPEC-0073.

## 9. Questões em Aberto
- [x] O contrato novo vira `@2` (como dizia o rascunho do épico) ou mantém `@1` com o nome novo? — `boson-atlas/collector@1`: o formato não muda, e o ADR-0011 só sobe a versão quando ele quebra (thomas, 2026-11-16: piloto automático com o recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
**Fase 1: Contrato**
- [ ] Red: CH-01, UT-01 a UT-04, IT-01, CT-01 com a tag `SPEC-0071:<ID>`
- [ ] Green: `CONTRACT`/`SUPPORTED_CONTRACTS`, coletores de referência, mensagens e references

**Fase 2: Vendor (Emenda v2)**
- [ ] Red: UT-05, UT-06
- [ ] Green: estado "desconhecido" da CI e atualização das duas cópias
- [ ] Validar: suítes da boson-atlas, tests/plugin e mcp, arquitetura (G2/G3)

**Fase final: Integração, entrega e documentação**
- [ ] Review independente (G4)
- [ ] Integração + CI verde (G5) e aprovação (H2)
- [ ] Deploy via pipeline (G6) — N/A: skill distribuída pelo plugin e por cópia
- [ ] Relatório de Entrega, references, CHANGELOG, versão do plugin (G7)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 3ec7d76 (árvore suja) | 2026-11-16 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=31, skipped=1)) — 9e2d9da | 2026-11-17 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 63c14b6 | 2026-11-17 |
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0071`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| v1 (sem mudança de contrato) | 2026-11-17 | Emenda v2: entram os dois minors do G4 da SPEC-0070 (CI mantida que não cita nenhuma das duas pastas não conta como migrada; com dois tipos de CI, o `vendor` atualiza as duas cópias), a descrição `--help` dos coletores com o nome novo e a guarda de nomes da SPEC-0055 exigindo o contrato novo; `touches` ganha `tests/plugin/test_skill_names.py` e `skills/boson-atlas/references/modes.md`; testes UT-05 e UT-06 | achados da revisão da SPEC-0070 no mesmo `atlas.py`, sem abrir spec nova | nenhuma | thomas, 2026-11-17 (piloto automático com o recomendado) |
