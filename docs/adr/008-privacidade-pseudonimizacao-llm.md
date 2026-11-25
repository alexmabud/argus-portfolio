# ADR 008 — Privacidade ao usar LLM de terceiro: minimizar, pseudonimizar, auditar

## Status
Aceito (design fechado; implementação em curso — tarefas 16 e 21)

## Contexto
O sistema guarda dado pessoal sensível (identificação, localização,
biometria) sob a LGPD. Usar um LLM hospedado por terceiro significa que
parte desse conteúdo pode ser enviada para fora do servidor. A decisão de
produto aceita isso **apenas em produção** e **apenas com mitigações**, e a
autorização institucional da organização usuária é um passo separado, de
responsabilidade do operador do sistema.

## Decisão
1. **Minimização**: nenhuma ferramenta devolve CPF, RG nem endereço
   completo. O modelo só vê o que precisa para organizar a resposta.
2. **Pseudonimização**: o LLM recebe **códigos** ("P12") no lugar de nomes;
   o código do servidor troca pelos nomes na resposta final.
3. **Máscara automática** de CPF e telefone em textos livres antes do envio.
4. **Biometria nunca sai**: fotos e embeddings faciais são tratados só por
   modelo local; o LLM não interpreta imagem.
5. **Conversa efêmera**: contexto apenas em memória curta (Redis, validade
   de ~1 h, apagado ao fechar o chat); sem tabela de histórico; nada no
   armazenamento do navegador.
6. **Auditoria**: cada pergunta e cada ferramenta acionada vão para o log de
   auditoria (frase, caminho, ferramentas, IDs) — não a resposta inteira.
7. **Ambientes não produtivos só com dado sintético**: desenvolvimento, CI e
   avaliação do modelo.
8. **Sem retenção de sessão no provedor**: laço de ferramentas no nosso
   servidor com a API de mensagens comum (ver ADR 006).
9. **Rotas atrás de chave de funcionalidade**, ligadas só depois da tarefa de
   LGPD e segurança.

## Consequências
- Nomes digitados pelo usuário na pergunta ainda chegam ao modelo (são
  necessários para a busca); a pseudonimização cobre o que *volta* das
  ferramentas.
- Pseudonimizar adiciona uma etapa de ida e volta (codificar/decodificar)
  que precisa de teste próprio.
- A decisão jurídica (autorização institucional, base legal) **não** é
  tomada pelo código nem por este ADR; fica registrada na documentação de
  LGPD do projeto.
