# Atlas — Acme

Mapa de como a organização desenvolve e opera software, mantido pela skill `org-atlas` junto com os agentes.
O texto fora das regiões geradas é de quem mantém o atlas: o `atlas.py` nunca o reescreve.

## Sobre

<!-- atlas:begin about -->
Estrutura: `services/` (um serviço por página), `platform/` (infraestrutura e entrega), `conventions/`
(padrões de código e de repositório), `process/` (como o time trabalha), `glossary.md` (termos), `graph.json`
(o grafo de entidades e relações) e `snapshots/` (saída dos coletores). Configuração compartilhada em
`atlas-config.yml`.
<!-- atlas:end about -->

## Resumo

<!-- atlas:begin summary -->
- 14 entidades, 11 relações (4 inferidas), 0 conflitos
- repository: 5
- service: 4
- environment: 1
- deployment: 2
- datastore: 1
- team: 1
- Plataforma: [code](platform/code.md), [data](platform/data.md), [delivery](platform/delivery.md)
<!-- atlas:end summary -->

## Serviços

<!-- atlas:begin services -->
- [backoffice](services/backoffice.md) — repositório `acme/backoffice`
- [ledger](services/ledger.md)
- [payments](services/payments.md) — repositório `acme/payments`
- [search](services/search.md)
<!-- atlas:end services -->

## Última coleta

<!-- atlas:begin scans -->
- facts: 2026-11-02 (ok, 11 entidades, 7 relações)
- signals: 2026-11-02 (ok, 5 entidades, 0 relações)
<!-- atlas:end scans -->
