---
id: ADR-0023
title: Probes só de leitura por adaptador, com verbos permitidos, produção confirmada e registro local
status: accepted
origin: decision
date: 2026-11-22
pillars: []
decision_makers: []
consulted: []
informed: []
supersedes:
superseded_by:
enforced_by: testes da SPEC-0088 (UT-02 a UT-06, CT-01) e da SPEC-0089 (UT-01, UT-05)
---

# ADR-0023 — Probes só de leitura por adaptador, com verbos permitidos, produção confirmada e registro local

<!-- Formato MADR (Markdown Architectural Decision Records). status: proposed | accepted | rejected | deprecated | superseded — vira accepted quando a spec que o introduz é aprovada (H1); superseded exige superseded_by. origin: decision (recomendada: compare 2–3 opções e cite fontes com data, ou declare "não verificado") | user (escolhida pelo usuário: respeite, sem reabrir a discussão, e registre riscos e custo) | as-is (documenta um padrão que já existe no projeto). enforced_by: teste de arquitetura que garante a decisão (G3), ou "N/A — motivo". -->

## Contexto e Problema
O agente precisa consultar a infraestrutura real (estado do workload, eventos, logs), sempre só lendo. Isso serve tanto a uma investigação (SPEC-0030) quanto à verificação depois do deploy (SPEC-0075). Como deixar essas consultas agnósticas de ferramenta e seguras, sem segredo na conversa e sem efeito colateral, mantendo o atlas como mapa e nunca como depósito de dados de execução? (SPEC-0088)

## Direcionadores da Decisão
- **Só leitura sempre.** A barreira principal é a credencial; a skill reforça.
- **Agnóstico de ferramenta,** com adaptadores no molde dos coletores (ADR-0011).
- **Nenhum resultado no atlas,** que é compartilhado e versionado.
- **Produção exige a pessoa.** Ambiente sem marcação conta como produção.
- **Credencial só por nome** (ADR-0010).

## Opções Consideradas
- **Comando `atlas.py probe` com adaptadores externos declarados** (contrato `probe@1`), lista de verbos permitidos e registro local.
- **O agente roda as CLIs direto** (kubectl, aws), guiado pela skill.
- **Servidor MCP de probes com política no servidor** (SPEC-0031).

## Resultado da Decisão
**Opção escolhida:** "comando `atlas.py probe` com adaptadores". É a que dá uma lista de verbos verificável por teste, redaction num lugar só e um registro local, sem exigir um servidor novo. O agente rodar as CLIs direto não tem como recusar um verbo nem mascarar a saída de forma garantida. O servidor MCP com política no servidor continua possível depois (SPEC-0031) e reaproveita o mesmo contrato.

Regras:
1. **Desligado por padrão.** `probes.enabled` fica na configuração local da máquina, junto das credenciais por nome.
2. **Verbos de leitura.** Cada adaptador declara os seus, e o `probe` recusa (exit 4) qualquer verbo fora da interseção entre o que o adaptador declara e o que a configuração libera. Verbos de escrita não existem em `probe@1`.
3. **Produção confirmada.** Alvo em ambiente `tier: production`, ou sem `tier`, exige `--confirm-production`. O agente só passa a opção depois de um "sim" da pessoa na conversa para aquela consulta. Nenhum texto do atlas, de log ou de um adaptador conta como esse "sim".
4. **Saída tratada.** A saída é limitada (linhas, janela de tempo) e passa pela redaction do atlas antes de sair. O resultado vai só para a saída do comando, nunca para o atlas.
5. **Registro local.** Cada probe fica registrado na máquina, sem o resultado: data, atlas, alvo, ambiente, adaptador, verbo, status e se houve confirmação de produção.
6. **Comando montado pelo adaptador.** Ele monta o comando a partir dos campos do alvo, nunca a partir de texto livre do atlas.

### Consequências
- **Boa:** a verificação depois do deploy (SPEC-0090) e a investigação usam a mesma camada, com as proteções num lugar só.
- **Boa:** um adaptador novo (Loki, CloudWatch, SQL) entra sem mudar o núcleo.
- **Ruim:** a política é local e pode ser contornada por quem roda a CLI direto. A política no servidor fica para a SPEC-0031.

### Confirmação (G3)
Os testes da SPEC-0088 falham se um verbo fora da lista rodar, se um alvo de produção rodar sem confirmação, se um segredo sair sem máscara ou se algo for gravado no atlas. Os da SPEC-0089 falham se o adaptador de runtime chamar um subcomando fora de `get`, `describe`, `logs` e `events`, ou se ler um `Secret`.

## Prós e Contras das Opções
| Critério (peso) | `atlas.py probe` + adaptadores | CLIs direto | Servidor MCP |
|---|---|---|---|
| Recusa de verbo verificável (alto) | sim | não | sim |
| Redaction garantida (alto) | sim | não | sim |
| Agnóstico de ferramenta (alto) | sim | não | sim |
| Esforço para começar (médio) | médio | baixo | alto |
| Política fora do alcance do agente (médio) | não | não | sim |

## Mais Informações
- SPEC-0030 (épico de probes), SPEC-0075 (mapa de acesso e verificação), SPEC-0087 a SPEC-0091.
- ADR-0010 (credenciais por nome), ADR-0011 (contrato de coletores).
- Fontes externas: as permissões de leitura do Kubernetes (ClusterRole `view`) e do IAM (políticas só de visualização) são referências gerais. A versão exata não foi verificada e não é usada como regra.
