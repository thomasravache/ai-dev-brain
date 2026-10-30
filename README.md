# ai-dev-brain

Skills e materiais de apoio para desenvolvimento com agentes de IA (Claude Code, Gemini CLI, Antigravity e outros que leem `SKILL.md`).

## Skills

| Skill | O que faz |
|---|---|
| [`sdd-management`](skills/sdd-management/SKILL.md) | Spec-Driven Development de ponta a ponta: specs com dependências, aprovação humana antes do código, execução multiagente em ondas, TDD verificado no git, gates de qualidade até o deploy, pilares de entrega e relatório de entrega. Agnóstica de tecnologia e de ferramenta. |
| [`second-brain`](skills/second-brain/SKILL.md) | Segundo cérebro num vault do Obsidian mantido com uma LLM. Faz o onboarding de um vault novo ou existente e guarda notas, PDFs e vídeos: o texto é extraído por yt-dlp, Whisper ou pdftotext, as notas são ligadas às relacionadas e entram no MOC e no log. Também consulta o vault citando as notas, captura pelo celular via `inbox/`, faz manutenção com `lint` e exporta para o NotebookLM. Agnóstica de provedor (Google Drive, OneDrive, iCloud ou pasta local) e de LLM. |

## Próximos passos e nomes futuros

Em rascunho, ainda sem aprovação: a skill `org-atlas`, que mapeia como uma organização desenvolve e opera software para os agentes usarem (SPEC-0029), com probes só de leitura na infraestrutura (SPEC-0030), e a distribuição como plugin e servidor MCP (SPEC-0031).

O conjunto vai ganhar a marca **Hadron** (`hadron-lab` no repositório, marketplace e domínio; `hadron` como plugin). A troca de nomes fica para depois, e os nomes atuais continuam valendo como apelidos na transição. O tema é **partículas**: cada parte é uma partícula cujo papel na física espelha o papel dela. Cada skill segue o padrão `<nome>-<função>`, porque o nome é o que ajuda o agente a entender quando usá-la.

| Hoje | Nome futuro | Por quê |
|---|---|---|
| ai-dev-brain | **Hadron** (`hadron-lab`) | o hádron é uma partícula feita de várias outras, como o conjunto de skills; "lab" lembra o laboratório do LHC, o Grande Colisor de Hádrons |
| `sdd-management` | `gluon-spec` | o glúon segura os quarks dentro do hádron, como specs, gates e aprovações seguram a entrega |
| `second-brain` | `photon-brain` | olhar uma estrela é ver a luz do passado: o fóton é memória viajando |
| `org-atlas` | `boson-atlas` | os bósons carregam as interações entre partículas; o atlas mapeia as interações entre os sistemas |
| probes | **Muon** | múons "radiografaram" a Grande Pirâmide sem mover uma pedra: ver por dentro sem alterar |

Alternativas descartadas e a checagem de disponibilidade que falta: SPEC-0031, seção "Nomes e por quê".

## Instalação

Copie a pasta da skill para o diretório de skills da sua ferramenta, por exemplo:

```bash
cp -R skills/sdd-management ~/.claude/skills/
cp -R skills/second-brain ~/.claude/skills/
```

A ferramenta da `sdd-management` (`scripts/spec_graph.py`) só precisa de Python 3.9+ e git; a da `second-brain` (`scripts/brain.py`), só de Python 3.9+. O CHANGELOG da `second-brain` fica em [`skills/second-brain/CHANGELOG.md`](skills/second-brain/CHANGELOG.md).

Num repositório compartilhado com um time que não usa SDD, ative o **modo privado** (`spec_graph.py private init`): specs e registros ficam numa pasta fora do repositório, e o time só vê código, commits e PRs normais. Detalhes em [`references/private-mode.md`](skills/sdd-management/references/private-mode.md).

Cada projeto ganha dois **documentos vivos** escritos para pessoas — o guia de jornadas e o mapa do sistema (`living_docs` no `sdd-config.yml`, criados com `spec_graph.py living-docs --init` e checados pelo `validate`).

## Novidades e CHANGELOG

O CHANGELOG da skill fica em [`skills/sdd-management/CHANGELOG.md`](skills/sdd-management/CHANGELOG.md), dentro da pasta que se copia para as ferramentas, com uma seção por versão (`SDD_TOOL_VERSION`). Depois de atualizar a skill, rode `spec_graph.py whats-new` no projeto: mostra as novidades desde a versão do projeto, as chaves novas do `sdd-config` e os comandos para se atualizar (`whats-new --ack` registra a versão revisada em projetos sem `tools/sdd`). O `status` avisa quando há novidade.

## Testes

```bash
python3 -m unittest discover -s skills/sdd-management/tests   # suíte completa, inclui os testes de arquitetura
python3 -m unittest discover -s skills/second-brain/tests     # suíte da second-brain, inclui os testes de arquitetura
uvx ruff check                                                 # lint (Ruff 0.17, configurado em ruff.toml)
```

A CI (`.github/workflows/ci.yml`) roda tudo isso em todo PR, em Python 3.9 e 3.15.
