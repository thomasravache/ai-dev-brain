---
id: SPEC-0029
title: "org-atlas: mapa da organização para agentes"
tier: epic
type: feature
status: proposed
created: 2026-10-30
depends_on: []
adrs: [ADR-0010]
external: []
approved_by:
approved_at:
---

# SPEC-0029 — org-atlas: mapa da organização para agentes (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0029`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

> Rascunho de radar (2026-10-30): registra o desenho conversado com o thomas. As filhas são criadas depois que as Questões em Aberto forem respondidas.

## 1. Visão
Uma terceira skill no `ai-dev-brain`, a `org-atlas`, que **varre como uma organização desenvolve e opera software** e gera um atlas versionado para os agentes usarem. A skill não é de uma empresa: funciona em qualquer organização e aprende os padrões dela. O atlas cobre vários repositórios, a infraestrutura, os dados, o processo e as convenções, e principalmente **como as peças se ligam** (o serviço A grava no banco B e publica na fila C, que o serviço D consome).

A divisão com a `sdd-management`:

| | `org-atlas` | `sdd-management` |
|---|---|---|
| Escopo | a organização: N repos, infra, processo | um repositório |
| Relação com o mundo | só lê e descreve como as coisas são | muda o código seguindo um processo |
| Saída | atlas versionado | specs, ADRs, PRs |

Ao final do MVP, o fluxo é:
- **init:** onboarding pergunta onde está cada categoria e sugere coletores.
- **scan:** roda os coletores declarados, grava snapshots normalizados e mostra o diff ("serviço novo", "fila sem consumidor").
- **curate:** o agente infere convenções (ex.: a partir do histórico de PRs) como `inferred`; o humano confirma e elas viram `confirmed`. Só convenção `confirmed` vira regra para outras skills.
- **context QUERY:** pacote para uma tarefa ("feature de cashout no backoffice" → serviços, bancos, filas e convenções envolvidos), com aviso de envelhecimento.
- **lint / doctor:** fatos velhos, referências quebradas, segredo vazado, convenção sem confirmação, configuração.

## 2. Escopo
**Objetivos (dentro do escopo):**
- Skill nova em `skills/org-atlas/` no padrão da `sdd-management` e da `second-brain`: `SKILL.md` com fluxos e regras, `references/` sob demanda e um script único `scripts/atlas.py` só com a biblioteca padrão do Python 3.9+ (ADR-0010).
- **Agnóstica:** a skill conhece **categorias**, não ferramentas — código, CI, entrega/GitOps, runtime, dados, mensageria, observabilidade, tracker, documentação, segredos. Cada organização declara **coletores** no `atlas-config.yml`: comandos que imprimem JSON num formato neutro. `references/collectors/<provedor>.md` traz exemplos por provedor, sempre com um `generic`.
- **Modelo neutro do atlas:** `ATLAS.md` (índice curto), `graph.json` (sistemas ↔ serviços ↔ datastores ↔ filas ↔ ambientes), `services/<id>.md`, `platform/<categoria>.md`, `conventions/*.md`, `process/*.md`, `glossary.md` e `snapshots/`. Cada fato com `source`, `seen_at` e `confidence: inferred | confirmed`. O texto gerado fica em regiões `<!-- atlas:begin <nome> -->` / `<!-- atlas:end <nome> -->`; o texto escrito por pessoas nunca é reescrito.
- **Cruzamento de fontes:** env vars e manifests de entrega + código + infra montam o grafo de dependências entre aplicações.
- **Configuração em duas camadas** (como o ADR-0008 da `second-brain`): local por máquina (`~/.config/org-atlas/`: nomes de profile e de variável de ambiente, nunca valores) e compartilhada no atlas (categorias e coletores, sem segredo).
- **Credenciais:** os coletores usam credenciais só de leitura da própria máquina ou da CI; o atlas guarda só metadados (schema, recursos, nomes), nunca dados nem valores de segredo; o `atlas.py` mascara o que parecer segredo antes de gravar e o `lint` acusa vazamento como erro.
- **Onde fica o atlas:** modo repositório (preferido — repo git próprio da organização, revisão por PR, CI agendada rodando `scan` e abrindo PR com o diff) e modo local (pasta da máquina com `git init` sem remote, mesmo formato; migrar para repo = adicionar um remote).
- **Envelhecimento:** `seen_at` em todo fato, `stale_days` na configuração, aviso no `context` a cada uso, `lint` acusando fato velho e `vendor --ci` instalando o scan agendado no modo repositório.
- **MVP de coletores:** categorias **código** (GitHub) e **entrega** (Argo CD), cada uma com o coletor `generic`, que já dão o grafo de dependências quase sem credencial sensível.
- **Integração com a `sdd-management`** por arquivo e CLI, sem import: chave opcional `org_context` no `sdd-config.yml`; com ela, o DISCOVER roda `atlas.py context` automaticamente. Sem ela, nada muda.

