"""Coletor falso (SPEC-0033): escreve 25 linhas no stderr (a 24ª com um token) e sai com 1.

O scan mostra só as últimas 20 linhas do stderr, já mascaradas.
"""
import sys

token = "ghp_" + "Zx9" * 12
for number in range(1, 26):
    line = f"stderr-linha-{number:02d}"
    if number == 24:
        line += " token=" + token
    print(line, file=sys.stderr)
sys.exit(1)
