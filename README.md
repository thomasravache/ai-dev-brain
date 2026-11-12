# ai-dev-brain

Skills e materiais de apoio para desenvolvimento com agentes de IA (Claude Code, Gemini CLI, Antigravity e outros que leem `SKILL.md`).

## Skills

| Skill | O que faz |
|---|---|
| [`sdd-management`](skills/sdd-management/SKILL.md) | Spec-Driven Development de ponta a ponta: specs com dependências, aprovação humana antes do código, execução multiagente em ondas, TDD verificado no git, gates de qualidade até o deploy, pilares de entrega e relatório de entrega. Agnóstica de tecnologia e de ferramenta. |
| [`second-brain`](skills/second-brain/SKILL.md) | Segundo cérebro num vault do Obsidian mantido com uma LLM. Faz o onboarding de um vault novo ou existente e guarda notas, PDFs e vídeos: o texto é extraído por yt-dlp, Whisper ou pdftotext, as notas são ligadas às relacionadas e entram no MOC e no log. Também consulta o vault citando as notas, captura pelo celular via `inbox/` ou pelo conector do provedor (sem a pasta do vault na máquina, achando o vault sozinho), faz manutenção com `lint` e exporta para o NotebookLM. Guarda itens confidenciais sem expô-los (referência ao gerenciador de senhas, documentos sem extração, fora da busca por padrão e alarme de segredo ou dado pessoal no `lint`) e faz backup verificado do vault em vários destinos, com restauração que nunca sobrescreve. Agnóstica de provedor (Google Drive, OneDrive, iCloud ou pasta local) e de LLM. |
| [`org-atlas`](skills/org-atlas/SKILL.md) | Atlas de como uma organização desenvolve e opera software (serviços, plataforma, convenções, processo e glossário), mantido com os agentes num repositório compartilhado ou numa pasta local. Faz o onboarding (`init`, `init --join` numa máquina nova), mostra a configuração em duas camadas com a origem de cada valor e diagnostica o atlas com `doctor`. Credenciais só pelo nome da variável ou do profile, nunca o valor. Agnóstica de organização e de provedor. |

## Próximos passos e nomes futuros

Entregue: a skill `org-atlas` (SPEC-0029, versão 2026.11.2), com o esqueleto, a configuração e o `doctor` (SPEC-0032), o `scan` com o contrato dos coletores (SPEC-0033), os coletores `generic` e GitHub (SPEC-0034) o coletor Argo CD (SPEC-0035) e o `build`, que junta tudo num grafo e gera as páginas do atlas (SPEC-0036), e a curadoria de convenções, em que o agente propõe e uma pessoa confirma (SPEC-0037), e o `context`, o pacote que os agentes consultam antes de agir, com aviso quando o atlas está desatualizado (SPEC-0038), e o `lint`, que acha segredo, configuração quebrada e referência solta antes de compartilhar o atlas (SPEC-0039), e o modo repositório, em que `vendor --ci` gera o scan agendado que abre um PR com as mudanças do atlas (SPEC-0040). Endurecimentos menores, ainda propostos: SPEC-0046, SPEC-0047 e SPEC-0048. Em rascunho, ainda sem aprovação: probes só de leitura na infraestrutura (SPEC-0030) e a distribuição como plugin e servidor MCP (SPEC-0031).

O conjunto vai ganhar a marca **Fermion** (`fermion-lab` no marketplace, no domínio e, no futuro, no repositório; `fermion` como plugin). Hadron foi descartado em 2026-11-12: `hadron-lab` já existe no GitHub e a Hadron Memory publica um plugin do Claude Code chamado `hadron`. A troca de nomes das skills fica para depois, e os nomes atuais continuam valendo como apelidos na transição. O tema é **partículas**: cada parte é uma partícula cujo papel na física espelha o papel dela. Cada skill segue o padrão `<nome>-<função>`, porque o nome é o que ajuda o agente a entender quando usá-la.

| Hoje | Nome futuro | Por quê |
|---|---|---|
| ai-dev-brain | **Fermion** (`fermion-lab`) | os férmions são as partículas de matéria (quarks e elétrons): o conjunto é a matéria em que os agentes trabalham, e as skills são bósons, as forças que a mantêm junta; "lab" é o lugar de experimento e construção |
| `sdd-management` | `gluon-spec` | o glúon segura os quarks dentro de prótons e nêutrons, como specs, gates e aprovações seguram a entrega |
| `second-brain` | `photon-brain` | olhar uma estrela é ver a luz do passado: o fóton é memória viajando |
| `org-atlas` | `boson-atlas` | os bósons carregam as interações entre partículas; o atlas mapeia as interações entre os sistemas |
| probes | **Muon** | múons "radiografaram" a Grande Pirâmide sem mover uma pedra: ver por dentro sem alterar |

Alternativas descartadas e a checagem de disponibilidade que falta: SPEC-0031, seção "Nomes e por quê".

## Instalação

Copie a pasta da skill para o diretório de skills da sua ferramenta, por exemplo:

```bash
cp -R skills/sdd-management ~/.claude/skills/
cp -R skills/second-brain ~/.claude/skills/
cp -R skills/org-atlas ~/.claude/skills/
```

A ferramenta da `sdd-management` (`scripts/spec_graph.py`) só precisa de Python 3.9+ e git; a da `second-brain` (`scripts/brain.py`) e a da `org-atlas` (`scripts/atlas.py`), só de Python 3.9+. O CHANGELOG da `second-brain` fica em [`skills/second-brain/CHANGELOG.md`](skills/second-brain/CHANGELOG.md) e o da `org-atlas` em [`skills/org-atlas/CHANGELOG.md`](skills/org-atlas/CHANGELOG.md).

Num repositório compartilhado com um time que não usa SDD, ative o **modo privado** (`spec_graph.py private init`): specs e registros ficam numa pasta fora do repositório, e o time só vê código, commits e PRs normais. Detalhes em [`references/private-mode.md`](skills/sdd-management/references/private-mode.md).

Cada projeto ganha dois **documentos vivos** escritos para pessoas — o guia de jornadas e o mapa do sistema (`living_docs` no `sdd-config.yml`, criados com `spec_graph.py living-docs --init` e checados pelo `validate`).

## Novidades e CHANGELOG

O CHANGELOG da skill fica em [`skills/sdd-management/CHANGELOG.md`](skills/sdd-management/CHANGELOG.md), dentro da pasta que se copia para as ferramentas, com uma seção por versão (`SDD_TOOL_VERSION`). Depois de atualizar a skill, rode `spec_graph.py whats-new` no projeto: mostra as novidades desde a versão do projeto, as chaves novas do `sdd-config` e os comandos para se atualizar (`whats-new --ack` registra a versão revisada em projetos sem `tools/sdd`). O `status` avisa quando há novidade.

## Testes

```bash
python3 -m unittest discover -s skills/sdd-management/tests   # suíte completa, inclui os testes de arquitetura
python3 -m unittest discover -s skills/second-brain/tests     # suíte da second-brain, inclui os testes de arquitetura
python3 -m unittest discover -s skills/org-atlas/tests        # suíte da org-atlas, inclui os testes de arquitetura
uvx ruff check                                                 # lint (Ruff 0.17, configurado em ruff.toml)
```

A CI (`.github/workflows/ci.yml`) roda tudo isso em todo PR, em Python 3.9 e 3.15.
