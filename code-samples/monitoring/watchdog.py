"""Watchdog do próprio sistema de monitoramento (dead-man's switch).

Todos os alertas do Argus são avaliados pelo Grafana e entregues via Telegram.
Isso cria um ponto cego óbvio: **se o Grafana ou o Prometheus morrer, ninguém
avisa** — o silêncio no Telegram é indistinguível de "está tudo bem". Era o
follow-up G7-2 de `docs/auditoria-status.md` ("watchdog Telegram dead-man"),
adiado por supostamente exigir um receptor externo.

Não exige: este script roda no container `telegram-reporter`, que é um processo
**separado** do Grafana e do Prometheus, e fala direto com a API do Telegram.
Se a stack de observabilidade cair, ele continua de pé e avisa.

Três modos de falha cobertos:

1. **Prometheus fora** — Grafana não consegue avaliar nenhuma regra.
2. **Grafana fora** — ninguém avalia nem entrega alerta nenhum.
3. **Grafana de pé, scheduler travado** — o mais traiçoeiro: a UI responde,
   os painéis funcionam, e nenhuma regra está sendo avaliada. Detectado pelo
   contador de ticks do scheduler (`grafana_alerting_schedule_periodic_
   duration_seconds_count`), que precisa subir entre duas execuções.

Envia no Telegram só nas **transições** (ficou ruim / voltou), nunca a cada
execução — senão vira ruído e as pessoas param de ler. O estado fica em
`/tmp` dentro do container: recriar o container reenvia o aviso uma vez, o
que é o comportamento certo (é uma mudança real de estado do ponto de vista
do watchdog).

Roda via supercronic a cada 5 minutos (ver `Dockerfile`).
"""

import json
import os
import sys
from pathlib import Path

import requests

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
#: Em produção o compose passa "http://grafana:3000/grafana" (COM subpath):
#: serve_from_sub_path faz o /metrics raiz responder 301 para a URL pública,
#: que o Caddy bloqueia com 403 — sob o subpath tudo responde 200 direto.
#: Fora do modo subpath (dev), o default raiz continua correto.
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

#: Estado entre execuções. Fica em /tmp de propósito: não vale a pena um volume
#: só para isso, e perder o estado só custa uma notificação repetida.
STATE_FILE = Path(os.environ.get("WATCHDOG_STATE_FILE", "/tmp/argus_watchdog_state.json"))

#: Contador de ticks do scheduler de alertas do Grafana. Sobe a cada avaliação
#: periódica (tick de 10s). Parado entre duas execuções do watchdog = scheduler
#: travado, mesmo com o Grafana respondendo HTTP normalmente.
METRICA_TICK = "grafana_alerting_schedule_periodic_duration_seconds_count"

#: Quantidade de regras carregadas no scheduler. Zero com o provisioning cheio
#: significa que o Grafana subiu mas descartou as regras (erro de schema).
METRICA_REGRAS = "grafana_alerting_schedule_alert_rules"


def _ler_estado() -> dict:
    """Lê o estado da execução anterior.

    Returns:
        Dicionário com as chaves ``falhas`` (lista) e ``tick`` (float), ou um
        estado vazio se o arquivo não existir ou estiver corrompido.
    """
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"falhas": [], "tick": None}


def _gravar_estado(falhas: list[str], tick: float | None) -> None:
    """Persiste o estado desta execução.

    Args:
        falhas: Lista de mensagens de falha detectadas agora.
        tick: Valor atual do contador de ticks do scheduler do Grafana.
    """
    try:
        STATE_FILE.write_text(json.dumps({"falhas": falhas, "tick": tick}), encoding="utf-8")
    except OSError as exc:
        print(f"[watchdog] não consegui gravar {STATE_FILE}: {exc}", file=sys.stderr)


def _metrica_do_grafana(texto: str, nome: str) -> float | None:
    """Extrai o valor de uma métrica sem labels do texto de exposição.

    Args:
        texto: Corpo da resposta de ``/metrics`` no formato de exposição.
        nome: Nome exato da métrica (sem labels).

    Returns:
        Valor da métrica, ou None se não estiver presente.
    """
    for linha in texto.splitlines():
        if linha.startswith(f"{nome} "):
            try:
                return float(linha.split(" ", 1)[1])
            except ValueError:
                return None
    return None


