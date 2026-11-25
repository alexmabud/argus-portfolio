"""Métricas de domínio da fila arq (profundidade, falhas e duração de jobs).

Até a auditoria de 2026-07-28 a observabilidade parava no HTTP: dava para ver
que `/fotos/buscar-rosto` demorou, mas não o que acontecia **depois** da
resposta. Com os dois workers vivos e a fila entupida — ou com todo job de face
falhando em silêncio — nenhum alerta disparava e nenhum painel mostrava nada.
`argus_worker_alive` só responde "o processo está de pé", não "o trabalho está
andando".

O worker roda em processo separado e não expõe HTTP, então não dá para o
Prometheus raspá-lo direto. Este módulo usa a mesma ponte já validada pelo
`app/core/worker_health.py`: **o worker escreve contadores no Redis, a API lê e
publica como métricas Prometheus**.

Métricas publicadas (todas com ``multiprocess_mode="mostrecent"``, porque a API
roda com múltiplos workers Gunicorn):

* ``argus_arq_queue_size`` — jobs prontos para execução agora na fila.
* ``argus_arq_jobs_completed_total{function}`` — jobs concluídos com sucesso.
* ``argus_arq_jobs_failed_total{function}`` — tentativas que levantaram exceção.
* ``argus_arq_job_duration_seconds_total{function}`` — segundos acumulados.

São Gauges (não Counters) porque espelham um valor lido do Redis em vez de
serem incrementados no processo. Como os contadores no Redis são monotônicos,
``rate()``/``increase()`` funcionam normalmente, e a duração média sai de
``rate(duration_total) / rate(completed_total)``.
"""

import asyncio
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis
from arq.constants import default_queue_name
from prometheus_client import Gauge

from app.config import settings

logger = logging.getLogger("argus")

#: Hashes no Redis onde o worker acumula os contadores, por nome de função.
CHAVE_CONCLUIDOS = "argus:metrics:jobs:completed"
CHAVE_FALHAS = "argus:metrics:jobs:failed"
CHAVE_DURACAO = "argus:metrics:jobs:duration_seconds"

QUEUE_SIZE_GAUGE = Gauge(
    "argus_arq_queue_size",
    "Jobs arq prontos para execução na fila (backlog)",
    multiprocess_mode="mostrecent",
)

JOBS_COMPLETED_GAUGE = Gauge(
    "argus_arq_jobs_completed_total",
    "Total de jobs arq concluídos com sucesso, por função",
    ["function"],
    multiprocess_mode="mostrecent",
)

JOBS_FAILED_GAUGE = Gauge(
    "argus_arq_jobs_failed_total",
    "Total de tentativas de job arq que terminaram em exceção, por função",
    ["function"],
    multiprocess_mode="mostrecent",
)

JOB_DURATION_GAUGE = Gauge(
    "argus_arq_job_duration_seconds_total",
    "Segundos acumulados de execução de jobs arq, por função",
    ["function"],
    multiprocess_mode="mostrecent",
)


