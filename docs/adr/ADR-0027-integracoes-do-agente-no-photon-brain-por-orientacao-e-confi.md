---
id: ADR-0027
title: Integrações do agente no photon-brain por orientação e configuração, nunca pelo brain.py
status: proposed
origin: decision
date: 2026-11-26
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: skills/photon-brain/tests/test_architecture.py (sem módulo de rede no brain.py, ADR-0007)
---

# ADR-0027 — Integrações do agente no photon-brain por orientação e configuração, nunca pelo brain.py

## Contexto e Problema
Os feedbacks de uso real da SPEC-0093 trouxeram integrações que o `brain.py` não alcança: o conector do provedor numa sessão na nuvem (achar a pasta do vault e a inbox pelos IDs do Drive, ler o `.yml`), a ferramenta de tarefas (Google Tasks) para os itens de ação da inbox e a agenda para compromissos. O ADR-0007 e o ADR-0013 já dizem que o `brain.py` não tem rede e que o conector é do agente. Falta decidir onde ficam os dados dessas integrações (IDs de pasta, listas de tarefas por área) e quem as executa.

## Direcionadores da Decisão
- `brain.py` só com a biblioteca padrão, sem rede e sem credenciais (ADR-0007, ADR-0008).
- Agnóstica de provedor e de ferramenta: Drive hoje, OneDrive ou outra ferramenta de tarefas amanhã.
- Pelo conector, o agente só cria arquivo novo na inbox e só lê (ADR-0013).
- Uma sessão na nuvem não tem a configuração local do computador do usuário; só o vault viaja.

## Opções Consideradas
- **A — Orientação e configuração no vault.** O `brain-config.yml` guarda dados opacos das integrações (IDs de pasta por provedor, nomes de listas de tarefas por contexto), validados pelo `brain.py` só como texto. O `SKILL.md` e as referências dizem ao agente quando usar cada ferramenta que ele tiver. O `brain.py` nunca chama nada.
- **B — Clientes das APIs no `brain.py`.** Descartada no ADR-0008: rede, credenciais e uma dependência por provedor.
- **C — Dados das integrações na configuração local da máquina.** Não serve na nuvem, onde a configuração local não existe.

## Resultado da Decisão
**Opção escolhida:** "A", porque mantém o `brain.py` sem rede e funciona em qualquer sessão que alcance o vault.

- Dados de integração ficam em chaves opcionais do `brain-config.yml` (`connectors.<provedor>`, `contexts.<nome>.tasks`, `timezone`), validadas como texto curto, sem caminho e sem valor sensível; uma chave ausente nunca é erro.
- O agente usa a ferramenta que tiver (conector, tarefas, agenda) a partir dessa orientação. Sem a ferramenta, o fluxo do vault segue igual e nada se perde: o item fica na inbox ou vira nota.
- Nenhuma integração escreve no vault fora da inbox pelo conector (ADR-0013); tudo o que organiza o vault continua pelo `brain.py`, com log.
- Credenciais e autorização das ferramentas ficam com o agente; a skill nunca as pede nem guarda.

### Consequências
- **Boa**, porque a sessão na nuvem acha o vault e a inbox pelos IDs guardados no próprio vault, e o agente sabe em que lista criar cada tarefa.
- **Boa**, porque trocar de provedor ou de ferramenta é mudar a configuração, sem código.
- **Ruim**, porque o efeito da integração depende do agente seguir a orientação; os testes do `brain.py` só provam a configuração e o texto das instruções.

### Confirmação (G3)
O teste de arquitetura da photon-brain (`tests/test_architecture.py`, regras em `tests/brain_architecture_rules.py`) continua reprovando qualquer módulo de rede no `brain.py`. As chaves novas são cobertas pelos testes de configuração das specs SPEC-0109, SPEC-0110 e SPEC-0113.

## Prós e Contras das Opções
| Critério (peso) | A | B | C |
|---|---|---|---|
| Sem rede no `brain.py` (3) | sim | não | sim |
| Funciona na sessão na nuvem (3) | sim | sim | não |
| Agnóstica de provedor (2) | sim | não | sim |
| Esforço (1) | baixo | alto | baixo |

## Mais Informações
- ADR-0007, ADR-0008, ADR-0013 e ADR-0014.
- Feedbacks de uso real registrados na SPEC-0093 (2026-11-23 a 2026-11-25).
- O tipo `application/octet-stream` recusado pela leitura de texto do conector do Google Drive foi observado no uso real (2026-11-23); não verificado em documentação oficial.
