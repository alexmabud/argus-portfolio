"""Testes unitários para o lock inter-processo (``app/core/interprocess_lock.py``).

Cobre a mitigação da contenção de CPU no warm-up de IA em produção (achado
2026-08-03): os 4 workers Gunicorn carregavam EmbeddingService/FaceService
em paralelo a cada restart, disputando CPU. O lock serializa chamadores
concorrentes que compartilham o mesmo nome, sem bloquear chamadores com
nomes diferentes.

Os testes usam threads reais (não mock de ``fcntl.flock``): cada thread abre
seu próprio file descriptor via ``os.open``, então o `flock` do SO serializa
entre elas do mesmo jeito que serializaria entre processos irmãos — prova o
comportamento de fato, não a chamada da API.
"""

import os
import shutil
import threading
import time
import uuid

from app.core.interprocess_lock import _LOCK_DIR, interprocess_lock


def test_mesmo_nome_serializa_chamadores_concorrentes():
    """Duas threads com o MESMO nome de lock não executam a seção protegida
    ao mesmo tempo — os intervalos de execução não podem se sobrepor.
    """
    nome = f"teste-{uuid.uuid4()}"
    intervalos: list[tuple[float, float]] = []
    trava = threading.Lock()

    def tarefa():
        with interprocess_lock(nome):
            inicio = time.monotonic()
            time.sleep(0.1)
            fim = time.monotonic()
        with trava:
            intervalos.append((inicio, fim))

    t1 = threading.Thread(target=tarefa)
    t2 = threading.Thread(target=tarefa)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(intervalos) == 2
    (inicio_a, fim_a), (inicio_b, fim_b) = intervalos
    sobrepoe = inicio_a < fim_b and inicio_b < fim_a
    assert not sobrepoe, f"intervalos se sobrepuseram: {intervalos} — lock não serializou"


def test_nomes_diferentes_nao_se_bloqueiam():
    """Duas threads com nomes de lock DIFERENTES não esperam uma pela
    outra — rodam em paralelo, então o tempo total é próximo ao de uma
    única seção protegida, não a soma das duas.
    """
    duracao = 0.2

    def tarefa(nome: str):
        with interprocess_lock(nome):
            time.sleep(duracao)

    t1 = threading.Thread(target=tarefa, args=(f"teste-a-{uuid.uuid4()}",))
    t2 = threading.Thread(target=tarefa, args=(f"teste-b-{uuid.uuid4()}",))

    inicio = time.monotonic()
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    total = time.monotonic() - inicio

    assert total < duracao * 1.5, (
        f"levou {total:.2f}s para duas seções de {duracao}s com nomes diferentes — "
        "parece ter serializado quando não devia"
    )


def test_excecao_dentro_do_bloco_ainda_libera_o_lock():
    """Se o código protegido lança exceção, o lock é liberado mesmo assim —
    uma aquisição seguinte com o mesmo nome não pode ficar presa esperando
    por um lock cujo dono já saiu (com erro) do bloco `with`.
    """
    nome = f"teste-excecao-{uuid.uuid4()}"

    with interprocess_lock(nome):
        pass  # aquisição solta normalmente antes da que lança exceção

    try:
        with interprocess_lock(nome):
            raise ValueError("falha simulada durante a seção protegida")
    except ValueError:
        pass

    resultado: list[str] = []

    def tenta_adquirir_de_novo():
        with interprocess_lock(nome):
            resultado.append("adquiriu")

    t = threading.Thread(target=tenta_adquirir_de_novo)
    t.start()
    t.join(timeout=2)

    assert not t.is_alive(), "thread ficou presa — lock não foi liberado após exceção"
    assert resultado == ["adquiriu"]


def test_cria_diretorio_de_lock_automaticamente():
    """Sem nenhum setup prévio (diretório de lock ausente), a primeira
    aquisição precisa funcionar — não pode exigir que algo externo (hook do
    Gunicorn, script de deploy) crie o diretório antes.
    """
    shutil.rmtree(_LOCK_DIR, ignore_errors=True)
    assert not os.path.exists(_LOCK_DIR)

    with interprocess_lock(f"teste-dir-{uuid.uuid4()}"):
        pass

    assert os.path.exists(_LOCK_DIR)
