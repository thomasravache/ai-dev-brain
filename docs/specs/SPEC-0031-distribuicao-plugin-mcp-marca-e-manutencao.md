---
id: SPEC-0031
title: "Distribuição do ai-dev-brain: plugin, servidor MCP, marca e manutenção"
tier: epic
type: feature
status: proposed
created: 2026-10-30
depends_on: [SPEC-0029]
adrs: [ADR-0016, ADR-0017, ADR-0018]
external: []
approved_by:
approved_at:
---

# SPEC-0031 — Distribuição do ai-dev-brain: plugin, servidor MCP, marca e manutenção (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0031`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

> Radar de 2026-10-30, detalhado em 2026-11-12 para o caminho mínimo: plugin (SPEC-0053) e MCP do atlas (SPEC-0054). As outras frentes viram filhas quando forem priorizadas.

## 1. Visão
Hoje cada skill é instalada copiando a sua pasta, e o usuário chama uma de cada vez. Este épico junta as skills (`sdd-management`, `second-brain`, `org-atlas`) numa **distribuição única**, sem perder o que já funciona:
- **Uma instalação:** um plugin com todas as skills.
- **Uma entrada:** o usuário pede a tarefa e as skills se encadeiam (a `sdd-management` puxa o `org-atlas` sozinha quando ele existe), com hook de início de sessão e um comando de entrada única.
- **Sempre adaptável:** a pasta `skills/<nome>` continua instalável por cópia em qualquer agente que lê `SKILL.md`; plugin e MCP são embalagens a mais, nunca substituem.
- **Ferramentas tipadas por MCP**, que funcionam em vários agentes e permitem política aplicada fora do alcance do agente.
- **Marca própria**, **manutenção da própria skill** e, por último, **distribuição sem entregar o "como a gente faz"**.

## 2. Escopo
**Objetivos (dentro do escopo), em ordem de prioridade:**
1. **Plugin do Claude Code:** o repositório vira marketplace (`.claude-plugin/marketplace.json`) com **um plugin** que traz as três skills, porque elas se ligam entre si. Formato confirmado na documentação oficial na pesquisa da filha.
2. **Encadeamento e entrada única:** hook `SessionStart` que coloca no contexto o índice do atlas e o `status` do SDD quando existirem; comando de entrada única (ex.: `/deliver <tarefa>`) que dispara atlas → spec → aprovação → implementação → PR. É atalho: a lógica continua nas skills.
3. **Servidor MCP local:** um servidor só, stdio, com tools separadas por prefixo (`atlas_*`, `brain_*`, `sdd_*`); cada tool é camada fina sobre a CLI da skill, que continua a fonte da verdade (sem lógica duplicada, ADR-0001). Ordem: `atlas` primeiro (grafo tipado e, com a SPEC-0030, política de probes no servidor), `brain` depois (uso no desktop e no celular, sem shell), `sdd` por último (ganho marginal).
4. **Auto-melhoria (manutenção da própria skill):** `doctor` de cada skill avisa quando o ambiente sai do suporte (ex.: versão do Python sem suporte); uma skill ou agente mantenedor abre a spec de atualização. Subir a versão mínima do Python é spec `type: migration` com um ADR que substitui a regra de versão do ADR-0001/ADR-0007. A base já existe: `whats-new`, CHANGELOG e versão por skill.
5. **Marca:** nome do plugin (`fermion`, SPEC-0053) e das skills (SPEC-0055, antes do plugin). Renomear é migração: muda o nome visível e a descrição continua dizendo o que a skill faz (é ela que faz o agente acionar a skill); caminhos já instalados nos projetos (`tools/sdd/`, `sdd-config.yml`, bloco `sdd:start`) ficam como estão.
6. **Proteção do "como a gente faz" (última frente):** usar a skill numa organização sem entregar o código e o método. Caminhos, do mais aberto ao mais fechado: (a) instalar menos no projeto — a CI baixa a ferramenta numa versão fixa em vez de uma cópia no repo, como o modo privado já faz para as specs; (b) **MCP remoto** hospedado, em que o cliente só tem o conector. Limite: o texto do `SKILL.md` é sempre legível quando roda localmente; só o hospedado esconde o método de verdade.