**Não-objetivos (fora do escopo):**
- Consultas ao vivo em dados, nuvem, cluster e logs (probes) — SPEC-0030.
- Plugin, servidor MCP, proteção de IP, marca e auto-melhoria — SPEC-0031.
- Guardar dados de negócio, valores de segredo ou código-fonte da organização no atlas.
- Qualquer escrita na infraestrutura da organização.
- Coletores de nuvem, runtime, dados, mensageria, observabilidade, tracker e documentação — fase 2 deste épico (seção 4), depois do MVP.
- Relação com a Malha: fora de questão por ora (thomas, 2026-10-30).

## 3. Arquitetura Alvo
**Contexto:** projeto existente (brownfield). Referências: a `second-brain` (SPEC-0016, ADR-0007/0008/0009) para script único, configuração em duas camadas, processos externos declarados e regiões geradas; a `sdd-management` (ADR-0001) para `vendor` e CI. Testes `unittest` (ADR-0002), Ruff (ADR-0003), mudança por PR (ADR-0005).

Desenho:
- `skills/org-atlas/SKILL.md`: fluxos (`init`, `scan`, `curate`, `context`, `lint`) e regras do agente: nunca pedir nem ler valor de credencial, só convenção `confirmed` vira regra, nunca reescrever texto humano.
- `skills/org-atlas/scripts/atlas.py`: comandos determinísticos. Executa só os coletores declarados (sem shell), normaliza a saída no contrato neutro, cruza as fontes, gera páginas e grafo, calcula diff e envelhecimento, faz redaction e lint.
- `skills/org-atlas/references/`: modelo neutro, contrato dos coletores, categorias, guias `collectors/<provedor>.md`, modos repositório e local, curadoria.
- `skills/org-atlas/assets/`: modelo do `atlas-config.yml` e workflow de scan agendado.

**Decisões (ADRs):**
- ADR-0010 — fronteiras da skill: script único stdlib, sem import entre skills, só coletores declarados, sem rede própria, só metadados, redaction, regiões geradas.
- A criar antes do H1: modelo neutro e contrato dos coletores (formato e versão do JSON); política de curadoria (`inferred` → `confirmed`).

**Regras de arquitetura a garantir (G3):** as do ADR-0010, em `skills/org-atlas/tests/test_architecture.py` (criado pela primeira filha).

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
Planejada (as filhas ganham ID com `new --parent SPEC-0029` depois das respostas da seção 8):

| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| a criar | Esqueleto: `atlas.py`, configuração em duas camadas, `init`, `doctor`, testes de arquitetura e CI | full | feature | M | — | — |
| a criar | Modelo neutro, contrato dos coletores, `scan` com snapshots e diff | full | feature | M | esqueleto | — |
| a criar | Coletores de código (GitHub e `generic`): repos, stack, CI, histórico de PRs | full | feature | M | — | contrato dos coletores |
| a criar | Coletores de entrega (Argo CD e `generic`): apps, ambientes, configuração | full | feature | M | — | contrato dos coletores |
| a criar | Cruzamento de fontes: `graph.json`, `services/`, `platform/` | full | feature | M | scan | — |
| a criar | Curadoria: `curate`, `inferred` → `confirmed` | full | feature | S | cruzamento | — |
| a criar | `context QUERY` com aviso de envelhecimento | full | feature | S | cruzamento | — |
| a criar | `lint`: fato velho, referência quebrada, segredo vazado, convenção sem confirmação | full | feature | S | cruzamento | — |
| a criar | Modo repositório (`vendor --ci` com scan agendado abrindo PR) e modo local | full | feature | S | scan | — |
| a criar | `sdd-management`: chave `org_context` e DISCOVER usando `atlas.py context` | lite | feature | S | context | — |

