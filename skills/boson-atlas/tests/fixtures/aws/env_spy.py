"""Coletor falso (SPEC-0097:CH-01 e UT-07): grava em <arquivo> um objeto JSON com os NOMES das variáveis de
ambiente que recebeu e o valor de ATLAS_COLLECTOR_PROFILE (só esse valor, que é um nome de profile, nunca uma
credencial), e imprime uma saída válida do contrato boson-atlas/collector@1 (category code).

Uso: python3 env_spy.py <arquivo> <id-do-coletor>
"""
import json
import os
import sys

out, collector = sys.argv[1], sys.argv[2]
with open(out, "w", encoding="utf-8") as handle:
    json.dump({"names": sorted(os.environ), "profile": os.environ.get("ATLAS_COLLECTOR_PROFILE")}, handle)
print(json.dumps({
    "contract": "boson-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-11-24T12:00:00Z",
    "entities": [{"kind": "repository", "id": f"{collector}/api", "name": "api", "attrs": {}, "source": collector}],
    "relations": [],
}))
