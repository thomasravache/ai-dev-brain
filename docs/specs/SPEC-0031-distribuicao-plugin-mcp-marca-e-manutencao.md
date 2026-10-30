---
id: SPEC-0031
title: "Distribuição do ai-dev-brain: plugin, servidor MCP, marca e manutenção"
tier: epic
type: feature
status: proposed
created: 2026-10-30
depends_on: []
adrs: []
external: []
approved_by:
approved_at:
---

# SPEC-0031 — Distribuição do ai-dev-brain: plugin, servidor MCP, marca e manutenção (Épico)

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0031`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

> Rascunho de radar (2026-10-30). Registra o desenho conversado com o thomas; cada frente vira filha quando for priorizada.

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
5. **Marca:** nome do plugin e, num futuro distante, das skills. Renomear é migração: muda o nome visível e a descrição continua dizendo o que a skill faz (é ela que faz o agente acionar a skill); caminhos já instalados nos projetos (`tools/sdd/`, `sdd-config.yml`, bloco `sdd:start`) ficam como estão.
6. **Proteção do "como a gente faz" (última frente):** usar a skill numa organização sem entregar o código e o método. Caminhos, do mais aberto ao mais fechado: (a) instalar menos no projeto — a CI baixa a ferramenta numa versão fixa em vez de uma cópia no repo, como o modo privado já faz para as specs; (b) **MCP remoto** hospedado, em que o cliente só tem o conector. Limite: o texto do `SKILL.md` é sempre legível quando roda localmente; só o hospedado esconde o método de verdade.

**Não-objetivos (fora do escopo):**
- Abandonar a instalação por cópia ou a compatibilidade com outros agentes.
- API HTTP própria como produto separado: se houver serviço hospedado, ele é exposto como MCP remoto.
- Relação com a Malha ou com o `smart-admin-ai`: fora de questão por ora; talvez num futuro distante (thomas, 2026-10-30).

## 3. Arquitetura Alvo
**Contexto:** brownfield. Hoje: skills independentes (ADR-0001, ADR-0007, ADR-0010), cada uma com CLI stdlib, instaladas por cópia.

Desenho:
- `.claude-plugin/marketplace.json` na raiz e a pasta do plugin apontando para as skills existentes, sem duplicar arquivos (a confirmar na pesquisa: link, cópia gerada na release ou `source` do marketplace).
- Servidor MCP local: arquivo único stdlib (JSON-RPC sobre stdio), que só chama as CLIs das skills.
- MCP remoto (frente 6): o mesmo conjunto de tools, hospedado.

**Opinião registrada — MCP local primeiro, nunca API própria:** MCP local custa pouco (sem hospedagem, sem autenticação, sem cobrança, reaproveita as CLIs) e qualquer agente com MCP já sabe usar. Uma API própria exige hospedar, autenticar, versionar e escrever cliente para cada agente. Quando for preciso hospedar (frente 6), o MCP remoto é essa API com protocolo padrão; o custo de hospedar é o mesmo, mas o cliente sai de graça.

**Decisões (ADRs):** a criar, uma por frente — empacotamento como plugin; servidor MCP (fronteira com as CLIs); política de versão mínima e auto-melhoria; marca; distribuição fechada.

**Regras de arquitetura a garantir (G3):** o servidor MCP não importa código das skills, só chama as CLIs; nenhuma skill depende do plugin para funcionar — testes a definir.

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| a criar | Plugin e marketplace com as skills | full | feature | M | — | — |
| a criar | Hook `SessionStart` e comando de entrada única | full | feature | S | plugin; SPEC-0029 | — |
| a criar | Servidor MCP local: tools `atlas_*` | full | feature | M | SPEC-0029 | — |
| a criar | Servidor MCP: tools `brain_*` | full | feature | M | MCP atlas | — |
| a criar | Servidor MCP: tools `sdd_*` | full | feature | S | MCP atlas | — |
| a criar | Auto-melhoria: `doctor` de ambiente e fluxo do mantenedor | full | feature | S | — | — |
| a criar | Marca: nome do plugin (e depois das skills) | full | migration | S | plugin | — |
| a criar | Distribuição sem cópia do código e MCP remoto | full | feature | M | MCP | — |

## 5. Estratégia de Entrega
- **Ambientes:** N/A até a frente 6 (MCP remoto exige ambiente hospedado; definido na filha).
- **Entrega por onda:** plugin → entrada única → MCP do atlas → demais tools MCP → auto-melhoria → marca → distribuição fechada.
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
- [ ] Um comando instala as três skills pelo plugin, e a cópia da pasta continua funcionando — teste a definir
- [ ] Uma tarefa pedida uma vez passa pelo atlas e pela `sdd-management` sem o usuário chamar cada skill — teste a definir
- [ ] As tools MCP devolvem o mesmo resultado que a CLI correspondente — teste a definir

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
- [x] Um plugin ou um por skill? — Um plugin com todas as skills (thomas, 2026-10-30)
- [x] MCP só do atlas ou do conjunto? — Do conjunto, começando pelo atlas (thomas, 2026-10-30)
- [x] Renomear as skills? — Sim, mas bem no futuro; por ora os nomes ficam (thomas, 2026-10-30)
- [x] Nome da marca e das skills — tema partículas: cada parte é uma partícula cujo papel físico espelha o da skill. Padrão `<nome>-<função>`, com a função em uma palavra em inglês para o agente entender o que a skill faz. Marca falada **Hadron** (a partícula composta: o conjunto); repositório, marketplace e domínio `hadron-lab`; plugin instalado `hadron`. `sdd-management` → `gluon-spec` (o glúon segura os quarks dentro do hádron: o processo segura a entrega); `second-brain` → `photon-brain` (a luz das estrelas é o passado que chega: memória viajando); `org-atlas` → `boson-atlas` (os bósons carregam as interações; o atlas mapeia as interações entre sistemas — o glúon é o bóson que segura o hádron); probes da SPEC-0030 chamados **Muon** como nome da capacidade (comando continua `probe`; se um dia virar skill, `muon-probe`). Renomear fica para bem no futuro; os nomes antigos ficam como apelidos na transição. Descartados: tema cérebro (`engrama`, `egide`, `hipocampo`, `talamo`), filosofia grega (`organon`, `kanon`, `hegemonikon`, `anamnesis`, `gnomon` e variações — terminações em -mon/-kon lembram Pokémon), mito do labirinto (`daedala`, `eunomia`, `mneme`, `ariadne`), `noether`, `horizon` e `gaia` (fora do tema partículas; `noether` é nome de pessoa), `graviton` (colide com o AWS Graviton), `quark` (lembra o Quarkus), `pion` (biblioteca WebRTC), `higgs` (nome de pessoa), `neutrino` para os probes e o sufixo `-dev` na marca (thomas, 2026-10-30)
- [ ] Os nomes escolhidos estão livres (GitHub, PyPI, npm, domínio, registro de marca), principalmente `hadron-lab`? Atenção conhecida: `hadron` aparece em pacotes internos do MongoDB Compass; `photon` tem Photon OS (VMware) e Photon Engine (jogos), fora da nossa área; `gluon` já foi API do MXNet e é usado pela GluonHQ (thomas, na filha de marca)
- [ ] O plugin aponta para as pastas de `skills/` ou a release gera uma cópia? (pesquisa da filha)
- [ ] Modelo de distribuição fechada: só MCP remoto, ou também ferramenta baixada pela CI? (thomas)

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
