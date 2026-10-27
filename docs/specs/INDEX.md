# Índice de Specs

> Gerado por `spec_graph.py index` em 2026-10-27 — não edite manualmente.

## Saúde

- Validação (G0): **0 erro(s), 5 aviso(s)** — rode `spec_graph.py validate`
- Specs: implemented 14
- Impedimentos: **0 aberto(s)**, 12 resolvido(s)

## Cobertura de Pilares

Perfil: **minimo**

| Pilar | Situação | Detalhe |
|---|---|---|
| Arquitetura e fronteiras | coberto | ADR-0001 |
| Estratégia de testes | coberto | ADR-0002 |
| Qualidade de código | coberto | ADR-0003 |
| Entrega contínua e ambientes | dispensado | sem deploy nem ambientes: a skill é usada direto do checkout da main (link simbólico) ou copiada; release, versão e rollback estão no ADR-0005 |
| Fluxo de mudança | coberto | ADR-0005 |
| Segredos e dados sensíveis | dispensado | a skill e seus testes não usam credenciais nem dados pessoais; o board usa a autenticação da ferramenta do agente, nunca guardada aqui |

## Plano de Execução

Nenhuma spec aberta.

## Épicos

| Épico | Título | Status | Progresso |
|---|---|---|---|
| SPEC-0002 | Modo privado: SDD fora do repositório do time | implemented | 4/4 implementadas |

## Todas as Specs

| ID | Título | Tier | Tipo | Status | Criada | Épico | Depende de | Consome contrato |
|---|---|---|---|---|---|---|---|---|
| [SPEC-0001](SPEC-0001-ci-da-skill.md) | CI da skill: testes, lint e arquitetura | full | foundation | implemented | 2026-10-14 | — | — | — |
| [SPEC-0002](SPEC-0002-modo-privado.md) | Modo privado: SDD fora do repositório do time | epic | feature | implemented | 2026-10-14 | — | — | — |
| [SPEC-0003](SPEC-0003-registro-e-spec-root.md) | Registro do usuário e spec_root | full | feature | implemented | 2026-10-14 | SPEC-0002 | — | — |
| [SPEC-0004](SPEC-0004-leak-check.md) | Checagem de vazamento | full | feature | implemented | 2026-10-14 | SPEC-0002 | — | SPEC-0003@1 |
| [SPEC-0005](SPEC-0005-rastreio-sem-marcas.md) | Rastreio sem marcas no repositório | full | feature | implemented | 2026-10-14 | SPEC-0002 | — | SPEC-0003@1 |
| [SPEC-0006](SPEC-0006-pr-neutro-e-convencoes.md) | PR neutro, convenções do time e documentação do modo privado | full | feature | implemented | 2026-10-14 | SPEC-0002 | SPEC-0004, SPEC-0005 | SPEC-0003@1 |
| [SPEC-0007](SPEC-0007-pr-breaking-e-maiuscula.md) | PR do modo completo: breaking changes falso e texto em minúscula | lite | fix | implemented | 2026-10-14 | — | — | — |
| [SPEC-0008](SPEC-0008-spec-root-fora-do-repo.md) | Recusar spec_root dentro do repositório | lite | fix | implemented | 2026-10-14 | — | — | — |
| [SPEC-0009](SPEC-0009-gate-evidence-complemento.md) | gate --run grava o complemento de --evidence | lite | fix | implemented | 2026-10-14 | — | — | — |
| [SPEC-0010](SPEC-0010-isolamento-do-registro-nos-testes.md) | Testes antigos isolados do registro do usuário | lite | fix | implemented | 2026-10-14 | — | — | — |
| [SPEC-0011](SPEC-0011-documentos-vivos-guia-de-jornadas-e-mapa-do-sistema.md) | Documentos vivos: guia de jornadas e mapa do sistema | full | feature | implemented | 2026-10-26 | — | — | SPEC-0003@1 |
| [SPEC-0012](SPEC-0012-leak-check-acha-o-spec-root-tambem-pelo-caminho-nao-resolvid.md) | leak-check acha o spec_root também pelo caminho não resolvido | lite | fix | implemented | 2026-10-26 | — | SPEC-0011 | — |
| [SPEC-0013](SPEC-0013-novidades-da-skill-para-os-projetos-whats-new.md) | Novidades da skill para os projetos (whats-new) | full | feature | implemented | 2026-10-26 | — | — | SPEC-0003@1 |
| [SPEC-0014](SPEC-0014-validate-nao-sugere-a-politica-de-h2-ja-declarada.md) | validate não sugere a política de H2 já declarada | lite | fix | implemented | 2026-10-26 | — | — | — |
| [SPEC-0015](SPEC-0015-rodape-refs-decide-a-spec-do-commit.md) | Rodapé Refs decide a spec do commit | lite | fix | implemented | 2026-10-27 | — | — | — |

## ADRs

| ID | Título | Status | Garantido por (G3) |
|---|---|---|---|
| [ADR-0001](../adr/ADR-0001-arquitetura-e-fronteiras.md) | Arquitetura e fronteiras | accepted | SPEC-0001 |
| [ADR-0002](../adr/ADR-0002-estrategia-de-testes.md) | Estratégia de testes | accepted | SPEC-0001 |
| [ADR-0003](../adr/ADR-0003-qualidade-de-codigo.md) | Qualidade de código | accepted | SPEC-0001 |
| [ADR-0005](../adr/ADR-0005-fluxo-de-mudanca.md) | Fluxo de mudança e versionamento da skill | accepted | N/A — repositório privado no plano gratuito do GitHub não tem proteção de branch; `validate` aponta commits diretos e merges fora de PR |
| [ADR-0006](../adr/ADR-0006-modo-privado.md) | Modo privado: estado do SDD fora do repositório | accepted | SPEC-0003 |
