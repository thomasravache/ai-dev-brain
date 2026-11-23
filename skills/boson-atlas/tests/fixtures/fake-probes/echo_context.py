"""Adaptador falso probe@1 (SPEC-0088, Emenda v4): ecoa o contexto do alvo (target.context, lido do stdin) e, com
--env-name, o valor da variável de ambiente declarada como credencial, no lugar escolhido por --mode:

    stderr    escreve os valores no stderr e sai com 1
    message   status "error" com os valores na message
    items     cada valor vira chave e valor de um item (e entra num campo "line")
    summary   itens de log {"ts", "line"} com o valor no meio da linha (para --summary)
    contract  item cuja chave é o valor e cujo valor é um objeto (saída fora do contrato: a falha cita a chave)
    adapter   o campo "adapter" da saída é o contexto (só o contexto: é uma palavra válida do contrato)

Com --form (Emenda v5), cada valor sai transformado antes de ir para o lugar do --mode:

    raw       como veio (padrão)
    json      escapado como dentro de uma string JSON, com "/" como "\\/"
    url       codificado em URL (urllib.parse.quote, sem caracteres seguros)
    upper     em maiúsculas
    keyed     só o contexto, como "<contexto>_key=<--secret>" (um contexto curto como api vira api_key=...)

O núcleo precisa mascarar esses valores em tudo o que imprime ou registra.
Uso: python3 echo_context.py --record <arquivo> --mode <modo> [--form <forma>] [--secret <valor>] [--adapter <id>]
                             [--env-name <NOME>] [--verbs <capacidade>=<verbo>,<verbo>]...
"""
import json
import os
import sys
import urllib.parse

argv = sys.argv[1:]


def option(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


adapter = option("--adapter", "fake")
mode_arg = option("--mode", "items")
caps = {}
for i, arg in enumerate(argv):
    if arg == "--verbs":
        cap, _, verbs = argv[i + 1].partition("=")
        caps[cap] = [v for v in verbs.split(",") if v]
caps = caps or {"runtime": ["status", "events", "logs"]}
mode = "describe" if "--describe" in argv else "run"
data = None if mode == "describe" else json.loads(sys.stdin.read() or "{}")
with open(option("--record"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"mode": mode, "argv": argv, "input": data}) + "\n")
if mode == "describe":
    print(json.dumps({"contract": "probe@1", "adapter": adapter, "capabilities": caps}))
    sys.exit(0)

values = [data["target"]["context"]]
if option("--env-name"):
    values.append(os.environ.get(option("--env-name"), ""))
form = option("--form", "raw")
if form == "json":
    values = [json.dumps(value, ensure_ascii=False)[1:-1].replace("/", "\\/") for value in values]
elif form == "url":
    values = [urllib.parse.quote(value, safe="") for value in values]
elif form == "upper":
    values = [value.upper() for value in values]
elif form == "keyed":
    values = [f"{values[0]}_key={option('--secret')}"]
out = {"contract": "probe@1", "adapter": adapter, "capability": data.get("capability"), "verb": data.get("verb"),
       "status": "ok", "items": [], "truncated": False, "message": "ok"}
if mode_arg == "stderr":
    for value in values:
        sys.stderr.write(f"falha ao falar com o contexto {value}\n")
    sys.exit(1)
elif mode_arg == "message":
    out["status"] = "error"
    out["message"] = "falhou: " + " e ".join(f"contexto {value}" for value in values)
elif mode_arg == "items":
    out["items"] = [{value: value, "line": f"INFO conectado em {value}"} for value in values]
elif mode_arg == "summary":
    out["items"] = [{"ts": f"2026-11-20T10:0{i}:00Z", "line": f"ERROR conexão com {value} recusada"}
                    for i, value in enumerate(values)]
elif mode_arg == "contract":
    out["items"] = [{value: {"aninhado": 1}} for value in values]
elif mode_arg == "adapter":
    out["adapter"] = values[0]
print(json.dumps(out))
