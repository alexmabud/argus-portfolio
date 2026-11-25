# Lições de incidentes reais

Postmortems curtos de problemas que aconteceram em produção (ou quase),
com causa raiz, correção e o que mudou no processo depois. Sem dados
operacionais; o foco é o raciocínio de diagnóstico.

Formato: **Sintoma → Causa → Correção → O que mudou.**

---

## 1. Picos de latência e rajadas de erro 5xx com o banco saudável

**Sintoma.** Relatório diário acusava p95 de 27–54 s quase todo dia e
rajadas de 5xx que sumiam sozinhas em ~5 minutos.

**Diagnóstico.** A primeira hipótese óbvia (banco lento) foi descartada
com evidência: log de queries lentas (`log_min_duration_statement`) e
`pg_stat_statements` mostraram **zero** query acima de 500 ms, e o
`EXPLAIN` da busca principal levava poucos milissegundos. Índices "sem uso"
no `pg_stat_user_tables` eram normais para o volume (o planner prefere
seq scan em tabela de poucas páginas).

**Causa.** Esgotamento do *pool* de conexões. O proxy interno que serve as
fotos mantinha uma conexão do pool aberta durante a resposta inteira — o
que inclui baixar a imagem do storage e renderizar a marca d'água. Uma tela
com galeria dispara dezenas de requisições simultâneas de imagem; o pool
(15 conexões por worker) estourava e *toda* requisição nova, até as mais
simples, ficava na fila.

**Correção.**
1. Núcleo: a autenticação e a verificação de acesso ao arquivo passaram a
   rodar numa sessão de escopo curto, **fechada antes** de o handler tocar
   o storage ou renderizar qualquer coisa.
2. Pool de conexões do cliente S3 ampliado.
3. `loading="lazy"` nas grades de foto que faltavam.
4. Deduplicação, no cliente, de GETs idênticos em voo.

**O que mudou.**
- Uma proposta de cache no cliente para as fotos foi **derrubada na
  revisão de código**: pularia a checagem de acesso e vazaria dado entre
  operadores em aparelho compartilhado. O problema foi resolvido só no
  backend.
- Lição geral: *conexão de banco não pode ficar presa durante I/O de rede
  externo*. Dependências de requisição que seguram recurso escasso até o
  fim da resposta são uma armadilha clássica.

---

## 2. Alerta "preso" e alertas que nunca disparavam

**Sintoma.** Alertas no Telegram que ficavam ativos por horas sem motivo;
e, pior, regras que falhavam em silêncio.

**Causa raiz (várias, todas na configuração de alertas).**
- O motor de expressão do Grafana só aceita `gt`, `lt`, `within_range` e
  `outside_range` — `gte` **não existe**, e a regra falhava a cada avaliação.
- Casamento de vetores PromQL entre um agregado (sem label) e uma série
  crua nunca bate sem `on()`.
- Vetor vazio + `noDataState: Alerting` = alerta perpétuo.
- `histogram_quantile` de um histograma todo-zero devolve `NaN`, e o
  threshold do Grafana trata `NaN` como disparo.

**Correção.** Em vez de "consertar a regra da vez", o processo mudou:
as regras do Grafana viraram **código testado**. Um script converte o
provisioning real para o formato do Prometheus e o `promtool` roda
cenários de comportamento no CI (um por modo de falha que já aconteceu),
mais um smoke test que sobe o Grafana de produção com o provisioning
inteiro. As regras de teste são **geradas** da mesma fonte que produção
carrega — o teste não pode divergir dela.

**O que mudou.** 23 alertas, todos com cenário de teste; regra nova sem
teste não passa. Código em
[`code-samples/monitoring/`](../code-samples/monitoring/).

---

## 3. "Quem vigia o vigia?" — o ponto cego do próprio monitoramento

**Sintoma (risco identificado em auditoria, antes de virar incidente).**
Todos os alertas são avaliados pelo Grafana. Se o Grafana ou o Prometheus
morresse — ou se só o *scheduler* de alertas travasse, com a interface
respondendo normalmente — o silêncio no Telegram seria indistinguível de
"está tudo bem".

