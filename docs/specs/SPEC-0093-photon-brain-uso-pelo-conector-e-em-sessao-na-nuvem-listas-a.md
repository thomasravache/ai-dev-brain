---
id: SPEC-0093
title: "photon-brain: uso pelo conector e em sessão na nuvem (listas, achar o vault, fuso e sessão sem a pasta)"
tier: epic
type: feature
status: proposed
created: 2026-11-23
depends_on: []
adrs: []
external: []
approved_by:
approved_at:
---

# SPEC-0093 — photon-brain: uso pelo conector e em sessão na nuvem (listas, achar o vault, fuso e sessão sem a pasta) (Épico)

> **Radar (thomas, 2026-11-23):** primeiro feedback de uso real da photon-brain por conector, numa sessão na nuvem. Está registrado na inbox do vault, na nota `inbox/2026-11-23-020743-feedback-da-skill-second-brain-melhorias.md`; novos feedbacks entram na inbox do mesmo jeito. Um segundo feedback, do modo só conector no Google Drive (thomas, 2026-11-23), acrescentou os pontos 6 e 7 e detalhes nos pontos 3 e 5. Um terceiro, de uso real em 2026-11-25 (thomas), confirmou os pontos 1 a 6, trouxe detalhes nos pontos 3, 4 e 5 e acrescentou os pontos 8 a 11. Fica a detalhar antes do G0, sempre agnóstico e configurável. Os pontos:
> 1. **Lista que cresce:**
>    - pelo conector só dá para criar arquivo novo;
>    - uma lista que vai ganhando itens vira várias capturas soltas na inbox;
>    - falta um jeito de acrescentar a uma nota que já existe, ou de juntar as capturas depois.
> 2. **Tipo para listas:**
>    - nenhum tipo de nota serve para lista ou checklist;
>    - sugestão do usuário: um tipo `list` e um comando `list add`.
> 3. **Achar o vault no Drive:**
>    - foi preciso procurar o `brain-config.yml` para descobrir onde o vault fica;
>    - há várias pastas `inbox` antigas que confundem a busca;
>    - falta um jeito claro de identificar o vault e a inbox certos pelo conector;
>    - no segundo feedback, o caminho que funcionou foi buscar `title = 'brain-config.yml'` e depois a pasta `inbox` com o mesmo `parentId`;
>    - sugestões: documentar esse passo no `references/connectors.md`, ou guardar o ID da pasta inbox do Drive na config local;
>    - no terceiro feedback, a sugestão é guardar os IDs da pasta do vault e da inbox **por provedor**.
> 4. **Horário das capturas:**
>    - numa sessão na nuvem, a captura sai em UTC quando ninguém ajusta o fuso;
>    - o campo `created` vem sem o fuso;
>    - a ideia é gravar a data com o fuso e usar o fuso configurado do usuário;
>    - sugestão do terceiro feedback: um campo `timezone` no `brain-config.yml` e o `created` em ISO 8601 com o fuso.
> 5. **Sessão sem a pasta do vault:**
>    - sem a pasta conectada, nenhum fluxo completo de escrita funciona;
>    - o modo só conector resolve a captura, mas não dá para rodar `index`, `relate` nem processar a inbox;
>    - a skill deveria orientar a pedir só a pasta do vault;
>    - no terceiro feedback, pedir acesso a toda a pasta de nuvem do usuário e à config local foi negado, e só funcionou depois de conectar a pasta do vault;
>    - o SKILL.md deve explicar como conectar a pasta do vault ("Add folder") e deixar claro que, na nuvem, o `init --join` roda na máquina virtual da sessão, sem a config local do computador do usuário.
> 6. **Config ilegível pelo conector do Drive:**
>    - o `brain-config.yml` vem com o tipo `application/octet-stream`, e o `read_file_content` recusa esse tipo;
>    - sem ler a config, o `capture --print` não confere o `layout.inbox` nem se o contexto existe;
>    - sugestões: no `references/connectors.md`, orientar a ler o `.yml` com o `download_file_content`; ou manter uma cópia do layout e dos contextos num arquivo `.md` que o conector lê.
> 7. **Nome antigo na conta:**
>    - a sessão na nuvem do segundo feedback ainda carregou a skill com o nome `second-brain`, não a `photon-brain`;
>    - conferir se a conta tem uma versão antiga da skill ou o plugin antigo instalado, e se a SPEC-0067 cobre esse caso.
>
> 8. **Cópia da skill no vault sem os `assets/`:**
>    - uma cópia do `brain.py` guardada dentro do vault, para uso na nuvem, falhou porque procura `assets/brain-config.yml`;
>    - o remendo foi copiar `scripts` e `assets` juntos;
>    - a correção é o `brain.py` não depender de `assets/` quando o vault já tem `brain-config.yml`, ou um comando oficial que copia a skill inteira para o vault.
> 9. **Segredo na inbox sem alerta:**
>    - uma captura antiga da inbox tem senhas em texto, e o `lint --only secret-in-note` não acusou nada;
>    - aparentemente o `lint` não olha a `inbox/`;
>    - o `lint` e o `inbox list` devem olhar a inbox e avisar quando um item parece ter senha ou token, sem mostrar o valor.
> 10. **Acrescentar a uma nota que já existe:**
>    - para completar notas já existentes, as seções foram inseridas antes de `## Relations` com um script à mão, fora do `log.md`;
>    - sugestão: `append NOTA --section "Título" --text-file ARQ`, que insere antes de `## Relations` e registra no log.
> 11. **Corpo da nota criada pelo `new-note`:**
>    - o `new-note` cria só o esqueleto, e o corpo também foi escrito à mão, fora do log;
>    - sugestão: aceitar `--body-file ARQ` no `new-note`.
>
> Antes de detalhar, conferir as specs entregues de captura e inbox (SPEC-0021) e de configuração (SPEC-0017), para não repetir o que já existe.

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0093`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

## 1. Visão
{{Resultado de negócio e técnico esperado ao final do épico.}}

## 2. Escopo
**Objetivos (dentro do escopo):**
- {{O que o épico entrega}}

**Não-objetivos (fora do escopo):**
- {{O que fica explicitamente de fora}}

## 3. Arquitetura Alvo
**Contexto:** {{Projeto existente: arquitetura atual (ADRs as-is) e o que muda — se muda, type: migration | Projeto novo: stack e arquitetura definidas nos ADRs de fundação}}

{{Como o sistema fica ao final: módulos, fronteiras, fluxos principais, contratos entre as filhas. Diagrama se ajudar.}}

**Decisões (ADRs):** {{ADR-NNNN — decisão. Toda decisão transversal vira ADR (liste também no frontmatter `adrs`) | N/A}}

**Regras de arquitetura a garantir (G3):** {{ex: Domain não referencia Infrastructure; módulos só se comunicam por contratos públicos — cada regra com o teste de arquitetura que a garante}}

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| {{SPEC-NNNN}} | {{título}} | {{full}} | {{feature}} | {{M}} | {{—}} | {{—}} |

## 5. Estratégia de Entrega
- **Ambientes:** {{ex: staging automático a cada merge; produção via pipeline com aprovação}}
- **Entrega por onda:** {{o que vai para produção ao fim de cada onda e o que fica atrás de feature flag}}
- **Feature flags:** {{nome — o que controla — critério para ligar e para remover | N/A}}
- **Rollback:** {{como reverter cada onda}}
- **Métricas de sucesso pós-release:** {{o que observar e por quanto tempo}}

## 6. Riscos & Mitigações
- {{risco — mitigação | N/A}}

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] {{critério verificável — SPEC-NNNN:E2E-01}}

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0093` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
