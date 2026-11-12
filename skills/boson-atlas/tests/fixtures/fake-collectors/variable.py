"""Coletor falso (SPEC-0033): a saída muda conforme o estado gravado pelo teste num arquivo.

Uso: python3 variable.py <id-do-coletor> <arquivo-de-estado>
Estados: v1 (padrão, arquivo ausente) | v2 (acme/c entra, acme/b sai) | v2-shuffled (o mesmo que v2, com
entidades, relações e attrs em outra ordem).
"""
import json
import sys
from pathlib import Path

collector, state_file = sys.argv[1], Path(sys.argv[2])
state = state_file.read_text(encoding="utf-8").strip() if state_file.is_file() else "v1"


def repo(name, branch="main"):
    return {"kind": "repository", "id": f"acme/{name}", "name": name,
            "attrs": {"default_branch": branch, "visibility": "private"}, "source": collector}


pipeline = {"kind": "pipeline", "id": "acme/a/ci", "name": "ci", "attrs": {}, "source": collector}
relations = [
    {"from": "pipeline:acme/a/ci", "to": "repository:acme/a", "type": "builds", "source": collector},
    {"from": "team:acme/core", "to": "repository:acme/a", "type": "owns", "source": collector},
]
team = {"kind": "team", "id": "acme/core", "name": "core", "attrs": {}, "source": collector}

if state == "v1":
    entities = [repo("a"), repo("b"), pipeline, team]
elif state == "v2":
    entities = [repo("a"), repo("c"), pipeline, team]
else:  # v2-shuffled
    shuffled = repo("a")
    shuffled["attrs"] = {"visibility": "private", "default_branch": "main"}
    entities = [team, repo("c"), pipeline, shuffled]
    relations = list(reversed(relations))

print(json.dumps({
    "contract": "org-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": entities,
    "relations": relations,
}))
