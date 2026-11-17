# ai-dev-brain

Skills e materiais de apoio para desenvolvimento com agentes de IA (Claude Code, Gemini CLI, Antigravity e outros que leem `SKILL.md`).

## Skills

| Skill | O que faz |
|---|---|
| [`gluon-spec`](skills/gluon-spec/SKILL.md) (antes `sdd-management`) | Spec-Driven Development de ponta a ponta: specs com dependências, aprovação humana antes do código, execução multiagente em ondas, TDD verificado no git, gates de qualidade até o deploy, pilares de entrega e relatório de entrega. Agnóstica de tecnologia e de ferramenta. |
| [`photon-brain`](skills/photon-brain/SKILL.md) (antes `second-brain`) | Segundo cérebro num vault do Obsidian mantido com uma LLM. Faz o onboarding de um vault novo ou existente e guarda notas, PDFs e vídeos: o texto é extraído por yt-dlp, Whisper ou pdftotext, as notas são ligadas às relacionadas e entram no MOC e no log. Também consulta o vault citando as notas, captura pelo celular via `inbox/` ou pelo conector do provedor (sem a pasta do vault na máquina, achando o vault sozinho), faz manutenção com `lint` e exporta para o NotebookLM. Guarda itens confidenciais sem expô-los (referência ao gerenciador de senhas, documentos sem extração, fora da busca por padrão e alarme de segredo ou dado pessoal no `lint`) e faz backup verificado do vault em vários destinos, com restauração que nunca sobrescreve. Agnóstica de provedor (Google Drive, OneDrive, iCloud ou pasta local) e de LLM. |
| [`boson-atlas`](skills/boson-atlas/SKILL.md) (antes `org-atlas`) | Atlas de como uma organização desenvolve e opera software (serviços, plataforma, convenções, processo e glossário), mantido com os agentes num repositório compartilhado ou numa pasta local. Faz o onboarding (`init`, `init --join` numa máquina nova), mostra a configuração em duas camadas com a origem de cada valor e diagnostica o atlas com `doctor`. Credenciais só pelo nome da variável ou do profile, nunca o valor. Agnóstica de organização e de provedor. |

## Próximos passos e nomes

Entregue: a skill `boson-atlas` (antes `org-atlas`; SPEC-0029, versão 2026.11.3), com o esqueleto, a configuração e o `doctor` (SPEC-0032), o `scan` com o contrato dos coletores (SPEC-0033), os coletores `generic` e GitHub (SPEC-0034) o coletor Argo CD (SPEC-0035) e o `build`, que junta tudo num grafo e gera as páginas do atlas (SPEC-0036), e a curadoria de convenções, em que o agente propõe e uma pessoa confirma (SPEC-0037), e o `context`, o pacote que os agentes consultam antes de agir, com aviso quando o atlas está desatualizado (SPEC-0038), e o `lint`, que acha segredo, configuração quebrada e referência solta antes de compartilhar o atlas (SPEC-0039), e o modo repositório, em que `vendor --ci` gera o scan agendado que abre um PR com as mudanças do atlas (SPEC-0040). Endurecimentos menores, ainda propostos: SPEC-0046, SPEC-0047 e SPEC-0048. Entregue: a distribuição Fermion (SPEC-0031): as skills com os nomes novos (SPEC-0055), o plugin `fermion` no marketplace `fermion-lab` (SPEC-0053), o servidor MCP local com as tools `atlas_*`, `brain_*`, `sdd_*` e `fermion_doctor` (SPEC-0054, SPEC-0059, SPEC-0060, SPEC-0061), o hook de início de sessão e o `/fermion:deliver` (SPEC-0058) e o aviso de instalação desatualizada (SPEC-0061). Propostas: versão do plugin ligada às mudanças das skills (SPEC-0056) e hook do leak-check sem caminho absoluto (SPEC-0057). Em rascunho, ainda sem aprovação: probes só de leitura na infraestrutura (SPEC-0030).

O conjunto vai ganhar a marca **Fermion** (`fermion-lab` no marketplace, no domínio e, no futuro, no repositório; `fermion` como plugin). Hadron foi descartado em 2026-11-12: `hadron-lab` já existe no GitHub e a Hadron Memory publica um plugin do Claude Code chamado `hadron`. As skills já usam os nomes novos (SPEC-0055), antes da primeira publicação do plugin; o nome antigo continua na `description` de cada uma como apelido. Os nomes técnicos também já mudaram (veja a nota de compatibilidade logo abaixo). O tema é **partículas**: cada parte é uma partícula cujo papel na física espelha o papel dela. Cada skill segue o padrão `<nome>-<função>`, porque o nome é o que ajuda o agente a entender quando usá-la.

