"""Coletor de terceiro da versão anterior (SPEC-0071): imprime uma saída fixa e válida com o nome antigo do contrato
(org-atlas/collector@1, aceito até a SPEC-0073), com dois serviços, um banco e as relações entre eles. É a prova de
compatibilidade: o fixture do MCP (mcp/tests/fixtures/collector.py) passou a emitir o nome novo.

Uso: python3 legacy_contract.py <id-do-coletor>
"""
import json
import sys

OLD_CONTRACT = "org" + "-atlas/collector@1"  # montado por partes: o nome antigo só aparece como reserva
collector = sys.argv[1] if len(sys.argv) > 1 else "legacy"
print(json.dumps({
    "contract": OLD_CONTRACT,
    "collector": collector,
    "category": "code",
    "collected_at": "2026-10-30T12:00:00Z",
    "entities": [
        {"kind": "service", "id": "billing", "name": "billing", "attrs": {"tier": 2}, "source": collector},
        {"kind": "service", "id": "api", "name": "api", "attrs": {"tier": 1}, "source": collector},
        {"kind": "datastore", "id": "payments-db", "name": "payments-db", "attrs": {"engine": "postgres"},
         "source": collector},
    ],
    "relations": [
        {"from": "service:billing", "to": "service:api", "type": "depends_on", "source": collector},
        {"from": "service:api", "to": "datastore:payments-db", "type": "depends_on", "source": collector},
    ],
}))
