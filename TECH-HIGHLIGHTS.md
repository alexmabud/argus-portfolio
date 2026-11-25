# Destaques técnicos

Alguns dos problemas de engenharia mais interessantes resolvidos no
projeto. Onde faz sentido, linko o código real em
[code-samples/](code-samples/) — o resto é descrição conceitual (ver nota
de segurança no README sobre o que fica de fora). Para o raciocínio por
trás de falhas reais, ver [docs/lessons-learned.md](docs/lessons-learned.md).

## Busca híbrida num único banco

O sistema precisa responder perguntas de busca muito diferentes: "quem se
parece com esse rosto", "quem foi abordado perto daqui" e "quem tem um nome
parecido com esse, mesmo com erro de digitação". Em vez de introduzir um
banco vetorial e um motor geoespacial separados, tudo roda num único
PostgreSQL com três extensões (`pgvector`, `PostGIS`, `pg_trgm`), com
índices especializados (HNSW para vetores, GiST para geografia). Menos
peças móveis, menos infraestrutura para manter em produção, e filtros
relacionais combináveis na mesma query. Decisão registrada no
[ADR 002](docs/adr/002-pgvector-embeddings.md).

## Captura em campo, sem depender de sinal

O requisito operacional era cadastrar uma abordagem em menos de 40
segundos — e no campo, sinal de dados não é garantido. A solução foi um PWA
offline-first: os dados entram em IndexedDB local imediatamente, e a
sincronização com o servidor acontece em background assim que a conexão
volta, sem bloquear o fluxo de quem está cadastrando.

O difícil não é guardar offline — é **sincronizar sem duplicar nem perder**:

- Cada item recebe um `client_id` (UUID) no cliente; o servidor deduplica
  por ele, inclusive quando duas requisições concorrentes disputam o mesmo
  id (o índice único parcial rejeita a segunda, e o serviço devolve a
  entidade vencedora) →
  [`client_id_dedup.py`](code-samples/backend/client_id_dedup.py).
- A trava de "sincronização em andamento" é setada **antes** do primeiro
  `await`, fechando uma janela de corrida em que reconexões geravam vários
  eventos `online` e duplicavam o upload de fotos.
- Abordagem com fotos segue um fluxo próprio (precisa do id do servidor
  para subir a mídia) e **retoma foto a foto**: o que já foi enviado fica
  marcado, e cada foto leva seu próprio `client_id` para o servidor
  deduplicar mesmo se a marcação falhar →
  [`sync.js`](code-samples/frontend/sync.js).

## Pipeline de IA assíncrono

Reconhecimento facial é caro o suficiente para nunca rodar no caminho
síncrono de uma requisição HTTP. A tarefa vai para uma fila (Redis +
`arq`) e é processada por workers separados da API — a guarnição recebe a
confirmação do cadastro na hora, e o enriquecimento acontece em paralelo.

- Modelo de rosto: InsightFace `buffalo_l` (CPU), maior rosto por foto,
  embedding de 512 dimensões →
  [`face_service.py`](code-samples/backend/face_service.py).
- Embeddings de texto com cache em Redis →
  [`embedding_service.py`](code-samples/backend/embedding_service.py).
- Carga dos modelos no startup serializada entre os workers Gunicorn com
  `fcntl.flock`, para não disputar CPU →
  [`interprocess_lock.py`](code-samples/backend/interprocess_lock.py)
  (com [testes](code-samples/tests/test_interprocess_lock.py)).

## Vínculos entre pessoas materializados com UPSERT

"Com quem fulano costuma andar?" não é recalculado a cada consulta. Cada
abordagem conjunta reforça (ou cria) uma linha por *par* de pessoas, com
frequência e primeira/última vez, via `INSERT … ON CONFLICT DO UPDATE`. O
par é normalizado (`id_a < id_b`), então uma única restrição de unicidade
cobre as duas direções →
[`relacionamento_repo.py`](code-samples/backend/relacionamento_repo.py).

## Observabilidade como código

Regras de alerta do Grafana costumam ser configuração solta, editada na UI
e nunca testada. Aqui elas são versionadas e validadas no CI: um script
converte o provisioning do Grafana para o formato de teste do Prometheus
(`promtool`), roda cenários de **comportamento** (não só sintaxe), e um
smoke test sobe a stack de monitoramento real antes do merge. Motivação
direta: alertas mal configurados que ficaram presos sem disparar em
produção.

- Conversor + cenários:
  [`code-samples/monitoring/`](code-samples/monitoring/) e
  [ADR 005](docs/adr/005-alertas-como-codigo-testado.md).
- **Métricas de domínio da fila** por uma ponte worker → Redis → API (o
  worker não expõe HTTP) →
  [`job_metrics.py`](code-samples/backend/job_metrics.py),
  [ADR 004](docs/adr/004-ponte-metricas-worker-redis-api.md).
- **Liveness por instância de worker**, com falha fechada quando o Redis
  não responde →
  [`worker_health.py`](code-samples/backend/worker_health.py).
- **Watchdog do próprio monitoramento** (dead-man's switch fora da stack
  vigiada, avisando só nas transições) →
  [`watchdog.py`](code-samples/monitoring/watchdog.py).

## Infraestrutura testada como código

Invariantes de operação viram testes de unidade: a ordem das etapas do
script de deploy (build antes de parar a aplicação, para que falha de
build não vire outage), a configuração do bot de dependências, a
estrutura do provisioning de alertas
([exemplo](code-samples/tests/test_grafana_alert_rules.py)). Regressão de
infra aparece no CI, não na madrugada.

## LGPD por padrão, não por exceção

Dado pessoal sensível (CPF, foto, biometria facial) passa por criptografia
em repouso, nunca é removido fisicamente (soft delete + auditoria), e todo
acesso é atribuído a um usuário e a uma guarnição específicos. Esses
princípios são aplicados nos mixins e na camada de acesso a dados — não
são uma checagem manual espalhada pelo código; são parte da estrutura que
qualquer nova entidade herda por padrão. Em produção, a aplicação ainda
roda com um papel de banco **só-DML**, separado do papel que aplica
migrations.

## Resiliência operacional

Backup em três camadas (local, dois provedores de nuvem com cifra GPG,
script de restauração interativo), alerta de "último backup bem-sucedido",
plano de recuperação de desastre documentado e um postmortem de como um
backup chegou a morrer em silêncio
([lição 5](docs/lessons-learned.md#5-backup-que-morria-em-silêncio)).
