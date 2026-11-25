/**
 * Gerenciador de sincronização offline → online.
 *
 * Monitora conectividade, processa fila de itens pendentes
 * e sincroniza batch com backend via /api/v1/sync/batch.
 */
class SyncManager {
  constructor() {
    this.syncing = false;
    this.intervalId = null;
    this.onStatusChange = null;
  }

  start() {
    // Escutar eventos de conectividade
    window.addEventListener("online", () => this.syncAll());

    // Escutar mensagem do Service Worker
    navigator.serviceWorker?.addEventListener("message", (event) => {
      if (event.data?.type === "SYNC_NOW") this.syncAll();
    });

    // Poll a cada 30 segundos
    this.intervalId = setInterval(() => {
      if (navigator.onLine && !this.syncing) this.syncAll();
    }, 30000);
  }

  stop() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  async syncAll() {
    if (this.syncing || !navigator.onLine) return;
    // Trava setada ANTES do primeiro await — se duas chamadas concorrentes
    // (ex.: reconexão gerando vários eventos "online" em sequência) chegam
    // aqui quase simultaneamente, só a primeira passa: a segunda vê
    // this.syncing === true e retorna. Antes a trava só era setada depois de
    // `await getPendingSync()`, deixando uma janela onde ambas liam os
    // mesmos itens pendentes e rodavam _syncAbordagemComFotos em paralelo
    // para o mesmo item, duplicando o upload das fotos.
    this.syncing = true;

    let semFotos = [];
    try {
      const pending = await getPendingSync();
      if (pending.length === 0) return;

      this._notify("syncing", { total: pending.length });

      // Abordagens com fotos vão pelo fluxo /abordagens/ (idempotente por client_id)
      // para obter o id do servidor e subir a mídia — o batch não retorna esse id (#5).
      const comFotos = pending.filter((p) => p.tipo === "abordagem" && p.fotos && p.fotos.length);
      semFotos = pending.filter((p) => !(p.tipo === "abordagem" && p.fotos && p.fotos.length));

      let synced = 0;
      let failed = 0;

      for (const item of comFotos) {
        (await this._syncAbordagemComFotos(item)) ? synced++ : failed++;
      }

      if (semFotos.length > 0) {
        const items = semFotos.map((item) => ({
          client_id: item.clientId,
          tipo: item.tipo,
          dados: item.dados,
        }));

        const response = await api.post("/sync/batch", { items });

        for (const result of response.results) {
          const item = semFotos.find((p) => p.clientId === result.client_id);
          if (!item) continue;

          if (result.status === "ok") {
            await markSynced(item.id);
            synced++;
          } else {
            await markFailed(item.id, result.error || "Erro desconhecido");
            failed++;
          }
        }
      }

      this._notify("done", { synced, failed });
    } catch (err) {
      // Auth/rede: sync de background NUNCA deve causar logout — abortar silenciosamente
      if (err.status === 401 || err.status === 0) {
        this._notify("done", { synced: 0, failed: 0 });
        return;
      }
      // Se endpoint não existe ainda, sincronizar individualmente
      await this._syncIndividual(semFotos);
    } finally {
      this.syncing = false;
    }
  }

  async _syncAbordagemComFotos(item) {
    // Recria a abordagem pelo endpoint normal (dedup por client_id no payload)
    // e sobe cada foto persistida com o id retornado pelo servidor.
    //
    // Pula fotos já marcadas `enviada` (tentativa anterior deste item que
    // enviou algumas fotos e falhou antes de completar) e manda o clientId
    // de cada foto como client_id — o backend deduplica por ele
    // (FotoService.upload_foto), então mesmo que este retry reenvie uma foto
    // que na verdade já tinha sido aceita (ex.: markFotoEnviada falhou por
    // queda de rede logo após o upload), o servidor não duplica.
    try {
      const created = await api.post("/abordagens/", item.dados);
      for (let i = 0; i < item.fotos.length; i++) {
        const foto = item.fotos[i];
        if (foto.enviada) continue;
        const extra = { tipo: foto.tipo, abordagem_id: created.id, client_id: foto.clientId };
        if (foto.pessoa_id != null) extra.pessoa_id = foto.pessoa_id;
        if (foto.veiculo_id != null) extra.veiculo_id = foto.veiculo_id;
        await api.uploadFile("/fotos/upload", foto.blob, extra);
        await markFotoEnviada(item.id, i);
      }
      await markSynced(item.id);
      return true;
    } catch (err) {
      await markFailed(item.id, err.message || "Erro ao sincronizar abordagem com fotos");
      return false;
    }
  }

  async _syncIndividual(pending) {
    let synced = 0;
    let failed = 0;

    for (const item of pending) {
      try {
        const endpointMap = {
          abordagem: "/abordagens/",
          pessoa: "/pessoas/",
          veiculo: "/veiculos/",
        };
        const endpoint = endpointMap[item.tipo];
        if (!endpoint) {
          await markFailed(item.id, `Tipo desconhecido: ${item.tipo}`);
          failed++;
          continue;
        }
        await api.post(endpoint, item.dados);
        await markSynced(item.id);
        synced++;
      } catch (err) {
        await markFailed(item.id, err.message || "Erro na sincronização");
        failed++;
      }
    }

    this._notify("done", { synced, failed });
  }

  _notify(status, detail = {}) {
    if (this.onStatusChange) {
      this.onStatusChange(status, detail);
    }
  }
}

// Singleton global
const syncManager = new SyncManager();
