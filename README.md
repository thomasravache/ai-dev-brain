# ai-dev-brain

Skills e materiais de apoio para desenvolvimento com agentes de IA (Claude Code, Gemini CLI, Antigravity e outros que leem `SKILL.md`).

## Skills

| Skill | O que faz |
|---|---|
| [`gluon-spec`](skills/gluon-spec/SKILL.md) (antes `sdd-management`) | Spec-Driven Development de ponta a ponta: specs com dependências, aprovação humana antes do código, execução multiagente em ondas, TDD verificado no git, gates de qualidade até o deploy, pilares de entrega e relatório de entrega. Agnóstica de tecnologia e de ferramenta. |
| [`photon-brain`](skills/photon-brain/SKILL.md) (antes `second-brain`) | Segundo cérebro num vault do Obsidian mantido com uma LLM. Faz o onboarding de um vault novo ou existente e guarda notas, PDFs e vídeos: o texto é extraído por yt-dlp, Whisper ou pdftotext, as notas são ligadas às relacionadas e entram no MOC e no log. Também consulta o vault citando as notas, captura pelo celular via `inbox/` ou pelo conector do provedor (sem a pasta do vault na máquina, achando o vault sozinho), faz manutenção com `lint` e exporta para o NotebookLM. Guarda itens confidenciais sem expô-los (referência ao gerenciador de senhas, documentos sem extração, fora da busca por padrão e alarme de segredo ou dado pessoal no `lint`) e faz backup verificado do vault em vários destinos, com restauração que nunca sobrescreve. Agnóstica de provedor (Google Drive, OneDrive, iCloud ou pasta local) e de LLM. |
| [`boson-atlas`](skills/boson-atlas/SKILL.md) (antes `org-atlas`) | Atlas de como uma organização desenvolve e opera software (serviços, plataforma, convenções, processo e glossário), mantido com os agentes num repositório compartilhado ou numa pasta local. Faz o onboarding (`init`, `init --join` numa máquina nova), mostra a configuração em duas camadas com a origem de cada valor e diagnostica o atlas com `doctor`. Credenciais só pelo nome da variável ou do profile, nunca o valor. Agnóstica de organização e de provedor. |

## Próximos passos e nomes

Entregue: a skill `boson-atlas` (antes `org-atlas`; SPEC-0029, versão 2026.11.3), com o esqueleto, a configuração e o `doctor` (SPEC-0032), o `scan` com o contrato dos coletores (SPEC-0033), os coletores `generic` e GitHub (SPEC-0034) o coletor Argo CD (SPEC-0035) e o `build`, que junta tudo num grafo e gera as páginas do atlas (SPEC-0036), e a curadoria de convenções, em que o agente propõe e uma pessoa confirma (SPEC-0037), e o `context`, o pacote que os agentes consultam antes de agir, com aviso quando o atlas está desatualizado (SPEC-0038), e o `lint`, que acha segredo, configuração quebrada e referência solta antes de compartilhar o atlas (SPEC-0039), e o modo repositório, em que `vendor --ci` gera o scan agendado que abre um PR com as mudanças do atlas (SPEC-0040). Endurecimentos menores, ainda propostos: SPEC-0046, SPEC-0047 e SPEC-0048. Em rascunho, ainda sem aprovação: probes só de leitura na infraestrutura (SPEC-0030) e a distribuição como plugin e servidor MCP (SPEC-0031).

O conjunto vai ganhar a marca **Fermion** (`fermion-lab` no marketplace, no domínio e, no futuro, no repositório; `fermion` como plugin). Hadron foi descartado em 2026-11-12: `hadron-lab` já existe no GitHub e a Hadron Memory publica um plugin do Claude Code chamado `hadron`. As skills já usam os nomes novos (SPEC-0055), antes da primeira publicação do plugin; o nome antigo continua na `description` de cada uma como apelido. Scripts (`spec_graph.py`, `brain.py`, `atlas.py`), pastas de configuração da máquina (`~/.config/second-brain`, `~/.config/org-atlas`), o contrato `org-atlas/collector@1`, a pasta `.org-atlas/` dos atlas e `tools/sdd/` continuam com os nomes de antes, para que máquinas, vaults, atlas e projetos já configurados sigam funcionando sem nenhuma ação. O tema é **partículas**: cada parte é uma partícula cujo papel na física espelha o papel dela. Cada skill segue o padrão `<nome>-<função>`, porque o nome é o que ajuda o agente a entender quando usá-la.

| Nome | Antes | Por quê |
|---|---|---|
| **Fermion** (`fermion-lab`, futuro) | ai-dev-brain | os férmions são as partículas de matéria (quarks e elétrons): o conjunto é a matéria em que os agentes trabalham, e as skills são bósons, as forças que a mantêm junta; "lab" é o lugar de experimento e construção |
| `gluon-spec` | `sdd-management` | o glúon segura os quarks dentro de prótons e nêutrons, como specs, gates e aprovações seguram a entrega |
| `photon-brain` | `second-brain` | olhar uma estrela é ver a luz do passado: o fóton é memória viajando |
| `boson-atlas` | `org-atlas` | os bósons carregam as interações entre partículas; o atlas mapeia as interações entre os sistemas |
| **Muon** (futuro) | probes | múons "radiografaram" a Grande Pirâmide sem mover uma pedra: ver por dentro sem alterar |

Alternativas descartadas e a checagem de disponibilidade que falta: SPEC-0031, seção "Nomes e por quê".

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

No Claude Code 2.1.275 ou mais novo, um comando só faz os dois passos: `/plugin install fermion --marketplace thomasravache/ai-dev-brain`.

As skills aparecem como `/fermion:gluon-spec`, `/fermion:photon-brain` e `/fermion:boson-atlas`, e o agente também as usa sozinho quando o pedido combina com a `description` de cada uma.

Para atualizar, rode `claude plugin marketplace update fermion-lab` e depois `claude plugin update fermion@fermion-lab` (ou use `/plugin` dentro do Claude Code); a versão do plugin segue o formato `AAAA.MM.N`. Para desinstalar, `claude plugin uninstall fermion@fermion-lab` e, se quiser tirar também o marketplace, `claude plugin marketplace remove fermion-lab`.

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

## Testes

```bash
python3 -m unittest discover -s skills/gluon-spec/tests       # suíte da gluon-spec, inclui os testes de arquitetura
python3 -m unittest discover -s skills/photon-brain/tests     # suíte da photon-brain, inclui os testes de arquitetura
python3 -m unittest discover -s skills/boson-atlas/tests      # suíte da boson-atlas, inclui os testes de arquitetura
python3 -m unittest discover -s tests/plugin                  # plugin e marketplace (SPEC-0053) e nomes das skills (SPEC-0055)
uvx ruff check                                                 # lint (Ruff 0.17, configurado em ruff.toml)
```

A CI (`.github/workflows/ci.yml`) roda tudo isso em todo PR, em Python 3.9 e 3.15.
