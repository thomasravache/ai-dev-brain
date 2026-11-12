#!/usr/bin/env python3
"""`argocd` falso (SPEC-0035:IT-02, IT-03, CT-01): responde `argocd app list -o json` com as Applications gravadas
de um cluster fictício, no formato da CLI real (lista JSON de Applications). Só biblioteca padrão.

Os testes copiam este arquivo como `argocd` para uma pasta no início do PATH. Variáveis:
- FAKE_ARGOCD_OUTPUT: arquivo com a resposta (padrão: acme/argocd-app-list.json, ao lado deste arquivo);
- FAKE_CLI_LOG: arquivo onde cada chamada é anotada (uma linha JSON {"cli": "argocd", "argv": [...]});
- FAKE_CLI_FAIL: falha simulada, como a CLI real:
    unauthenticated = sessão inválida ou expirada (rpc error Unauthenticated, exit 20);
    forbidden       = RBAC nega a leitura (rpc error PermissionDenied, exit 20);
    garbage         = exit 0 com uma resposta que não é JSON;
    shape           = exit 0 com JSON que não é uma lista de Applications;
    unconfigured    = nenhum contexto/servidor configurado ("Argo CD server address unspecified", exit 20;
                      revisão G4).

Comandos: `argocd version [--client]` e `argocd app list [opções]`. Com `-o json` (também `-o=json`, `-ojson`,
`--output json`, `--output=json`) imprime o arquivo; sem ele, a tabela que a CLI imprime por padrão (não é JSON).
Opções globais (--server, --grpc-web, --insecure, --plaintext, --core, --auth-token...) são aceitas e ignoradas.
Qualquer outro comando (`app get`, `app manifests`, `app resources`...) sai com 2: o coletor só lê a lista.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get("FAKE_ARGOCD_OUTPUT") or HERE / "acme" / "argocd-app-list.json")
VALUE_OPTIONS = {"-o", "--output", "--server", "--config", "--context", "--auth-token", "--grpc-web-root-path",
                 "-H", "--header", "--loglevel", "--logformat", "--port-forward-namespace", "-l", "--selector",
                 "-p", "--project", "-r", "--repo", "-c", "--cluster", "-N", "--app-namespace"}


def log(argv):
    path = os.environ.get("FAKE_CLI_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"cli": "argocd", "argv": argv}) + "\n")


def parse(argv):
    """(palavras posicionais, formato de saída) dos argumentos."""
    words, output, i = [], "", 0
    while i < len(argv):
        arg = argv[i]
        name, eq, value = arg.partition("=")
        if arg.startswith("-o") and len(arg) > 2 and not eq:  # -ojson
            output = arg[2:]
        elif name in VALUE_OPTIONS:
            if not eq:
                value = argv[i + 1] if i + 1 < len(argv) else ""
                i += 1
            if name in ("-o", "--output"):
                output = value
        elif not arg.startswith("-"):
            words.append(arg)
        i += 1
    return words, output


def table(apps):
    lines = ["NAME           CLUSTER                         NAMESPACE         PROJECT   STATUS     HEALTH"]
    for app in apps:
        dest = app.get("spec", {}).get("destination", {})
        status = app.get("status", {})
        lines.append(f"argocd/{app['metadata']['name']}  {dest.get('server') or dest.get('name')}  "
                     f"{dest.get('namespace')}  {app['spec'].get('project')}  "
                     f"{status.get('sync', {}).get('status')}  {status.get('health', {}).get('status')}")
    return "\n".join(lines) + "\n"


def fatal(message):
    print(f'time="2026-10-30T12:00:00Z" level=fatal msg="{message}"', file=sys.stderr)
    return 20


def main(argv):
    log(argv)
    words, output = parse(argv)
    if words[:1] == ["version"]:
        print("argocd: v2.13.1+fake")
        return 0
    if words != ["app", "list"]:
        print(f"argocd falso: comando não suportado: {' '.join(argv)}", file=sys.stderr)
        return 2
    failure = os.environ.get("FAKE_CLI_FAIL", "")
    if failure == "unauthenticated":
        return fatal("rpc error: code = Unauthenticated desc = invalid session: token has invalid claims: "
                     "token is expired")
    if failure == "forbidden":
        return fatal("rpc error: code = PermissionDenied desc = permission denied: applications, list")
    if failure == "unconfigured":
        return fatal("Argo CD server address unspecified")
    if failure == "garbage":
        print("<html><body><h1>502 Bad Gateway</h1></body></html>")
        return 0
    if failure == "shape":
        print("42")
        return 0
    text = OUTPUT.read_text(encoding="utf-8")
    if output != "json":
        sys.stdout.write(table(json.loads(text)))
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
