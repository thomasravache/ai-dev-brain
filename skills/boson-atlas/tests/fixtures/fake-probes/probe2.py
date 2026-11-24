"""Adaptador falso probe@2 com roteiro (SPEC-0096): a descrição vem de um arquivo JSON e a resposta de cada verbo, de
um arquivo de cenário, sem nenhuma CLI de nuvem, psql, kubectl nem rede.

Uso: python3 probe2.py --record <arquivo> --describe-file <descrição.json> --scenario <cenário.json>
                       [--adapter <id>]
O núcleo acrescenta --describe para pedir a descrição: o adaptador imprime o JSON de <descrição.json> como está
(o teste escolhe contract, adapter e capabilities, inclusive inválidos), trocando "adapter" por --adapter quando o
arquivo não traz a chave.
Cada chamada acrescenta ao <arquivo> uma linha JSON {"mode": "describe" | "run", "argv": [...], "input": <JSON do
stdin>, "env": {<nome>: <valor>}} (o registro de processos do dublê, com o ambiente recebido).

Cenário (lido a cada execução): {"<verbo>": <resposta>, "*": <resposta>}; verbo sem resposta = itens vazios.
    <resposta>:
        {"items": [...], "truncated": false, "message": "..."}  status "ok" com esses itens
        {"error": "<mensagem>"}                                   status "error", itens vazios, a mensagem (exit 0)
        {"exit": <n>, "stderr": "<texto>"}                         escreve no stderr e sai com n
        "contract": "<c>" (opcional)                               contract da saída (padrão: o da descrição)
        "extra": {...} (opcional)                                  chaves somadas à saída (para fugir do contrato)
        "echo": true (opcional)                                    acrescenta um item {"target": <target recebido em
                                                                   JSON>} aos itens
"""
import json
import os
import sys


def option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def record(argv, mode, data=None):
    with open(option(argv, "--record"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"mode": mode, "argv": argv, "input": data, "env": dict(os.environ)}) + "\n")


def main(argv):
    adapter = option(argv, "--adapter", "fake2")
    with open(option(argv, "--describe-file"), encoding="utf-8") as handle:
        described = json.load(handle)
    if isinstance(described, dict):
        described.setdefault("adapter", adapter)
    if "--describe" in argv:
        record(argv, "describe")
        print(json.dumps(described))
        return 0
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {"raw": raw}
    record(argv, "run", data)
    with open(option(argv, "--scenario"), encoding="utf-8") as handle:
        scenario = json.load(handle)
    answer = scenario.get(data.get("verb")) or scenario.get("*") or {}
    if "exit" in answer:
        sys.stderr.write(answer.get("stderr", "falha do adaptador falso") + "\n")
        return int(answer["exit"])
    contract = answer.get("contract") or (described.get("contract") if isinstance(described, dict) else None)
    items = list(answer.get("items", []))
    if answer.get("echo"):
        items.append({"target": json.dumps(data.get("target"), sort_keys=True)})
    out = {"contract": contract, "adapter": adapter, "capability": data.get("capability"), "verb": data.get("verb"),
           "status": "ok", "items": items, "truncated": bool(answer.get("truncated", False))}
    if answer.get("message"):
        out["message"] = answer["message"]
    if "error" in answer:
        out.update(status="error", items=[], truncated=False, message=answer["error"])
    out.update(answer.get("extra", {}))
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
