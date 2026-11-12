#!/usr/bin/env python3
"""`gh` falso sem autenticação (SPEC-0034:IT-03). Só biblioteca padrão.

FAKE_GH_AUTH escolhe a falha, como o gh real:
- missing (padrão): nenhuma conta logada — todo comando sai com 4 e pede `gh auth login`;
- bad: token inválido — `gh auth status` sai com 1 e `gh api ...` responde HTTP 401 (exit 1).
FAKE_GH_LOG, se definido, recebe uma linha JSON por chamada.
"""
import json
import os
import sys


def main(argv):
    path = os.environ.get("FAKE_GH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")
    if argv[:1] == ["--version"]:
        print("gh version 2.62.0 (fake)")
        return 0
    if os.environ.get("FAKE_GH_AUTH", "missing") == "bad":
        if argv[:2] == ["auth", "status"]:
            print("github.com\n  X Failed to log in to github.com account acme-bot (fake)\n"
                  "  - The token in GH_TOKEN is invalid.", file=sys.stderr)
            return 1
        print(json.dumps({"message": "Bad credentials", "documentation_url": "https://docs.github.com/rest",
                          "status": "401"}))
        print("gh: Bad credentials (HTTP 401)", file=sys.stderr)
        return 1
    print("To get started with GitHub CLI, please run:  gh auth login\n"
          "Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.",
          file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
