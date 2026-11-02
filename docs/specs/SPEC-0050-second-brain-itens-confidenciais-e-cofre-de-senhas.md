---
id: SPEC-0050
title: "second-brain: itens confidenciais e cofre de senhas"
tier: full
type: feature
user_facing: false
status: proposed
created: 2026-11-02
parent:
depends_on: [SPEC-0023, SPEC-0024, SPEC-0044]
consumes_contract: []
contract_version: 1
touches: [skills/second-brain/scripts/brain.py, skills/second-brain/tests/**, skills/second-brain/SKILL.md, skills/second-brain/references/confidential.md, skills/second-brain/references/config.md, skills/second-brain/CHANGELOG.md]
adrs: [ADR-0007]
external: []
size: M
approved_by:
approved_at:
---

# SPEC-0050 — second-brain: itens confidenciais e cofre de senhas

> Rascunho no radar (pedido do usuário em 2026-11-02). Desenho proposto abaixo; contrato e testes são detalhados depois das Questões em Aberto.

## 1. Visão Geral
O segundo cérebro passa a conviver com informação confidencial sem expô-la. A ideia **não** é guardar senhas no vault em texto, nem fazer a LLM ler senhas. Ela tem duas peças:
- **Referência a um cofre:** uma nota pode apontar para uma entrada do gerenciador de senhas que a pessoa já usa (KeePass, Bitwarden, 1Password ou outro), por exemplo `vault_ref: keepass://Pessoal/Banco/Conta`. Assim o segundo cérebro sabe que a senha existe e onde está, sem nunca conter a senha.
- **Arquivos confidenciais opacos:** documentos sensíveis (o próprio `.kdbx`, um PDF cifrado, cópias de documentos) ficam em `files/` marcados como confidenciais. A skill guarda e liga esses arquivos, mas nunca abre, extrai, processa, exporta nem envia por conector.

Notas marcadas com `confidential: true` ficam fora da busca, do `context`, do `related`, da exportação para o NotebookLM e do modo só conector, a menos que a pessoa peça explicitamente.

## 2. Motivação & Escopo
**Motivação:** a pessoa quer o segundo cérebro como lugar central também para o que é sensível, e hoje usa o KeePass para senhas. A skill não pode virar um vazamento: o vault sincroniza com a nuvem, a LLM lê o que a busca devolve, e há exportação e conector.

**Objetivos (proposta):**
- Chave de frontmatter `confidential: true` e um tipo de nota `secret-ref`, só com metadados e a referência ao cofre.
- `brain.py ingest --confidential`: guarda o arquivo em `files/` sem rodar processador e sem extrair texto. A nota de fonte registra só o nome, o tamanho e um hash.
- Filtros: `search`, `related`, `context`, `export-notebooklm` e o modo só conector ignoram itens confidenciais por padrão, e `--include-confidential` liga de propósito.
- `lint`: nova regra que aponta texto com cara de segredo numa nota não confidencial (padrões de senha, token, chave privada, número de cartão), sem mostrar o valor.
- Agnóstico: a referência tem o formato `<gerenciador>://<caminho>`, a skill não fala com nenhum gerenciador e só a pessoa abre o cofre.

**Não-objetivos:**
- A skill ler, escrever, gerar ou mostrar senhas, ou abrir o `.kdbx`.
- Criptografia própria no `brain.py`: só biblioteca padrão, e cripto caseira é risco.
- Integração com a API de um gerenciador de senhas.

## 3. Dependências
- **Implementações necessárias:** SPEC-0023 (`lint`), SPEC-0024 (exportação) e SPEC-0044 (modo só conector), que ganham o filtro.
- **Contratos consumidos:** N/A
- **Pré-requisitos externos:** um gerenciador de senhas da pessoa (opcional).

## 4. Decisão Arquitetural
**Contexto:** projeto existente; segue o ADR-0007 (só biblioteca padrão, sem rede, só cria e acrescenta). Provavelmente exige um ADR novo: "itens confidenciais: referência e opacidade, nunca o segredo no vault".

**Decisão:** a detalhar depois das Questões em Aberto.

**Justificativa:** manter o segredo fora do vault é o único jeito de ser agnóstico e seguro ao mesmo tempo.

**Desvio do padrão existente:** a definir (ADR novo).

**Alternativas descartadas (prévia):** guardar senhas cifradas no vault com cripto própria; integrar a skill com a API do KeePass ou de outro gerenciador.

**ADRs:** ADR-0007 (aplicado); ADR novo a criar.

## 5. Requisitos Não-Funcionais
- **Desempenho e escala:** N/A — rascunho.
- **Segurança:** nenhum segredo em texto no vault, no log, na saída dos comandos ou em pacotes exportados; a regra do `lint` não mostra o valor encontrado.
- **Privacidade e dados pessoais:** itens confidenciais nunca saem pelo conector nem pela exportação sem pedido explícito.
- **Disponibilidade e resiliência:** N/A — rascunho.
- **Acessibilidade (UI):** N/A — CLI.
- **Custo:** N/A.

## 6. Artefato A — Contrato
**Interface:** a definir depois das Questões em Aberto.

```text
(proposta) frontmatter: confidential: true | vault_ref: "<gerenciador>://<caminho da entrada>"
(proposta) brain.py ingest FONTE --confidential   → files/, sem processador, nota de fonte só com nome/tamanho/hash
(proposta) search|related|context|export-notebooklm --include-confidential
(proposta) lint: regra "secret-in-note" (aviso, sem mostrar o valor)
```

**Design:** N/A — sem interface gráfica.

**Arquivos/módulos afetados:** ver `touches`.

### 6.1 Mapa de Comportamentos
| Cenário | Condição / Entrada | Resultado esperado | Testes |
|---|---|---|---|
| A detalhar | depois das Questões em Aberto | — | UT-01 |

## 7. Artefato B — Plano de Testes (TDD)

### 7.1 Testes de Caracterização
- N/A — rascunho.

### 7.2 Testes Unitários
- **UT-01** — A detalhar depois das Questões em Aberto.

### 7.3 Testes de Integração
- **IT-01** — A detalhar depois das Questões em Aberto.

### 7.4 Testes de Contrato
- N/A — sem contrato entre specs.

### 7.5 Testes E2E
- N/A — conforme o ADR-0002, a jornada é a CLI, coberta pelos testes de integração.

### 7.6 Outros
- N/A.

**Dublês e dados de teste:** a definir.

**Ambiente de execução:** local e CI (Python 3.9 e 3.15).

## 8. Plano de Rollout
- **Estratégia:** deploy direto; itens sem `confidential` não mudam.
- **Dados/schema:** chaves novas opcionais de frontmatter.
- **Compatibilidade:** os filtros só excluem notas marcadas.
- **Observabilidade:** o `doctor` pode mostrar quantos itens confidenciais existem (sem conteúdo).
- **Rollback:** `git revert` do merge.
- **Etapas de migração/coexistência:** N/A.

## 9. Questões em Aberto
- [ ] Quais gerenciadores de senha você usa ou quer suportar na referência (KeePass/KeePassXC, Bitwarden, 1Password, outro)? (thomas)
- [ ] O arquivo `.kdbx` do KeePass deve ficar dentro da estrutura do segundo cérebro (em `files/`, como anexo opaco) ou continuar só onde está hoje, com a nota apontando para ele? (thomas)
- [ ] Itens confidenciais devem ser totalmente invisíveis para a LLM (nem o título aparece na busca) ou só o conteúdo é protegido (o título e a referência aparecem)? (thomas)
- [ ] A regra do `lint` que acha "texto com cara de segredo" é desejada, mesmo podendo dar falso positivo? (thomas)

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
<!-- Mudança em spec aprovada: uma linha por emenda. Mudou o contrato? Incremente `contract_version` e rode `spec_graph.py impacted SPEC-0043`. -->
| Versão do contrato | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
