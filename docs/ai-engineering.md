# Engenharia de IA no Argus

Onde a IA entra no sistema, como é operada em produção, como é medida e
como é controlada. A regra que organiza tudo:

> **A IA organiza e conecta dados que já existem. Nunca gera fatos.**

Num sistema de apoio operacional a policiais, uma resposta plausível porém
inventada é pior do que "não sei". Quase toda decisão de engenharia abaixo
vem dessa frase.

## Mapa de IA

| Peça | Tecnologia | Onde roda | Situação |
|---|---|---|---|
| Reconhecimento facial | InsightFace `buffalo_l`, embedding 512-d, busca por cosseno no pgvector (HNSW) | Servidor próprio (worker + API, CPU) | **Em produção** |
| Embeddings de texto | SentenceTransformers MiniLM multilíngue, 384-d, cache em Redis | Servidor próprio | **Em produção** (ocorrências); estendido às observações no Trace |
| Busca vetorial | PostgreSQL + pgvector, índices HNSW | Banco próprio | **Em produção** |
| Pipeline assíncrono de IA | Fila `arq` sobre Redis, 2 workers, métricas de fila | Servidor próprio | **Em produção** |
| Busca híbrida (palavra-chave + significado) | `pg_trgm` + pgvector | Banco próprio | Projetada; embeddings novos em construção (Trace, grupo C) |
| Orquestrador de chat | Claude via API (tool calling), ferramentas só de leitura | API do provedor | Projetado em detalhe (Trace, grupo D) |
| Grafo de vínculos | BFS em lote sobre 3 fontes de aresta | Backend | 1ª fatia implementada (vizinhança); caminho mais curto a seguir |

Detalhe do orquestrador e do grafo em [argus-trace.md](argus-trace.md).

## O que já roda em produção

### Pipeline de IA fora do caminho crítico
Reconhecimento facial e embeddings são caros demais para o caminho
síncrono de uma requisição. A API confirma o cadastro na hora e enfileira
o job; workers separados calculam o vetor e o gravam. **Nenhuma inferência
bloqueia quem está em campo.**

### Operar modelos em CPU sem GPU
O deploy é uma VM ARM sem GPU. Isso impõe disciplina:
- **Warm-up eager** dos modelos no `lifespan`, antes de aceitar tráfego —
  a primeira busca depois de cada deploy chegou a levar ~25 s.
