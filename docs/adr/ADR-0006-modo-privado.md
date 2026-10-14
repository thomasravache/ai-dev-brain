---
id: ADR-0006
title: "Modo privado: estado do SDD fora do repositório"
status: proposed
origin: decision
date: 2026-10-14
pillars: []
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0003
---

# ADR-0006 — Modo privado: estado do SDD fora do repositório

## Contexto e Problema
A skill guarda todo o estado do SDD no repositório (`docs/specs`, `docs/adr`, `Refs: SPEC-NNNN` nos commits, tags nos testes, job `sdd` na CI). Num repositório compartilhado com um time que não adotou o SDD, nada disso pode aparecer: para o time, o resultado tem que ser código, commits e PRs normais. Como usar a skill do seu lado, com specs, gates e evidência, sem deixar marca no repositório?

## Direcionadores da Decisão
- Zero marca do SDD no repositório do time: arquivos, mensagens, nomes de branch, comentários, corpo de PR.
- O modo completo (SDD versionado no repositório) não muda em nada para quem não ativa o modo privado.
- Agnóstico de stack e de plataforma (ADR-0001): só `git` e comandos do sdd-config.
- O conteúdo das specs descreve o domínio do time: onde ele fica é decisão de quem usa, não da ferramenta.
- Estado sobrevive a um novo clone e a uma nova sessão.

## Opções Consideradas
- **A — Pasta externa (`spec_root`) encontrada por um registro do usuário**, versionada por um git local próprio, com push opcional.
- **B — Repositório "sombra" separado**, ligado ao repositório do time.
- **C — Dentro do repositório, ignorado por `.git/info/exclude`.**

## Resultado da Decisão
**Opção escolhida:** A, porque é a única que não deixa nada dentro do clone do time e sobrevive a um novo clone; a opção B vira um caso particular de A (a pasta tem um remoto e `sync: push`).

**Regras (verificáveis):**
- O modo de cada repositório vem de um registro do usuário fora de qualquer repositório: `projects.json` em `$SDD_CONFIG_HOME`, ou `$XDG_CONFIG_HOME/sdd`, ou `~/.config/sdd`. Chave: o remoto normalizado (`host/caminho`, sem protocolo, usuário, porta nem `.git`); sem remoto, o caminho absoluto do repositório.
- Sem entrada no registro, a skill se comporta exatamente como hoje (modo completo).
- Em modo privado, specs, ADRs, sdd-config e INDEX vivem no `spec_root` (`specs/`, `adr/`, `sdd-config.yml`); nenhum comando escreve no repositório do time, e os comandos que só fazem sentido no repositório (`vendor`, `pr-check`) se recusam.
- O `spec_root` é um repositório git local; cada comando que grava registros faz commit nele. Push só com `sync: push` no registro (padrão: `none`).
- Raiz padrão das pastas: `default_root` do registro; sem ele, `$XDG_DATA_HOME/sdd` (`~/.local/share/sdd`).
- Rastreabilidade sem marcas: commits ligados à spec pela branch e registrados (SHA e `patch-id`) no `spec_root`; red antes do green provado pelos arquivos do commit e pela execução dos testes no commit red; testes do plano apontados por `caminho::nome`.
- Toda saída que vai para o time (diff, mensagens, nome de branch, corpo de PR) passa pelo `leak-check` antes.
- A ferramenta não mexe em atribuição de IA nos commits (`Co-Authored-By` e similares): isso segue a configuração do agente e a política do time.

### Consequências
- **Boa**, porque o mesmo processo (specs, gates, evidência) funciona num repositório onde o SDD não foi combinado, sem mudar nada no modo completo.
- **Ruim**, porque some o controle fora do modelo que só a CI dá (job `sdd` obrigatório): o modo privado é disciplina com evidência, protegida pelo `leak-check` e pelo hook local, não um bloqueio no merge. E o `spec_root` sem remoto se perde junto com a máquina.
- **Neutra:** o registro usa JSON (biblioteca padrão) e não YAML, porque o parser de YAML da ferramenta só aceita chaves simples e a chave aqui é uma URL.

### Confirmação (G3)
Testes de integração da SPEC-0003 (sem registro, comportamento idêntico; com registro, repositório do time intocado) e da SPEC-0006 (jornada privada completa sem nenhuma marca no repositório); o teste de arquitetura UT-04 da SPEC-0001 garante que o código novo só executa `git` e comandos do sdd-config.

## Prós e Contras das Opções
| Critério (peso) | A — pasta externa + registro | B — repositório sombra | C — `.git/info/exclude` |
|---|---|---|---|
| Nada dentro do clone do time (3) | sim | sim | não (arquivos no clone, risco de `git add -f`, apagados por `git clean -fdx`) |
| Sobrevive a novo clone (3) | sim | sim | não |
| Várias máquinas (1) | com `sync: push` | sim | não |
| Onde ficam dados do time (2) | decisão do usuário | remoto obrigatório | só local |
| Esforço (1) | médio | médio | baixo |

## Mais Informações
Fontes: não verificado — decisão de design interna, sem ferramenta externa. Discussão e respostas do mantenedor em 2026-10-13/14 (armazenamento local com push opcional; sem mexer em atribuição de IA; skill agnóstica).