**Compatibilidade com os nomes técnicos antigos:** desde as SPEC-0069 a SPEC-0071 (ADR-0020) a configuração da máquina fica em `~/.config/photon-brain` e `~/.config/boson-atlas` (antes `~/.config/second-brain` e `~/.config/org-atlas`), o `vendor` grava a cópia da skill no atlas em `.boson-atlas/skill` (antes `.org-atlas/skill`) o contrato dos coletores é `boson-atlas/collector@1` (antes `org-atlas/collector@1`) e os backups do vault usam o prefixo `photon-brain-` (antes `second-brain-`). As skills só gravam nos nomes novos e leem os dois (leitura dupla): a pasta antiga de configuração vale só quando o `config.yml` da pasta nova não existe, a cópia antiga no atlas segue reconhecida e o `scan` aceita a saída do coletor com qualquer dos dois contratos. A exceção, até a SPEC-0073, é o snapshot: o `scan` ainda grava `snapshots/<id>.json` com `org-atlas/collector@1`, para que máquinas na versão anterior da skill sigam lendo o atlas. Os nomes antigos deixam de ser lidos só com a remoção anunciada no `CHANGELOG.md`, não antes de 2027-03 (SPEC-0073); até lá, o `doctor` de cada skill e o aviso de instalação antiga do plugin (SPEC-0072) mostram o que ainda está no nome antigo e como migrar. `spec_graph.py`, `brain.py`, `atlas.py` e `tools/sdd/` mantêm os nomes.

| Nome | Antes | Por quê |
|---|---|---|
| **Fermion** (`fermion-lab`, futuro) | ai-dev-brain | os férmions são as partículas de matéria (quarks e elétrons): o conjunto é a matéria em que os agentes trabalham, e as skills são bósons, as forças que a mantêm junta; "lab" é o lugar de experimento e construção |
| `gluon-spec` | `sdd-management` | o glúon segura os quarks dentro de prótons e nêutrons, como specs, gates e aprovações seguram a entrega |
| `photon-brain` | `second-brain` | olhar uma estrela é ver a luz do passado: o fóton é memória viajando |
| `boson-atlas` | `org-atlas` | os bósons carregam as interações entre partículas; o atlas mapeia as interações entre os sistemas |
| **Muon** (futuro) | probes | múons "radiografaram" a Grande Pirâmide sem mover uma pedra: ver por dentro sem alterar |

Alternativas descartadas e a checagem de disponibilidade dos nomes (2026-11-12): SPEC-0031, seção "Nomes e por quê".

## Instalação

### Pelo plugin do Claude Code (recomendado)

O repositório é o marketplace `fermion-lab`, com um plugin `fermion` que traz as três skills (SPEC-0053, ADR-0016). No terminal:

```bash
claude plugin marketplace add thomasravache/ai-dev-brain
claude plugin install fermion@fermion-lab
```

Ou, dentro do Claude Code:

```text
/plugin marketplace add thomasravache/ai-dev-brain
/plugin install fermion@fermion-lab
```

Um comando só também faz os dois passos no terminal: `claude plugin install fermion --marketplace thomasravache/ai-dev-brain`.

As skills aparecem como `/fermion:gluon-spec`, `/fermion:photon-brain` e `/fermion:boson-atlas`, e o agente também as usa sozinho quando o pedido combina com a `description` de cada uma.

O plugin também traz (SPEC-0058 e SPEC-0061):

- **Hook de início de sessão** (`hooks/hooks.json` → `hooks/session_start.py`): ao abrir, retomar, limpar, compactar ou bifurcar (`fork`) a sessão, põe no contexto o `status` do SDD quando o projeto tem `docs/specs/sdd-config.yml` (cortado em 6.000 caracteres), e uma linha avisando quando o atlas (`boson-atlas`) e o segundo cérebro (`photon-brain`) estão configurados na máquina. Só roda comandos de leitura das CLIs do plugin, sem shell, com timeout de 10 s por CLI e de 20 s no total, e nunca atrapalha o início da sessão: o que falha some do contexto e vira uma linha no log de debug (`claude --debug`).
- **Aviso de instalação antiga** (`scripts/fermion_doctor.py`, SPEC-0061, ADR-0019): no início de cada sessão o hook acima confere se há instalação antiga ao lado do plugin e, quando há, acrescenta o bloco "Instalação desatualizada (fermion)" ao contexto (até 1.500 caracteres), uma linha por achado com o comando de atualização. Confere cópias das skills com o nome antigo (`sdd-management`, `second-brain`, `org-atlas`) ou com o nome novo mais velhas que o plugin, em `$CLAUDE_CONFIG_DIR/skills` (ou `~/.claude/skills`) e em `.claude/skills` do projeto; `tools/sdd/` do projeto mais velho que a `gluon-spec`; bloco `sdd:start` que ainda cita a `sdd-management`; atlas vendorizado (`.boson-atlas/skill/`, ou `.org-atlas/skill/` de antes) mais velho que a `boson-atlas`; configuração da máquina na pasta antiga (`~/.config/second-brain` ou `~/.config/org-atlas`), com o comando de cópia para `~/.config/photon-brain` ou `~/.config/boson-atlas`, ou "pode apagar" quando a nova já existe (só sem `BRAIN_CONFIG_HOME`/`ATLAS_CONFIG_HOME`); e a pasta `.org-atlas/` no atlas, com o passo de migração do `vendor` para `.boson-atlas/` (SPEC-0072). O script só lê: nunca grava, apaga nem move nada, não abre processo nem usa rede, e sempre sai com 0. Nada é atualizado sozinho; quem roda o comando é você. Para conferir na hora: `python3 <pasta do plugin>/scripts/fermion_doctor.py [--project PASTA] [--json]`, ou a tool MCP `fermion_doctor`.
- **Comando `/fermion:deliver <tarefa>`** (`commands/deliver.md`): entrada única para entregar uma tarefa. Monta o contexto com o atlas (quando configurado), escreve a spec com a `gluon-spec`, para no H1 pedindo "Aprovado" e depois segue até o PR. Nunca aprova H1/H2 nem faz merge sem o seu "sim".

