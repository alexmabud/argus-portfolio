# ADR 007 — Roteamento em cascata: IA só quando necessária

## Status
Aceito (design fechado; implementação em curso)

## Contexto
Chamar um LLM para toda mensagem do chat seria caro, lento e frágil: se a
API do provedor cair ou o orçamento acabar, o analista em campo ficaria
sem busca. Mas a maior parte das buscas é trivial (um nome, uma placa, um
CPF) e já tem implementação determinística e rápida.

## Decisão
O código decide o caminho **antes** de gastar, nesta ordem:

1. **Foto anexada** → busca facial local existente (modelo próprio), sem LLM.
2. **Padrão claro** (placa, CPF, número de RAP, comando `chave: valor`) →
   SQL direto.
3. **Texto curto de nome** (até ~4 palavras, sem palavra de pergunta) →
   busca unificada em SQL.
4. **Todo o resto** → LLM orquestrador (ADR 006).
5. Se o SQL voltar **vazio** e a mensagem não for padrão exato → **uma**
   tentativa com o LLM, dentro do teto de gasto.

**Fallback:** com LLM indisponível (API fora, lenta, sem orçamento), os
itens 1–3 seguem normais e o item 4 responde com orientação ("use busca por
nome, placa, CPF ou comandos como `bairro: X`").

**Teto de gasto em 3 camadas:** por pergunta (rodadas de ferramenta, tokens,
~30 s), por usuário/dia e global/mês (contadores no Redis) e limite mensal
no console do provedor.

Cada mensagem registra o caminho seguido; cada resposta mostra a etiqueta
("SQL · sem IA", "Reconhecimento facial · sem IA", "IA · N buscas internas").

## Consequências
- Custo e latência previsíveis; a maioria das mensagens nunca toca o LLM
  (**meta a medir**, não suposição).
- O chat deixa de ser ponto único de falha — condição para substituir a
  tela de consulta antiga, que só sai quando a paridade de funções estiver
  provada.
- Buscas por endereço e veículo sem IA ficam mais duras que as listas de
  seleção antigas; mitigadas por comandos `chave: valor` e por a IA extrair
  os filtros no caso normal.
- Exige manter dois caminhos (determinístico e IA) coerentes: o contrato de
  resposta tipado é o que os mantém compatíveis.
