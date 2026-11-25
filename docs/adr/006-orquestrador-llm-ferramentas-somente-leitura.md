# ADR 006 — Orquestrador de LLM com ferramentas somente de leitura

## Status
Aceito (design fechado; implementação em curso — ver [argus-trace.md](../argus-trace.md))

## Contexto
O chat do Trace precisa responder perguntas **compostas** ("caminho entre
duas pessoas + houve droga no caminho + moram no mesmo bairro + usaram o
mesmo veículo?") e perguntas que ninguém previu. Um roteador de intenções
fixas não compõe consultas; um LLM com acesso livre ao banco seria um
risco de segurança e de alucinação inaceitável num sistema operacional.

Alternativas avaliadas:
1. **Roteador de intenções por regras** — barato, mas não compõe e quebra em
   pergunta nova. Fica, mas como primeira camada (ADR 007).
2. **Text-to-SQL** — flexível, mas dá ao modelo SQL livre: superfície de
   ataque (injeção, vazamento de coluna sensível) e resultado impossível de
   citar de forma verificável.
3. **Serviço de agente gerenciado pelo provedor** — guarda histórico de
   sessão do lado do provedor e não é elegível a retenção zero: conflita
   com o requisito de privacidade.
4. **Laço de *tool calling* no nosso servidor, com ferramentas fechadas** —
   escolhida.

## Decisão
- O laço roda **no nosso servidor**, com a API de mensagens comum: a IA
  chama uma ferramenta, o código executa e devolve, até ela ter o que
  precisa.
- O catálogo é **pequeno, geral e combinável** (resolver pessoa, buscar
  registros com filtros, grafo, agregadores, busca por significado), com
  filtros numa **lista fechada validada pelo código**.
- Ferramentas são **somente leitura** e devolvem **tabelas pequenas já
  agregadas**; sem SQL livre, sem escrita, sem internet.
- A resposta final é **estruturada**: cada afirmação traz IDs de origem. O
  código **confere os IDs contra os resultados das ferramentas**, monta os
  links e **descarta afirmação sem fonte**.
- O grafo exibido é **saída de ferramenta**; a IA só escolhe quais nós
  destacar (IDs validados).
- Tudo atrás de uma interface `LLMClient`, para trocar modelo/provedor por
  configuração e testar com cliente simulado.

## Consequências
- A superfície de ataque do agente é exatamente o catálogo: pequeno e
  auditável.
- A correção da resposta é **verificável** (citação), não apenas "parece
  certa".
- Sem streaming na fase 1: a validação exige a resposta completa.
- Cada ferramenta nova é código novo a manter e testar; em troca, cada
  pergunta sem resposta registrada aponta onde o catálogo deve crescer.
- Fase 2 (cadastro conversado): a IA só *extrai campos*; quem valida e
  grava é o código, após confirmação do usuário.
