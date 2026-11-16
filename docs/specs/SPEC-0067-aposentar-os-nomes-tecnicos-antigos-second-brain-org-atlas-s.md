---
id: SPEC-0067
title: Aposentar os nomes técnicos antigos (second-brain, org-atlas) sem quebrar instalações
tier: epic
type: migration
status: proposed
created: 2026-11-16
depends_on: []
adrs: [ADR-0018, ADR-0020]
external: []
approved_by:
approved_at:
---

# SPEC-0067 — Aposentar os nomes técnicos antigos (second-brain, org-atlas) sem quebrar instalações (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0067`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

## 1. Visão
> Rascunho (2026-11-16): pedido do thomas ("concordo, vamos sim") à recomendação de aposentar os nomes técnicos antigos depois da SPEC-0055. Detalhar as filhas antes do H1.

Ao fim do épico, nenhuma parte técnica do Fermion usa mais `second-brain` ou `org-atlas`, e nenhuma máquina, vault, atlas ou coletor já configurado quebra no caminho: o nome novo passa a ser o padrão, o antigo continua lido por um período anunciado e o `doctor` de cada skill oferece migrar o que existe.

## 2. Escopo
**Objetivos (dentro do escopo):**
- `photon-brain`: pasta de configuração da máquina `~/.config/photon-brain` (antes `~/.config/second-brain`); mensagens ("second-brain não configurado"), cabeçalho do `config.yml` local e nome dos backups (`second-brain-<data>.zip`).
- `boson-atlas`: pasta de configuração `~/.config/boson-atlas` (antes `~/.config/org-atlas`); pasta do atlas vendorizado `.boson-atlas/` (antes `.org-atlas/`); contrato do coletor `boson-atlas/collector@2` (o `org-atlas/collector@1` continua aceito); mensagens e workflow de CI gerado pelo `vendor`.
- Leitura dupla: o caminho novo primeiro, o antigo como reserva, gravação só no novo; o `doctor` acusa a configuração no caminho antigo e oferece copiar (nunca move nem apaga sozinho, ADR-0019).
- O `fermion_doctor` (SPEC-0061) passa a avisar também da configuração e da pasta `.org-atlas/` antigas.
- Remoção do caminho antigo numa versão futura, anunciada no CHANGELOG de cada skill com a data.

**Não-objetivos (fora do escopo):**
- Renomear o marketplace (`fermion-lab` → `fermion-ai-lab`, ainda não decidido) ou o repositório.
- `tools/sdd/` e os nomes dos scripts (`spec_graph.py`, `brain.py`, `atlas.py`), que não carregam o nome antigo.
- O apelido "antes `sdd-management`/`second-brain`/`org-atlas`" na `description` das skills: continua até a remoção, para o agente reconhecer pedidos pelo nome antigo.

## 3. Arquitetura Alvo
**Contexto:** brownfield, `type: migration` (muda a configuração definida no ADR-0008 e no ADR-0010 e o contrato do ADR-0011). A SPEC-0055 e o ADR-0018 renomearam as skills e mantiveram os nomes técnicos de propósito, para não quebrar instalações.

Cada CLI resolve a pasta de configuração assim: variável de ambiente (`BRAIN_CONFIG_HOME`/`ATLAS_CONFIG_HOME`, sem mudança), senão a pasta nova se existir, senão a antiga se existir, senão a nova. O atlas lê `.boson-atlas/` e, na falta, `.org-atlas/`; o `vendor` grava só a nova. O validador do contrato aceita `@1` e `@2`, com o mesmo formato; os coletores de referência passam a emitir `@2`.

**Decisões (ADRs):** ADR-0020 — nomes técnicos novos com leitura dupla e remoção anunciada (proposto junto com este épico).

**Regras de arquitetura a garantir (G3):** nenhuma gravação em caminho antigo (teste por filha); a guarda de nomes antigos (`tests/plugin/test_skill_names.py`) passa a cobrir os nomes técnicos, com exceção só para a leitura de compatibilidade e o CHANGELOG.

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| a criar | `photon-brain`: pasta de configuração, mensagens e backups com o nome novo, leitura dupla | full | migration | M | — | — |
| a criar | `boson-atlas`: pasta de configuração, `.boson-atlas/` e mensagens com o nome novo, leitura dupla | full | migration | M | — | — |
| a criar | `boson-atlas`: contrato `boson-atlas/collector@2` com `@1` aceito | full | migration | S | filha anterior | — |
| a criar | `fermion_doctor` avisa de configuração e `.org-atlas/` antigas | lite | feature | S | as três acima | — |
| a criar | Remoção dos caminhos antigos (versão anunciada) | full | migration | S | todas | — |

## 5. Estratégia de Entrega
- **Ambientes:** N/A, sem deploy; distribuição pelo plugin e por cópia.
- **Entrega por onda:** uma skill por onda (photon-brain, depois boson-atlas com o contrato), depois o aviso no `fermion_doctor`; a remoção do caminho antigo é uma filha separada, numa versão posterior anunciada.
- **Feature flags:** N/A — a leitura dupla é a compatibilidade.
- **Rollback:** reverter a onda; como a leitura antiga continua, nada configurado deixa de funcionar.
- **Métricas de sucesso pós-release:** o `doctor` desta máquina sem aviso de caminho antigo depois da migração oferecida.

## 6. Riscos & Mitigações
- Configuração em dois lugares divergindo — gravação só no novo e aviso do `doctor` enquanto o antigo existir.
- Coletor de terceiros emitindo `@1` — o validador aceita `@1` até a remoção anunciada.
- Atlas compartilhado com máquinas em versões diferentes — o atlas lê as duas pastas; o `vendor` só regrava quando alguém roda.

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] Uma máquina configurada com os nomes antigos continua funcionando depois da atualização, sem nenhuma ação — teste a definir nas filhas
- [ ] Configuração nova é gravada só no caminho novo — teste a definir nas filhas
- [ ] O `doctor` acusa o caminho antigo e mostra como migrar — teste a definir nas filhas

## 8. Questões em Aberto
- [x] Por quanto tempo o caminho antigo continua lido antes da remoção? — Três versões mensais, com a data da remoção anunciada no CHANGELOG de cada skill (thomas, 2026-11-16: segue o recomendado)
- [x] O `doctor` copia a configuração antiga para a nova quando a pessoa confirma, ou só mostra o comando de cópia? — Só mostra o comando, como o ADR-0019 (thomas, 2026-11-16: segue o recomendado)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0067` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
