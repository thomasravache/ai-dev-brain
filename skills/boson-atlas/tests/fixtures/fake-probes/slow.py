"""Adaptador falso probe@1 (SPEC-0088): descreve na hora, mas ao rodar dorme além do timeout do teste (1 s)
antes de imprimir uma saída válida com o marcador ITEM-MARCADOR-0088 (que nunca pode aparecer).

Uso: python3 slow.py --record <arquivo> [--adapter <id>]
"""
import json
import sys
import time

argv = sys.argv[1:]
record_path = argv[argv.index("--record") + 1]
adapter = argv[argv.index("--adapter") + 1] if "--adapter" in argv else "fake"
mode = "describe" if "--describe" in argv else "run"
with open(record_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"mode": mode, "argv": argv, "input": None}) + "\n")
if mode == "describe":
    print(json.dumps({"contract": "probe@1", "adapter": adapter,
                      "capabilities": {"runtime": ["status", "events", "logs"]}}))
    sys.exit(0)
time.sleep(30)
print(json.dumps({"contract": "probe@1", "adapter": adapter, "capability": "runtime", "verb": "status",
                  "status": "ok", "items": [{"name": "ITEM-MARCADOR-0088"}], "truncated": False, "message": "ok"}))
