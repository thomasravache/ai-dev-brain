#!/usr/bin/env python3
"""`gh` falso (SPEC-0034:IT-02, IT-03, CT-01): responde `gh api <caminho>` com as respostas gravadas de uma
organização fictícia, no formato que o `gh api` devolve. Só biblioteca padrão.

Os testes copiam este arquivo como `gh` para uma pasta no início do PATH. Variáveis:
- FAKE_GH_FIXTURES: pasta das respostas (padrão: fixtures/github/acme, ao lado deste arquivo);
- FAKE_GH_ORG: organização que existe (padrão: acme); qualquer outra responde 404;
- FAKE_GH_LOG: arquivo onde cada chamada é anotada (uma linha JSON com os argumentos);
- FAKE_GH_PAGINATE_SIZE: com --paginate, o tamanho de cada página impressa (padrão: per_page ou 30);
- FAKE_GH_FAIL: falha simulada (revisão G4): `rate-limit` = todo `gh api` responde HTTP 403 "API rate limit
  exceeded"; `forbidden` = orgs/<org>/repos responde HTTP 403 "Forbidden" (sem acesso);
- FAKE_GH_FAIL_ON: com FAKE_GH_FAIL=rate-limit, só os caminhos que contêm este texto falham (ex.: /pulls).

Comandos: `gh --version`, `gh auth status` (sempre autenticado) e `gh api [opções] <caminho>`. O caminho é
reconhecido sem a barra inicial; org e repositório sem diferença de caixa (como no GitHub; a resposta traz o
nome canônico). Opções aceitas: --paginate, --slurp, --silent, -i/--include, -H/--header (só `Accept: ...raw...`
muda a resposta de um arquivo), -X/--method GET, -f/-F e a query string (page e per_page valem nas listas),
--hostname e --cache. --jq/-q e --template/-t não são suportados (o coletor lê o JSON com a biblioteca padrão).

Paginação das listas (repos, pulls e os workflows de actions/workflows), como na API: sem --paginate vem só a
página `page` (padrão 1) com `per_page` itens (padrão 30, máximo 100); com --paginate vêm todas as páginas, uma
depois da outra no stdout (`[...][...]`), como o gh imprime.

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
from urllib.parse import parse_qsl

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


def fail(status, message):
    print(json.dumps({"message": message, "documentation_url": "https://docs.github.com/rest", "status": str(status)}))
    print(f"gh: {message} (HTTP {status})", file=sys.stderr)
    return 1


def page_of(items, query, paginate, key=None):
    """A página pedida (ou, com --paginate, todas em sequência) de uma lista; key = lista dentro de um objeto."""
    per_page = min(int(query.get("per_page", 30)), 100)
    size = int(os.environ.get("FAKE_GH_PAGINATE_SIZE") or per_page) if paginate else per_page
    chunks = [items[i:i + size] for i in range(0, len(items), size)] or [[]]

    def wrap(chunk):
        return chunk if key is None else {"total_count": len(items), key: chunk}

    if paginate:
        for chunk in chunks:
            print(json.dumps(wrap(chunk), ensure_ascii=False))
        return 0
    page = int(query.get("page", 1))
    return emit(wrap(chunks[page - 1] if 0 < page <= len(chunks) else []))


def api(args):
    path, raw, paginate, query = None, False, False, {}
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
            if name in ("-f", "--raw-field", "-F", "--field") and "=" in value:
                query.update([value.split("=", 1)])
            i += 1 if "=" in arg else 2
            continue
        if name in FLAG_OPTIONS:
            paginate = paginate or name == "--paginate"
            i += 1
            continue
        if path is None and not arg.startswith("-"):
            path = arg
        i += 1
    if path is None:
        print("gh falso: faltou o caminho da API", file=sys.stderr)
        return 2
    base, _, qs = path.partition("?")
    query = dict(parse_qsl(qs), **query)
    parts = base.strip("/").split("/")
    failure = os.environ.get("FAKE_GH_FAIL", "")
    if failure == "rate-limit" and os.environ.get("FAKE_GH_FAIL_ON", "") in base:
        return fail(403, "API rate limit exceeded for user ID 4242.")
    names = {name.lower(): name for name in repo_names()}
    if parts[:1] == ["orgs"] and len(parts) == 3 and parts[2] == "repos":
        if parts[1].lower() != ORG.lower():
            return not_found()
        if failure == "forbidden":
            return fail(403, "Forbidden")
        return page_of(read_json(FIXTURES / "repos.json", []), query, paginate)
    if (parts[:1] != ["repos"] or len(parts) < 3 or parts[1].lower() != ORG.lower()
            or parts[2].lower() not in names):
        return not_found()
    repo, rest = names[parts[2].lower()], parts[3:]
    if not rest:
        data = read_json(FIXTURES / "repo" / f"{repo}.json")
        return emit(data) if data is not None else not_found()
    if rest == ["actions", "workflows"]:
        data = read_json(FIXTURES / "workflows" / f"{repo}.json", {"total_count": 0, "workflows": []})
        return page_of(data.get("workflows", []), query, paginate, key="workflows")
    if rest == ["pulls"]:
        return page_of(read_json(FIXTURES / "pulls" / f"{repo}.json", []), query, paginate)
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
