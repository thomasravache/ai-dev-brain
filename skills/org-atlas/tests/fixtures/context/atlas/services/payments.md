# payments

Serviço `service:payments` do atlas de Acme. As regiões `atlas:` são geradas pelo `atlas.py build` a partir do
`graph.json`; o resto da página é do time e nunca é reescrito.

## Resumo

<!-- atlas:begin summary -->
- Chave: `service:payments`
- Visto em: 2026-11-02
- Fontes: facts
- description: processa pagamentos
<!-- atlas:end summary -->

## Repositório

<!-- atlas:begin repository -->
- [payments](../platform/code.md) (`repository:acme/payments`)
<!-- atlas:end repository -->

## Deployments

<!-- atlas:begin deployments -->
- **prod**: `payments-prod`
<!-- atlas:end deployments -->

## Depende de

<!-- atlas:begin depends-on -->
- [payments-db](../platform/data.md) (`datastore:payments-db`) — inferida de `DB_URL=db.interno`
<!-- atlas:end depends-on -->

## Usado por

<!-- atlas:begin used-by -->
- [backoffice](backoffice.md) — inferida de `PAYMENTS_URL=payments`
<!-- atlas:end used-by -->

## Donos

<!-- atlas:begin owners -->
_(nenhum)_
<!-- atlas:end owners -->

## Pipelines

<!-- atlas:begin pipelines -->
_(nenhum)_
<!-- atlas:end pipelines -->

## Fontes

<!-- atlas:begin sources -->
- facts (visto em 2026-11-02)
<!-- atlas:end sources -->

## Notas

