"""Lock inter-processo baseado em ``fcntl.flock``.

Serializa seções críticas entre processos irmãos que compartilham o mesmo
filesystem (mesmo container) — usado para evitar que os 4 workers Gunicorn
carreguem o mesmo modelo de IA (EmbeddingService/FaceService) em paralelo no
warm-up de startup, disputando CPU (achado 2026-08-03, ver
``app/dependencies.py::warm_up_ai_services``).
"""

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager

#: Diretório dos arquivos de lock. Fica em ``/tmp`` (efêmero, específico do
#: container) e é criado sob demanda — diferente do
#: ``PROMETHEUS_MULTIPROC_DIR``, não precisa ser limpo por um hook do
#: master antes do fork: os arquivos de lock não acumulam estado entre
#: restarts, só existem para coordenar a aquisição do ``flock``.
_LOCK_DIR = "/tmp/argus_startup_locks"


@contextmanager
def interprocess_lock(name: str) -> Iterator[None]:
    """Adquire um lock exclusivo e bloqueante identificado por nome.

    Chamadores concorrentes (threads do mesmo processo ou processos
    irmãos que compartilham o filesystem) com o MESMO ``name`` executam a
    seção protegida em sequência, nunca simultaneamente. Chamadores com
    nomes diferentes não se bloqueiam entre si.

    Bloqueia sem timeout próprio: um chamador travado dentro da seção
    protegida mantém o lock até o processo terminar (crash, OOM-kill ou o
    ``--timeout`` do Gunicorn matando o worker) — ao fechar o file
    descriptor, o SO libera o ``flock`` automaticamente, sem risco de lock
    órfão.

    Args:
        name: Identificador do lock. Vira o nome do arquivo sob
            ``_LOCK_DIR`` — chamadores com o mesmo ``name`` se serializam.

    Yields:
        None. O bloco ``with`` roda com o lock adquirido.
    """
    os.makedirs(_LOCK_DIR, exist_ok=True)
    caminho = os.path.join(_LOCK_DIR, f"{name}.lock")
    fd = os.open(caminho, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
