---
id: SPEC-0075
title: "boson-atlas: mapa de acesso, observabilidade e validação por ambiente e serviço"
tier: epic
type: feature
status: proposed
created: 2026-11-17
depends_on: []
adrs: [ADR-0010, ADR-0011, ADR-0012]
external: []
approved_by:
approved_at:
---

# SPEC-0075 — boson-atlas: mapa de acesso, observabilidade e validação por ambiente e serviço (Épico)

> **Radar (thomas, 2026-11-17):** pedido do thomas a partir do uso real da boson-atlas. A detalhar antes do G0, sempre agnóstico e configurável, com um onboarding fácil de entender para uma pessoa.
> - **Problema:** o atlas sabe o que existe e como se liga, mas não sabe *como chegar* em cada coisa nem *como testá-la*. Ao verificar um deploy ("subiu a feature X no dev, está tudo certo?"), o agente redescobre sozinho:
>   - contexto do kubectl, profile e região da AWS, namespace e workload;
>   - onde ficam os logs e como reconhecer a versão que subiu;
>   - por qual URL entrar, com que conta de teste e qual suíte ou jornada de e2e cobre o serviço.
> - **Objetivo:** guardar no atlas o mapa de acesso, observabilidade e validação, por ambiente e por serviço, e entregá-lo no `context`.
>   - **Por ambiente:** cluster, contexto do kubectl, profile e região da AWS, como renovar o acesso (ex.: SSO), marcação `test` ou `production` e URLs públicas de fronts e APIs.
>   - **Por serviço ou deployment:** namespace, workload ou container, fontes de log (kubectl, Loki/Grafana, log group do CloudWatch), dashboards, health check e o padrão da tag da imagem (PR → run da CI → tag → Application).
>   - **Contas de teste:** só a referência (`secret-ref` com store e path, ou o nome do item no gerenciador de senhas), buscada na hora da execução.
>   - **Validação:** relação serviço ou jornada → suíte de e2e, com o comando vindo da documentação do repositório da suíte. Jornadas de smoke por serviço escritas pelo time e curadas como as convenções (ADR-0012).
> - **Restrições:**
>   - O atlas não guarda logs, métricas nem dados de execução.
>   - Credenciais só por nome ou referência (ADR-0010), com o `lint` `secret-leak` valendo para os campos novos.
>   - Conteúdo do atlas é dado, não instrução: só campos estruturados, nunca comandos prontos. Quem consome monta o comando, sempre só de leitura.
>   - Agente com navegador nunca atua em ambiente `production`, e a skill que consome recusa.
>   - Kind ou relação nova (endpoint, jornada, suíte) muda o contrato do coletor (ADR-0011) com spec e ADR.
>   - Diagnóstico e validação ativos ficam fora do atlas.
> - **Entregas candidatas (filhas):**
>   1. ADR com o desenho: attrs de `environment`/`deployment`, kinds novos ou as categorias `observability`/`docs`, quem coleta e como aparece no `context`.
>   2. Coletores automáticos onde der: nomes dos contextos do kubeconfig, log groups do CloudWatch, Grafana/Loki do cluster, padrão de tag e hosts de Ingress, mais o caminho manual pelo `generic` para contas, suítes e jornadas.
>   3. No `context`, as seções `## Acesso e diagnóstico` e `## Como validar` quando a tarefa envolve deploy, incluindo os vizinhos do grafo. No `lint`, credencial colada e ambiente sem marcação.
>   4. A verificação pós-deploy, como skill do fermion ou etapa da `gluon-spec` (avaliar qual), com o relatório anexado ao G6/G7. Ela encadeia:
>      - `context`;
>      - rollout via kubectl (Synced/Healthy com a tag nova, pods sem restart);
>      - logs dos primeiros minutos do serviço e dos vizinhos;
>      - smoke no navegador ou suíte e2e, só em `test`.
> - **Relação com a SPEC-0030 (probes):** a verificação ativa é o consumidor natural das probes. Decidir no DISCOVER se a entrega 4 vira filha da SPEC-0030 ou se as duas se fundem.
> - **Rotina real de verificação pós-deploy (thomas, 2026-11-17), como inspiração para a entrega 4.** A rotina é toda só de leitura, e cada passo responde a uma pergunta. Os nomes de ferramenta aqui são exemplos; a entrega precisa ser agnóstica, com cada passo ligado a uma capacidade que o atlas mapeia e um adaptador por ferramenta:
>   1. **O deploy chegou?** Run da CI no branch, Application do GitOps lida pelo cluster com Synced/Healthy e a revisão do repositório de IaC recém-mergeada.
>   2. **O pod novo está de pé?** Rollout concluído, imagem nova e 0 restarts. Quando muda configuração, a variável aparece no deployment, só pelo nome.
>   3. **Os logs estão limpos?** Erros agrupados por nível, separando erros novos de antigos (um erro é antigo se o arquivo que gera o log não foi tocado pelo PR) e a mensagem esperada da mudança.
>   4. **O banco ficou como esperado?** Usuário só de leitura, com a credencial num arquivo de senhas local e nunca no comando. Migrations aplicadas e tabelas no estado esperado.
>   5. **A mensageria está saudável?**
>      - login por SSO;
>      - fila e DLQ contando só as mensagens;
>      - assinaturas do tópico com os filtros;
>      - role do pod pela identidade de workload do cluster;
>      - permissão testada por simulação no IAM, junto com a política do recurso, porque sem ela a simulação dá um falso negativo;
>      - no cofre, só os nomes das chaves.
>   6. **Onde mora a configuração?** Arquivo da app por ambiente no repositório de GitOps e busca do nome da variável.
>
>   **Ordem:** foto do estado antes do merge (pod, imagem, migrations, tabelas, filas), merge, deploy, comparação com a foto, registro do resultado no board e no runbook.
>
>   **Regras:** só leitura; nenhum segredo em comando, log ou comentário; restart ou alteração no ambiente ficam com a pessoa.
> - **O que isso pede do atlas (mapa) e da verificação (ação):**
>   - **Campos novos por ambiente:**
>     - organização ou repositório da CI e branch por ambiente;
>     - namespace do GitOps e nome da Application;
>     - repositório de IaC e o caminho do arquivo da app;
>     - cluster, mecanismo de identidade do workload e profile/região com o modo de login;
>     - banco e o usuário só de leitura, só pelo nome, com a referência ao arquivo de senhas ou ao `secret-ref`;
>     - filas, DLQs e tópicos por nome.
>   - **Verificação em fases:** `foto` (antes), `aguardar` (CI, GitOps, rollout), `comparar` (pod, logs, banco, mensageria contra a foto) e `registrar`. A foto fica na conversa ou num arquivo temporário da tarefa, nunca no atlas.
>   - **Capacidades plugáveis,** cada uma com adaptadores:
>     - `ci-run` (GitHub Actions, GitLab…);
>     - `gitops-app` (Argo CD, Flux…);
>     - `rollout` (kubectl…);
>     - `logs` (kubectl, Loki, CloudWatch…);
>     - `db-readonly` (Postgres, MySQL…);
>     - `messaging` (SQS/SNS, Kafka, RabbitMQ…);
>     - `iam-simulate`;
>     - `config-source`.
>
>     O comando é montado pelo adaptador a partir dos campos, nunca lido do atlas. Uma capacidade sem adaptador ou sem campo vira "não verificado", com o motivo.
>   - **Onboarding humano:** perguntas em linguagem simples ("como você vê se o deploy chegou?", "onde ficam os logs?"), com cada resposta virando um campo. Ele mostra o que já foi coletado automaticamente para a pessoa só confirmar, e permite pular uma capacidade.
>   - **Métricas para atualizar a configuração:**
>     - em cada verificação, contar as capacidades verificadas, não verificadas (sem campo ou sem adaptador) e com erro de acesso;
>     - quanto tempo cada fase levou;
>     - quais campos o agente teve de descobrir sozinho.
>
>     O `lint` e o `doctor` usam isso para sugerir a atualização da configuração (ex.: "a última verificação descobriu o log group à mão: confirmar no atlas?"), sempre como proposta, no estilo da curadoria (ADR-0012).
> - **Ordem revista e melhorias de mercado (Architect, 2026-11-17, a validar no DISCOVER).** A rotina real fica como base; muda a ordem e entram práticas de verificação de deploy (análise de canário como Kayenta, Flagger e Argo Rollouts; golden signals e RED do SRE; quality gates do Keptn; DORA). Tudo descrito por capacidade, sem ferramenta fixa:
>   0. **Pré-voo: o que mudou e o que verificar.**
>      - Ler o diff do PR: código, configuração, migration, contrato de mensagem e flags.
>      - Com o grafo do atlas, escolher só as verificações que importam (serviço alterado e vizinhos). "Onde mora a configuração" sai do fim e vira insumo daqui.
>      - Tirar a foto de base (linha de base dos sinais, não só o estado) e confirmar que o rollback é conhecido. A decisão de executá-lo fica com a pessoa.
>   1. **Entrega:** a CI gerou o artefato, o GitOps sincronizou e o rollout concluiu. A versão é conferida pelo digest da imagem (a tag pode ser reaproveitada) e pela revisão do repositório de IaC.
>   2. **Saúde do runtime:**
>      - réplicas prontas, restarts, eventos (OOMKilled, CrashLoop, probes falhando) e uso contra limites;
>      - a variável nova presente, só pelo nome;
>      - o estado da feature flag, quando houver.
>   3. **Sinais contra a linha de base,** numa janela de observação configurável (soak, ex.: 10 a 30 min):
>      - taxa de erro, latência (p95/p99), tráfego e saturação, pelas métricas quando existirem, com os logs como apoio;
>      - erros novos contra antigos por assinatura (mensagem normalizada mais origem) e pelos arquivos tocados no PR;
>      - a mensagem esperada da mudança presente;
>      - traces correlacionados pela versão, quando houver.
>   4. **Dependências e dados:** só as que o diff ou o grafo indicam.
>      - migration aplicada e estado das tabelas, sempre com usuário só de leitura;
>      - fila e DLQ (profundidade, idade da mensagem mais antiga, lag de consumidor), assinaturas e filtros;
>      - permissões por simulação, levando a política do recurso.
>   5. **Funcional:** smoke com navegador ou suíte e2e, só em ambiente `test`. Em `production`, só verificações passivas: sinais, logs e health. Nunca navegador.
>   6. **Veredito e registro:**
>      - veredito `passou | degradou | inconclusivo` com a evidência de cada verificação, e "não verificado" com o motivo;
>      - em `degradou`, sugere rollback e não executa;
>      - registro no Relatório de Entrega (G6/G7) e, opcionalmente, no board;
>      - métricas DORA derivadas (lead time do commit ao deploy, taxa de falha de mudança, tempo de recuperação).
>
>   **Garantias transversais:**
>   - Cada adaptador declara uma lista permitida de verbos só de leitura (`get`, `list`, `describe`, `logs`, `select`, `simulate`), e a skill recusa qualquer outro.
>   - Timeouts e janelas são configuráveis por ambiente.
>   - Tudo é idempotente, e o resultado é comparável entre execuções.
>   - Segredos só por referência, com a saída mascarada.
>   - Os limites (ex.: aumento de taxa de erro tolerado) ficam na configuração, com padrões conservadores, e são ajustados pelas métricas de uso (proposta, nunca automático).
> - **Radar (thomas, 2026-11-17): escrita com aprovação humana, opcional.** Quando a infraestrutura permitir, a verificação poderá propor ações que modificam o ambiente: rollback, restart, reprocessar mensagens da DLQ, desligar uma flag, escalar réplicas. O padrão continua só leitura. A escrita é opt-in por ambiente e por capacidade, desligada por padrão. Desenho inicial, a validar no DISCOVER:
>   - **Verbos separados:** cada adaptador declara os verbos de leitura, sempre permitidos, e os de escrita (ex.: `rollback`, `restart`, `redrive`, `scale`, `toggle-flag`), cada um bloqueado até a configuração liberá-lo.
>   - **Aprovação por ação:**
>     - a skill mostra o comando exato, o alvo (ambiente, recurso), o efeito esperado, como desfazer e o que verifica depois;
>     - executa só depois de um "sim" explícito da pessoa na conversa, para aquela ação;
>     - nenhuma aprovação vale para a próxima ação, e nenhum texto vindo do atlas ou de logs conta como aprovação.
>   - **`production`:** exige uma configuração própria além da de `test` e, opcionalmente, uma segunda pessoa ou um fluxo externo (ex.: aprovação de ambiente da CI, change request), sempre que a infraestrutura oferecer.
>   - **Preferir o caminho auditado da própria infraestrutura,** quando existir: rollback do GitOps por revert no repositório de IaC com PR, `argo rollouts undo`, aprovação de ambiente da CI. Comando direto no cluster fica como último recurso.
>   - **Credenciais de escrita separadas das de leitura** (outro profile ou role), só por referência, com o menor privilégio possível. Dry-run antes de executar, quando a ferramenta oferecer.
>   - **Registro:** cada ação aprovada entra no Relatório de Entrega com quem aprovou, quando, o comando, o resultado e a verificação depois da ação. As métricas contam ações propostas, aprovadas, recusadas e revertidas.
> - **Coletor `aws` oficial:** um coletor local do usuário (AWS CLI, só leitura: caches serverless, RDS, SQS, SNS e assinaturas SNS→SQS, cruzados com as env das Applications) serve de referência. Ele fica fora deste repositório.

