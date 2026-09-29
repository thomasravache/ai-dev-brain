# Especificação Técnica: [Nome da Funcionalidade]

## 1. Visão Geral
Breve descrição da funcionalidade e seu impacto no sistema.

## 2. Motivação & Escopo

**Motivação:** Por que essa alteração é necessária? Qual problema resolve ou qual valor agrega?

**Dentro do escopo:**
- [O que será entregue nesta spec]

**Fora do escopo:**
- [O que explicitamente NÃO será feito — itens que poderiam ser assumidos mas não serão]

## 3. Pré-requisitos
O que deve existir ou estar concluído antes que a implementação possa começar.

- [Spec, feature, pacote, ou serviço externo necessário]
- N/A se não houver dependências.

## 4. Decisão Arquitetural
Qual abordagem ou padrão será adotado e por quê — justificado pelo contexto descoberto na fase de análise.

**Decisão:** [ex: Vertical Slice, Event-Driven, CQRS, módulo isolado]
**Justificativa:** [por que essa abordagem se encaixa no contexto atual do projeto]
**Alternativas descartadas:** [o que foi considerado e por que foi rejeitado]

## 5. Requisitos Não-Funcionais
Restrições de performance, concorrência, segurança ou volume que o implementador deve respeitar.

- [ex: resposta em menos de 200ms sob carga de 100 req/s]
- N/A se não houver requisitos específicos — não omitir a seção.

## 6. Artefato A: O Contrato (Design)
Definição técnica da interface, evento ou estrutura de dados.

**Contrato / Endpoint / Evento / Método:** `[ex: POST /api/v1/resource]`

**Especificação:**
```
# Substitua por OpenAPI, AsyncAPI, Proto, Schema, ou outro formato adequado ao projeto.
# Inclua: payload de entrada, resposta de sucesso e mapeamento de erros.
```

**Arquivos Afetados:** `[lista de arquivos a criar ou modificar]`

## 7. Artefato B: Plano de Testes (TDD)
Cenários que devem ser validados ANTES de qualquer implementação.

### 7.1 Testes Unitários
- `[Comportamento esperado]` → Dado [Contexto], Quando [Ação], Então [Resultado]
- `[Edge Case]` → Dado [Contexto Inválido], Quando [Ação], Então [Erro/Exceção]

### 7.2 Testes de Integração
- **Fluxo Principal:** [ex: persistência, chamadas externas, mensageria]
- **Dublês Necessários:** [ex: repositório em memória, serviço externo mockado, fila fake]

## 8. Aprovação
- [ ] Aprovado pelo Desenvolvedor
- [ ] Aprovado pelo Arquiteto (SDD Manager)

---
*A Seção 9 (Implementation Checklist) será adicionada pelo SDD Manager após a aprovação, como parte do Handoff.*