def checar() -> tuple[list[str], float | None]:
    """Executa as checagens de saúde da stack de observabilidade.

    Returns:
        Tupla (falhas, tick): lista de mensagens descrevendo o que está
        quebrado (vazia = tudo certo) e o valor atual do contador de ticks
        do scheduler do Grafana (None se não deu para ler).
    """
    falhas: list[str] = []

    try:
        resp = requests.get(f"{PROMETHEUS_URL}/-/healthy", timeout=10)
        if not resp.ok:
            falhas.append(f"Prometheus respondeu HTTP {resp.status_code}")
    except requests.RequestException as exc:
        falhas.append(f"Prometheus inacessível ({type(exc).__name__})")

    try:
        resp = requests.get(f"{GRAFANA_URL}/api/health", timeout=10)
        if not resp.ok:
            falhas.append(f"Grafana respondeu HTTP {resp.status_code}")
        elif resp.json().get("database") != "ok":
            falhas.append("Banco interno do Grafana degradado (alertas não persistem estado)")
    except requests.RequestException as exc:
        falhas.append(f"Grafana inacessível ({type(exc).__name__})")
    except ValueError:
        falhas.append("Grafana devolveu /api/health inválido")

    tick: float | None = None
    try:
        resp = requests.get(f"{GRAFANA_URL}/metrics", timeout=10)
        resp.raise_for_status()
        tick = _metrica_do_grafana(resp.text, METRICA_TICK)
        regras = _metrica_do_grafana(resp.text, METRICA_REGRAS)
        if regras is not None and regras < 1:
            falhas.append("Grafana está sem NENHUMA regra de alerta carregada")
    except requests.RequestException:
        # Grafana fora já foi reportado acima; não duplica a mensagem.
        pass

    anterior = _ler_estado()
    tick_anterior = anterior.get("tick")
    # `==`, não `<=`: contador MENOR que o anterior significa que o Grafana
    # reiniciou (o contador zera), não que o scheduler travou. Como o Grafana
    # reinicia em todo deploy, `<=` acusaria "scheduler travado" depois de cada
    # um — um falso-positivo recorrente no watchdog que existe justamente para
    # ser confiável. Travado de verdade é o contador parado no MESMO valor
    # entre duas execuções (o tick é de 10s, o watchdog roda a cada 5min).
    if tick is not None and tick_anterior is not None and tick == tick_anterior:
        falhas.append(
            f"Scheduler de alertas do Grafana travado (contador de avaliações parado em {tick:.0f})"
        )

    return falhas, tick


def enviar_telegram(texto: str) -> None:
    """Envia uma mensagem no Telegram.

    Args:
        texto: Conteúdo em Markdown.

    Raises:
        SystemExit: Código 1 se o envio falhar — este é o único canal do
            watchdog, então uma falha aqui precisa aparecer no log do cron.
    """
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "Markdown"},
            timeout=15,
        )
    except requests.RequestException as exc:
        # Nunca logar a URL — contém o bot token.
        print(
            f"[watchdog] erro de conexão ao enviar Telegram: {type(exc).__name__}", file=sys.stderr
        )
        raise SystemExit(1) from exc
    if not resp.ok:
        print(f"[watchdog] erro ao enviar Telegram: status={resp.status_code}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    """Checa a stack de observabilidade e notifica apenas nas transições.

    Raises:
        SystemExit: Código 1 se houver falha ativa (sinaliza o run como ruim
            para quem olhar o log do supercronic), ou se o envio ao Telegram
            falhar.
    """
    falhas, tick = checar()
    anterior = _ler_estado().get("falhas", [])
    _gravar_estado(falhas, tick)

    if falhas and falhas != anterior:
        corpo = "\n".join(f"• {f}" for f in falhas)
        enviar_telegram(
            "🚨 *ArgusMonitor — O MONITORAMENTO ESTÁ CEGO*\n"
            f"{corpo}\n\n"
            "_Enquanto isso durar, nenhum alerta do Grafana chega aqui — "
            "silêncio no Telegram NÃO significa que está tudo bem._"
        )
    elif anterior and not falhas:
        enviar_telegram(
            "✅ *ArgusMonitor — monitoramento normalizado*\nAlertas voltaram a ser avaliados."
        )

    if falhas:
        print(f"[watchdog] DEGRADADO: {falhas}", file=sys.stderr)
        raise SystemExit(1)
    print("[watchdog] stack de observabilidade saudável.")


if __name__ == "__main__":
    main()