<!-- type: feature | migration | foundation (produto novo: ver references/greenfield.md). O épico não é executado: define visão, decisões, decomposição e entrega. Quem executa são as specs filhas (tier full ou lite, tamanho S/M, `parent: SPEC-0075`). A ordem de execução é calculada a partir do frontmatter das filhas (`spec_graph.py waves`). -->

## 1. Visão
{{Resultado de negócio e técnico esperado ao final do épico.}}

## 2. Escopo
**Objetivos (dentro do escopo):**
- {{O que o épico entrega}}

**Não-objetivos (fora do escopo):**
- {{O que fica explicitamente de fora}}

## 3. Arquitetura Alvo
**Contexto:** {{Projeto existente: arquitetura atual (ADRs as-is) e o que muda — se muda, type: migration | Projeto novo: stack e arquitetura definidas nos ADRs de fundação}}

{{Como o sistema fica ao final: módulos, fronteiras, fluxos principais, contratos entre as filhas. Diagrama se ajudar.}}

**Decisões (ADRs):** {{ADR-NNNN — decisão. Toda decisão transversal vira ADR (liste também no frontmatter `adrs`) | N/A}}

**Regras de arquitetura a garantir (G3):** {{ex: Domain não referencia Infrastructure; módulos só se comunicam por contratos públicos — cada regra com o teste de arquitetura que a garante}}