**Correção.** Um watchdog (dead-man's switch) num processo separado, que
checa o Prometheus, o Grafana e o contador de ticks do scheduler, e avisa
só nas **transições** (ficou ruim / voltou) para não virar ruído.

**Lição.** Todo sistema de alerta precisa de um alerta sobre si mesmo,
rodando fora dele. Ver
[`watchdog.py`](../code-samples/monitoring/watchdog.py).

---

## 4. Primeira busca depois de cada deploy levava ~25 s

**Sintoma.** p95 voltava a ~28 s depois de cada reinício da API.

**Cadeia de causas (resolvida em três passos).**
1. O modelo de embeddings era carregado de forma **síncrona** dentro da
   corrotina da primeira busca, congelando o *event loop* inteiro.
   → carga movida para uma thread (`asyncio.to_thread`).
2. A própria requisição que disparava a carga ainda esperava ~25 s.
   → *warm-up* eager dos modelos de IA no `lifespan`, antes de a API
   aceitar tráfego.
3. Com 4 workers Gunicorn, os 4 carregavam os modelos ao mesmo tempo e
   disputavam CPU. → lock inter-processo (`fcntl.flock`) serializando a
   carga ([`interprocess_lock.py`](../code-samples/backend/interprocess_lock.py)).

**Lição.** Cada correção expôs o gargalo seguinte; só o diagnóstico com
evidência de produção (e não palpite) evitou parar no primeiro passo.

---

## 5. Backup que morria em silêncio

**Sintoma.** O backup offsite parou e ninguém foi avisado.

**Causa.** O `tar` de um banco SQLite em uso saiu com código 1 ("arquivo
mudou durante a leitura"); com `set -e`, o script abortou — e o `stderr`
estava sendo descartado pelo cron.

**Correção.** `stderr` para log, `trap ERR` com mensagem, e tolerância
específica ao código 1 do `tar`. Alerta de "último backup bem-sucedido" já
existia como métrica — foi ele que revelou a falha.

**Lição.** Script de cron sem log e sem métrica de sucesso falha mudo.
Medir o *sucesso* (timestamp do último backup ok), não a execução.

---

## 6. Retry de abordagem recadastrava pessoas já criadas

**Sintoma.** Registrar uma abordagem com várias pessoas novas falhava
com erro de conflito ("já cadastrada") e repetir a ação repetia o erro.

**Causa.** O envio criava as pessoas novas num laço e só limpava a lista de
"novas" no fim. Se a requisição falhasse no meio, as primeiras já estavam
no banco, mas o retry as reenviava — com identificador, conflito de novo;
sem identificador, **duplicatas silenciosas**.

**Correção.** Cada pessoa criada sai imediatamente da lista de pendentes;
o retry continua apenas do que falta. Em produção, uma consulta de
leitura confirmou que o bug não tinha deixado duplicatas.

**Lição.** Operações em lote no cliente precisam de **progresso
persistido por item**, e o servidor precisa ser idempotente
([`client_id_dedup.py`](../code-samples/backend/client_id_dedup.py),
[`sync.js`](../code-samples/frontend/sync.js)).

---

## 7. Dependência que quebra o worker: o teto do `redis-py`

**Sintoma.** O bot de atualização de dependências propunha, mês após mês,
subir o cliente `redis` — e o worker de filas (`arq`) quebraria.

**Causa.** O `arq` limita `redis<6`, e a própria tentativa upstream de
subir o limite foi fechada sem merge. Com atualizações agrupadas num PR
mensal, o bump apareceu *misturado* com outros sete seguros.

**Correção.** Ignorar o pacote no bot de forma permanente, com a razão e a
condição de desbloqueio registradas num arquivo de "atualizações
bloqueadas" — nunca apenas fechar o PR.

**Lição.** Recusa de atualização é conhecimento: precisa de registro com
evidência e critério de reavaliação, senão será redescoberta a cada mês.
