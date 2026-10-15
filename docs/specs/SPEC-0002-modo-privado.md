---
id: SPEC-0002
title: "Modo privado: SDD fora do repositório do time"
tier: epic
type: feature
status: implemented
created: 2026-10-14
depends_on: []
adrs: [ADR-0006]
external: []
approved_by: thomas
approved_at: 2026-10-14
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
- [x] Sem entrada no registro, todos os comandos se comportam como hoje — SPEC-0003:IT-04
- [x] Com o modo privado ligado, nenhum comando escreve no repositório do time e o estado vive no `spec_root` versionado — SPEC-0003:IT-02
- [x] Um push com marca do SDD é bloqueado pelo hook local — SPEC-0004:IT-04
- [x] Red antes do green é provado sem `Refs:` nem tags — SPEC-0005:IT-01
- [x] O merge da spec é achado depois de um squash — SPEC-0005:IT-05
- [x] Jornada privada completa (init → spec → red → green → gates → pr) termina sem nenhuma marca do SDD no repositório nem no PR — SPEC-0006:IT-05
- [x] O código novo só executa `git` e comandos do sdd-config — SPEC-0001:UT-04

## 8. Questões em Aberto
- [x] Onde fica o `spec_root`? — Pasta local versionada por git próprio (opção A); remoto opcional e configurável (`sync: push`) (thomas, 2026-10-14)
- [x] Mexer em atribuição de IA nos commits? — Não; segue a configuração do agente e a política do time (thomas, 2026-10-14)
- [x] Raiz padrão das pastas? — Padrão da ferramenta `$XDG_DATA_HOME/sdd`; o registro aceita `default_root`, e o do mantenedor usa `~/dev/sdd` (`~/dev/sdd`: thomas, 2026-10-14; padrão XDG e `default_root`: proposta do Architect, confirmada no H1 por thomas, 2026-10-14)
- [x] Mais de uma ferramenta de plataforma? — Não: a skill é agnóstica; G5 pelo comando `ci` do sdd-config, merge e convenções detectados pelo `git` (agnóstico: thomas, 2026-10-14; forma de detecção: proposta do Architect, confirmada no H1 por thomas, 2026-10-14)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|
| IMP-01 | 2026-10-14 | G1 | decisão | Ondas do épico aguardam o H2 da SPEC-0001, parada por IMP-02 (GitHub Actions bloqueado por cobrança) | next/waves: SPEC-0003..0005 aguardando por arquivos em comum com SPEC-0001 | thomas | thomas autorizou em 2026-10-14 começar a SPEC-0003 antes do H2 da SPEC-0001 ('não podemos parar agora'); risco baixo: o código da SPEC-0001 já está na base da épica (sdd/SPEC-0002). G5 de cada filha segue exigindo a CI quando as Actions voltarem | 2026-10-14 |
| IMP-02 | 2026-10-14 | G5 | externo | G5 de todas as filhas depende da CI, e o GitHub Actions está bloqueado por cobrança (mesma causa do IMP-02 da SPEC-0001) | filhas integradas localmente na branch do épico; suíte, lint e arquitetura verdes localmente em 3.9/3.10/3.15 | thomas | repositório tornado público por thomas em 2026-10-15 (Actions sem cobrança); CI de volta: PR #3 verde (runs 38675524740 e 38675524715); G5 das filhas regravados com a CI | 2026-10-15 |

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico. -->
**O que foi entregue:** modo privado do SDD na mesma skill — registro do usuário e `spec_root` externo com git próprio (SPEC-0003), `leak-check` com hook `pre-push` local e branches neutras (SPEC-0004), rastreio sem marcas com G1 no commit red e G7 achando merge, squash ou rebase (SPEC-0005), convenções do time, `pr` neutro e guia `references/private-mode.md` (SPEC-0006). Correções achadas no caminho: SPEC-0007 (`pr` sem quebra falsa), SPEC-0008 (`spec_root` fora do repositório), SPEC-0009 (nota do `--evidence`), SPEC-0010 (suíte antiga isolada do registro). O modo completo segue igual (guardas SPEC-0003:IT-04, SPEC-0005:IT-09, SPEC-0006:IT-06).

**Como:** as filhas rodaram em sequência na branch `sdd/SPEC-0002`, com exceção de onda autorizada por thomas (IMP-01), cada uma red → green com G1–G4 e merge `--no-ff` na branch do épico; integração pelo PR #3, com merge commit. O GitHub Actions ficou bloqueado por cobrança em 2026-10-14 (IMP-02); o G5 foi regravado na CI do GitHub em 2026-10-15, depois que o repositório se tornou público. Versão da ferramenta 2026.10.8; sem deploy próprio (pilar entrega dispensado): vale na `main` pelo link simbólico da skill.

**Critérios de aceite:** todos provados pelos testes citados na seção 7, verdes na CI do PR #3 (run 38677000910, Python 3.9 e 3.15); SPEC-0001:UT-04 verde na CI do PR #1 (run 38676625286).

**Métricas pós-release:** N/A — ferramenta local de linha de comando, sem telemetria.

**Pendências:** nenhuma spec nova. A cópia `tools/sdd` é atualizada em PR próprio depois do merge (ADR-0005). A revisão (G4) de todas as filhas foi em modo solo.

## 12. Emendas
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
