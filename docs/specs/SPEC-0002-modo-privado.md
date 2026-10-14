---
id: SPEC-0002
title: "Modo privado: SDD fora do repositório do time"
tier: epic
type: feature
status: proposed
created: 2026-10-14
depends_on: []
adrs: [ADR-0006]
external: []
approved_by:
approved_at:
---

# SPEC-0002 — Modo privado: SDD fora do repositório do time (Épico)

## 1. Visão
Quem usa a skill pode trabalhar com o SDD completo (specs, aprovação, TDD verificado, gates com evidência, relatório de entrega) num repositório compartilhado com um time que não adotou o processo, sem deixar nenhuma marca do SDD no repositório: para o time, o resultado é código, commits e PRs normais. Nos projetos onde o SDD é do repositório (modo completo), nada muda.

## 2. Escopo
**Objetivos (dentro do escopo):**
- Registro do usuário que liga cada repositório ao modo privado e a uma pasta externa (`spec_root`) versionada por git local, com push opcional (SPEC-0003).
- `leak-check` que acha marcas do SDD em diff, mensagens, nomes de branch e corpo de PR, com hook local de pre-push e nomes de branch neutros (SPEC-0004).
- Rastreio sem marcas: commits ligados à spec pela branch, red antes do green provado pelos arquivos e pela execução dos testes no commit red, testes do plano por `caminho::nome`, merge encontrado por `patch-id` mesmo com squash (SPEC-0005).
- `pr` com título e corpo no padrão do time, detecção das convenções do time e a documentação do modo (SPEC-0006).

**Não-objetivos (fora do escopo):**
- Esconder o uso de IA: a ferramenta não mexe em `Co-Authored-By` e similares (ADR-0006).
- Escolher onde o `spec_root` fica ou sincroniza além do padrão: decisão de quem usa.
- Integração com board em modo privado (fica desligada).
- Controle na CI do time: não é nossa; o G5 só lê o resultado dela pelo comando `ci` do sdd-config.
- Correções do `pr` no modo completo achadas na SPEC-0001 (seção "Breaking changes" falsa com emenda, "Como foi feito" em minúscula): spec lite própria, fora deste épico.

## 3. Arquitetura Alvo
**Contexto:** projeto existente; ADR-0001 (arquivo único, só biblioteca padrão, só `git` e comandos do sdd-config) continua valendo. O ponto de entrada de todos os comandos é `Project(root)` (`spec_graph.py:459`), que hoje fixa `docs/specs` e `docs/adr` na raiz do repositório.

**Como fica:**
- `Project` passa a resolver o modo: consulta o registro do usuário pelo remoto normalizado do repositório (ou pelo caminho). Modo completo → caminhos de hoje. Modo privado → `spec_root/specs`, `spec_root/adr`, `spec_root/sdd-config.yml`.
- Todo comando que grava registros, em modo privado, faz commit no git do `spec_root` (e push com `sync: push`).
- Comandos que tocam o repositório do time passam pelo `leak-check`: `worktree` (nome da branch), `gate` G4/G5 (diff e mensagens da branch), `pr` (título e corpo); o hook local de pre-push cobre o resto.
- `verify` em modo privado usa o registro de commits da spec (branch → SHAs, `patch-id`) em vez de `Refs:` e tags; o G1 roda os testes no commit red.
- Contrato entre as filhas: a API do modo da SPEC-0003 (registro, `spec_root`, modo do `Project`) é consumida por SPEC-0004 e SPEC-0005; a SPEC-0006 depende das implementações de todas.

**Decisões (ADRs):** ADR-0006 — estado do SDD fora do repositório, pasta externa + registro do usuário.

**Regras de arquitetura a garantir (G3):** as do ADR-0001 (testes da SPEC-0001: só biblioteca padrão, arquivo único, processos só `git` ou comando do sdd-config). Nenhuma regra estrutural nova.

