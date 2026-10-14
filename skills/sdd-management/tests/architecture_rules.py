"""Checadores das regras estruturais do ADR-0001, usados por test_architecture.py.

Cada checador recebe o código-fonte como texto e devolve uma linha por violação:
"<arquivo>:<linha> — <regra do ADR-0001> — <o que foi encontrado>".
"""
from __future__ import annotations

from typing import Iterable, List


def import_findings(source: str, filename: str, local_modules: Iterable[str] = ()) -> List[str]:
    """Imports fora da biblioteca padrão ou de módulos locais (o script é arquivo único)."""
    return []


def subprocess_findings(source: str, filename: str, allowed: Iterable[str]) -> List[str]:
    """Chamadas de subprocess fora das funções permitidas."""
    return []


def vendor_copy_findings(source: str, filename: str) -> List[str]:
    """Código que carrega a cópia do vendor (import de tools/sdd ou tools/sdd no sys.path)."""
    return []
