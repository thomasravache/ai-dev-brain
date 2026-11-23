---
id: SPEC-0030
title: "boson-atlas: probes — consultas ao vivo na infraestrutura"
tier: epic
type: feature
status: proposed
created: 2026-10-30
depends_on: [SPEC-0029]
adrs: [ADR-0010, ADR-0011, ADR-0023]
external: []
approved_by:
approved_at:
---

# SPEC-0030 — boson-atlas: probes — consultas ao vivo na infraestrutura (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0030`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

> Rascunho de radar (2026-10-30), pós-MVP da SPEC-0029. Detalhado em 2026-11-22 junto com o épico SPEC-0075, que usa as probes para a verificação depois do deploy (decisão de thomas em 2026-11-22). A skill `org-atlas` hoje se chama `boson-atlas`.

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
- Comando `atlas.py probe` na própria `boson-atlas` (mesmo atlas e mesmo mapa; a configuração `probes` fica na camada local da máquina, junto das credenciais por nome), **desligado por padrão** (`probes.enabled: false`).
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

**Decisões (ADRs):** ADR-0023 — probes só de leitura por adaptador (contrato `probe@1`), com:
- verbos permitidos (interseção entre o que o adaptador declara e o que a máquina libera);
- produção, ou ambiente sem marcação, só com `--confirm-production` depois do "sim" da pessoa;
- redaction e limites na saída;
- registro local sem resultados;
- configuração `probes` na camada local da máquina, desligada por padrão.

A marcação dos ambientes e o acesso por cluster vêm da SPEC-0087 (filha da SPEC-0075).

**Regras de arquitetura a garantir (G3):**
- **Verbo fora da lista recusado** antes de executar (SPEC-0088 UT-02).
- **Produção sem confirmação recusada** (SPEC-0088 UT-03).
- **Nenhum resultado gravado no atlas** (SPEC-0088 UT-05).
- **Adaptador de runtime limitado:** só `get` e `logs` em recursos permitidos, sem `Secret` (SPEC-0089 UT-05).

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0088 | boson-atlas: núcleo do probe — contrato de adaptador, verbos permitidos, ambientes e registro local | full | feature | M | — | SPEC-0087@1 |
| SPEC-0089 | boson-atlas: adaptador de probe de runtime (Kubernetes: estado, eventos e logs) | full | feature | M | SPEC-0088 | — |
| depois | Adaptador de referência de dados (SQL só leitura, agregado, com `LIMIT` e `statement_timeout`) | full | feature | M | SPEC-0088 | — |
| depois | Adaptadores de nuvem (listar e descrever, nunca ler valor de segredo) e de observabilidade (logs externos, métricas) | full | feature | M | SPEC-0088 | — |
| depois | Política no servidor (tool MCP de probe) | full | feature | M | SPEC-0088 | — |

## 5. Estratégia de Entrega
- **Ambientes:** N/A, sem deploy.
- **Entrega por onda:** núcleo primeiro; depois uma categoria por onda.
- **Feature flags:** `probes.enabled` e os verbos liberados por adaptador, na configuração local da máquina.
- **Rollback:** desligar `probes.enabled`.
- **Métricas de sucesso pós-release:** uma investigação real resolvida com probes, sem nenhum dado sensível na conversa.

## 6. Riscos & Mitigações
- Probe com efeito colateral — credencial só de leitura é a barreira principal; lista de verbos e recusa no `atlas.py` reforçam.
- Dado sensível na conversa — consulta agregada por padrão, redaction e colunas `pii` do atlas.
- Consulta pesada derrubando produção — réplica/staging por padrão, `statement_timeout`, `LIMIT` e confirmação em produção.
- Agente contornando a política local — política no servidor MCP (SPEC-0031).

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] Um verbo fora da lista permitida é recusado antes de executar — SPEC-0088:UT-02
- [ ] Probe em produção (ou em ambiente sem marcação) sem confirmação não roda — SPEC-0088:UT-03
- [ ] Token, e-mail e os padrões de redaction saem mascarados — SPEC-0088:UT-04
- [ ] Nenhum resultado de probe é gravado no atlas, e o registro local não guarda resultado — SPEC-0088:UT-05
- [ ] O adaptador de runtime só chama `get` e `logs` em recursos permitidos — SPEC-0089:UT-05

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
- [x] Probe é outra skill? — Não: comando da `org-atlas`, porque depende do mapa e da configuração dela; com ADR próprio e desligado por padrão (thomas, 2026-10-30)
- [x] Nome da capacidade? — **Muon** (múons "radiografaram" a Grande Pirâmide sem mover uma pedra: ver por dentro sem alterar); o comando continua `probe`; se um dia virar skill, `muon-probe`; nomes finais na SPEC-0031 (thomas, 2026-10-30)
- [x] Produção pode ser alvo de probe, mesmo com confirmação, ou só réplica e staging? — Sim, só com confirmação humana a cada consulta; o padrão continua réplica ou staging e tudo vem desligado (thomas, 2026-11-16)
- [x] Onde fica o registro de probes: só local ou também no atlas (sem resultados)? — Só local, na máquina de quem consulta; o atlas é compartilhado e versionado e não recebe o registro (thomas, 2026-11-16)
- [x] A verificação depois do deploy (SPEC-0075) usa as probes? — Sim. O núcleo (SPEC-0088) e o adaptador de runtime (SPEC-0089) entram primeiro, antes do `verify` (SPEC-0090). O adaptador de dados por SQL vem numa onda seguinte (thomas, 2026-11-22).
- [x] Quais categorias entram primeiro? — Um contrato de adaptador agnóstico (no modelo do `collector@1`) e dois adaptadores de referência: dados por SQL só leitura e runtime por Kubernetes; nuvem e observabilidade entram depois, como adaptadores. A skill segue agnóstica de provedor (thomas, 2026-11-16)

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