### Nomes e por quê
Decididos em 2026-10-30 e revistos em 2026-11-12 (Questões em Aberto); a troca acontece só na filha de marca, bem no futuro. Tema: **partículas** — cada parte é uma partícula cujo papel na física espelha o papel dela no conjunto. Padrão das skills: `<nome>-<função>`, com a função em uma palavra em inglês, porque é o nome (com a descrição) que faz o agente entender quando usar a skill.

| Parte | Nome | Partícula | Por quê |
|---|---|---|---|
| Marca | **Fermion** (falado) · `fermion-lab` (marketplace, domínio e, no futuro, repositório) · `fermion` (plugin) | férmion: partícula de matéria (quarks e elétrons) | o conjunto é a matéria em que os agentes trabalham, e as skills são bósons (glúon, fóton, bóson), as forças que a mantêm junta. Era **Hadron**, trocado em 2026-11-12 porque `github.com/hadron-lab` já existe e a Hadron Memory publica um plugin do Claude Code chamado `hadron` (mesma área: memória para IA) |
| `sdd-management` | `gluon-spec` | glúon | o glúon segura os quarks dentro de prótons e nêutrons: specs, gates e aprovações seguram a entrega inteira junta |
| `second-brain` | `photon-brain` | fóton | olhar uma estrela é ver a luz do passado, e a radiação cósmica de fundo é a memória mais antiga do universo: o fóton é memória viajando |
| `org-atlas` | `boson-atlas` | bóson | os bósons carregam todas as interações entre partículas; o atlas mapeia as interações entre os sistemas. O glúon é um desses bósons: o atlas mapeia todas as forças, o `gluon-spec` é a que mantém a entrega inteira |
| Probes (SPEC-0030) | **Muon** (capacidade; comando `probe`; `muon-probe` se virar skill) | múon | múons "radiografaram" a Grande Pirâmide e acharam uma câmara escondida sem mover uma pedra (ScanPyramids, 2017): ver por dentro sem alterar, que é o que um probe só de leitura faz |

**Por que não os outros:** tema cérebro (`engrama`, `egide`, `hipocampo`, `talamo`) — sentido bom, fonética fraca; filosofia grega (`organon`, `kanon`, `hegemonikon`, `anamnesis`, `gnomon`) — as terminações em -mon/-kon lembram Pokémon; mito do labirinto (`daedala`, `eunomia`, `mneme`, `ariadne`) — o tema grego não agradou; `noether`, `higgs` — nomes de pessoas (risco de marca), e com o sufixo de função o nome não precisa explicar sozinho; `horizon`, `gaia` — fora do tema partículas; `graviton` — colide com os processadores AWS Graviton, confuso num atlas com coletor de AWS; `quark` — lembra o framework Quarkus; `pion` — biblioteca WebRTC conhecida; `neutrino` (probes) — não agradou; sufixo `-dev` na marca — soou fraco, `-lab` ficou melhor.

**Não-objetivos (fora do escopo):**
- Abandonar a instalação por cópia ou a compatibilidade com outros agentes.
- API HTTP própria como produto separado: se houver serviço hospedado, ele é exposto como MCP remoto.
- Relação com a Malha ou com o `smart-admin-ai`: fora de questão por ora; talvez num futuro distante (thomas, 2026-10-30).

## 3. Arquitetura Alvo
**Contexto:** brownfield. Hoje: skills independentes (ADR-0001, ADR-0007, ADR-0010), cada uma com CLI stdlib, instaladas por cópia.

Desenho:
- `.claude-plugin/marketplace.json` e `.claude-plugin/plugin.json` na raiz: o repositório inteiro é o plugin (`"source": "./"`), e o Claude Code carrega as skills de `skills/` sem cópia nem link (ADR-0016).
- Servidor MCP local: arquivo único stdlib (JSON-RPC sobre stdio, protocolo das duas eras), que só chama as CLIs das skills (ADR-0017).
- MCP remoto (frente 6): o mesmo conjunto de tools, hospedado.

