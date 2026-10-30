# Estrutura do vault

A estrutura é sempre em inglês; o conteúdo das notas fica no idioma da pessoa (`language`). Os nomes abaixo são os padrões do `brain-config.yml` e podem ser trocados por `layout`/`para` (ou `--map` no `init --adopt`).

```
<vault>/
├── inbox/            ← entrada: o que ainda não foi processado
├── raw/              ← notas de fonte (texto extraído, links), geradas pela skill
├── projects/         ← PARA: projetos com fim (ex.: projects/college)
├── areas/            ← PARA: responsabilidades contínuas
├── resources/        ← PARA: assuntos de interesse; destino de notas sem contexto
├── archive/          ← PARA: o que saiu de uso
├── mocs/             ← um MOC (mapa de conteúdo) por contexto: mocs/<contexto>.md
├── templates/        ← modelos por tipo de nota: note, lecture, source, video, document, link, moc
├── index.md          ← índice geral, com regiões geradas
├── log.md            ← uma linha por escrita do brain.py
└── brain-config.yml  ← configuração compartilhada (references/config.md)
```

Arquivos pesados (PDFs, vídeos) ficam na pasta `files`, fora do vault (configuração local).

## Vault novo e vault adotado

- `init` num vault novo cria tudo acima que falta, copia os modelos de `assets/templates/` e cria a pasta e o MOC de cada `--context`.
- `init --adopt` não move nem altera nada que existe e não cria as pastas de PARA que a pessoa não tem: cria só `inbox/`, `raw/`, `templates/`, `index.md`, `log.md` e `brain-config.yml` que faltarem (as pastas mapeadas com `--map` que já existem contam como presentes). O `doctor` mostra como AVISO o que ficou faltando.
- `index.md` ou `log.md` que já existem sem os marcadores `<!-- brain:begin` são da pessoa: o `init --adopt` sai com 2 e não escreve nada. Use `--map log=<outro>` (ou `--map index=<outro>`) para a skill usar outro arquivo.
- `init` sem `--adopt` numa pasta que já tem conteúdo e não tem `brain-config.yml` sai com 2 (`vault não está vazio — use --adopt`) e não cria nada.

## Regiões geradas

O `brain.py` só reescreve texto entre marcadores, e o resto do arquivo é da pessoa:

```
<!-- brain:begin <nome> -->
… gerado pela skill …
<!-- brain:end <nome> -->
```

`index.md` tem as regiões `contexts` e `recent`; cada MOC tem a região `notes`; `log.md` tem a região `about` no topo.

## log.md

Toda escrita do `brain.py` no vault acrescenta uma linha no fim: `- AAAA-MM-DD HH:MM <comando> <resumo>` (ex.: `- 2026-10-30 14:05 init vault novo — 18 item(ns) criado(s)`).
