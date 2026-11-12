"""Coletor falso (SPEC-0033, revisão G4 2): saída com tipo errado num campo do contrato — signals[].sample com
um objeto que carrega um valor de senha (montado em tempo de execução). O scan precisa falhar o coletor sem
gravar snapshot e sem imprimir o valor.

Uso: python3 bad_types.py <id-do-coletor>
"""
import json
import sys

collector = sys.argv[1] if len(sys.argv) > 1 else "fake-bad-types"
value = "hunter" + "2"
print(json.dumps({
    "contract": "org-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": [{"kind": "repository", "id": "acme/api", "name": "api", "attrs": {}, "source": collector}],
    "relations": [],
    "signals": [{"type": "pr-titles", "repository": "acme/api", "total": 1, "pattern_counts": {"other": 1},
                 "sample": [{"password": value}]}],
}))
