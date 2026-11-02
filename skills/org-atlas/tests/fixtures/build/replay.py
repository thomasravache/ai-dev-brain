"""Coletor falso (SPEC-0036): reimprime a saída esperada de um coletor da skill (SPEC-0034, SPEC-0035) com o
cabeçalho do contrato org-atlas/collector@1.

Uso: python3 replay.py <id-do-coletor> <categoria> <arquivo expected-*.json> [--without kind:id ...]
--without tira a entidade e toda relação que aponta para ela (serviço que some do scan, IT-03).
"""
import json
import sys
from pathlib import Path

collector, category, source = sys.argv[1], sys.argv[2], Path(sys.argv[3])
rest = sys.argv[4:]
without = {rest[i + 1] for i in range(len(rest) - 1) if rest[i] == "--without"}
data = json.loads(source.read_text(encoding="utf-8"))
entities = [e for e in data["entities"] if f"{e['kind']}:{e['id']}" not in without]
relations = [r for r in data["relations"] if r["from"] not in without and r["to"] not in without]
output = {
    "contract": "org-atlas/collector@1",
    "collector": collector,
    "category": category,
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": entities,
    "relations": relations,
}
if "signals" in data:
    output["signals"] = data["signals"]
print(json.dumps(output))
