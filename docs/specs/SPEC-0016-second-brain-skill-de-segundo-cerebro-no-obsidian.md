---
id: SPEC-0016
title: "Second brain: skill de segundo cérebro no Obsidian"
tier: epic
type: feature
status: implemented
created: 2026-10-30
depends_on: []
adrs: [ADR-0007, ADR-0008, ADR-0009]
external: []
approved_by: thomas
approved_at: 2026-10-30
---

# SPEC-0016 — Second brain: skill de segundo cérebro no Obsidian (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0016`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

## 1. Visão
Uma segunda skill no `ai-dev-brain`, ao lado da `sdd-management`, que transforma um vault do Obsidian guardado na nuvem num segundo cérebro mantido por uma LLM. O usuário pede em linguagem natural: "guarda isso", "sintetiza esse vídeo/PDF", "o que eu sei sobre X", "me prepara para a prova de Y". A skill segue sempre o mesmo fluxo para guardar e para consultar. Antes de escrever, procura notas relacionadas. Liga a nota nova ao que já existe, explicando por que liga, e mantém os índices e o log. Funciona igual em qualquer máquina e em qualquer agente que leia `SKILL.md`, e o celular entra como ponto de captura.

Ao final, existe um fluxo concreto e repetível:
- **Guardar:** classificar → guardar o bruto → buscar relações → escrever a nota sintetizada → atualizar índices e log → reportar.
- **Consultar:** buscar → ler e seguir links → responder citando as notas → oferecer salvar a resposta.
- **Manter:** links quebrados, órfãs, inbox parada, conflitos de sincronização.

## 2. Escopo
**Objetivos (dentro do escopo):**
- Skill nova em `skills/second-brain/` no padrão da `sdd-management`: `SKILL.md` com o fluxo e as regras, detalhe em `references/`, e um script único só com a biblioteca padrão para a parte determinística (caminhos, busca, índices, log, lint, modelos).
- Estrutura do vault, pastas, nomes de arquivo e chaves de frontmatter **em inglês**; o conteúdo das notas no idioma em que o usuário escrever.
- Agnóstica para qualquer pessoa. Sem configuração, um onboarding pergunta provedor, vault novo ou existente, contextos e processadores (conferindo se cada comando roda) e grava a configuração. Com configuração, a skill usa o que está configurado sem perguntar de novo; numa máquina nova, só pergunta onde o vault está. Um comando `doctor` mostra o que está configurado, o que funciona e o que falta.
- Configuração em duas camadas: uma compartilhada dentro do vault (estrutura, contextos PARA, modelos, regras de link, processadores) e uma local por máquina (só onde o vault e a pasta de arquivos ficam naquela máquina).
- Armazenamento na nuvem, com o provedor escolhido no onboarding: Google Drive, OneDrive, iCloud ou pasta local; celular iOS e Android. Arquivos pesados (vídeos, PDFs) ficam numa pasta de arquivos fora do vault e são ligados pela nota.
- Captura pelo celular por uma `inbox/` na nuvem (compartilhar do celular ou nota rápida pelo Obsidian mobile), processada sob pedido por qualquer máquina com a skill ("processa minha inbox").
- Processadores por tipo de arquivo declarados na configuração, todos opcionais: yt-dlp (YouTube), Whisper (vídeo e áudio locais) e pdftotext (PDF). Sem processador, a skill usa a própria LLM ou guarda só o bruto.
- Exportação opcional para o NotebookLM: pacote com as notas de um MOC.
- Exemplo de uso guiado para a faculdade: contexto por disciplina, MOC por disciplina, notas de aula e preparação para prova.

**Não-objetivos (fora do escopo):**
- Plugin do Obsidian ou app próprio: a skill opera sobre os arquivos Markdown do vault.
- Guardar conteúdo do vault, credenciais ou caminhos pessoais neste repositório.
- Substituir a sincronização do provedor de nuvem: a skill usa a sincronização que já existe.
- Processar a inbox por tarefa agendada na nuvem (acesso ao provedor por API): spec futura.
- Integração com o NotebookLM além da exportação de arquivos (API, automação do navegador).

## 3. Arquitetura Alvo
**Contexto:** projeto existente (brownfield). A referência é a `sdd-management`, seguindo as regras do ADR-0001: `SKILL.md` com fluxo e mandatos, `references/` sob demanda, script único só com a biblioteca padrão do Python 3.9+, e processos externos só quando declarados em configuração. Testes em `unittest` (ADR-0002), Ruff (ADR-0003) e mudanças por PR (ADR-0005). A CI hoje roda só a suíte da `sdd-management` e precisa passar a rodar a suíte da skill nova.

