---
id: SPEC-0030
title: "org-atlas: probes — consultas ao vivo na infraestrutura"
tier: epic
type: feature
status: proposed
created: 2026-10-30
depends_on: [SPEC-0029]
adrs: []
external: []
approved_by:
approved_at:
---

# SPEC-0030 — org-atlas: probes — consultas ao vivo na infraestrutura (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0030`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

> Rascunho de radar (2026-10-30), pós-MVP da SPEC-0029. Registra o desenho conversado com o thomas.

## 1. Visão
Deixar o agente **consultar a infraestrutura real** para obter o que o código sozinho não mostra, sempre só lendo: "existe wallet duplicada?", "o secret `x/db-url` existe em staging?", "por que o pod está em CrashLoop?", "quais erros o serviço X deu na última hora?". Serve a quem implementa (decisão com evidência, não achismo) e a quem investiga incidente.

O atlas (SPEC-0029) é o que torna isso útil: ele sabe que o serviço X é o deployment Y no namespace Z do cluster W, qual banco é dele e quais colunas são sensíveis, então o agente não adivinha onde procurar.

**Atlas × probe:**

| | Atlas (scan) | Probe (consulta pontual) |
|---|---|---|
| O que lê | metadados: schema, recursos | dados, estado e logs |
| Quando | scan agendado | na hora, durante uma tarefa |
| Fica guardado? | sim, versionado | nunca no atlas: a resposta vai só para a conversa |

## 2. Escopo
**Objetivos (dentro do escopo):**
- Comando `atlas.py probe` na própria `org-atlas` (mesmo atlas, mesma configuração de credenciais e categorias), **desligado por padrão** (`probes.enabled: false`).
- Capacidade por categoria, cada uma declarando o que pode e o que nunca pode:

| Categoria | Exemplo | Pode | Nunca |
|---|---|---|---|
| Dados | "existe wallet duplicada?" | `SELECT` agregado (`EXISTS`, `COUNT`, `GROUP BY`) com `LIMIT` | escrita, dump |
| Nuvem | "o secret existe em staging?" | listar e descrever recursos (ex.: `list-secrets`, `describe-*`) | ler valor de segredo (ex.: `get-secret-value`) |
| Runtime | "por que o pod está em CrashLoop?" | `get`, `describe`, `logs --tail`, `events` | `exec`, `delete`, ler `Secret` |
| Observabilidade | "erros do serviço X na última hora" | consulta com janela de tempo | exportar tudo |

- **Proteções em camadas** (a da credencial é a que vale; as outras reforçam):
  - Credencial: usuário de banco só leitura com `READ ONLY` e `statement_timeout`; RBAC de leitura sem acesso a `Secret` (ex.: ClusterRole `view`); política de nuvem só de visualização com *deny* explícito na leitura de valor de segredo. `references/` traz as políticas de exemplo por provedor.
  - Ambiente declarado por datastore e cluster: padrão réplica ou staging; produção exige confirmação humana a cada probe.
  - Saída limitada (linhas, janela de tempo, `LIMIT`) e com redaction (token, CPF, e-mail e as colunas `pii` marcadas no atlas).
  - Registro local de cada probe (quem, quando, alvo, consulta), sem os resultados.
- Verbos permitidos por categoria declarados na configuração; o `atlas.py` recusa o que não estiver na lista.

**Não-objetivos (fora do escopo):**
- Qualquer ação que mude a infraestrutura (restart, scale, rollback, escrita em banco).
- Guardar resultado de probe no atlas.
- Política aplicada no servidor (fora do alcance do agente): vem com o servidor MCP da SPEC-0031.

## 3. Arquitetura Alvo
**Contexto:** extensão da `org-atlas` (SPEC-0029), mesmas fronteiras do ADR-0010; probe é processo externo declarado, como os coletores.

**Decisões (ADRs):** a criar antes do H1 — política de probes (o que é leitura por categoria, ambientes, confirmação em produção, redaction, registro).

**Regras de arquitetura a garantir (G3):** probe só executa verbos da lista permitida; nenhum resultado de probe é escrito no atlas — testes a definir.

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| a criar | Núcleo do `probe`: configuração, lista de verbos, ambientes, confirmação em produção, redaction e registro | full | feature | M | SPEC-0029 | — |
| a criar | Probes de dados | full | feature | M | núcleo | — |
| a criar | Probes de nuvem | full | feature | M | núcleo | — |
| a criar | Probes de runtime (cluster e logs) | full | feature | M | núcleo | — |
| a criar | Probes de observabilidade | full | feature | S | núcleo | — |

## 5. Estratégia de Entrega
- **Ambientes:** N/A, sem deploy.
- **Entrega por onda:** núcleo primeiro; depois uma categoria por onda.
- **Feature flags:** `probes.enabled` e uma chave por categoria na configuração.
- **Rollback:** desligar `probes.enabled`.
- **Métricas de sucesso pós-release:** uma investigação real resolvida com probes, sem nenhum dado sensível na conversa.

## 6. Riscos & Mitigações
- Probe com efeito colateral — credencial só de leitura é a barreira principal; lista de verbos e recusa no `atlas.py` reforçam.
- Dado sensível na conversa — consulta agregada por padrão, redaction e colunas `pii` do atlas.
- Consulta pesada derrubando produção — réplica/staging por padrão, `statement_timeout`, `LIMIT` e confirmação em produção.
- Agente contornando a política local — política no servidor MCP (SPEC-0031).

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] Um verbo fora da lista permitida é recusado antes de executar — teste a definir
- [ ] Probe em produção sem confirmação não roda — teste a definir
- [ ] Token, CPF e colunas `pii` saem mascarados — teste a definir
- [ ] Nenhum resultado de probe é gravado no atlas — teste a definir

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
- [x] Probe é outra skill? — Não: comando da `org-atlas`, porque depende do mapa e da configuração dela; com ADR próprio e desligado por padrão (thomas, 2026-10-30)
- [x] Nome da capacidade? — **Muon** (múons "radiografaram" a Grande Pirâmide sem mover uma pedra: ver por dentro sem alterar); o comando continua `probe`; se um dia virar skill, `muon-probe`; nomes finais na SPEC-0031 (thomas, 2026-10-30)
- [ ] Produção pode ser alvo de probe, mesmo com confirmação, ou só réplica e staging? (thomas)
- [ ] Onde fica o registro de probes: só local ou também no atlas (sem resultados)? (thomas)
- [ ] Quais categorias entram primeiro? (thomas)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0030` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
