# Mapa do sistema

<!-- Documento vivo (SPEC-0011): o que roda onde, por camada, como sobe localmente e como chega em produção, e qual
ADR justifica cada escolha. Escrito para pessoas — descreve o sistema como ele está hoje, não o histórico (esse
fica nas specs, nos ADRs e no CHANGELOG). O `validate` avisa quando um ADR accepted não é citado pelo ID. Atualize
no CLOSE (G7) sempre que a entrega mudar um componente. `spec_graph.py living-docs` mostra a cobertura.
Diagramas são bem-vindos (contexto, containers, fluxo de deploy) no formato que o time preferir — Mermaid, C4,
imagem versionada —, nenhum é obrigatório. -->

## Visão geral

<!-- Em poucas linhas: o que o sistema faz, para quem e as peças principais. Um diagrama de contexto ajuda aqui. -->

## Componentes por camada

<!-- Para cada camada: o que existe, a tecnologia, onde está no repositório e o ADR que justifica a escolha.
Camada que não se aplica: "N/A — motivo". -->

### UI

### Backend

### Dados

### Infraestrutura

### Entrega

### Observabilidade

### Testes

## Serviços externos

<!-- Cada serviço de terceiros: para que serve, como autentica, o que acontece quando ele cai e como é simulado
nos testes. -->

## Ambientes

<!-- Um item por ambiente (local, homologação, produção...): onde roda, como acessar e de onde vêm a configuração
e os segredos (nunca os valores). -->

## Rodar localmente

<!-- Pré-requisitos e os comandos, na ordem, para subir o sistema e rodar os testes do zero. -->

## Caminho até produção

<!-- Do commit ao ambiente: pipeline, gates, estratégia de deploy, verificação após o deploy e rollback. -->

## Decisões

<!-- ADRs aceitos: diga em uma linha onde cada decisão aparece no sistema. -->
{{decisions}}
