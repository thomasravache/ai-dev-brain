#!/usr/bin/env python3
"""`kubectl` falso (SPEC-0035:IT-02, IT-03, CT-01): responde `kubectl get applications.argoproj.io -A -o json` com
as Applications gravadas de um cluster fictício, no formato da CLI real (objeto List com items). Só biblioteca
padrão.

Os testes copiam este arquivo como `kubectl` para uma pasta no início do PATH. Variáveis:
- FAKE_KUBECTL_OUTPUT: arquivo com a resposta (padrão: acme/kubectl-applications.json, ao lado deste arquivo);
- FAKE_CLI_LOG: arquivo onde cada chamada é anotada (uma linha JSON {"cli": "kubectl", "argv": [...]});
- FAKE_CLI_FAIL: falha simulada, como a CLI real:
    unauthenticated = credencial inválida ("You must be logged in to the server (Unauthorized)", exit 1);
    forbidden       = RBAC nega o list ("Error from server (Forbidden): ...", exit 1);
    garbage         = exit 0 com uma resposta que não é JSON;
    shape           = exit 0 com JSON que não é uma lista de Applications.

Comandos: `kubectl version [--client]` e `kubectl get <recurso> [opções]`. Só o recurso
`applications.argoproj.io` existe (qualquer outro: "the server doesn't have a resource type", exit 1; Secrets
nunca são servidos). Com -A/--all-namespaces vêm as Applications de todos os namespaces; sem ele, só as do
namespace de -n/--namespace (padrão `default`, onde não há nenhuma), como no kubectl real. Com `-o json` (também
`-o=json`, `-ojson`, `--output json`, `--output=json`) imprime JSON; sem ele, a tabela padrão (não é JSON).
Opções globais (--context, --kubeconfig, --request-timeout...) são aceitas e ignoradas.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get("FAKE_KUBECTL_OUTPUT") or HERE / "acme" / "kubectl-applications.json")
RESOURCE = "applications.argoproj.io"
VALUE_OPTIONS = {"-o", "--output", "-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user",
                 "-l", "--selector", "--field-selector", "--request-timeout", "--chunk-size", "-s", "--server"}
ALL_NAMESPACES = {"-A", "--all-namespaces", "--all-namespaces=true"}


def log(argv):
    path = os.environ.get("FAKE_CLI_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"cli": "kubectl", "argv": argv}) + "\n")


def parse(argv):
    """(palavras posicionais, formato de saída, namespace, todos os namespaces) dos argumentos."""
    words, output, namespace, everything, i = [], "", "default", False, 0
    while i < len(argv):
        arg = argv[i]
        name, eq, value = arg.partition("=")
        if arg in ALL_NAMESPACES:
            everything = True
        elif arg.startswith("-o") and len(arg) > 2 and not eq:  # -ojson
            output = arg[2:]
        elif name in VALUE_OPTIONS:
            if not eq:
                value = argv[i + 1] if i + 1 < len(argv) else ""
                i += 1
            if name in ("-o", "--output"):
                output = value
            elif name in ("-n", "--namespace"):
                namespace = value
        elif not arg.startswith("-"):
            words.append(arg)
        i += 1
    return words, output, namespace, everything


def table(items):
    lines = ["NAMESPACE   NAME            SYNC STATUS   HEALTH STATUS"]
    for item in items:
        status = item.get("status", {})
        lines.append(f"{item['metadata']['namespace']}   {item['metadata']['name']}   "
                     f"{status.get('sync', {}).get('status')}   {status.get('health', {}).get('status')}")
    return "\n".join(lines) + "\n"


def main(argv):
    log(argv)
    words, output, namespace, everything = parse(argv)
    if words[:1] == ["version"]:
        print("Client Version: v1.31.2+fake")
        return 0
    if words[:1] != ["get"] or len(words) != 2:
        print(f"kubectl falso: comando não suportado: {' '.join(argv)}", file=sys.stderr)
        return 2
    if words[1] != RESOURCE:
        print(f'error: the server doesn\'t have a resource type "{words[1]}"', file=sys.stderr)
        return 1
    failure = os.environ.get("FAKE_CLI_FAIL", "")
    if failure == "unauthenticated":
        print("error: You must be logged in to the server (Unauthorized)", file=sys.stderr)
        return 1
    if failure == "forbidden":
        print('Error from server (Forbidden): applications.argoproj.io is forbidden: User '
              '"system:serviceaccount:atlas:reader" cannot list resource "applications" in API group '
              '"argoproj.io" at the cluster scope', file=sys.stderr)
        return 1
    if failure == "garbage":
        print("<html><body><h1>502 Bad Gateway</h1></body></html>")
        return 0
    if failure == "shape":
        print("42")
        return 0
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if not everything:
        data = dict(data, items=[i for i in data["items"] if i["metadata"].get("namespace") == namespace])
    if output != "json":
        if not data["items"]:
            print(f"No resources found in {namespace} namespace.", file=sys.stderr)
            return 0
        sys.stdout.write(table(data["items"]))
        return 0
    print(json.dumps(data, indent=4, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