**Fase 2 (pós-MVP, mesmo épico ou épico novo):** coletores de nuvem (ex.: AWS, GCP, Azure — inventário só de metadados), runtime (ex.: Kubernetes), dados (schemas: ex.: PostgreSQL, MySQL, MongoDB, com dono por tabela e colunas sensíveis marcadas para a SPEC-0030), mensageria, observabilidade, tracker e documentação (ex.: Jira, Linear, Confluence, ADRs e runbooks).

## 5. Estratégia de Entrega
- **Ambientes:** N/A, sem deploy. Distribuída por cópia da pasta da skill (README); o plugin vem na SPEC-0031.
- **Entrega por onda:** cada onda deixa a skill utilizável: esqueleto → scan de código e entrega → grafo e context → curadoria e lint → integração com a sdd.
- **Feature flags:** N/A. Categorias e coletores ligam pela configuração.
- **Rollback:** voltar para a versão anterior da pasta da skill; o atlas é versionado por git.
- **Métricas de sucesso pós-release:** um atlas real de uma organização com ≥ 5 repositórios, grafo conferido por quem conhece o sistema, e uma feature entregue pela `sdd-management` usando o `context`.

## 6. Riscos & Mitigações
- Vazamento de segredo ou dado sensível no atlas — só metadados por regra, redaction no `atlas.py`, `lint` com erro, credenciais só de leitura e fora do atlas.
- Convenção ruim registrada como padrão — curadoria: inferido é dica; regra só depois de `confirmed` pelo humano.
- Atlas desatualizado levando o agente a errar — `seen_at`, `stale_days`, aviso no `context` e scan agendado no modo repositório.
- Acoplamento a um provedor — categorias e contrato neutro; provedor só em `references/collectors/` e na configuração.
- Atlas grande demais para o contexto do agente — índice curto e `context` montando pacote por tarefa; MCP tipado no radar (SPEC-0031).

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
Os IDs dos testes entram quando as filhas forem criadas.
- [ ] Uma organização com coletores de código e entrega declarados gera o atlas e o grafo de dependências entre aplicações — teste a definir
- [ ] Um segundo scan mostra só o que mudou — teste a definir
- [ ] Nenhum valor de segredo chega ao atlas, e um segredo plantado num coletor é mascarado e acusado pelo `lint` — teste a definir
- [ ] O `context` de uma tarefa traz os serviços, dados e convenções certos e avisa quando o atlas está velho — teste a definir
- [ ] Convenção inferida só vira regra depois de confirmada — teste a definir
- [ ] Com `org_context`, o DISCOVER da `sdd-management` usa o atlas; sem a chave, nada muda — teste a definir

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
- [x] Skill separada ou feature da `sdd-management`? — Skill separada, ligada por arquivo e CLI (thomas, 2026-10-30)
- [x] Agnóstica de organização e provedor? — Sim; GitHub, Argo CD, AWS e PostgreSQL foram só exemplos (thomas, 2026-10-30)
- [x] Onde fica o atlas? — Repositório próprio da organização como preferido, com modo local também suportado (thomas, 2026-10-30)
- [x] Nome de trabalho? — `org-atlas`; o nome futuro é `boson-atlas`, na marca Hadron (`hadron-lab`, SPEC-0031); renomear fica para depois (thomas, 2026-10-30)
- [x] Quais provedores o MVP entrega em código e em entrega, além do `generic`? — GitHub (código) e Argo CD (entrega); GitLab e Flux entram depois como guias em `references/collectors/` (thomas, 2026-10-30)
- [x] Idioma da estrutura do atlas (pastas, chaves)? — Inglês, como a `second-brain`; o conteúdo fica no idioma da organização (thomas, 2026-10-30)
- [x] Valor padrão de `stale_days`? — 14 dias: com o scan semanal, perder dois scans seguidos já gera aviso (thomas, 2026-10-30)
- [x] Quem pode confirmar uma convenção? — No modo repositório, quem aprova o PR do atlas que muda a convenção para `confirmed`; no modo local, quem roda o `curate` (thomas, 2026-10-30)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0029` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