Desenho:
- `skills/second-brain/SKILL.md`: os três fluxos (guardar, consultar, manter) e as regras do agente: buscar antes de escrever, nunca sobrescrever texto do usuário, sempre linkar explicando a relação, registrar no log.
- `skills/second-brain/scripts/brain.py`: comandos determinísticos (`init`, `config`, `context add`, `doctor`, `search`, `related`, `links`, `ingest`, `new-note`, `relate`, `index`, `context`, `capture`, `inbox`, `process`, `lint`, `export-notebooklm`). A busca é por varredura em memória, sem índice persistente (SPEC-0018).
- `skills/second-brain/references/`: modelos de nota por tipo, guia de configuração por provedor de nuvem e guia dos processadores.
- Configuração compartilhada em `<vault>/brain-config.yml`; configuração local por máquina fora do repositório e fora do vault.

**Decisões (ADRs):**
- ADR-0007 — fronteiras da skill: arquivo único só com a biblioteca padrão, sem import entre skills, só cria e acrescenta no vault, processos só pelos processadores.
- ADR-0008 — armazenamento: pasta sincronizada pelo app do provedor; configuração compartilhada no vault e local por máquina; arquivos pesados fora do vault.
- ADR-0009 — processadores: comandos declarados no `brain-config.yml`, sem shell, opcionais.

**Regras de arquitetura a garantir (G3):** as do ADR-0007, verificadas por `skills/second-brain/tests/test_architecture.py` (SPEC-0017:UT-06 e SPEC-0022:UT-04): só biblioteca padrão, arquivo único, nenhum import entre skills, processo externo só em `run_processor`, nenhum caminho pessoal em `skills/second-brain/`.

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0017 | Esqueleto, configuração em duas camadas, onboarding (`init`), `doctor` e CI | full | feature | M | — | — |
| SPEC-0018 | Busca e relações entre notas (`search`, `related`, `links`) | full | feature | M | SPEC-0017 | — |
| SPEC-0019 | Fluxo de guardar (`ingest`, `new-note`, `relate`, `index`, log) | full | feature | M | SPEC-0018 | — |
| SPEC-0020 | Fluxo de consultar (`context`, tipo `answer`) | full | feature | S | SPEC-0019 | — |
| SPEC-0021 | Inbox e captura pelo celular (`capture`, `inbox`, `ingest --move`) | full | feature | S | SPEC-0019 | — |
| SPEC-0022 | Processadores de vídeo e documento (`process`, `ingest` automático) | full | feature | M | SPEC-0021 | — |
| SPEC-0023 | Manutenção do vault (`lint`) | full | feature | S | SPEC-0021 | — |
| SPEC-0024 | Exportação para o NotebookLM | lite | feature | S | SPEC-0020 | — |

Todas as filhas mexem no `brain.py` (arquivo único, ADR-0007), então rodam uma de cada vez. A ordem respeita as dependências: cada onda entrega a skill utilizável até aquele ponto.

## 5. Estratégia de Entrega
- **Ambientes:** N/A, sem deploy. A skill é distribuída copiando a pasta para o diretório de skills da ferramenta (como no README).
- **Entrega por onda:** cada onda termina com a skill utilizável até aquele ponto: primeiro guardar, depois consultar, depois inbox e processadores.
- **Feature flags:** N/A. Capacidades opcionais (processadores, exportação) ligam pela configuração.
- **Rollback:** voltar para a versão anterior da pasta da skill. A skill nunca apaga nem sobrescreve texto do usuário no vault.
- **Métricas de sucesso pós-release:** uso real por duas semanas, com o fluxo da faculdade (aulas guardadas, consultas respondidas com citação, `lint` sem pendências).

