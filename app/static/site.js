/* LicitaRadar: atualização segura da visualização local; não executa consultas PNCP. */
(() => {
  "use strict";

  const refreshButton = document.querySelector("#refresh-view");
  const refreshLabel = document.querySelector("#refresh-state");
  const tableBody = document.querySelector("#items-body");
  const historyBody = document.querySelector("#events-body");
  if (!refreshButton || !refreshLabel || !tableBody || !historyBody) return;

  const statuses = Object.freeze({
    1: "Em andamento", 2: "Homologado", 3: "Cancelado",
    4: "Deserto", 5: "Fracassado"
  });
  const currency = new Intl.NumberFormat("pt-BR", {
    style: "currency", currency: "BRL"
  });

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined && value !== null) element.textContent = String(value);
    return element;
  }

  function statusBadge(number) {
    const status = Number(number);
    const value = Object.hasOwn(statuses, status) ? status : 0;
    return node("span", "status s" + value, statuses[value] || "Não identificado");
  }

  function sourceLink(address, label) {
    const value = String(address || "");
    let url;
    try {
      url = new URL(value);
    } catch {
      return node("span", "muted", "Fonte indisponível");
    }
    // Dados renderizados no client nunca podem direcionar para domínio arbitrário.
    if (url.protocol !== "https:" || url.hostname !== "pncp.gov.br") {
      return node("span", "muted", "Fonte não verificada");
    }
    const link = node("a", "table-link", label);
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  }

  function itemRow(item) {
    const row = node("tr");
    const description = node("td");
    const analysis = item.analysis || {};
    description.append(
      node("strong", "", item.descricao || "Sem descrição"),
      node("small", "", "Item " + String(item.numero ?? "?") + " · " +
        String(item.data_publicacao || "data não publicada")),
      node("small", "category-tag", (analysis.category_label || "Outros / a verificar") +
        " · " + (analysis.ease || "Verificar especificações"))
    );
    const financeLabels = {
      sem_cotacao: "Análise financeira: sem cotação.",
      desatualizada: "Cotação desatualizada. Revalidar.",
      margem_insuficiente: "Sua cotação não atende à margem desejada.",
      potencial_financeiro: "Sua cotação indica margem possível. Revisar edital.",
      sem_referencia: "Sem preço de referência para comparar."
    };
    description.append(node("small", "finance-note", financeLabels[analysis.status] ||
      "Análise financeira: verificar."));
    const location = node("td");
    location.append(
      node("strong", "", (item.municipio || "Município não informado") +
        " / " + (item.uf || "?")),
      node("small", "", item.orgao || "Órgão não informado")
    );
    const amount = node("td");
    const rawAmount = item.valor_total;
    const numericAmount = Number(rawAmount);
    const published = rawAmount !== null && rawAmount !== undefined &&
      rawAmount !== "" && Number.isFinite(numericAmount);
    amount.append(published
      ? document.createTextNode(currency.format(numericAmount))
      : node("span", "muted", "Não informado / sigiloso"));

    const state = node("td");
    state.append(statusBadge(item.status));

    const source = node("td", "link-cell");
    source.append(sourceLink(item.link, "Ver edital ↗"));
    const quoteLink = node("a", "table-link quote-link", "Custo e margem ↗");
    const query = new URLSearchParams({
      tender_id: String(item.tender_id || ""),
      numero: String(item.numero || "")
    });
    quoteLink.href = "/quote?" + query.toString();
    source.append(quoteLink);
    row.append(description, location, amount, state, source);
    return row;
  }

  function emptyItemRow() {
    const row = node("tr");
    const cell = node("td", "empty");
    cell.colSpan = 5;
    cell.append(
      node("span", "empty-icon", "◎"),
      node("strong", "", "Nenhum item encontrado"),
      node("span", "", "Sincronize o PNCP ou ajuste os filtros.")
    );
    row.append(cell);
    return row;
  }

  function eventRow(event) {
    const row = node("div", "event-row");
    const main = node("div", "event-main");
    const dot = node("span", "event-marker");
    dot.setAttribute("aria-hidden", "true");
    const meta = node("div");
    meta.append(
      node("strong", "", event.descricao || "Item sem descrição"),
      node("small", "", (event.municipio || "Município não informado") +
        " / " + (event.uf || "?") + " · Item " + String(event.numero ?? "?") +
        " · " + String(event.changed_at || "").slice(0, 19) + " UTC")
    );
    main.append(dot, meta);

    const badges = node("div", "event-badges");
    if (event.previous_status === null || event.previous_status === undefined) {
      badges.append(node("span", "muted", "Novo registro →"));
    } else {
      badges.append(
        statusBadge(event.previous_status),
        node("span", "muted", "→")
      );
    }
    badges.append(statusBadge(event.current_status), sourceLink(event.link, "PNCP ↗"));
    row.append(main, badges);
    return row;
  }

  function updateCount(elementId, number) {
    const element = document.getElementById(elementId);
    if (element) element.textContent = String(Number(number) || 0);
  }

  function updatePagination(total, page) {
    const pagination = document.querySelector(".pagination");
    if (!pagination) return;
    const text = document.getElementById("pagination-total");
    if (text) text.textContent = String(total);
    const navigation = pagination.querySelector("div");
    if (!navigation) return;
    navigation.replaceChildren();
    const addLink = (number, label) => {
      const target = new URL(window.location.href);
      target.searchParams.set("page", String(number));
      const link = node("a", "", label);
      link.href = target.pathname + target.search;
      navigation.append(link);
    };
    if (page > 1) addLink(page - 1, "← Anterior");
    if (page * 25 < total) addLink(page + 1, "Próxima →");
  }

  function updateItems(payload) {
    if (!payload || !Array.isArray(payload.data)) throw new Error("Itens inválidos");
    const counts = payload.counts || {};
    const total = Number(payload.total) || 0;
    const page = Number(payload.page) || 1;
    updateCount("filtered-count", total);
    updateCount("pagination-total", total);
    for (const [key, value] of Object.entries({
      all: Object.values(counts).reduce((sum, amount) => sum + (Number(amount) || 0), 0),
      4: counts[4] || 0,
      5: counts[5] || 0,
      1: counts[1] || 0
    })) {
      document.querySelectorAll('[data-count="' + key + '"]').forEach((element) => {
        element.textContent = String(value);
      });
    }
    const sync = document.getElementById("sync-result");
    if (sync && payload.last_sync) {
      const info = payload.last_sync;
      sync.classList.toggle("warn", Boolean(info.errors));
      sync.replaceChildren(
        node("span", "result-icon", "●"),
        node("span", "", "Última coleta: " + String(info.started_at || "").slice(0, 19) +
          " UTC · " + String(info.fetched ?? 0) + " publicações analisadas · " +
          String(info.material_items ?? 0) + " itens · " + String(info.errors ?? 0) +
          " erros." + (info.errors ? " " + String(info.details || "") : ""))
      );
    }
    if (!tableBody.contains(document.activeElement)) {
      const items = payload.data.map(itemRow);
      tableBody.replaceChildren(...(items.length ? items : [emptyItemRow()]));
      updatePagination(total, page);
    }
  }

  function updateHistory(payload) {
    if (!payload || !Array.isArray(payload.data)) throw new Error("Histórico inválido");
    const events = payload.data.slice(0, 10);
    updateCount("event-count", events.length);
    const rows = events.map(eventRow);
    if (rows.length === 0) {
      const blank = node("div", "history-empty");
      blank.append(
        node("span", "empty-icon", "◌"),
        node("p", "", "Nenhuma mudança registrada ainda. Após novas coletas, o histórico aparecerá aqui.")
      );
      rows.push(blank);
    }
    if (!historyBody.contains(document.activeElement)) historyBody.replaceChildren(...rows);
  }

  let pending = false;
  async function refresh(manual = false) {
    if (pending || (!manual && document.visibilityState !== "visible")) return;
    pending = true;
    refreshButton.disabled = true;
    refreshLabel.textContent = "Atualizando dados locais…";
    try {
      const query = new URLSearchParams(window.location.search);
      const responses = await Promise.all([
        fetch("/api/items?" + query.toString(), { credentials: "same-origin", cache: "no-store" }),
        fetch("/api/changes", { credentials: "same-origin", cache: "no-store" })
      ]);
      if (responses.some(response => response.status === 401 || response.status === 503)) {
        refreshLabel.textContent = "Sessão encerrada. Faça login novamente.";
        return;
      }
      if (responses.some(response => !response.ok)) throw new Error("Consulta local falhou");
      const [items, history] = await Promise.all(responses.map(response => response.json()));
      updateItems(items);
      updateHistory(history);
      const time = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      refreshLabel.textContent = "Tela atualizada às " + time + " · PNCP depende de sincronização";
    } catch {
      refreshLabel.textContent = "Falha ao atualizar a tela. Dados anteriores preservados.";
    } finally {
      pending = false;
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener("click", () => void refresh(true));
  window.setInterval(() => void refresh(false), 45_000);
  // Não confundir recarga da visualização com consulta remota ao PNCP.
  refreshLabel.textContent = "Atualização local a cada 45 s";
})();
