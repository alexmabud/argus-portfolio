"""Testes das métricas de domínio da fila arq.

Cobre a lacuna que a auditoria de 2026-07-28 encontrou: com os dois workers
vivos, fila entupida ou task falhando em loop eram completamente invisíveis —
`argus_worker_alive` só responde "o processo está de pé", não "o trabalho está
andando".
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import job_metrics


@pytest.fixture
def redis_falso() -> MagicMock:
    """Conexão Redis dublê com os comandos usados pelo módulo.

    Returns:
        Mock com ``hincrby``, ``hincrbyfloat``, ``zcount``, ``hgetall`` e
        ``aclose`` assíncronos.
    """
    client = MagicMock()
    client.hincrby = AsyncMock()
    client.hincrbyfloat = AsyncMock()
    client.zcount = AsyncMock(return_value=0)
    client.hgetall = AsyncMock(return_value={})
    client.aclose = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_task_bem_sucedida_conta_como_concluida(redis_falso):
    """Job que retorna normalmente incrementa concluídos e acumula duração."""

    async def minha_task(ctx: dict, valor: int) -> int:
        """Task dublê que devolve o dobro do valor."""
        return valor * 2

    instrumentada = job_metrics.instrumentar_task(minha_task)
    assert await instrumentada({"redis": redis_falso}, 21) == 42

    redis_falso.hincrby.assert_awaited_once_with(job_metrics.CHAVE_CONCLUIDOS, "minha_task", 1)
    chave, nome, duracao = redis_falso.hincrbyfloat.await_args.args
    assert chave == job_metrics.CHAVE_DURACAO
    assert nome == "minha_task"
    assert duracao >= 0


@pytest.mark.asyncio
async def test_task_que_falha_conta_como_falha_e_propaga(redis_falso):
    """Exceção do job vira métrica de falha — e continua subindo.

    Engolir a exceção quebraria o retry do arq (max_tries=3): a observabilidade
    não pode alterar o comportamento da fila.
    """

    async def task_quebrada(ctx: dict) -> None:
        """Task dublê que sempre falha."""
        raise RuntimeError("modelo de IA não carregou")

    instrumentada = job_metrics.instrumentar_task(task_quebrada)
    with pytest.raises(RuntimeError, match="modelo de IA não carregou"):
        await instrumentada({"redis": redis_falso})

    redis_falso.hincrby.assert_awaited_once_with(job_metrics.CHAVE_FALHAS, "task_quebrada", 1)


@pytest.mark.asyncio
async def test_instrumentacao_preserva_o_nome_do_job(redis_falso):
    """O wrapper não pode mudar o nome pelo qual o arq registra a task.

    Os routers enfileiram por string (``enqueue_job("processar_face_task")``) e
    o arq deriva o nome de ``__qualname__``. Perder isso faria todo job
    enfileirado morrer com "function not found" — em silêncio, do ponto de
    vista do usuário.
    """

    async def processar_face_task(ctx: dict) -> None:
        """Task dublê com o nome real de produção."""

    instrumentada = job_metrics.instrumentar_task(processar_face_task)
    assert instrumentada.__qualname__ == processar_face_task.__qualname__
    assert instrumentada.__name__ == "processar_face_task"


@pytest.mark.asyncio
async def test_falha_do_redis_nao_derruba_o_job(redis_falso):
    """Redis fora não pode transformar um job saudável em job falhado.

    A métrica é observabilidade, não regra de negócio.
    """
    redis_falso.hincrby.side_effect = ConnectionError("redis fora")

    async def minha_task(ctx: dict) -> str:
        """Task dublê bem-sucedida."""
        return "ok"

    instrumentada = job_metrics.instrumentar_task(minha_task)
    assert await instrumentada({"redis": redis_falso}) == "ok"


@pytest.mark.asyncio
async def test_task_sem_redis_no_contexto_roda_normal():
    """Contexto sem conexão Redis (testes, execução direta) não pode estourar."""

    async def minha_task(ctx: dict) -> str:
        """Task dublê bem-sucedida."""
        return "ok"

    instrumentada = job_metrics.instrumentar_task(minha_task)
    assert await instrumentada({}) == "ok"


@pytest.mark.asyncio
async def test_gauges_refletem_fila_e_contadores(monkeypatch, redis_falso):
    """A API publica backlog e contadores por função lidos do Redis."""
    redis_falso.zcount = AsyncMock(return_value=17)
    redis_falso.hgetall = AsyncMock(
        side_effect=[
            {"processar_pdf_task": "120"},  # concluídos
            {"processar_face_task": "9"},  # falhas
            {"processar_pdf_task": "480.5"},  # duração acumulada
        ]
    )
    monkeypatch.setattr(job_metrics.aioredis, "from_url", lambda *a, **k: redis_falso)

    await job_metrics.atualizar_job_metrics()

    assert job_metrics.QUEUE_SIZE_GAUGE._value.get() == 17
    concluidos = job_metrics.JOBS_COMPLETED_GAUGE.labels(function="processar_pdf_task")
    falhas = job_metrics.JOBS_FAILED_GAUGE.labels(function="processar_face_task")
    duracao = job_metrics.JOB_DURATION_GAUGE.labels(function="processar_pdf_task")
    assert concluidos._value.get() == 120
    assert falhas._value.get() == 9
    assert duracao._value.get() == 480.5


@pytest.mark.asyncio
async def test_redis_fora_nao_zera_o_tamanho_da_fila(monkeypatch, redis_falso):
    """Redis inacessível mantém o último valor em vez de publicar zero.

    Zerar diria "fila vazia" (saudável) justamente durante um incidente —
    diferente do worker_health, aqui o fail-closed seria o comportamento
    errado. Quem alerta sobre Redis fora é o alert-redis-down.
    """
    redis_falso.zcount = AsyncMock(return_value=42)
    redis_falso.hgetall = AsyncMock(return_value={})
    monkeypatch.setattr(job_metrics.aioredis, "from_url", lambda *a, **k: redis_falso)
    await job_metrics.atualizar_job_metrics()
    assert job_metrics.QUEUE_SIZE_GAUGE._value.get() == 42

    def explode(*a, **k):
        """Simula Redis inacessível na coleta seguinte."""
        raise ConnectionError("redis fora")

    monkeypatch.setattr(job_metrics.aioredis, "from_url", explode)
    await job_metrics.atualizar_job_metrics()

    assert job_metrics.QUEUE_SIZE_GAUGE._value.get() == 42
