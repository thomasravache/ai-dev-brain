"""Coletor falso (SPEC-0079:IT-02): grava em <arquivo> só os NOMES das variáveis *_TOKEN que recebeu no ambiente
(nunca os valores) e imprime uma saída válida do contrato boson-atlas/collector@1.

Uso: python3 env_names.py <arquivo> <id-do-coletor>
"""
import json
import os
import sys

out, collector = sys.argv[1], sys.argv[2]
names = sorted(name for name in os.environ if name.endswith("_TOKEN"))
with open(out, "w", encoding="utf-8") as handle:
    handle.write("\n".join(names) + "\n")
print(json.dumps({
    "contract": "boson-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-11-18T12:00:00Z",
    "entities": [{"kind": "repository", "id": f"{collector}/api", "name": "api", "attrs": {}, "source": collector}],
    "relations": [],
}))
