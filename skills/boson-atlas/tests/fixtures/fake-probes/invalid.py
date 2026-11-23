"""Adaptador falso probe@1 (SPEC-0088): descrição válida, saída inválida conforme --kind:

    badjson         texto que não é JSON (com o marcador)
    unknown-key     saída com uma chave fora do contrato (chave_extra_0088)
    nested-item     item com um valor que é objeto (só escalar ou lista de escalares)
    wrong-contract  contract diferente de probe@1
    bad-status      status fora de ok | error
    deep            "[" repetido 100000 vezes (aninhamento profundo: RecursionError no parser; Emenda v4)
    nan             item com NaN (constante fora do JSON padrão; Emenda v4)
    infinity        item com Infinity e -Infinity (Emenda v4)
    surrogate-line  item com "line": "\\ud800 bad" (surrogate solto: não vira UTF-8; Emenda v5)
    surrogate-value item com um valor "x \\udfff" (surrogate solto num valor qualquer; Emenda v5)

Todas (menos deep) trazem o marcador ITEM-MARCADOR-0088 num item, que nunca pode aparecer na saída do núcleo.
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
if kind == "deep":
    print("[" * 100000)
    sys.exit(0)
if kind in ("nan", "infinity"):
    value, other = ("NaN", "NaN") if kind == "nan" else ("Infinity", "-Infinity")
    print('{"contract": "probe@1", "adapter": "' + adapter + '", "capability": "runtime", "verb": "status", '
          '"status": "ok", "items": [{"name": "ITEM-MARCADOR-0088", "valor": ' + value + ', "outro": ' + other
          + '}], "truncated": false, "message": "ok"}')
    sys.exit(0)
if kind in ("surrogate-line", "surrogate-value"):
    item = '"line": "\\ud800 bad"' if kind == "surrogate-line" else '"valor": "x \\udfff"'
    print('{"contract": "probe@1", "adapter": "' + adapter + '", "capability": "runtime", "verb": "status", '
          '"status": "ok", "items": [{"name": "ITEM-MARCADOR-0088", ' + item + '}], "truncated": false, '
          '"message": "ok"}')
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