## 4. Decomposição
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0003 | Registro do usuário e spec_root | full | feature | M | — | — |
| SPEC-0004 | Checagem de vazamento | full | feature | M | — | SPEC-0003@1 |
| SPEC-0005 | Rastreio sem marcas no repositório | full | feature | M | — | SPEC-0003@1 |
| SPEC-0006 | PR neutro, convenções do time e documentação do modo privado | full | feature | M | SPEC-0004, SPEC-0005 | SPEC-0003@1 |

Todas alteram `spec_graph.py` e `test_spec_graph.py` (arquivo único, ADR-0001): as ondas saem sequenciais.

## 5. Estratégia de Entrega
- **Ambientes:** N/A — pilar entrega dispensado; a skill vale na `main` pelo link simbólico.
- **Entrega por onda:** cada filha entra na `main` por PR próprio, com `SDD_TOOL_VERSION` e CHANGELOG atualizados (ADR-0005). O modo privado só se ativa com `private init`, então filhas parciais não afetam ninguém.
- **Feature flags:** N/A — o próprio registro do usuário é o liga/desliga por repositório.
- **Rollback:** `git revert` do merge de cada filha; o registro e as pastas do usuário não são apagados.
- **Métricas de sucesso pós-release:** primeiro uso real num repositório de time: zero marca encontrada pelo `leak-check` e por inspeção do PR, por duas semanas.

## 6. Riscos & Mitigações
- Vazamento por caminho não coberto (ex.: comentário escrito pelo agente fora dos comandos) — hook local de pre-push com `leak-check`; regras extras do usuário em `leak_patterns`.
- Time com gerenciador de hooks (husky, lefthook, pre-commit, `core.hooksPath`) impede o hook local — `leak-check` roda dentro de `worktree`, `gate` e `pr`; o `private init` avisa.
- Squash ou rebase no merge apagam os SHAs da branch — evidência guarda `patch-id`; G7 acha o merge por `patch-id`.
- `spec_root` só local se perde com a máquina — `status` avisa mudanças sem commit; `sync: push` para quem tiver remoto permitido.
- Dados do time num remoto pessoal — fora da ferramenta: `sync` desligado por padrão e a documentação diz que a escolha do remoto é do usuário com o time.

## 7. Critérios de Aceite do Épico
- [ ] Sem entrada no registro, todos os comandos se comportam como hoje — SPEC-0003:IT-04
- [ ] Com o modo privado ligado, nenhum comando escreve no repositório do time e o estado vive no `spec_root` versionado — SPEC-0003:IT-02
- [ ] Um push com marca do SDD é bloqueado pelo hook local — SPEC-0004:IT-04
- [ ] Red antes do green é provado sem `Refs:` nem tags — SPEC-0005:IT-01
- [ ] O merge da spec é achado depois de um squash — SPEC-0005:IT-05
- [ ] Jornada privada completa (init → spec → red → green → gates → pr) termina sem nenhuma marca do SDD no repositório nem no PR — SPEC-0006:IT-05
- [ ] O código novo só executa `git` e comandos do sdd-config — SPEC-0001:UT-04

## 8. Questões em Aberto
- [x] Onde fica o `spec_root`? — Pasta local versionada por git próprio (opção A); remoto opcional e configurável (`sync: push`) (thomas, 2026-10-14)
- [x] Mexer em atribuição de IA nos commits? — Não; segue a configuração do agente e a política do time (thomas, 2026-10-14)
- [x] Raiz padrão das pastas? — Padrão da ferramenta `$XDG_DATA_HOME/sdd`; o registro aceita `default_root`, e o do mantenedor usa `~/dev/sdd` (`~/dev/sdd`: thomas, 2026-10-14; padrão XDG e `default_root`: proposta do Architect, a confirmar no H1)
- [x] Mais de uma ferramenta de plataforma? — Não: a skill é agnóstica; G5 pelo comando `ci` do sdd-config, merge e convenções detectados pelo `git` (agnóstico: thomas, 2026-10-14; forma de detecção: proposta do Architect, a confirmar no H1)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico. -->

## 12. Emendas
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