## 4. Decomposição
<!-- Uma linha por spec filha. As colunas de dependência são informativas: a fonte da verdade é o frontmatter de cada filha. -->
| Spec | Título | Tier | Tipo | Tamanho | Depende de | Consome contrato de |
|---|---|---|---|---|---|---|
| {{SPEC-NNNN}} | {{título}} | {{full}} | {{feature}} | {{M}} | {{—}} | {{—}} |

## 5. Estratégia de Entrega
- **Ambientes:** {{ex: staging automático a cada merge; produção via pipeline com aprovação}}
- **Entrega por onda:** {{o que vai para produção ao fim de cada onda e o que fica atrás de feature flag}}
- **Feature flags:** {{nome — o que controla — critério para ligar e para remover | N/A}}
- **Rollback:** {{como reverter cada onda}}
- **Métricas de sucesso pós-release:** {{o que observar e por quanto tempo}}

## 6. Riscos & Mitigações
- {{risco — mitigação | N/A}}

## 7. Critérios de Aceite do Épico
<!-- Verificáveis ponta a ponta. Cada critério cita o teste que o prova (`SPEC-NNNN:E2E-01`; IT para critérios que não são jornada). O épico só fecha com todos marcados e todas as filhas implemented/deprecated. -->
- [ ] {{critério verificável — SPEC-NNNN:E2E-01}}

