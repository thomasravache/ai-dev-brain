"""Coletor falso (SPEC-0033): dorme além do timeout do teste (1 s) antes de imprimir uma saída válida."""
import json
import sys
import time

collector = sys.argv[1] if len(sys.argv) > 1 else "fake-slow"
time.sleep(30)
print(json.dumps({"contract": "org-atlas/collector@1", "collector": collector, "category": "code",
                  "collected_at": "2026-10-30T12:00:00Z", "entities": [], "relations": []}))
