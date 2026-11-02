---
id: ADR-0015
title: Rotação de backups como única remoção do brain.py
status: accepted
origin: decision
date: 2026-11-02
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0051
---

# ADR-0015 — Rotação de backups como única remoção do brain.py

## Contexto e Problema
O ADR-0007 diz que o `brain.py` só cria e acrescenta, e nunca apaga arquivo do vault. A SPEC-0051 cria backups zip em pastas escolhidas pela pessoa (`backup_targets`), fora do vault. Sem rotação, esses destinos crescem sem limite. Com rotação, o `brain.py` passa a apagar arquivos pela primeira vez, e isso precisa de regra explícita e testada: um erro de rotação pode apagar exatamente a cópia que salvaria a pessoa.

## Direcionadores da Decisão
- Nada do vault nem da pasta `files` é apagado, nunca (ADR-0007).
- O espaço dos destinos fica sob controle sem trabalho manual.
- Um backup novo que falhou nunca pode custar um backup antigo bom.
- Arquivos da pessoa que estejam no destino nunca são tocados.

## Opções Consideradas
- **A — Rotação restrita:** o `brain.py` apaga só zips com o nome que ele mesmo cria, só nos destinos de backup, só depois de verificar o zip novo, mantendo `backup.keep` por destino.
- **B — Sem rotação:** o `brain.py` nunca apaga, e a pessoa limpa os destinos à mão (o `doctor` avisa quando há muitos).
- **C — Rotação por idade:** apagar backups mais velhos que N dias.

## Resultado da Decisão
**Opção escolhida:** A, porque controla o espaço sem trabalho manual e limita a remoção ao que a própria skill criou.

**Regras (verificáveis):**
- Remoção de arquivo (`os.remove`, `os.unlink`, `Path.unlink`, `os.rmdir`, `Path.rmdir`, `shutil.rmtree`) só dentro de `rotate_backups` e de uma lista fechada de limpezas que só removem o que a própria chamada criou: `write_export` (pasta de staging), `copy_to_files` (cópia incompleta) e `move_out_of_inbox` (reserva vazia). A limpeza do `.partial` que o próprio backup criou, quando a escrita falha, fica em `rotate_backups`. Entrar na lista exige emenda deste ADR.
- `rotate_backups` só considera nomes `second-brain-AAAA-MM-DD-HHMMSS.zip` e `second-brain-AAAA-MM-DD-HHMMSS-files.zip`, conta cada tipo separado, e só age dentro de um destino de backup.
- Um destino de backup nunca pode estar dentro do vault nem da pasta `files` (exit 2 antes de gravar).
- A rotação só roda num destino depois que o zip novo desse destino foi gravado e passou na verificação. O zip novo nunca é removido.
- `backup.keep` é no mínimo 1. Valor inválido usa o padrão (10).
- Cada remoção aparece na saída do `backup` (e no `--json`, em `removed`).

### Consequências
- **Boa**, porque os destinos ficam com um tamanho previsível e nunca perdem o último backup bom.
- **Ruim**, porque passa a existir código que apaga arquivos, o que exige o teste de arquitetura e cuidado em toda mudança futura de `rotate_backups`. Backups mais velhos que os `keep` mais recentes se perdem: quem quiser um histórico longo deve copiar um zip para outro lugar.

### Confirmação (G3)
UT-07 da SPEC-0051, em `skills/second-brain/tests/test_architecture.py` (com o checador em `brain_architecture_rules.py`): chamadas de remoção só dentro de `rotate_backups`. Os testes UT-02 e IT-03 da SPEC-0051 cobrem os nomes considerados, os arquivos da pessoa preservados e a falha que não apaga nada.

## Prós e Contras das Opções
| Critério (peso) | A — rotação restrita | B — sem rotação | C — rotação por idade |
|---|---|---|---|
| Nunca perde o último backup bom (3) | sim | sim | não (sem backup recente, apaga todos) |
| Espaço controlado sem trabalho manual (2) | sim | não | sim |
| Só toca o que a skill criou (3) | sim | sim | depende da regra de nomes |

## Mais Informações
ADR-0007 (só cria e acrescenta, no vault), ADR-0008 (pastas). Fontes: não verificado — decisão sobre o próprio código, sem ferramenta externa.
