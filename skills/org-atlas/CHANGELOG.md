# Changelog

Todas as mudanças relevantes da skill `org-atlas` são documentadas aqui. Este arquivo viaja com a skill (fica na
pasta dela).

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
As versões são as de `ATLAS_VERSION` (`AAAA.MM.N`), uma seção por versão, a mais nova primeiro (ADR-0010, ADR-0005).
Cada entrada cita a spec de origem (`SPEC-NNNN`).

## [Unreleased]

## [2026.10.2] - 2026-10-30

### Added
- Comando `scan [--only id,...] [--json]` (`ATLAS_VERSION` 2026.10.2): roda os coletores declarados em `collectors` (`id`, `category`, `command` como lista sem shell, `timeout` padrão 300 s, `enabled`; marcadores `{skill}` e `{atlas}`; caminho absoluto em `command` sai com 2), valida a saída contra o contrato `org-atlas/collector@1` (ADR-0011), descarta e reporta chaves de `attrs` proibidas, mascara segredos (`[REDACTED]`, só a contagem no relatório), grava `snapshots/<id>.json` normalizado e `snapshots/_scan.json` (`seen_at`, `status`, contagens) e mostra o diff por coletor. Um coletor com falha (exit ≠ 0, timeout, JSON inválido, violação do contrato) mantém o snapshot anterior e o `seen_at`, não para os outros e faz o scan sair com 1; o stderr é mascarado inteiro e depois cortado nas últimas 20 linhas. Só os campos do contrato chegam ao snapshot: campo fora do contrato (na saída, na entidade, na relação ou no sinal) e chave proibida (`password`, `passwd`, `pwd`, `secret`, `token`, `key`, `credential`, `private`, também nos sinais) são descartados e reportados sem o valor. Campo do contrato com tipo errado (por exemplo `name` ou `source` como objeto, `sample` com objeto, `pattern_counts` aninhado, `counts` que não é objeto de números, `present` que não é objeto de booleanos) é violação, sem repetir o valor. Sem coletor habilitado nada é gravado (SPEC-0033).
- `run_collector`, a única função do `atlas.py` que executa processo externo: lista de argumentos, sem shell, pasta temporária, grupo de processos próprio encerrado no timeout (SPEC-0033).
- Funções `validate_collector_output`, `redact` (também nas chaves dos objetos, com `[REDACTED]#2`… em colisão; chave privada PEM e PGP; URL com usuário vazio ou senha com `/` e `@`; tokens colados a pontuação, sem falso positivo dentro de palavras; casamento de largura zero nunca mascara; `extra_patterns` que casa com o texto vazio sai com 2), `normalize` e `diff_snapshots`, reaproveitadas pelo `lint` (SPEC-0033).
- `references/collector-contract.md` (contrato, mensagens de violação e exemplos válidos e inválidos) e `references/redaction.md` (padrões embutidos e `redaction.extra_patterns`); `assets/atlas-config.yml` documenta `collectors` e `redaction` (SPEC-0033).

## [2026.10.1] - 2026-10-30

### Added
- Skill `org-atlas`: `SKILL.md` com "Antes de qualquer fluxo" (`config`; exit 3 → onboarding) e o onboarding (organização, modo `repo` ou `local`, pasta do atlas, `git init` pelo agente no modo local, credenciais só pelo nome); `references/config.md` e `references/atlas-layout.md`; `assets/atlas-config.yml` padrão e os esqueletos `ATLAS.md` e `glossary.md` com regiões `<!-- atlas:begin/end <nome> -->` em `assets/pages/` (SPEC-0032).
- `scripts/atlas.py` (`ATLAS_VERSION` 2026.10.1, só biblioteca padrão): configuração em duas camadas (`$ATLAS_CONFIG_HOME/config.yml` local e `<atlas>/atlas-config.yml` compartilhada) com a origem de cada valor; `credentials` só com nomes de variável (`^[A-Z_][A-Z0-9_]*$`) e de profile; parser e escritor de YAML próprios; comandos `init` (pasta vazia, repetido igual, `--force` com `.bak` que nunca sobrescreve um backup antigo, `--join` sem `--org`/`--mode`/`--force`), `config [--json]` e `doctor [--json]`, que nunca executa processo nem imprime o valor de uma variável e acusa `atlas` relativo ou ilegível; erros de sistema de arquivos saem com 1 sem traceback (SPEC-0032).
- Testes de arquitetura do ADR-0010 e suíte da skill na CI (SPEC-0032).
