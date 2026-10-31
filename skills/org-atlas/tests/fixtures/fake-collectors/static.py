"""Coletor falso (SPEC-0033): imprime uma saída fixa e válida do contrato org-atlas/collector@1.

Uso: python3 static.py <id-do-coletor>
"""
import json
import sys

collector = sys.argv[1] if len(sys.argv) > 1 else "fake-ok"
print(json.dumps({
    "contract": "org-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": [
        {"kind": "repository", "id": f"{collector}/api", "name": "api", "attrs": {"default_branch": "main"},
         "source": collector},
        {"kind": "repository", "id": f"{collector}/web", "name": "web", "attrs": {"default_branch": "main"},
         "source": collector},
        {"kind": "pipeline", "id": f"{collector}/api/ci", "name": "ci", "attrs": {}, "source": collector},
    ],
    "relations": [
        {"from": f"pipeline:{collector}/api/ci", "to": f"repository:{collector}/api", "type": "builds",
         "source": collector},
        {"from": f"pipeline:{collector}/api/ci", "to": f"repository:{collector}/web", "type": "builds",
         "source": collector},
    ],
}))
