# backoffice

Serviço `service:backoffice` do atlas de Acme. As regiões `atlas:` são geradas pelo `atlas.py build` a partir do
`graph.json`; o resto da página é do time e nunca é reescrito.

## Resumo

<!-- atlas:begin summary -->
- Chave: `service:backoffice`
- Visto em: 2026-11-02
- Fontes: facts
<!-- atlas:end summary -->

## Repositório

<!-- atlas:begin repository -->
- [backoffice](../platform/code.md) (`repository:acme/backoffice`)
<!-- atlas:end repository -->

## Deployments

<!-- atlas:begin deployments -->
- **prod**: `backoffice-prod`
<!-- atlas:end deployments -->

## Depende de

<!-- atlas:begin depends-on -->
- [payments](payments.md) — inferida de `PAYMENTS_URL=payments`
<!-- atlas:end depends-on -->

## Usado por

<!-- atlas:begin used-by -->
_(nenhum)_
<!-- atlas:end used-by -->

## Donos

<!-- atlas:begin owners -->
- pay (`acme/pay`)
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


O backoffice é onde o time de operações aprova o cashout dos lojistas.
