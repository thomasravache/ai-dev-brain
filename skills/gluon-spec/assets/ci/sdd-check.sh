#!/bin/sh
# SDD check para qualquer CI (Azure Pipelines, Jenkins, Bitbucket, CircleCI...).
# Pré-requisitos: histórico completo do git, python3, e as variáveis:
#   PR_TITLE, PR_BODY  título e descrição do PR/MR
#   BASE_REF           branch alvo (ex.: main)
set -eu

: "${BASE_REF:?defina BASE_REF com a branch alvo do PR}"
git fetch origin "$BASE_REF" >/dev/null 2>&1 || true

python3 tools/sdd/spec_graph.py validate --exclude-drafts
python3 tools/sdd/spec_graph.py pr-check --base "origin/$BASE_REF"