**Opinião registrada — MCP local primeiro, nunca API própria:** MCP local custa pouco (sem hospedagem, sem autenticação, sem cobrança, reaproveita as CLIs) e qualquer agente com MCP já sabe usar. Uma API própria exige hospedar, autenticar, versionar e escrever cliente para cada agente. Quando for preciso hospedar (frente 6), o MCP remoto é essa API com protocolo padrão; o custo de hospedar é o mesmo, mas o cliente sai de graça.

**Decisões (ADRs):** ADR-0016 (o repositório é o plugin) e ADR-0017 (servidor MCP como camada fina sobre as CLIs); a criar nas filhas seguintes: política de versão mínima e auto-melhoria, nomes das skills e distribuição fechada.

**Regras de arquitetura a garantir (G3):** o servidor MCP não importa código das skills, só chama as CLIs (SPEC-0054, `mcp/tests/test_architecture.py`); nenhuma skill depende do plugin para funcionar (SPEC-0053:IT-01, a cópia da pasta continua funcionando).

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| SPEC-0055 | Renomear as skills para `gluon-spec`, `photon-brain` e `boson-atlas` | full | migration | M | SPEC-0029 | — |
| SPEC-0053 | Plugin `fermion` e marketplace `fermion-lab` com as skills | full | feature | S | SPEC-0055 | — |
| SPEC-0054 | Servidor MCP local do plugin com as tools `atlas_*` | full | feature | M | SPEC-0053 | — |
| a criar | Hook `SessionStart` e comando de entrada única | full | feature | S | SPEC-0053 | — |
| a criar | Servidor MCP: tools `brain_*` | full | feature | M | MCP atlas | — |
| a criar | Servidor MCP: tools `sdd_*` | full | feature | S | MCP atlas | — |
| a criar | Auto-melhoria: `doctor` de ambiente e fluxo do mantenedor | full | feature | S | — | — |
| a criar | Distribuição sem cópia do código e MCP remoto | full | feature | M | MCP | — |

## 5. Estratégia de Entrega
- **Ambientes:** N/A até a frente 6 (MCP remoto exige ambiente hospedado; definido na filha).
- **Entrega por onda:** nomes das skills (SPEC-0055) → plugin (SPEC-0053) → MCP do atlas (SPEC-0054) → entrada única → demais tools MCP → auto-melhoria → distribuição fechada. O caminho mínimo combinado com o thomas é renomear, plugin e MCP do atlas; a troca de nomes veio para antes do plugin para ele já sair com os nomes finais (thomas, 2026-11-12).
- **Feature flags:** N/A; cada embalagem é opcional.
- **Rollback:** a instalação por cópia continua funcionando em qualquer ponto.
- **Métricas de sucesso pós-release:** instalação do plugin em uma máquina nova com um comando; uma tarefa entregue com uma única chamada do usuário.

