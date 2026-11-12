"""Coletor falso (SPEC-0037): imprime os sinais de um arquivo JSON ({"signals": [...]}) no contrato
org-atlas/collector@1, com um repository para cada repositório citado nos sinais.

Uso: python3 signals.py <id-do-coletor> <arquivo-de-sinais>
Arquivo ausente = nenhum sinal (só o contrato, sem entidades).
"""
import json
import sys
from pathlib import Path

collector, path = sys.argv[1], Path(sys.argv[2])
signals = json.loads(path.read_text(encoding="utf-8"))["signals"] if path.is_file() else []
repositories = sorted({s["repository"] for s in signals if "repository" in s})
print(json.dumps({
    "contract": "org-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": [{"kind": "repository", "id": r, "name": r.split("/")[-1], "attrs": {}, "source": collector}
                 for r in repositories],
    "relations": [],
    "signals": signals,
}))
