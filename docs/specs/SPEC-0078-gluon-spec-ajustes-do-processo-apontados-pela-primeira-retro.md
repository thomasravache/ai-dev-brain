---
id: SPEC-0078
title: "gluon-spec: ajustes do processo apontados pela primeira retrospectiva"
tier: full
type: feature
user_facing: false
status: in-progress
created: 2026-11-17
parent: SPEC-0066
depends_on: [SPEC-0074]
consumes_contract: []
contract_version: 3
touches: [skills/gluon-spec/scripts/spec_graph.py, skills/gluon-spec/tests/**, skills/gluon-spec/references/gates.md, skills/gluon-spec/references/retro.md, skills/gluon-spec/references/private-mode.md, skills/gluon-spec/SKILL.md, skills/gluon-spec/CHANGELOG.md, README.md, .claude-plugin/plugin.json]
adrs: [ADR-0001, ADR-0002, ADR-0006, ADR-0019]
external: []
size: M
approved_by: thomas
approved_at: 2026-11-17
---

# SPEC-0078 — gluon-spec: ajustes do processo apontados pela primeira retrospectiva

## 1. Visão Geral
A primeira retrospectiva real (SPEC-0074), sobre 25 projetos, mostrou três falhas do processo que a própria ferramenta causa ou esconde:
- o `gate` apaga as reprovações;
- specs entregues ficam sem fechar;
- os projetos em modo privado nunca registram a versão da ferramenta.

Esta spec corrige as três e fecha os resíduos da revisão da SPEC-0074. Assim, a próxima retrospectiva mede o processo, e não o defeito da ferramenta.

## 2. Motivação & Escopo
**Motivação:** os números da primeira retrospectiva, em 2026-11-17:
- **1 FAIL na tabela atual contra 183 no histórico do git.**
  - O `set_gate_row` sobrescreve a linha, então o PASS apaga o FAIL.
  - Sem o histórico, a regra "3 FAILs seguidos no mesmo gate → `impede --type falha`" (`references/gates.md`) não pode ser conferida por ninguém, nem pela ferramenta.
  - No modo privado, o histórico só existe no git do `spec_root`.
- **Specs entregues sem fechar (R3) em 14 de 25 projetos:** G5 PASS e G7 pendente. O `status` mostra o G7 como próximo passo, mas no meio das outras specs, sem idade nem destaque, e a spec fica esquecida depois do merge.
- **Versão da ferramenta "desconhecida" em 18 de 25 projetos (R1):** o `private init` copia o template com `sdd_version: ""`, e ninguém roda `whats-new --ack`. A R1 trata desconhecida e atrasada do mesmo jeito e domina o relatório.
- **Resíduos da revisão da SPEC-0074:**
  - um `spec_root` do registro com tipo errado ainda dá traceback;
  - "sem git" aparece também quando o histórico está ilegível ou o repositório não tem commits;
  - o ID do impedimento sai sem normalização;
  - duas specs sem `id` com o mesmo número saem duplicadas.

**Objetivos (dentro do escopo):**
- **Histórico de reprovações na própria spec.**
  - Todo FAIL registrado pelo `gate` (`--fail` ou `--run` que reprova) acrescenta uma linha na subseção `### Histórico de reprovações`, dentro do Registro de Gates. A subseção é criada quando precisa.
  - Quando um PASS substitui um FAIL, entra uma linha de PASS dizendo depois de quantas reprovações.
  - A partir da terceira reprovação seguida no mesmo gate, o `gate` avisa e o `status` mostra a parada sugerida (`impede --type falha`).
- **Entregue sem fechar em destaque.** O `status` e o `next` mostram as specs com G5 PASS e G7 não PASS, com a idade desde o G5, numa linha própria de aviso no topo.
- **Versão registrada no modo privado:** o `private init` grava `sdd_version` com a versão da skill no `sdd-config.yml` que ele cria.
- **Retrospectiva:**
  - separa a versão `desconhecida` da `atrasada` (`tool.state`, com a ação certa para cada uma);
  - conta as reprovações registradas na spec (`fail_recorded`), além das do git;
  - fecha os quatro resíduos da revisão.

**Não-objetivos (fora do escopo):**
- Reescrever specs antigas para criar o histórico a partir do git. O histórico começa a contar a partir desta versão; o passado continua visível pelo `retro` (git).
- Mudar o formato da tabela do Registro de Gates. A subseção nova fica abaixo dela, e as ferramentas vendorizadas antigas a ignoram.
- Abrir impedimento sozinho na terceira reprovação. O `gate` e o `status` só sugerem; quem registra é o Architect.
- Fechar specs ou mudar status automaticamente.

## 3. Dependências
- **Implementações necessárias:** SPEC-0074 — o `retro` precisa existir para ganhar `tool.state` e `fail_recorded`.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** N/A

## 4. Decisão Arquitetural
**Contexto:**
- O `gate` grava pela `set_gate_row`, e o `status` monta o próximo passo em `status_body`/`spec_phase` (os avisos de worktree esquecida e de pilares já saem no topo, como `⚠`).
- O `private init` cria o `sdd-config.yml` a partir do template, e o `whats-new --ack` grava `sdd_version` com `write_config_key`.
- O `retro` (SPEC-0074) está em `spec_graph.py`.

**Decisão:**
- **Histórico:** lista Markdown numa subseção abaixo da tabela, escrita só pela ferramenta. A linha de FAIL tem o formato `- G2 FAIL 2026-11-17 — <evidência> — <sha>`; a de PASS depois de reprovações, `- G2 PASS 2026-11-18 — depois de 2 reprovação(ões)`. A contagem de reprovações seguidas olha o histórico do gate a partir da última linha PASS dele.
- **Avisos:** no padrão `⚠` do `status`, reaproveitando `gate_table` (com a data, desde a SPEC-0074).
- **`private init`:** grava a versão com `write_config_key`.
- **`retro`:**
  - lê a subseção pelo mesmo parser;
  - `tool.state` com os valores `atual | atrasada | desconhecida`;
  - R1 com a ação `vendor --force`/`whats-new` para atrasada e `whats-new --ack` para desconhecida.

**Justificativa:**
- Guardar o histórico na spec faz o rigor aparecer sem depender do git, inclusive no modo privado e numa cópia do projeto.
- Uma subseção nova, e não uma coluna, não quebra a leitura da tabela pelas versões antigas da ferramenta que estão nos projetos.

**Desvio do padrão existente:** Nenhum

**Alternativas descartadas:**
- **Coluna nova na tabela:** quebraria as ferramentas vendorizadas antigas e exigiria `upgrade` em todos os projetos.
- **Uma linha por tentativa na tabela:** quebraria a regra de uma linha por gate, de que `gate_table`, `validate` e `pr-check` dependem.
- **Histórico só no git:** é o que existe hoje e não aparece para quem lê a spec.
- **Abrir o impedimento automaticamente:** tiraria do Architect a decisão de diagnosticar.

**ADRs:** ADR-0001 (script único, stdlib), ADR-0002 (CLI coberta por integração), ADR-0006 (modo privado), ADR-0019 (só sugere, não aplica)

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** `status` e `retro` sem regressão perceptível. O `retro` nos 25 projetos desta máquina segue abaixo de 15 s, medido na revisão (G4).
- **Segurança:** a evidência do histórico é a mesma que já vai para a tabela, sem conteúdo novo. O `retro` continua só lendo (IT-01 da SPEC-0074 segue valendo).
- **Privacidade e dados pessoais:** o `retro` conta as linhas do histórico e nunca imprime a evidência delas (UT-05).
- **Disponibilidade e resiliência:** uma subseção malformada ou editada à mão não derruba `status`, `gate` nem `retro`. Linha que não segue o formato não conta.
- **Acessibilidade (UI):** N/A — saída de terminal
- **Custo:** N/A — local

## 6. Artefato A — Contrato
**Interface:** `spec_graph.py gate`, `status`, `next`, `private init` e `retro` (saída e JSON)

```text
Histórico de reprovações (dentro de "Registro de Gates", abaixo da tabela)
  ### Histórico de reprovações
  - <G> FAIL <AAAA-MM-DD> — <evidência> — <sha|?>
  - <G> PASS <AAAA-MM-DD> — depois de <n> reprovação(ões)
  Escrita só pelo `gate`; criada na primeira reprovação; nunca reescreve linhas antigas.

gate SPEC-X <G> --fail "motivo" | --run (que reprova)
  grava a linha FAIL na tabela (como hoje) e acrescenta a linha FAIL no histórico.
  com >= 3 reprovações seguidas desse gate: imprime
  "⚠ <n> reprovações seguidas em <G> — registre `impede SPEC-X --type falha` e escale ao humano"
gate SPEC-X <G> (PASS ou N/A) depois de reprovações desse gate
  acrescenta a linha PASS "depois de <n> reprovação(ões)"; sem reprovações antes, nada.

status [ID ...]
  no topo, uma linha por spec com G5 PASS e G7 não PASS:
  "⚠ entregue sem fechar: SPEC-X — G5 há <d> dia(s); feche o G7 (Relatório de Entrega)"
  e, por spec em andamento com >= 3 reprovações seguidas num gate sem impedimento `falha` aberto:
  "⚠ SPEC-X: <n> reprovações seguidas em <G> — `impede SPEC-X --type falha`"
next
  seção "A fechar" com as mesmas specs entregues sem G7 (ID e dias desde o G5).

private init
  ao criar o sdd-config.yml, grava sdd_version = <versão da skill>; config existente não muda.

retro (contrato da SPEC-0074, retro_version continua 1, só acréscimos)
  projects[].tool.state         atual | atrasada | desconhecida
  projects[].fail_recorded      linhas FAIL no histórico das specs (inteiro)
  R1  dispara para atrasada e desconhecida; ação:
        atrasada     → `whats-new` e `vendor --force` (privado: `whats-new --ack` depois de atualizar)
        desconhecida → `whats-new --ack` (registra a versão)
  R5  dispara só com fail_history == 0, fail_recorded == 0, nenhum FAIL atual e >= 20 PASS
      de G1–G5; fail_history null nunca dispara (Emenda v2)
  rótulo Markdown de fail_history null: "sem histórico" (motivo: sem git, sem commits ou ilegível)
  impedimentos: ID mantido quando segue IMP-<dígitos>; senão IMP-? (Emenda v2)
  IDs repetidos de specs sem id (mesmo prefixo SPEC-NNNN) aparecem uma vez nas listas
  registro com spec_root que não é texto: entrada ignorada, em "Ignorados" com
  "registro inválido", sem traceback

Esclarecimentos (Emenda v2)
  - a linha FAIL do histórico usa a evidência gravada na tabela; ela já termina em " — <sha>"
    no --run, e o --fail acrescenta " — <sha|?>"
  - N/A depois de reprovações grava a mesma linha PASS "depois de <n> reprovação(ões)"
  - "entregue sem fechar": specs não épicas em approved ou in-progress
  - os avisos do topo do status saem no `status` sem IDs (visão geral), como os de worktree
    e pilares; o aviso do `gate` sai sempre na 3ª reprovação seguida, com ou sem impedimento
  - testes da SPEC-0074 que fixavam as chaves exatas de `tool` e de `projects[]` e o rótulo
    "sem git" passam a aceitar as chaves novas e "sem histórico" (o JSON só ganha chaves)

Ajustes da revisão (Emenda v3)
  - aviso de reprovações seguidas só quando o gate na tabela não está PASS nem N/A
    (PASS gravado por versão antiga ou à mão não deixa aviso preso)
  - evidência com \r ou \r\n vira espaço (tabela e histórico continuam uma linha só)
  - título da subseção reconhecido sem diferenciar maiúsculas e acentos (sem subseção duplicada)
  - sugestões de R1, R3 e R5 em "O que ajustar na skill" reescritas para a causa que sobra
    depois desta versão (texto, sem mudar regras nem limites)

Erros
  linha do histórico fora do formato: ignorada na contagem, sem erro
```

**Design:** N/A — sem interface

**Arquivos/módulos afetados:** ver `touches`.
- `spec_graph.py`: `set_gate_row`/`cmd_gate`, `status_body`, `print_next`, `cmd_private` (init) e o `retro`.
- Documentação: `references/gates.md` (histórico e regra dos 3 FAILs conferível), `references/retro.md`, `references/private-mode.md` (versão gravada no init), `SKILL.md`, CHANGELOG.
- Versões da skill e do plugin.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| Reprovação registrada | `gate --fail` e `gate --run` que reprova | linha FAIL na tabela (como hoje) e linha FAIL no histórico, criando a subseção | UT-01, IT-01 |
| PASS depois de reprovações | PASS em gate com reprovações | tabela com PASS; histórico mantém os FAILs e ganha a linha PASS com a contagem | UT-01, IT-01 |
| PASS sem reprovação antes | primeira tentativa passa | nenhuma subseção criada | CH-01 |
| Três reprovações seguidas | 3º FAIL do mesmo gate desde o último PASS | aviso no `gate` e no `status` sugerindo `impede --type falha`; some com impedimento `falha` aberto | UT-02, IT-01 |
| Histórico editado à mão | linhas fora do formato | ignoradas na contagem, sem erro | UT-02 |
| Entregue sem fechar | spec com G5 PASS há 9 dias e G7 pendente | aviso no topo do `status` com os dias e seção "A fechar" no `next` | UT-03, IT-02 |
| Versão no modo privado | `private init` sem `sdd-config.yml` | `sdd_version` = versão da skill; config existente não muda | UT-04 |
| Versão desconhecida × atrasada no retro | projeto sem versão e projeto atrasado | `tool.state` e ações distintas na R1 | UT-05 |
| Reprovações registradas no retro | specs com histórico | `fail_recorded` conta as linhas FAIL; R5 não dispara com `fail_recorded` > 0; nenhuma evidência na saída | UT-05 |
| Resíduos do retro | `spec_root` numérico no registro; histórico nulo; ID de impedimento livre; specs sem id repetidas | "registro inválido" em Ignorados; "sem histórico"; `IMP-?`; ID uma vez só | UT-06 |
| Ajustes da revisão (Emenda v3) | PASS na tabela sem linha PASS no histórico; `\r` na evidência; título editado; sugestões | sem aviso preso; tabela e histórico íntegros; sem subseção duplicada; sugestões atuais | UT-07 |
| Ferramentas antigas | spec com histórico lida pelo parser da tabela | `gate_table`, `validate` e `pr-check` como antes | CH-02 |

## 7. Artefato B — Plano de Testes (TDD)
### 7.1 Testes de Caracterização
- **CH-01** — Dado um gate que passa na primeira tentativa (`--run` verde e `--na`), quando o `gate` registra, então a spec fica igual à de hoje, sem subseção nova (guarda: passa antes da mudança).
- **CH-02** — Dada uma spec com a subseção `### Histórico de reprovações` preenchida abaixo da tabela, quando `gate_table`, `validate` e `pr-check` leem a spec, então o resultado é o mesmo da spec sem a subseção (guarda: passa antes da mudança).

### 7.2 Testes Unitários
- **UT-01** — Dada uma spec temporária, quando G2 recebe `--fail`, depois `--run` vermelho e depois `--run` verde, então a tabela termina em PASS e o histórico tem duas linhas FAIL (data, evidência e SHA) e uma linha PASS "depois de 2 reprovação(ões)", na ordem.
- **UT-02** — Dado um histórico com três FAILs de G4 depois do último PASS de G4, quando o `gate` registra o terceiro e quando o `status` roda, então os dois mostram o aviso das reprovações seguidas com `impede SPEC-X --type falha`. Com um impedimento `falha` aberto, o `status` não mostra o aviso. Com um PASS no meio, a contagem recomeça. Linhas fora do formato não contam.
- **UT-03** — Dadas uma spec com G5 PASS há 9 dias e G7 pendente, outra com G7 PASS e outra sem G5, quando `status` e `next` rodam com a data de hoje fixa, então só a primeira aparece no aviso "entregue sem fechar", com "9 dia(s)", e na seção "A fechar" do `next`.
- **UT-04** — Dado um repositório temporário sem `spec_root`, quando `private init` roda (`SDD_CONFIG_HOME` temporário), então o `sdd-config.yml` criado tem `sdd_version` igual a `SDD_TOOL_VERSION`. Dado um `sdd-config.yml` que já existe com outra versão, então ele não muda.
- **UT-05** — Dados projetos sintéticos (sem versão, atrasado e atual; specs com histórico de FAIL que tem um marcador único na evidência), quando as métricas e os achados do `retro` são calculados, então:
  - `tool.state` = desconhecida, atrasada ou atual, e a R1 traz a ação de cada estado;
  - `fail_recorded` conta as linhas FAIL;
  - a R5 não dispara com `fail_recorded` > 0;
  - o marcador não aparece no Markdown nem no JSON.
- **UT-06** — Dados um registro com `spec_root: 5`, um projeto com `fail_history` null, um impedimento com ID "texto livre" aberto há mais de N dias e duas specs sem `id` com o mesmo prefixo, quando o `retro` roda, então: exit 0 sem traceback, "registro inválido" em Ignorados, "sem histórico" no Markdown, `IMP-?` no achado R7 e o ID uma vez só em `stale`.
- **UT-07** — (Emenda v3) Dado um histórico com 3 FAILs de G2 e a tabela com G2 PASS sem linha PASS no histórico, quando o `status` roda, então não há aviso de reprovações seguidas. Dado `gate --fail` com `\r\n` na evidência, então a tabela segue legível por `gate_table` e o histórico conta a reprovação. Dada a subseção com o título editado ("### Histórico de Reprovações"), então a próxima reprovação entra nela, sem criar outra, e a contagem inclui as antigas. As sugestões de R1, R3 e R5 não citam o que esta versão já entrega.

### 7.3 Testes de Integração
- **IT-01** — Dado um repositório git temporário com uma spec aprovada, quando a CLI roda `gate SPEC-X G2 --fail` três vezes (com commit entre elas) e depois `gate --run` com o comando de teste do `sdd-config` verde, então:
  - a terceira chamada imprime o aviso;
  - o `status` mostra a parada sugerida até o PASS;
  - a spec final tem o histórico completo;
  - `validate` passa.
- **IT-02** — Dado um repositório temporário com uma spec entregue sem G7, quando a CLI roda `status` e `next`, então o aviso e a seção "A fechar" aparecem. Depois do G7 registrado, somem.

### 7.4 Testes de Contrato
- N/A — não há contrato entre specs; a extensão do JSON do `retro` é só aditiva e coberta por UT-05/UT-06

### 7.5 Testes E2E
- N/A — a jornada é a CLI e, conforme o ADR-0002, é coberta pelos testes de integração

### 7.6 Outros
- Desempenho (RNF): `retro` nos projetos desta máquina com `--registry` abaixo de 15 s, só leitura, medido na revisão (G4).

**Dublês e dados de teste:** repositórios git e specs temporários, `SDD_CONFIG_HOME` temporário, data de hoje fixa por parâmetro interno, nunca o `~/.config/sdd` real.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** merge direto. Os projetos recebem a mudança com `vendor --force` e o plugin atualizado.
- **Dados/schema:** a subseção nova só é criada na próxima reprovação, sem migração das specs existentes.
- **Compatibilidade:** a tabela não muda, e as ferramentas antigas ignoram a subseção (CH-02). O JSON do `retro` só ganha chaves (`retro_version` 1).
- **Observabilidade:** os avisos do `status` e a próxima retrospectiva (R3 e R5 devem cair com o uso).
- **Rollback:** `git revert` do merge. As subseções já escritas ficam como texto inofensivo.
- **Etapas de migração/coexistência:** N/A

## 9. Questões em Aberto
- [x] Onde guardar o histórico de reprovações? — numa subseção abaixo da tabela do Registro de Gates, escrita só pela ferramenta, para não quebrar as versões antigas que leem a tabela (thomas, 2026-11-17, piloto automático com o recomendado)
- [x] A terceira reprovação seguida abre impedimento sozinha? — não: o `gate` e o `status` sugerem, e o Architect registra (ADR-0019) (thomas, 2026-11-17, piloto automático com o recomendado)
- [x] A partir de quantos dias avisar "entregue sem fechar"? — desde o primeiro dia, mostrando a idade; sem chave nova de configuração nesta versão (thomas, 2026-11-17, piloto automático com o recomendado)

## 10. Aprovação (H1)
Registrada no frontmatter (`approved_by`, `approved_at`) somente depois que o humano responder "Aprovado". O arquiteto nunca aprova a própria spec.

## 11. Checklist de Implementação
<!-- Preenchido na fase PLAN, após a aprovação. Cada fase começa pelos testes. -->
- [x] Fase 1 (test-writer): CH-01, CH-02, UT-01 a UT-06, IT-01 e IT-02 com a tag `SPEC-0078:<ID>`; CH passando e os demais falhando pelo motivo certo
- [x] Fase 2 (implementer): histórico de reprovações no `gate`, avisos no `status`/`next`, `sdd_version` no `private init`, `retro` (tool.state, fail_recorded, resíduos), docs, CHANGELOG e versões
- [x] Emenda v3: test-writer (UT-07) e implementer (ajustes da revisão)
- [x] Fase 3 (reviewer): G4 independente, com o desempenho do `retro` (7.6)

## 12. Registro de Gates
<!-- Status: PENDING | PASS | FAIL | N/A. PASS e N/A exigem evidência (comando + resultado, SHA, execução de CI, veredito). -->
| Gate | Status | Evidência | Data |
|---|---|---|---|
| G0 Spec | PASS | validate: 0 erro(s) — 1eb26e7 | 2026-11-17 |
| G1 Red | PASS | verify G1: PASS; `python3 -m unittest discover -s skills/gluon-spec/tests && python3 -m unittest discover -s skills/photon-brain/tests && python3 -m unittest discover -s skills/boson-atlas/tests && python3 -m unittest discover -s tests/plugin && python3 -m unittest discover -s mcp/tests` exit 1 (red: FAILED (failures=8, skipped=1)) — 57377a7 | 2026-11-17 |
| G2 Green | PASS | test exit 0 (OK); lint exit 0 (All checks passed!) — 358e32c | 2026-11-17 |
| G3 Arquitetura | PASS | arch_test exit 0 (OK) — 6a6c6e5 | 2026-11-17 |
| G4 Review | PASS | verify G1+G4: PASS; revisão: reviewer independente: APPROVED (rodada 2; minors 1–3 e nits 1–4 da rodada 1 resolvidos pela Emenda v3; 220 testes em 3.9 e 3.14; 9 cenários de escrita sem corromper a spec; retro só leitura em 1,7 s) — 8ed04a3 | 2026-11-17 |
| G5 Integração & CI | PENDING | | |
| H2 Integração aprovada | PENDING | | |
| G6 Deploy | PENDING | | |
| G7 Pronto & Docs | PENDING | | |

## 13. Registro de Impedimentos
<!-- Toda parada é registrada pelo Architect com `spec_graph.py impede` e fechada com `resolve` — não edite à mão. Tipos: spec (spec errada/incompleta → resolve com Emenda) | decisão (só o humano decide → resposta ou ADR) | trabalho (falta algo que exige código → SPEC-0078 nova) | externo (acesso, ambiente, terceiro → ação tomada) | falha (3 FAILs seguidos no mesmo gate → diagnóstico e decisão). Com impedimento aberto a spec aparece como parada no INDEX e não pode ser fechada. -->
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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted {{id}}`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
| 2 | 2026-11-17 | Esclarecimentos do contrato: R5 com fail_history null nunca dispara; normalização de IMP; SHA no histórico; N/A depois de reprovações; escopo de "entregue sem fechar"; avisos só no `status` sem IDs; ajuste dos testes da SPEC-0074 que fixavam chaves exatas e "sem git" | Ambiguidades apontadas pelo test-writer (fase 1) | SPEC-0074 (testes) | thomas, 2026-11-17 (piloto automático com o recomendado) |
| 3 | 2026-11-17 | Ajustes da revisão G4: aviso de reprovações seguidas respeita o status da tabela; \r na evidência; título da subseção tolerante; sugestões R1/R3/R5 atualizadas; UT-07 | Revisão independente (APPROVED com minors 1–3 e nit 1) | — | thomas, 2026-11-17 (piloto automático com o recomendado) |