## 8. Questões em Aberto
<!-- Dúvidas que impedem fechar a spec, respondidas ANTES do H1. Aberta: `- [ ] pergunta (quem responde)`. Respondida: `- [x] pergunta — resposta (quem, data)`. Com alguma aberta o G0 reprova. Sem dúvidas: escreva "Nenhuma". Dúvida que surge depois da aprovação vira impedimento. -->
{{- [ ] dúvida que precisa de resposta e quem responde | Nenhuma}}

## 9. Aprovação (H1)
Uma aprovação humana cobre o épico e as specs filhas apresentadas junto com ele. Registrada no frontmatter (`approved_by`, `approved_at`) do épico e de cada filha.

## 10. Registro de Impedimentos
<!-- Problemas que envolvem várias filhas (conflito de integração da onda, CI quebrado, decisão transversal). Impedimento que trava uma filha específica vai na própria filha. -->
| ID | Aberto em | Fase/Gate | Tipo | Descrição | Tentativas | Responsável | Resolução | Fechado em |
|---|---|---|---|---|---|---|---|---|

## 11. Relatório de Entrega
<!-- Preenchido ao fechar o épico: o que foi entregue, como (ondas e deploys com versão/data), resultado dos critérios de aceite com os testes que os provam, métricas pós-release, pendências como novas specs. `spec_graph.py report SPEC-0075` ajuda a montar. -->

## 12. Emendas
<!-- Mudança em spec aprovada: uma linha por emenda, aprovada pelo humano. -->
| Versão | Data | Mudança | Motivo | Specs impactadas | Aprovado por |
|---|---|---|---|---|---|
