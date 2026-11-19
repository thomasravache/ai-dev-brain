---
description: Entrega uma tarefa de ponta a ponta pelo SDD (contexto do atlas, spec, aprovação, implementação e PR).
argument-hint: "<tarefa>"
---

Entregue a tarefa abaixo seguindo o fluxo do plugin `fermion`, nesta ordem:

1. **Tarefa:** `$ARGUMENTS`. Se estiver vazia, peça ao usuário a tarefa e pare aqui.
2. **Contexto da organização:** se o atlas estiver configurado nesta máquina, carregue a skill `boson-atlas` e monte o contexto da tarefa com `context` antes de propor qualquer coisa. Se o `docs/specs/sdd-config.yml` do projeto tiver `org_context`, passe esse valor como `--atlas <org_context>` ao `atlas.py config --json` e ao `context`, rodando da raiz do repositório (caminho relativo escrito como `./x` ou `../x`; sem `/` e sem começar com `.` ou `~`, o valor é lido como nome). O contexto do início da sessão diz se o atlas está configurado; se não disser, confira com `atlas.py config --json` da skill `boson-atlas` (exit 0 = configurado; exit 3 = atlas não configurado nesta máquina (o do `org_context`, ou nenhum): siga só pelo repositório, nunca por outro atlas). Exit 2: leia a mensagem da CLI; se ela lista vários atlas sem escolha, pergunte à pessoa qual atlas usar, sem adivinhar; senão, repasse o erro.
3. **Spec-Driven Development:** carregue a skill `gluon-spec` e siga o `status` (rode `status` antes de cada passo, sem depender da memória da conversa): DISCOVER → SPEC (G0) → pare no H1 e peça ao usuário que responda "Aprovado" → executar (testes antes do código, gates G1 a G5) → PR.
4. **Aprovações:** nunca aprove o H1 nem o H2 e nunca faça merge sem o "sim" explícito do usuário nesta conversa.
