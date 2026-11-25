# ADR 004 — Ponte de métricas: worker → Redis → API → Prometheus

## Status
Aceito

## Contexto
A observabilidade parava no HTTP: era possível ver que uma busca facial
demorou, mas não o que acontecia *depois* da resposta. Com os workers de
fila vivos e a fila entupida — ou com todo job de rosto falhando em
silêncio — nenhum alerta disparava. A métrica "worker está de pé" não
responde "o trabalho está andando".

O worker roda em processo separado e não expõe HTTP, então o Prometheus
não consegue raspá-lo diretamente.

## Decisão
- O **worker escreve contadores no Redis** (jobs concluídos, falhas e
  duração acumulada, por nome de função).
- A **API lê o Redis e publica métricas Prometheus** (gauges que espelham
  contadores monotônicos, mais tamanho da fila).
- A saúde de cada instância de worker é publicada por uma chave de
  health-check própria (`worker_id`), para alertar por instância.
- Falha ao consultar o Redis marca os workers como indisponíveis
  (*fail-closed*): na dúvida, não assume "vivo".

## Consequências
- `rate()`/`increase()` funcionam normalmente (contadores monotônicos), e a
  duração média sai de `rate(duração) / rate(concluídos)`.
- Alertas passam a cobrir "fila entupida" e "jobs falhando", não só
  "processo morto".
- Um alerta de worker parado precisa ser **inibido** quando o Redis está
  fora (senão um único incidente gera dois alertas, desviando o
  diagnóstico) — coberto por cenário de teste.
- Acoplamento: a API passa a depender do Redis também para métricas; a
  leitura é tolerante a falha.

Código: [`job_metrics.py`](../../code-samples/backend/job_metrics.py),
[`worker_health.py`](../../code-samples/backend/worker_health.py).
