---
id: merge-method-squash
title: Merge de PR só por squash
kind: merge-method
scope: organization
status: inferred
proposed_at: 2026-11-02
confirmed_by:
confirmed_at:
confirmed_via:
reason:
---

# Merge de PR só por squash

Convenção proposta pelo `atlas.py curate` a partir dos sinais dos coletores do atlas de Acme. Enquanto
`status` for `inferred` ela é só uma proposta: vale como regra só depois de `atlas.py curate confirm` (ou é
descartada por `curate reject`), sempre por uma pessoa. A região `evidence` é atualizada a cada `scan`; o resto do
arquivo é do time e nunca é reescrito.

## Evidência

<!-- atlas:begin evidence -->
- Padrão: só `squash` permitido
- Repositórios com o sinal: 5; seguem o padrão: 5 (100%)
  - acme/backoffice: segue
  - acme/payments: segue
  - acme/r3: segue
  - acme/r4: segue
  - acme/r5: segue
<!-- atlas:end evidence -->

## Notas