Para atualizar, rode `claude plugin marketplace update fermion-lab` e depois `claude plugin update fermion@fermion-lab` (ou use `/plugin` dentro do Claude Code); a versão do plugin segue o formato `AAAA.MM.N`. Para desinstalar, `claude plugin uninstall fermion@fermion-lab` e, se quiser tirar também o marketplace, `claude plugin marketplace remove fermion-lab`.

Ao mudar `skills/**`, `hooks/**`, `commands/**`, `mcp/**` ou `scripts/**`, o PR precisa subir a `version` do `.claude-plugin/plugin.json` (`AAAA.MM.N` maior que a da `main`): o Claude Code usa a versão para decidir se há atualização, e sem isso `claude plugin update` não traz a mudança. A CI confere isso em todo PR (`tests/plugin/check_plugin_version.py`, SPEC-0056 e SPEC-0058).

### Copiando a pasta da skill (alternativa)

Para outras ferramentas que leem `SKILL.md` (Gemini CLI, Antigravity e outras), ou sem o plugin, copie a pasta da skill para o diretório de skills da ferramenta, por exemplo:

```bash
cp -R skills/gluon-spec ~/.claude/skills/
cp -R skills/photon-brain ~/.claude/skills/
cp -R skills/boson-atlas ~/.claude/skills/
```

**Já copiou as pastas com os nomes antigos?** As cópias em `~/.claude/skills/sdd-management`, `~/.claude/skills/second-brain` e `~/.claude/skills/org-atlas` continuam funcionando, mas não recebem mais atualizações: apague essas cópias e instale o plugin `fermion` ou as pastas novas com os comandos acima. Nada mais muda: a configuração da máquina, os vaults, os atlas e os projetos continuam como estão.

A ferramenta da `gluon-spec` (`scripts/spec_graph.py`) só precisa de Python 3.9+ e git; a da `photon-brain` (`scripts/brain.py`) e a da `boson-atlas` (`scripts/atlas.py`), só de Python 3.9+. O CHANGELOG da `photon-brain` fica em [`skills/photon-brain/CHANGELOG.md`](skills/photon-brain/CHANGELOG.md) e o da `boson-atlas` em [`skills/boson-atlas/CHANGELOG.md`](skills/boson-atlas/CHANGELOG.md).

Num repositório compartilhado com um time que não usa SDD, ative o **modo privado** (`spec_graph.py private init`): specs e registros ficam numa pasta fora do repositório, e o time só vê código, commits e PRs normais. Detalhes em [`references/private-mode.md`](skills/gluon-spec/references/private-mode.md).

Cada projeto ganha dois **documentos vivos** escritos para pessoas — o guia de jornadas e o mapa do sistema (`living_docs` no `sdd-config.yml`, criados com `spec_graph.py living-docs --init` e checados pelo `validate`).

## Novidades e CHANGELOG

O CHANGELOG da `gluon-spec` fica em [`skills/gluon-spec/CHANGELOG.md`](skills/gluon-spec/CHANGELOG.md), dentro da pasta que se copia para as ferramentas, com uma seção por versão (`SDD_TOOL_VERSION`). Depois de atualizar a skill, rode `spec_graph.py whats-new` no projeto: mostra as novidades desde a versão do projeto, as chaves novas do `sdd-config` e os comandos para se atualizar (`whats-new --ack` registra a versão revisada em projetos sem `tools/sdd`). O `status` avisa quando há novidade.

Para ver o que o processo está seguindo de verdade em vários projetos, rode `spec_graph.py retro <pastas> [--registry]`: só lê, mostra números por projeto, achados com o comando que resolve e sugestões de spec para a skill, sem títulos nem textos das specs ([`references/retro.md`](skills/gluon-spec/references/retro.md)).

## Testes

```bash
python3 -m unittest discover -s skills/gluon-spec/tests       # suíte da gluon-spec, inclui os testes de arquitetura
python3 -m unittest discover -s skills/photon-brain/tests     # suíte da photon-brain, inclui os testes de arquitetura
python3 -m unittest discover -s skills/boson-atlas/tests      # suíte da boson-atlas, inclui os testes de arquitetura
python3 -m unittest discover -s tests/plugin                  # plugin e marketplace (SPEC-0053) e nomes das skills (SPEC-0055)
uvx ruff check                                                 # lint (Ruff 0.17, configurado em ruff.toml)
```

A CI (`.github/workflows/ci.yml`) roda tudo isso em todo PR, em Python 3.9 e 3.15.
