#!/usr/bin/env python3
"""`gh` falso (SPEC-0034:IT-02, IT-03, CT-01): responde `gh api <caminho>` com as respostas gravadas de uma
organização fictícia, no formato que o `gh api` devolve. Só biblioteca padrão.

Os testes copiam este arquivo como `gh` para uma pasta no início do PATH. Variáveis:
- FAKE_GH_FIXTURES: pasta das respostas (padrão: fixtures/github/acme, ao lado deste arquivo);
- FAKE_GH_ORG: organização que existe (padrão: acme); qualquer outra responde 404;
- FAKE_GH_LOG: arquivo onde cada chamada é anotada (uma linha JSON com os argumentos).

Comandos: `gh --version`, `gh auth status` (sempre autenticado) e `gh api [opções] <caminho>`. O caminho é
reconhecido sem a barra inicial e sem a query string; opções aceitas e ignoradas: --paginate, --slurp, --silent,
-i/--include, -H/--header (só `Accept: ...raw...` muda a resposta de um arquivo), -X/--method GET, -f/-F (campos
da query, por exemplo state=all e per_page=N: a lista vem sempre inteira, quem limita a amostra é o coletor),
--hostname e --cache. --jq/-q e --template/-t não são suportados (o coletor lê o JSON com a biblioteca padrão).

Rotas (repositório existe se está em repos.json):
    orgs/<org>/repos                     -> repos.json
    repos/<org>/<repo>                   -> repo/<repo>.json
    repos/<org>/<repo>/actions/workflows -> workflows/<repo>.json ({"total_count": 0, "workflows": []} sem arquivo)
    repos/<org>/<repo>/pulls             -> pulls/<repo>.json ([] sem arquivo)
    repos/<org>/<repo>/contents[/<p>]    -> árvore de arquivos do repositório (listagem de pasta ou arquivo
                                            com conteúdo base64; Accept raw devolve o texto)
A árvore de cada repositório tem README.md, os arquivos de workflow, o CODEOWNERS de codeowners/<repo> (em
.github/CODEOWNERS ou no caminho da primeira linha `# fake-gh-path: <caminho>`) e o template de PR de
pr-template/<repo> (primeira linha = caminho; terminando em `/` é a pasta PULL_REQUEST_TEMPLATE/ com feature.md).
Caminhos diferenciam maiúsculas de minúsculas, como no GitHub. Qualquer outra rota: 404 como o gh real
(corpo JSON no stdout, `gh: Not Found (HTTP 404)` no stderr, exit 1).
"""
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = Path(os.environ.get("FAKE_GH_FIXTURES") or HERE / "acme")
ORG = os.environ.get("FAKE_GH_ORG", "acme")
# arquivos extras para a busca do template não achar nome parecido
DECOYS = {"mobile": {".github/ISSUE_TEMPLATE/bug.md": "## Bug\n"}, "legacy": {"docs/CONTRIBUTING.md": "# Contribua\n"}}
VALUE_OPTIONS = {"-H", "--header", "-X", "--method", "-f", "--raw-field", "-F", "--field", "--hostname", "--cache",
                 "-p", "--preview", "--input"}
FLAG_OPTIONS = {"--paginate", "--slurp", "--silent", "-i", "--include", "--verbose"}
UNSUPPORTED = {"--jq", "-q", "--template", "-t"}


def log(argv):
    path = os.environ.get("FAKE_GH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")


def not_found():
    print(json.dumps({"message": "Not Found", "documentation_url": "https://docs.github.com/rest", "status": "404"}))
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    return 1