## 6. Riscos & Mitigações
- Formato de plugin mudar — formato confirmado na documentação oficial a cada filha; a instalação por cópia é o fallback.
- Lógica duplicada entre MCP e CLI — regra de arquitetura: MCP só chama a CLI.
- Renomear quebrar projetos instalados — nomes visíveis mudam, caminhos instalados ficam.
- Nome escolhido já usado por produto conhecido — checar disponibilidade (GitHub, PyPI, npm, domínio, registro de marca) antes de decidir.

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] Um comando instala as três skills pelo plugin, e a cópia da pasta continua funcionando — SPEC-0053:E2E-01, SPEC-0053:IT-01
- [ ] Uma tarefa pedida uma vez passa pelo atlas e pela `sdd-management` sem o usuário chamar cada skill — teste na filha de entrada única (a criar)
- [ ] As tools MCP devolvem o mesmo resultado que a CLI correspondente — SPEC-0054:IT-01

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
- [x] Um plugin ou um por skill? — Um plugin com todas as skills (thomas, 2026-10-30)
- [x] MCP só do atlas ou do conjunto? — Do conjunto, começando pelo atlas (thomas, 2026-10-30)
- [x] Renomear as skills? — Sim, mas bem no futuro; por ora os nomes ficam (thomas, 2026-10-30). Revisto: renomear agora, antes do plugin, para ele já sair com os nomes finais (SPEC-0055, ADR-0018) (thomas, 2026-11-12)
- [x] Nome da marca e das skills — tema partículas: cada parte é uma partícula cujo papel físico espelha o da skill. Padrão `<nome>-<função>`, com a função em uma palavra em inglês para o agente entender o que a skill faz. Marca falada **Hadron** (a partícula composta: o conjunto); repositório, marketplace e domínio `hadron-lab`; plugin instalado `hadron`. `sdd-management` → `gluon-spec` (o glúon segura os quarks dentro do hádron: o processo segura a entrega); `second-brain` → `photon-brain` (a luz das estrelas é o passado que chega: memória viajando); `org-atlas` → `boson-atlas` (os bósons carregam as interações; o atlas mapeia as interações entre sistemas — o glúon é o bóson que segura o hádron); probes da SPEC-0030 chamados **Muon** como nome da capacidade (comando continua `probe`; se um dia virar skill, `muon-probe`). Renomear fica para bem no futuro; os nomes antigos ficam como apelidos na transição. Descartados: tema cérebro (`engrama`, `egide`, `hipocampo`, `talamo`), filosofia grega (`organon`, `kanon`, `hegemonikon`, `anamnesis`, `gnomon` e variações — terminações em -mon/-kon lembram Pokémon), mito do labirinto (`daedala`, `eunomia`, `mneme`, `ariadne`), `noether`, `horizon` e `gaia` (fora do tema partículas; `noether` é nome de pessoa), `graviton` (colide com o AWS Graviton), `quark` (lembra o Quarkus), `pion` (biblioteca WebRTC), `higgs` (nome de pessoa), `neutrino` para os probes e o sufixo `-dev` na marca (thomas, 2026-10-30)
- [x] Os nomes escolhidos estão livres (GitHub, PyPI, npm, domínio, registro de marca), principalmente `hadron-lab`? — Não: `github.com/hadron-lab` existe desde 2026-10-12 (outra pessoa) e a Hadron Memory (hadronmemory.com, memória para IA) publica um marketplace e um plugin do Claude Code chamados `hadron`, com comandos `/hadron:*`; `hadron` também está ocupado no PyPI, no npm e em `hadron.dev`. A marca passa a **Fermion**: `fermion-lab` livre no GitHub, PyPI, npm e em .dev/.com/.io (só `fermion` sem sufixo existe no npm); `gluon-spec`, `photon-brain` e `boson-atlas` livres (`photon-brain` tem um repositório homônimo sem estrelas, mesmo conceito). Checagem só de leitura em 2026-11-12 (APIs do GitHub, PyPI, npm, RDAP, registro MCP); registro de marca (INPI/USPTO) fica para a filha de marca (thomas, 2026-11-12)
- [x] O plugin aponta para as pastas de `skills/` ou a release gera uma cópia? — Aponta: com `"source": "./"` o repositório é o plugin e o Claude Code faz o scan de `skills/` sozinho; caminhos fora da raiz do plugin são rejeitados, então um plugin em subpasta não alcançaria `skills/`. Na instalação a partir do GitHub a raiz é copiada para o cache (`${CLAUDE_PLUGIN_ROOT}`, que muda a cada versão; estado vai em `${CLAUDE_PLUGIN_DATA}`). Fonte: code.claude.com/docs/en/plugins (manifest-reference, marketplace-reference, loading), lida em 2026-11-12 (thomas, 2026-11-12)
- [x] Modelo de distribuição fechada: só MCP remoto, ou também ferramenta baixada pela CI? — Decidido na filha da frente 6, quando ela for priorizada; não trava o caminho mínimo (thomas, 2026-11-12)

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0031` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
