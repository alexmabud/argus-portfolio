# Amostras de código

Arquivos reais, copiados do sistema em produção — cada um revisado
individualmente antes de entrar aqui. Critério de seleção: nenhum toca
autenticação, permissões, rate limiting, criptografia ou multi-tenancy
(a parte sensível do sistema fica de fora, de propósito).

> São **trechos de leitura**, não um projeto executável: importam módulos
> que não estão neste repositório (ex.: `app.config`, `app.models`). O
> único ajuste feito nos arquivos originais foi trocar o domínio de
> produção por um placeholder (`argus.example.com`) nos testes de alerta.

## Backend (`backend/`)

| Arquivo | O que mostra |
|---|---|
| [`validators.py`](backend/validators.py) | Validador Pydantic reutilizável via tipo anotado (`Annotated` + `BeforeValidator`) |
| [`embedding_service.py`](backend/embedding_service.py) | Serviço async com cache Redis para embeddings de busca semântica (SentenceTransformers) |
| [`face_service.py`](backend/face_service.py) | Embedding facial de 512 dimensões com InsightFace; seleciona o rosto de maior confiança |
| [`geocoding_service.py`](backend/geocoding_service.py) | Integração com API externa (geocoding), com fallback entre provedores e degradação graciosa |
| [`relacionamento_repo.py`](backend/relacionamento_repo.py) | Repositório com UPSERT (`ON CONFLICT DO UPDATE`) para materializar vínculos entre pessoas |
| [`client_id_dedup.py`](backend/client_id_dedup.py) | Idempotência do sync offline sob concorrência: recupera da corrida de insert via índice único parcial |
| [`interprocess_lock.py`](backend/interprocess_lock.py) | Lock inter-processo com `fcntl.flock` para serializar o warm-up dos modelos entre workers Gunicorn |
| [`worker_health.py`](backend/worker_health.py) | Gauge Prometheus de liveness por worker `arq`, com falha fechada |
| [`job_metrics.py`](backend/job_metrics.py) | Ponte de métricas worker → Redis → API → Prometheus (fila, falhas, duração por job) |

## Frontend (`frontend/`)

| Arquivo | O que mostra |
|---|---|
| [`sync.js`](frontend/sync.js) | Gerenciador de sincronização offline → online do PWA: fila local, retry, batch, trava anti-corrida e retomada foto a foto |

## Observabilidade (`monitoring/`)

| Arquivo | O que mostra |
|---|---|
| [`build_promtool_rules.py`](monitoring/build_promtool_rules.py) | Converte as regras de alerta do Grafana para o formato do Prometheus, para testar no CI |
| [`promql_unit_tests.yml`](monitoring/promql_unit_tests.yml) | Cenários `promtool` — um por modo de falha que já aconteceu em produção |
| [`watchdog.py`](monitoring/watchdog.py) | Dead-man's switch do próprio monitoramento: avisa só nas transições de estado |

## Testes (`tests/`)

| Arquivo | O que mostra |
|---|---|
| [`test_schemas_abordagem.py`](tests/test_schemas_abordagem.py) | Testes unitários de schema Pydantic, incluindo normalização de texto |
| [`test_interprocess_lock.py`](tests/test_interprocess_lock.py) | Exclusão mútua entre threads com o mesmo nome de lock, liberação em caso de exceção |
| [`test_worker_health.py`](tests/test_worker_health.py) | Testes async com Redis em memória, incluindo o caminho de falha fechada |
| [`test_job_metrics.py`](tests/test_job_metrics.py) | Testes da ponte de métricas: job concluído/falho, nome preservado, e job que não cai quando o Redis cai |
| [`test_grafana_alert_rules.py`](tests/test_grafana_alert_rules.py) | Teste estrutural do provisioning de alertas (regressão do incidente de "alerta preso") |

Contexto em [ARCHITECTURE.md](../ARCHITECTURE.md),
[TECH-HIGHLIGHTS.md](../TECH-HIGHLIGHTS.md) e
[docs/lessons-learned.md](../docs/lessons-learned.md).