def emit(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def read_json(path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def repo_names():
    return [repo["name"] for repo in read_json(FIXTURES / "repos.json", [])]


def tree(repo):
    """{caminho: conteúdo} dos arquivos do repositório."""
    files = {"README.md": f"# {repo}\n"}
    workflows = read_json(FIXTURES / "workflows" / f"{repo}.json", {"workflows": []})
    for workflow in workflows.get("workflows", []):
        files[workflow["path"]] = f"name: {workflow['name']}\n"
    codeowners = FIXTURES / "codeowners" / repo
    if codeowners.is_file():
        text = codeowners.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        path = ".github/CODEOWNERS"
        if first.startswith("# fake-gh-path:"):
            path = first.split(":", 1)[1].strip()
        files[path] = text
    template = FIXTURES / "pr-template" / repo
    if template.is_file():
        lines = template.read_text(encoding="utf-8").splitlines()
        path, body = lines[0].strip(), "\n".join(lines[1:]) + "\n"
        files[path + "feature.md" if path.endswith("/") else path] = body
    files.update(DECOYS.get(repo, {}))
    return files


def entry(repo, path, kind, size=0):
    return {"name": path.rsplit("/", 1)[-1], "path": path, "type": kind, "size": size,
            "sha": hashlib.sha1(path.encode("utf-8")).hexdigest(),
            "url": f"https://api.github.com/repos/{ORG}/{repo}/contents/{path}"}


def contents(repo, path, raw):
    files = tree(repo)
    path = path.strip("/")
    if path in files:
        text = files[path]
        if raw:
            sys.stdout.write(text)
            return 0
        data = entry(repo, path, "file", len(text.encode("utf-8")))
        data.update(encoding="base64", content=base64.encodebytes(text.encode("utf-8")).decode("ascii"))
        return emit(data)
    prefix = f"{path}/" if path else ""
    children = {}
    for name in files:
        if name.startswith(prefix):
            rest = name[len(prefix):]
            child, _, deeper = rest.partition("/")
            children[child] = "dir" if deeper else "file"
    if not children:
        return not_found()
    return emit([entry(repo, prefix + name, kind) for name, kind in sorted(children.items())])


def api(args):
    path, raw = None, False
    i = 0
    while i < len(args):
        arg = args[i]
        name = arg.split("=", 1)[0]
        if name in UNSUPPORTED:
            print(f"gh falso: {name} não suportado — leia o JSON no coletor", file=sys.stderr)
            return 2
        if name in VALUE_OPTIONS:
            value = arg.split("=", 1)[1] if "=" in arg else (args[i + 1] if i + 1 < len(args) else "")
            if name in ("-H", "--header") and value.lower().startswith("accept") and "raw" in value.lower():
                raw = True
            i += 1 if "=" in arg else 2
            continue
        if name in FLAG_OPTIONS:
            i += 1
            continue
        if path is None and not arg.startswith("-"):
            path = arg
        i += 1
    if path is None:
        print("gh falso: faltou o caminho da API", file=sys.stderr)
        return 2
    parts = path.split("?", 1)[0].strip("/").split("/")
    if parts[:1] == ["orgs"] and len(parts) == 3 and parts[2] == "repos":
        return emit(read_json(FIXTURES / "repos.json", [])) if parts[1] == ORG else not_found()
    if parts[:1] != ["repos"] or len(parts) < 3 or parts[1] != ORG or parts[2] not in repo_names():
        return not_found()
    repo, rest = parts[2], parts[3:]
    if not rest:
        data = read_json(FIXTURES / "repo" / f"{repo}.json")
        return emit(data) if data is not None else not_found()
    if rest == ["actions", "workflows"]:
        return emit(read_json(FIXTURES / "workflows" / f"{repo}.json", {"total_count": 0, "workflows": []}))
    if rest == ["pulls"]:
        return emit(read_json(FIXTURES / "pulls" / f"{repo}.json", []))
    if rest[0] == "contents":
        return contents(repo, "/".join(rest[1:]), raw)
    return not_found()


def main(argv):
    log(argv)
    if argv[:1] == ["--version"]:
        print("gh version 2.62.0 (fake)")
        return 0
    if argv[:2] == ["auth", "status"]:
        print("github.com\n  ✓ Logged in to github.com account acme-bot (fake)")
        return 0
    if argv[:1] == ["api"]:
        return api(argv[1:])
    print(f"gh falso: comando não suportado: {' '.join(argv)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
