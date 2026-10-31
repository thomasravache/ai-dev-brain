"""Coletor falso (SPEC-0033): planta um token e uma URL com senha em attrs (valores montados em tempo de
execução, nunca literais no arquivo). O scan precisa gravar só [REDACTED] e contar 2.

Uso: python3 planted_secrets.py <id-do-coletor>
"""
import json
import sys

collector = sys.argv[1] if len(sys.argv) > 1 else "fake-secrets"
token = "ghp_" + "Zx9" * 12
password = "s3nh4" + "-fake-" + "0033"
print(json.dumps({
    "contract": "org-atlas/collector@1",
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": [
        {"kind": "repository", "id": "acme/api", "name": "api",
         "attrs": {"description": "deploy usa " + token + " no CI",
                   "clone_url": "https://bot:" + password + "@git.acme.example/acme/api.git",
                   "default_branch": "main"},
         "source": collector},
    ],
    "relations": [],
}))