## 6. Riscos & Mitigações
- Conteúdo pessoal do vault vazar para o repositório — o vault e a configuração local ficam fora do repo, e um teste garante que nenhum caminho pessoal entra.
- Conflitos de sincronização entre dispositivos (cópias "conflict" do provedor) — o `lint` detecta e lista, sem resolver sozinho.
- Obsidian mobile sem acesso ao provedor escolhido (o iOS não abre vault no Google Drive) — o guia de cada provedor diz qual app mobile abre o vault (iOS: iCloud; Android: Drive/OneDrive com app de sincronização) e o onboarding avisa.
- LLM sobrescrever ou bagunçar notas do usuário — a regra "só cria e acrescenta" vale na skill e no script, e o log registra cada mudança.
- Dependências externas (yt-dlp, Whisper) quebrarem a regra de "só biblioteca padrão" — elas entram só como comandos opcionais declarados na configuração, nunca importados.

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [x] Guardar o material de uma aula gera uma nota sintetizada ligada às notas relacionadas, com o MOC, o `index.md` e o `log.md` atualizados — SPEC-0019:IT-07
- [x] Um vídeo ou PDF com processador configurado chega à nota de fonte com o texto extraído, e sem processador o bruto fica guardado — SPEC-0022:IT-01, SPEC-0022:IT-03
- [x] Uma consulta entrega ao agente as notas certas para responder citando o vault, e a resposta pode ser salva e ligada — SPEC-0020:IT-01, SPEC-0020:IT-03
- [x] Um item jogado na inbox numa máquina é processado por outra com o mesmo resultado do fluxo de guardar — SPEC-0021:IT-05
- [x] O mesmo vault funciona em duas máquinas com caminhos diferentes, mudando só a configuração local — SPEC-0017:IT-04
- [x] Sem configuração, o onboarding cria um vault novo ou adota um existente sem alterar nada do usuário — SPEC-0017:IT-01, SPEC-0017:IT-02

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
- [x] Idioma da estrutura — pastas, nomes de arquivo e frontmatter em inglês; conteúdo no idioma do usuário (thomas, 2026-10-30)
- [x] Agnóstico e configurável — sim, para LLM, armazenamento e processadores (thomas, 2026-10-30)
- [x] Uso em várias máquinas e no celular — sim (thomas, 2026-10-30)
- [x] Onde fica a fonte de verdade — na nuvem, com o Google Drive como preferência inicial; o provedor final depende do sistema do celular (thomas, 2026-10-30)
- [x] A skill é agnóstica para qualquer pessoa? — Sim. Sem configuração, ela conduz um onboarding e grava a configuração; com configuração, usa o que está configurado sem perguntar de novo. Sistema do celular, provedor e forma de captura viram escolhas de cada pessoa no onboarding, e a spec define quais opções a v1 suporta (thomas, 2026-10-30)
- [x] Quais provedores de armazenamento a v1 suporta? — Google Drive, OneDrive, iCloud e pasta local (que cobre qualquer outra sincronização), com celular iOS e Android (thomas, 2026-10-30)
- [x] O onboarding cria só vault novo ou também adota um existente? — Os dois: cria a estrutura padrão ou adota um vault existente, mapeando as pastas sem reorganizar (thomas, 2026-10-30)
- [x] Quais processadores a v1 traz prontos para configurar? — yt-dlp (YouTube), Whisper (vídeo e áudio locais) e pdftotext (PDF), todos opcionais e declarados na configuração (thomas, 2026-10-30)
- [x] Quais canais de captura pelo celular a v1 documenta? — Compartilhar para a `inbox/` do provedor e nota rápida pelo Obsidian mobile (thomas, 2026-10-30)
- [x] Como a inbox é processada na v1? — Só sob pedido ("processa minha inbox"), em qualquer máquina com a skill; tarefa agendada na nuvem fica para uma spec futura (thomas, 2026-10-30)
- [x] Papel do NotebookLM? — Só exportação opcional: um comando monta um pacote com as notas de um MOC para subir no NotebookLM (thomas, 2026-10-30)
- [x] Nome da skill? — `second-brain` (thomas, 2026-10-30)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0016` ajuda a montar. -->

**O que foi entregue.** A skill `second-brain` (`skills/second-brain/`, versão 2026.10.11) é um segundo cérebro num vault do Obsidian mantido por uma LLM.
- **Configurar:** onboarding agnóstico (`init`, `--adopt`, `--join`), com configuração em duas camadas e `doctor`.
- **Guardar:** `ingest`, `new-note`, `relate` e `index`, com processadores de vídeo e documento (yt-dlp, Whisper, pdftotext).
- **Consultar:** `context`, com resposta citando as notas e tipo `answer`.
- **Capturar pelo celular:** `capture`, `inbox` e `ingest --move`.
- **Manter:** `lint`.
- **Exportar:** `export-notebooklm`.

São três ADRs: ADR-0007 (fronteiras), ADR-0008 (armazenamento) e ADR-0009 (processadores).

**Como.** Foram 11 specs executadas uma por onda, cada uma com Test-writer, Implementer e Reviewer independentes:
- as filhas SPEC-0017 a SPEC-0024;
- as correções SPEC-0025 a SPEC-0027, que saíram das revisões.

As emendas aprovadas foram a v2 da SPEC-0017 e a v2 da SPEC-0023. Cada onda foi integrada na branch `sdd/SPEC-0016` e no PR #15, com CI verde (Python 3.9 e 3.15, mais o `pr-check`) e H2 pela política auto-on-green. Não há deploy: o pilar entrega é dispensado e a skill é distribuída por cópia da pasta. A suíte da skill tem 220 testes, e os de desempenho com 5.000 notas ficam abaixo das metas (0,1 a 0,8 s).

**Critérios de aceite.** Todos passaram, com os testes citados em cada critério, na CI do PR #15 no run 41110986589 (11849fb).

**Métricas pós-release.** A combinada na seção 5 é uso real por duas semanas com o fluxo da faculdade. Ela começa depois do merge do PR #15, acompanhada pelo `doctor` e pelo `lint`.

**Pendências.**
- SPEC-0028 (avulsa): padrões de cópia de conflito conferidos com cópias reais de cada provedor. Depende de o usuário gerar as cópias.
- Fora do épico: o `verify` da `sdd-management` trata como teste da spec uma citação a outra spec no texto do plano (visto nas SPEC-0022 e SPEC-0025). É candidato a uma correção lite da `sdd-management`.

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
