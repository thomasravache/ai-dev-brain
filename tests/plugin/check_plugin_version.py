"""Checagem da versão do plugin fermion (SPEC-0056).

Um PR que muda `skills/**` precisa subir a `version` do `.claude-plugin/plugin.json` (`AAAA.MM.N`, comparada como
tupla de inteiros), senão `claude plugin update` não traz a mudança: o Claude Code usa a versão como chave do cache.

Uso, na raiz do repositório: python3 tests/plugin/check_plugin_version.py --base origin/main
Sai com 1 e imprime os achados quando há achado; 0 quando não há. Só stdlib, Python 3.9+.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_JSON = ".claude-plugin/plugin.json"
SKILLS_PREFIX = "skills/"
VERSION_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d+)$")


def parse_version(version):
    """`AAAA.MM.N` como tupla de inteiros, ou None fora do formato."""
    match = VERSION_RE.match(version) if isinstance(version, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def version_findings(changed_paths, base_version, head_version):
    """Achados da regra (lista vazia = ok): mudou `skills/**` e a versão da HEAD não é maior que a da base."""
    if not any(path.startswith(SKILLS_PREFIX) for path in changed_paths):
        return []
    head = parse_version(head_version)
    if head is None:
        return [f"plugin-version: versão da HEAD {head_version!r} fora de AAAA.MM.N em {PLUGIN_JSON}"]
    base = parse_version(base_version)
    if base is not None and head <= base:
        return [(f"plugin-version: skills/** mudou, mas a versão de {PLUGIN_JSON} ({head_version}) não é maior "
                 f"que a da base ({base_version}); suba para AAAA.MM.N maior, senão `claude plugin update` "
                 f"não traz a mudança")]
    return []


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def base_plugin_version(base):
    """Versão do plugin.json na base, ou None se o arquivo não existe lá."""
    result = subprocess.run(["git", "show", f"{base}:{PLUGIN_JSON}"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return json.loads(result.stdout).get("version")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Confere se a versão do plugin subiu quando skills/** mudou.")
    parser.add_argument("--base", required=True, help="ref da base do PR (ex.: origin/main)")
    args = parser.parse_args(argv)

    base_version = base_plugin_version(args.base)
    if base_version is None:
        print(f"ok: {PLUGIN_JSON} não existe em {args.base}; nada a exigir")
        return 0
    changed = git("diff", "--name-only", f"{args.base}...HEAD").splitlines()
    head_version = json.loads(Path(PLUGIN_JSON).read_text(encoding="utf-8")).get("version")

    findings = version_findings(changed, base_version, head_version)
    for finding in findings:
        print(finding)
    if not findings:
        print(f"ok: versão do plugin {base_version} -> {head_version}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