def instrumentar_task(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Decora uma task do arq para registrar duração e desfecho no Redis.

    Envolver a função na hora de registrar (``WorkerSettings.functions``) em vez
    de usar os hooks ``on_job_end``/``after_job_end`` do arq é o que dá
    granularidade **por função**: o ctx daqueles hooks não carrega o nome nem o
    resultado do job, só o id.

    ``functools.wraps`` preserva ``__qualname__``, que é como o arq deriva o
    nome do job — os enqueues por string (``enqueue_job("processar_pdf_task")``)
    continuam funcionando.

    Falha ao escrever no Redis nunca derruba o job: a métrica é observabilidade,
    não regra de negócio.

    Args:
        func: Task assíncrona do arq (primeiro argumento é o ``ctx``).

    Returns:
        A mesma task, instrumentada.
    """
    nome = func.__name__

    @functools.wraps(func)
    async def wrapper(ctx: dict, *args: Any, **kwargs: Any) -> Any:
        inicio = time.monotonic()
        try:
            resultado = await func(ctx, *args, **kwargs)
        except Exception:
            await _registrar(ctx, nome, time.monotonic() - inicio, sucesso=False)
            raise
        await _registrar(ctx, nome, time.monotonic() - inicio, sucesso=True)
        return resultado

    return wrapper


async def _registrar(ctx: dict, nome: str, duracao: float, *, sucesso: bool) -> None:
    """Acumula o desfecho de um job nos hashes do Redis.

    Reaproveita a conexão que o arq já mantém em ``ctx["redis"]`` em vez de
    abrir uma nova a cada job.

    Args:
        ctx: Contexto do job arq (contém a conexão ``redis``).
        nome: Nome da função executada.
        duracao: Duração da execução em segundos.
        sucesso: True se terminou sem exceção.
    """
    redis = ctx.get("redis")
    if redis is None:
        return
    try:
        chave = CHAVE_CONCLUIDOS if sucesso else CHAVE_FALHAS
        await redis.hincrby(chave, nome, 1)
        await redis.hincrbyfloat(CHAVE_DURACAO, nome, duracao)
    except Exception:
        logger.warning("job_metrics: falha ao registrar métrica do job %s", nome, exc_info=True)


async def _publicar_hash(client: aioredis.Redis, chave: str, gauge: Gauge) -> None:
    """Copia um hash de contadores do Redis para um gauge rotulado por função.

    Args:
        client: Conexão Redis.
        chave: Nome do hash no Redis.
        gauge: Gauge Prometheus com o label ``function``.
    """
    # redis-py tipa os comandos como `Awaitable[T] | T` (a mesma classe serve
    # o cliente sync e o async), então o mypy não consegue provar que o await
    # é válido no cliente assíncrono. Em runtime sempre é.
    valores: dict[str, str] = await client.hgetall(chave)  # type: ignore[misc]
    for nome, valor in valores.items():
        try:
            gauge.labels(function=nome).set(float(valor))
        except (TypeError, ValueError):
            logger.warning("job_metrics: valor inválido em %s[%s]: %r", chave, nome, valor)


async def atualizar_job_metrics() -> None:
    """Lê a fila e os contadores no Redis e atualiza os gauges Prometheus.

    Redis inacessível apenas loga e mantém os valores anteriores — ao contrário
    do ``worker_health``, aqui **não** faz sentido zerar: um zero falso em
    ``argus_arq_queue_size`` diria "fila vazia" (saudável) justamente durante um
    incidente. Quem alerta sobre Redis fora é o ``alert-redis-down``.
    """
    try:
        client: aioredis.Redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
        )
        try:
            # Score do sorted set do arq = instante (ms) em que o job fica
            # elegível. Contar só até agora mede o backlog real, sem inflar com
            # jobs agendados para o futuro.
            agora_ms = time.time() * 1000
            prontos = await client.zcount(default_queue_name, "-inf", agora_ms)
            QUEUE_SIZE_GAUGE.set(prontos)

            await _publicar_hash(client, CHAVE_CONCLUIDOS, JOBS_COMPLETED_GAUGE)
            await _publicar_hash(client, CHAVE_FALHAS, JOBS_FAILED_GAUGE)
            await _publicar_hash(client, CHAVE_DURACAO, JOB_DURATION_GAUGE)
        finally:
            await client.aclose()
    except Exception:
        logger.warning("job_metrics: falha ao consultar Redis, mantendo valores anteriores")


async def loop_job_metrics(intervalo_segundos: int = 30) -> None:
    """Loop em background que atualiza as métricas da fila periodicamente.

    Roda até ser cancelado no shutdown do lifespan da aplicação.

    Args:
        intervalo_segundos: Intervalo entre coletas (padrão 30s).
    """
    while True:
        await atualizar_job_metrics()
        await asyncio.sleep(intervalo_segundos)
