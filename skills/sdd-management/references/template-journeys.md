# Guia de jornadas

<!-- Documento vivo (SPEC-0011): o que cada perfil de usuário faz no produto hoje, passo a passo, como reproduzir
localmente e qual teste prova cada passo. Escrito para pessoas — quem chega ao projeto entende o produto sem ler
as specs. Uma seção por jornada de critical_journeys (sdd-config.yml), com [jornada: <id>] no título: o `validate`
avisa quando falta uma jornada crítica ou quando o guia cita um id desconhecido. Atualize no CLOSE (G7) sempre que
a entrega mudar uma jornada. `spec_graph.py living-docs` mostra a cobertura. -->

## Perfis

<!-- Quem usa o produto: um item por perfil, com o objetivo dele. Ex.: "- Paciente — agenda e acompanha consultas". -->

<!-- jornada:inicio -->
## {{title}} [jornada: {{id}}]

- Perfil: <!-- quem percorre esta jornada -->
- Passo a passo:
  1. <!-- o que a pessoa faz e o que vê como resultado em cada passo -->
- Como reproduzir localmente: <!-- comandos para subir o sistema, dados de exemplo, usuário de teste e URL ou
  endpoint de entrada -->
- Provada por: {{proof}}

<!-- jornada:fim -->
