"""Adaptador falso probe@1 (SPEC-0088): descrição válida, saída inválida conforme --kind:

    badjson         texto que não é JSON (com o marcador)
    unknown-key     saída com uma chave fora do contrato (chave_extra_0088)
    nested-item     item com um valor que é objeto (só escalar ou lista de escalares)
    wrong-contract  contract diferente de probe@1
    bad-status      status fora de ok | error

Todas trazem o marcador ITEM-MARCADOR-0088 num item, que nunca pode aparecer na saída do núcleo.
Uso: python3 invalid.py --record <arquivo> --kind <tipo> [--adapter <id>]
"""
import json
import sys

argv = sys.argv[1:]
record_path = argv[argv.index("--record") + 1]
kind = argv[argv.index("--kind") + 1]
adapter = argv[argv.index("--adapter") + 1] if "--adapter" in argv else "fake"
mode = "describe" if "--describe" in argv else "run"
with open(record_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"mode": mode, "argv": argv, "input": None}) + "\n")
if mode == "describe":
    print(json.dumps({"contract": "probe@1", "adapter": adapter,
                      "capabilities": {"runtime": ["status", "events", "logs"]}}))
    sys.exit(0)
if kind == "badjson":
    print('{"contract": "probe@1", "items": [{"name": "ITEM-MARCADOR-0088"}')
    sys.exit(0)
out = {"contract": "probe@1", "adapter": adapter, "capability": "runtime", "verb": "status", "status": "ok",
       "items": [{"name": "ITEM-MARCADOR-0088"}], "truncated": False, "message": "ok"}
if kind == "unknown-key":
    out["chave_extra_0088"] = "x"
elif kind == "nested-item":
    out["items"].append({"name": "outro", "spec": {"replicas": 1}})
elif kind == "wrong-contract":
    out["contract"] = "probe@9"
elif kind == "bad-status":
    out["status"] = "talvez"
print(json.dumps(out))