- **Carga serializada entre workers Gunicorn** com lock inter-processo
  (`fcntl.flock`): quatro workers carregando o mesmo modelo ao mesmo tempo
  disputavam CPU
  ([código](../code-samples/backend/interprocess_lock.py),
  [lição 4](lessons-learned.md#4-primeira-busca-depois-de-cada-deploy-levava-25-s)).
- **Carga em thread**, nunca na corrotina: carregar um modelo de forma
  síncrona dentro de `async def` congela o event loop inteiro.
- **Wheels por arquitetura**: produção é ARM, desenvolvimento e CI são
  x86 — um pacote com wheel num pode não ter no outro, e isso entra no
  planejamento de qualquer atualização de biblioteca de ML.

### Regressão de modelos entre versões de biblioteca
Atualizar `torch`, `onnxruntime`, `insightface` ou `sentence-transformers`
pode mudar *silenciosamente* o que os modelos produzem, e todos os
vetores já gravados no banco ficariam incomparáveis. Por isso existe um
**baseline de modelos**:

- Fixtures **sem nenhum dado real**: frases sintéticas em português e
  imagens de domínio público (incluindo uma fixture **negativa**, "sem
  rosto", para cobrir o caso de não detecção).
- O baseline é **capturado na imagem de produção** (mesmo Python, mesmo
  lock) e registra as versões dos pacotes.
- A comparação roda a cada atualização relevante e **falha** se o cosseno
  do rosto cair abaixo de 0,999, o do texto abaixo de 0,9999, ou se um
  rosto antes detectado deixar de ser detectado.

É o equivalente de um teste de regressão, aplicado a *comportamento de
modelo* em vez de comportamento de código.

### Observabilidade de IA
- **Liveness por instância de worker**, com falha fechada quando o Redis
  não responde ([código](../code-samples/backend/worker_health.py)).
- **Métricas de domínio da fila**: tamanho, jobs concluídos e falhos e
  duração acumulada por função — a ponte worker → Redis → API → Prometheus
  ([ADR 004](adr/004-ponte-metricas-worker-redis-api.md)). Permite alertar
  "todo job de rosto falhando" — que um alerta de "processo de pé" jamais
  veria.
- Alertas testados com `promtool` contra cenários de falha reais
  ([ADR 005](adr/005-alertas-como-codigo-testado.md)).

### Limiar medido, não assumido
O limiar de similaridade do código de busca por significado das
ocorrências veio de um valor inicial **nunca medido**. A política do
projeto é: **só confiar em limiar depois de medir** em perguntas com
resposta conhecida; até lá, a busca semântica não é exposta como
funcionalidade e a palavra-chave continua junto.

## O que está sendo construído: o Trace

O [Argus Trace](argus-trace.md) é onde as decisões de engenharia de LLM
aparecem — e todas já estão especificadas, com critérios de aceite:

| Decisão | Por quê |
|---|---|
| **Roteamento em cascata: foto → SQL → IA** ([ADR 007](adr/007-roteamento-ia-so-quando-necessaria.md)) | A maioria das buscas não precisa de LLM; custo, latência e superfície de erro caem |
| **Orquestrador com ferramentas só de leitura** ([ADR 006](adr/006-orquestrador-llm-ferramentas-somente-leitura.md)) | A IA decide *quais buscas* rodar; não executa SQL livre, não grava, não acessa a internet |
| **Citação validada pelo código** | Cada afirmação cita IDs de origem; o código os confere contra os resultados reais e descarta o que não tem fonte |
| **A teia do grafo vem do código** | A IA só escolhe nós a destacar; não consegue inventar uma aresta |
| **Poucas ferramentas gerais e combináveis** | Cobre perguntas imprevistas sem uma ferramenta por pergunta; filtros em lista fechada validada |
| **Perguntas sem resposta são registradas** | Lacuna do catálogo vira backlog de produto orientado por demanda real |
| **Pseudonimização + minimização + máscara** ([ADR 008](adr/008-privacidade-pseudonimizacao-llm.md)) | O LLM nunca recebe CPF, RG nem endereço completo; recebe códigos no lugar de nomes |
| **Foto nunca vai ao LLM** | Biometria é dado sensível; o rosto é tratado por modelo local |
| **Teto de gasto em 3 camadas + fallback** | Custo e disponibilidade previsíveis; o chat nunca é ponto único de falha |
| **`LLMClient` atrás de interface** | Trocar modelo/provedor é configuração; testes usam cliente simulado |
| **Modelo escolhido por avaliação** | Começa pelo menor; sobe só se ~50 perguntas sintéticas reprovarem |
| **Sem streaming na fase 1** | A validação de fontes exige a resposta completa antes de mostrar |
| **`parcial` ≠ `sem conexão`** | Busca interrompida por freio nunca vira afirmação de que não há vínculo |

## Avaliação de sistemas com LLM

O plano separa quatro tipos de evidência, porque cada um responde a uma
pergunta diferente:

| Evidência | Pergunta que responde | Como |
|---|---|---|
| **Teste determinístico** com cliente simulado | O laço, o teto, o fallback e a validação de citação funcionam? | Unitário, sem rede; **o CI nunca chama a API real** |
| **Avaliação com modelo real** | O modelo escolhe as ferramentas e os argumentos certos? | ~50 perguntas sintéticas (simples, compostas, ambíguas, **sem resposta**) com resultado esperado; mede acerto, custo e tempo |
| **Medição de recuperação** | A busca por significado acha o que deveria? | ~20 perguntas com resposta conhecida, em cópia local dos dados |
| **Auditoria em produção** | O que os usuários realmente perguntam? | Log de caminho seguido, ferramentas e perguntas sem resposta |

Incluir perguntas **sem resposta** na avaliação é essencial: mede se o
sistema sabe dizer "não encontrei" em vez de improvisar.

## Segurança específica de IA

- **Prompt injection por conteúdo armazenado**: observações e PDFs são
  texto livre digitado por terceiros e agora chegam a um modelo. Mitigação
  em camadas: resultado de ferramenta tratado como dado; IA sem ferramenta
  de escrita; citação validada; fonte clicável obrigatória.
- **Privilégio mínimo para o agente**: o conjunto de ferramentas *é* a
  superfície de ataque; por isso é pequeno, só de leitura e com argumentos
  validados contra listas fechadas.
- **Dados em ambientes não produtivos**: desenvolvimento, CI e avaliação do
  modelo usam apenas dado sintético.
- **Custo como vetor de abuso**: contadores por usuário/dia e global/mês
  tornam "esgotar o orçamento" uma falha contida e visível.

## Engenharia *com* IA: o processo de desenvolvimento

O próprio projeto é desenvolvido com um assistente de IA (Claude Code),
e o processo é tratado como engenharia, não como improviso:

- **Pacote de skills versionado no repositório** (spec, plano, TDD,
  verificação, revisão, simplificação, entrega): cada fase do trabalho
  tem uma instrução explícita e verificável.
- **Personas por área** (Python sênior, dados/Postgres, IA/ML,
  segurança/LGPD, frontend PWA, DevOps/SRE, QA): o assistente anuncia o
  papel, o fluxo e a cadeia de skills **antes** de agir, e fecha dizendo o
  que usou e o que pulou (com motivo).
- **Hooks do harness** reforçam o protocolo a cada mensagem — a regra não
  depende de o modelo "lembrar".
- **Evidência antes de afirmação**: "funciona" exige saída de comando ou
  teste; relatórios de verificação são obrigatórios.
- **Revisão multiagente** de código antes de promover mudanças — foi ela que
  derrubou uma otimização de cache no cliente que vazaria dado entre
  operadores em aparelho compartilhado
  ([lição 1](lessons-learned.md#1-picos-de-latência-e-rajadas-de-erro-5xx-com-o-banco-saudável)).
- **Memória do projeto** (decisões, incidentes e armadilhas) espelhada no
  repositório, com segredos e IPs mascarados, para qualquer sessão ou
  ferramenta partir do mesmo contexto.
- **Handoffs** estruturados entre sessões, para trabalho longo e em fatias.

## Competências demonstradas

| Competência | Evidência neste repositório |
|---|---|
| Embeddings e busca vetorial em produção | [ADR 002](adr/002-pgvector-embeddings.md), [`embedding_service.py`](../code-samples/backend/embedding_service.py), [`face_service.py`](../code-samples/backend/face_service.py) |
| Inferência em CPU e latência | Warm-up, lock inter-processo, carga em thread ([lição 4](lessons-learned.md)) |
| MLOps: regressão de modelo e versionamento | Baseline de modelos entre versões de biblioteca (acima) |
| Pipelines assíncronos e filas | [`job_metrics.py`](../code-samples/backend/job_metrics.py), [`worker_health.py`](../code-samples/backend/worker_health.py) |
| Observabilidade de sistemas de IA | [ADR 004](adr/004-ponte-metricas-worker-redis-api.md), [ADR 005](adr/005-alertas-como-codigo-testado.md) |
| Agentes e *tool calling* seguros | [ADR 006](adr/006-orquestrador-llm-ferramentas-somente-leitura.md), [argus-trace.md](argus-trace.md) |
| Controle de custo e resiliência de LLM | Teto em 3 camadas, fallback, `LLMClient` ([ADR 007](adr/007-roteamento-ia-so-quando-necessaria.md)) |
| Privacidade e LGPD em IA | [ADR 008](adr/008-privacidade-pseudonimizacao-llm.md) |
| Avaliação de LLM | Plano de avaliação com perguntas sem resposta (acima) |
| Grafos e algoritmos | BFS em lote, freios, "parcial ≠ sem conexão" ([argus-trace.md](argus-trace.md)) |
| Fluxos de desenvolvimento assistidos por IA | Skills, personas, hooks, revisão multiagente (acima) |
