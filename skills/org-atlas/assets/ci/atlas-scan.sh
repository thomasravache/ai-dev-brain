#!/usr/bin/env bash
# org-atlas — scan agendado do atlas para qualquer CI (gerado por `atlas.py vendor --ci generic`; SPEC-0040).
# Rode na raiz do repositório do atlas, com git e python3 (3.9+). As credenciais dos coletores (os nomes de ci.env
# no atlas-config.yml) chegam pelo ambiente, definidas como secrets da plataforma: nunca ficam no atlas.
# A ferramenta roda da cópia em .org-atlas/skill/, que o vendor sempre atualiza (references/modes.md).
#
# Saída: 0 sem mudança, 10 com mudança (a CI abre o PR/MR com o diff), 1 com falha (coletor, lint com ERRO, git).
set -uo pipefail

# Configuração local só desta execução, fora da árvore do atlas (mantém um ATLAS_CONFIG_HOME já definido).
if [ -z "${ATLAS_CONFIG_HOME:-}" ]; then
  ATLAS_CONFIG_HOME="$(mktemp -d)" || exit 1
fi
export ATLAS_CONFIG_HOME
python3 .org-atlas/skill/scripts/atlas.py init --join --atlas "$PWD" || exit 1

failed=0
python3 .org-atlas/skill/scripts/atlas.py scan || failed=1
python3 .org-atlas/skill/scripts/atlas.py lint || failed=1
if [ "$failed" -ne 0 ]; then
  echo "atlas-scan: scan ou lint falhou (veja acima)" >&2
  exit 1
fi

changes="$(git status --porcelain)" || exit 1
if [ -n "$changes" ]; then
  echo "atlas-scan: o atlas mudou — abra um PR/MR com o diff"
  exit 10
fi
echo "atlas-scan: sem mudanças no atlas"
exit 0
