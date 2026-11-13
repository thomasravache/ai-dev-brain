"""Coletor falso do IT-01 (SPEC-0054): imprime uma saída fixa do contrato org-atlas/collector@1, com dois serviços,
um banco, as relações entre eles e sinais de PR que viram convenções inferidas no curate.

Uso: python3 collector.py <id-do-coletor>
"""
import json
import sys

collector = sys.argv[1] if len(sys.argv) > 1 else "fake"
repos = [f"acme/s{i}" for i in range(1, 7)]
signals = []
for repo in repos:
    signals.append({"type": "pr-titles", "repository": repo, "total": 30,
                    "pattern_counts": {"conventional": 21, "ticket_key": 3, "other": 6}})
    signals.append({"type": "merge-methods", "repository": repo,
                    "present": {"merge": False, "squash": True, "rebase": False}})
entities = [{"kind": "repository", "id": r, "name": r.split("/")[-1], "attrs": {}, "source": collector}
            for r in repos]
entities += [
    {"kind": "service", "id": "api", "name": "api", "attrs": {"tier": 1}, "source": collector},
    {"kind": "service", "id": "billing", "name": "billing", "attrs": {"tier": 2}, "source": collector},
    {"kind": "datastore", "id": "payments-db", "name": "payments-db", "attrs": {"engine": "postgres"},
     "source": collector},
]
relations = [
    {"from": "service:billing", "to": "service:api", "type": "depends_on", "source": collector},
    {"from": "service:api", "to": "datastore:payments-db", "type": "depends_on", "source": collector},
]
print(json.dumps({
    "contract": "org-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": entities,
    "relations": relations,
    "signals": signals,
}))
