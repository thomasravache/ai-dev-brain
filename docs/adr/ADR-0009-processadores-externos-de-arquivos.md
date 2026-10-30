---
id: ADR-0009
title: Processadores externos de arquivos
status: accepted
origin: decision
date: 2026-10-30
pillars: [arquitetura]
decision_makers: [thomas]
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: SPEC-0022
---

# ADR-0009 — Processadores externos de arquivos

## Contexto e Problema
A skill precisa transformar vídeos do YouTube, vídeos e áudios locais e PDFs em texto antes de sintetizar (SPEC-0016). As ferramentas boas para isso (yt-dlp, Whisper, pdftotext) não são da biblioteca padrão. O ADR-0007 só permite processos declarados na configuração. Precisamos decidir como a skill usa essas ferramentas sem ficar presa a elas.

## Direcionadores da Decisão
- Script só com a biblioteca padrão (ADR-0007).
- Cada pessoa tem ferramentas diferentes instaladas, e algumas não têm nenhuma.
- A skill tem que funcionar sem processador nenhum.

## Opções Consideradas
- **A — Comandos declarados em `processors` no `brain-config.yml`**, com marcadores `{input}`, `{output}` e `{output_dir}`. A v1 traz modelos prontos para yt-dlp, Whisper e pdftotext.
- **B — Importar as bibliotecas Python** (`yt_dlp`, `whisper`, `pypdf`).
- **C — Só a LLM**, que lê PDF e imagem nativamente; vídeo fica só com link.

## Resultado da Decisão
**Opção escolhida:** A, porque deixa a ferramenta para cada pessoa, mantém o script só com a biblioteca padrão e funciona sem nada instalado.

**Regras (verificáveis):**
- Um processador é `{kind: {command: "...", output: "<extensão>"}}`, com `kind` em `youtube | video | audio | pdf` (outros nomes são aceitos e chamados pelo `--kind`).
- O comando roda sem shell (`shlex.split` e lista de argumentos), com os marcadores substituídos e um timeout configurável (`timeout`, padrão 1800 s).
- A saída vai para `raw/`. O arquivo original nunca é alterado.
- Sem processador para o tipo, ou com o executável ausente, a skill não falha: avisa e guarda só o bruto, para a LLM ler direto ou deixar só o link.
- O `doctor` confere se o primeiro termo de cada comando existe no PATH (`shutil.which`).
- Os modelos de yt-dlp, Whisper e pdftotext ficam em `references/processors.md`. O onboarding só grava os que o usuário escolher.

### Consequências
- **Boa**, porque a pessoa troca de ferramenta (ex.: whisper.cpp no lugar do Whisper) mudando uma linha da configuração.
- **Ruim**, porque instalar as ferramentas é com a pessoa, e a qualidade da transcrição depende da ferramenta escolhida.

### Confirmação (G3)
Teste de arquitetura da SPEC-0017 (processos só pela função de processadores) e testes de integração da SPEC-0022 com um processador falso (script Python do próprio teste), sem as ferramentas reais.

## Prós e Contras das Opções
| Critério (peso) | A — comandos na configuração | B — bibliotecas Python | C — só a LLM |
|---|---|---|---|
| Script só com a biblioteca padrão (3) | sim | não | sim |
| Funciona sem nada instalado (2) | sim (guarda o bruto) | não | sim |
| Transcreve vídeo (2) | sim, se configurado | sim | não |
| Troca de ferramenta sem mudar código (2) | sim | não | — |

## Mais Informações
Fontes: não verificado — as linhas de comando dos modelos em `references/processors.md` são conferidas na implementação da SPEC-0022, contra a ajuda (`--help`) de cada ferramenta na versão instalada, e a data da conferência fica registrada lá.
