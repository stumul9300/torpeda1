// Торпеда: интерфейс. Все расчёты делает сервер (backend/torpeda/calc), здесь только показ и ввод.

const api = async (method, url, body) => {
  const resp = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error((data && data.detail) || `Ошибка ${resp.status}`);
  return data;
};

const num = (v) => (v === null || v === undefined || v === "" ? null : Number(v));
const rub = (p) => (p.value === null || p.value === undefined ? "" : p.value.toLocaleString("ru-RU", { maximumFractionDigits: 2 }));
const pct = (p) => (p.value === null || p.value === undefined ? "" : p.value.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + "%");
const signClass = (p) => (p.value === null ? "" : p.value < 0 ? "neg" : "pos");
const setStatus = (text) => (document.getElementById("status").textContent = text);

const RU = {
  noRowsToShow: "Нет данных. Нажмите «Загрузить из WB».",
  loadingOoo: "Загрузка…",
  filterOoo: "Фильтр…",
  contains: "Содержит",
  equals: "Равно",
  lessThan: "Меньше",
  greaterThan: "Больше",
  inRange: "Между",
  andCondition: "И",
  orCondition: "Или",
};

// --- вкладки ---

document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
    if (b.dataset.tab === "history") loadHistory();
    if (b.dataset.tab === "promotions") loadPromotions();
    if (b.dataset.tab === "settings") loadSettings();
  })
);

// --- товары ---

const flatten = (r) => ({
  ...r,
  cost: num(r.cost),
  price: num(r.price),
  discount_pct: num(r.discount_pct),
  calc_price: num(r.calc_price),
  calc_discount_pct: num(r.calc_discount_pct),
  cur_seller_price: num(r.current?.seller_price),
  cur_commission: num(r.current?.commission),
  cur_logistics: num(r.current?.logistics),
  cur_tax: num(r.current?.tax),
  cur_profit: num(r.current?.profit),
  cur_margin: num(r.current?.margin_pct),
  cur_roi: num(r.current?.roi_pct),
  calc_seller_price: num(r.calc?.seller_price),
  calc_profit: num(r.calc?.profit),
  calc_margin: num(r.calc?.margin_pct),
  calc_roi: num(r.calc?.roi_pct),
  status: r.calc?.status || r.current?.status || null,
  missing_text: (r.missing || []).join(", "),
});

const editable = { editable: true, cellClass: "cell-edit", type: "numericColumn" };

const productColumns = [
  { headerName: "Артикул WB", field: "nm_id", pinned: "left", width: 120 },
  { headerName: "Арт. продавца", field: "vendor_code", pinned: "left", width: 120 },
  { headerName: "Название", field: "title", width: 200 },
  { headerName: "Бренд", field: "brand", width: 110 },
  { headerName: "Предмет", field: "subject", width: 120 },
  { headerName: "Остаток FBO", field: "stock_fbo", width: 110, type: "numericColumn" },
  { headerName: "Продано за период", field: "sold_net_qty", width: 110, type: "numericColumn" },
  { headerName: "Себест.", field: "cost", width: 100, valueFormatter: rub, ...editable },
  {
    headerName: "Сейчас в WB",
    children: [
      { headerName: "Цена до скидки", field: "price", width: 110, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Скидка", field: "discount_pct", width: 80, valueFormatter: pct, type: "numericColumn" },
      { headerName: "Цена продавца", field: "cur_seller_price", width: 110, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Комиссия", field: "cur_commission", width: 100, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Логистика", field: "cur_logistics", width: 100, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Налог", field: "cur_tax", width: 90, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Маржа, ₽", field: "cur_profit", width: 100, valueFormatter: rub, cellClass: signClass, type: "numericColumn" },
      { headerName: "Маржа, %", field: "cur_margin", width: 90, valueFormatter: pct, cellClass: signClass, type: "numericColumn" },
      { headerName: "ROI", field: "cur_roi", width: 90, valueFormatter: pct, type: "numericColumn" },
    ],
  },
  {
    headerName: "Новая цена (расчёт)",
    children: [
      { headerName: "Новая цена до скидки", field: "calc_price", width: 130, valueFormatter: rub, ...editable },
      { headerName: "Новая скидка", field: "calc_discount_pct", width: 100, valueFormatter: pct, ...editable },
      { headerName: "Цена продавца", field: "calc_seller_price", width: 110, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Маржа, ₽", field: "calc_profit", width: 100, valueFormatter: rub, cellClass: signClass, type: "numericColumn" },
      { headerName: "Маржа, %", field: "calc_margin", width: 90, valueFormatter: pct, cellClass: signClass, type: "numericColumn" },
      { headerName: "ROI", field: "calc_roi", width: 90, valueFormatter: pct, type: "numericColumn" },
    ],
  },
  { headerName: "Не хватает данных", field: "missing_text", width: 200, cellClass: "missing" },
];

let onlyLoss = false;
let onlyChanged = false;

const productsGrid = agGrid.createGrid(document.getElementById("grid-products"), {
  columnDefs: productColumns,
  defaultColDef: { sortable: true, filter: true, resizable: true, wrapHeaderText: true, autoHeaderHeight: true },
  suppressColumnVirtualisation: true,
  localeText: RU,
  getRowId: (p) => String(p.data.nm_id),
  rowClassRules: {
    "row-loss": (p) => p.data?.status === "loss",
    "row-risk": (p) => p.data?.status === "risk",
  },
  isExternalFilterPresent: () => onlyLoss || onlyChanged,
  doesExternalFilterPass: (n) =>
    (!onlyLoss || ["loss", "risk"].includes(n.data.status)) && (!onlyChanged || n.data.calc_price !== null),
  stopEditingWhenCellsLoseFocus: true,
  onCellValueChanged: saveCell,
});

async function loadProducts() {
  const rows = (await api("GET", "/api/products")).map(flatten);
  productsGrid.setGridOption("rowData", rows);
  updateSummary(rows);
}

function updateSummary(rows) {
  const loss = rows.filter((r) => r.status === "loss").length;
  const risk = rows.filter((r) => r.status === "risk").length;
  const changed = rows.filter((r) => r.calc_price !== null).length;
  document.getElementById("summary").textContent = `Товаров: ${rows.length} · убыточных: ${loss} · в зоне риска: ${risk} · с новой ценой: ${changed}`;
}

async function saveCell(e) {
  const nm = e.data.nm_id;
  const value = e.newValue === "" || e.newValue === null ? null : Number(String(e.newValue).replace(",", "."));
  try {
    if (e.colDef.field === "cost") {
      if (value === null) return;
      await api("PUT", `/api/products/${nm}/cost`, { cost: value });
    } else {
      await api("PUT", `/api/products/${nm}/calc-price`, {
        price: e.colDef.field === "calc_price" ? value : e.data.calc_price ?? e.data.price,
        discount_pct: e.colDef.field === "calc_discount_pct" ? value : e.data.calc_discount_pct,
      });
    }
    await refreshRow(nm);
  } catch (err) {
    alert(err.message);
    await loadProducts();
  }
}

async function refreshRow(nm) {
  // сервер пересчитывает всю таблицу; для пары тысяч товаров это доли секунды
  const rows = (await api("GET", "/api/products")).map(flatten);
  const row = rows.find((r) => r.nm_id === nm);
  if (row) productsGrid.applyTransaction({ update: [row] });
  productsGrid.onFilterChanged();
  updateSummary(rows);
}

document.getElementById("search").addEventListener("input", (e) => productsGrid.setGridOption("quickFilterText", e.target.value));
document.getElementById("only-loss").addEventListener("change", (e) => { onlyLoss = e.target.checked; productsGrid.onFilterChanged(); });
document.getElementById("only-changed").addEventListener("change", (e) => { onlyChanged = e.target.checked; productsGrid.onFilterChanged(); });

// --- загрузка из WB ---

document.getElementById("btn-sync").addEventListener("click", async (e) => {
  e.target.disabled = true;
  setStatus("Загружаю из WB… это может занять несколько минут");
  try {
    const res = await api("POST", "/api/wb/sync");
    const errors = Object.entries(res).filter(([, v]) => String(v).startsWith("ошибка"));
    setStatus(errors.length ? `Загружено с ошибками: ${errors.map(([k]) => k).join(", ")}` : "Данные загружены");
    if (errors.length) alert(errors.map(([k, v]) => `${k}: ${v}`).join("\n"));
    await loadProducts();
  } catch (err) {
    setStatus("");
    alert(err.message);
  } finally {
    e.target.disabled = false;
  }
});

// --- предпросмотр и отправка цен ---

const dialog = document.getElementById("preview-dialog");
let pending = null;

const previewGrid = agGrid.createGrid(document.getElementById("grid-preview"), {
  columnDefs: [
    { headerName: "Артикул WB", field: "nm_id", width: 110 },
    { headerName: "Арт. продавца", field: "vendor_code", width: 110 },
    { headerName: "Было: цена / скидка", valueGetter: (p) => `${p.data.old_price} ₽ / ${p.data.old_discount}%`, width: 150 },
    { headerName: "Станет: цена / скидка", valueGetter: (p) => `${p.data.new_price} ₽ / ${p.data.new_discount}%`, width: 160 },
    { headerName: "Маржа было, ₽", valueGetter: (p) => num(p.data.before.profit), valueFormatter: rub, cellClass: signClass, width: 120 },
    { headerName: "Маржа станет, ₽", valueGetter: (p) => num(p.data.after.profit), valueFormatter: rub, cellClass: signClass, width: 130 },
    { headerName: "Маржа станет, %", valueGetter: (p) => num(p.data.after.margin_pct), valueFormatter: pct, width: 120 },
    { headerName: "Не хватает", valueGetter: (p) => p.data.missing.join(", "), cellClass: "missing", width: 160 },
  ],
  defaultColDef: { sortable: true, resizable: true, wrapHeaderText: true, autoHeaderHeight: true },
  localeText: RU,
  rowClassRules: { "row-loss": (p) => p.data.after.status === "loss", "row-risk": (p) => p.data.after.status === "risk" },
});

async function openPreview(body) {
  try {
    pending = await api("POST", "/api/prices/preview", body);
  } catch (err) {
    alert(err.message);
    return;
  }
  if (!pending.items.length) {
    alert("Нет изменённых цен. Введите новую цену в колонке «Новая цена до скидки».");
    return;
  }
  const losses = pending.items.filter((i) => i.after.status === "loss").length;
  document.getElementById("preview-text").textContent =
    `Будет отправлено товаров: ${pending.items.length}.` + (losses ? ` Внимание: ${losses} уйдут в убыток.` : "");
  previewGrid.setGridOption("rowData", pending.items);
  dialog.showModal();
}

document.getElementById("btn-preview").addEventListener("click", () => openPreview({}));
document.getElementById("btn-cancel").addEventListener("click", () => dialog.close());

// Отправка — только двойным щелчком, одиночный щелчок лишь подсказывает
document.getElementById("btn-confirm").addEventListener("click", () =>
  setStatus("Для отправки нажмите кнопку дважды")
);
document.getElementById("btn-confirm").addEventListener("dblclick", async (e) => {
  if (!pending) return;
  e.target.disabled = true;
  const items = pending.items.map(({ nm_id, old_price, old_discount, new_price, new_discount }) => ({
    nm_id, old_price, old_discount, new_price, new_discount,
  }));
  try {
    const res = await api("POST", "/api/prices/send", { items, confirm_token: pending.confirm_token });
    dialog.close();
    if (res.status === "sent") setStatus(`Цены отправлены в WB (задача ${res.wb_task_id})`);
    else alert("WB не принял цены: " + res.error);
    await loadProducts();
  } catch (err) {
    alert(err.message);
  } finally {
    e.target.disabled = false;
    pending = null;
  }
});

// --- журнал ---

const historyGrid = agGrid.createGrid(document.getElementById("grid-history"), {
  columnDefs: [
    { headerName: "Когда", field: "sent_at", width: 170, valueFormatter: (p) => new Date(p.value).toLocaleString("ru-RU") },
    { headerName: "Артикул WB", field: "nm_id", width: 120 },
    { headerName: "Было", valueGetter: (p) => `${num(p.data.old_price)} ₽ / ${num(p.data.old_discount_pct)}%`, width: 150 },
    { headerName: "Стало", valueGetter: (p) => `${num(p.data.new_price)} ₽ / ${num(p.data.new_discount_pct)}%`, width: 150 },
    { headerName: "Статус", field: "status", width: 100, valueFormatter: (p) => (p.value === "sent" ? "отправлено" : "ошибка") },
    { headerName: "Ошибка", field: "error", width: 260 },
    {
      headerName: "",
      width: 150,
      sortable: false,
      filter: false,
      cellRenderer: (p) => {
        if (p.data.status !== "sent") return "";
        const b = document.createElement("button");
        b.textContent = "Вернуть прежнюю";
        b.addEventListener("click", () => openPreview({ revert_change_ids: [p.data.id] }));
        return b;
      },
    },
  ],
  defaultColDef: { sortable: true, filter: true, resizable: true, wrapHeaderText: true, autoHeaderHeight: true },
  localeText: RU,
});

async function loadHistory() {
  historyGrid.setGridOption("rowData", await api("GET", "/api/prices/history"));
}
document.getElementById("btn-history-refresh").addEventListener("click", loadHistory);

// --- акции ---

const promoGrid = agGrid.createGrid(document.getElementById("grid-promo"), {
  columnDefs: [
    { headerName: "Артикул WB", field: "nm_id", width: 120 },
    { headerName: "Арт. продавца", field: "vendor_code", width: 120 },
    { headerName: "Участвует", field: "in_action", width: 100, valueFormatter: (p) => (p.value ? "да" : "нет") },
    { headerName: "Маржа сейчас, ₽", valueGetter: (p) => num(p.data.current?.profit), valueFormatter: rub, cellClass: signClass, width: 130 },
    { headerName: "Маржа сейчас, %", valueGetter: (p) => num(p.data.current?.margin_pct), valueFormatter: pct, width: 130 },
    { headerName: "Цена продавца в акции", valueGetter: (p) => num(p.data.promo?.seller_price), valueFormatter: rub, width: 150 },
    { headerName: "Маржа в акции, ₽", valueGetter: (p) => num(p.data.promo?.profit), valueFormatter: rub, cellClass: signClass, width: 130 },
    { headerName: "Маржа в акции, %", valueGetter: (p) => num(p.data.promo?.margin_pct), valueFormatter: pct, width: 130 },
    { headerName: "Рекомендация", field: "recommend", width: 140 },
    { headerName: "Не хватает", valueGetter: (p) => (p.data.missing || []).join(", "), cellClass: "missing", width: 180 },
  ],
  defaultColDef: { sortable: true, filter: true, resizable: true, wrapHeaderText: true, autoHeaderHeight: true },
  localeText: RU,
  rowClassRules: { "row-loss": (p) => p.data.promo?.status === "loss", "row-risk": (p) => p.data.promo?.status === "risk" },
});

const promoSelect = document.getElementById("promo-select");
async function loadPromotions() {
  const promos = await api("GET", "/api/promotions");
  promoSelect.innerHTML = promos
    .map((p) => `<option value="${p.id}">${p.name} (${(p.start_at || "").slice(0, 10)} — ${(p.end_at || "").slice(0, 10)})</option>`)
    .join("");
  if (promos.length) await loadPromotion(promos[0].id);
  else promoGrid.setGridOption("rowData", []);
}
async function loadPromotion(id) {
  const data = await api("GET", `/api/promotions/${id}`);
  const loss = data.items.filter((i) => i.promo?.status === "loss").length;
  document.getElementById("promo-info").textContent = `Товаров: ${data.items.length} · в убыток в акции: ${loss}`;
  promoGrid.setGridOption("rowData", data.items);
}
promoSelect.addEventListener("change", () => loadPromotion(promoSelect.value));

// --- настройки ---

const form = document.getElementById("settings-form");
async function loadSettings() {
  const s = await api("GET", "/api/settings");
  for (const [k, v] of Object.entries(s)) if (form.elements[k]) form.elements[k].value = v;
  showKeys(await api("GET", "/api/keys"));
}

const keysForm = document.getElementById("keys-form");
function showKeys(keys) {
  document.getElementById("key-read-current").textContent = keys.read ? `сохранён ${keys.read}` : "не задан";
  document.getElementById("key-prices-current").textContent = keys.prices ? `сохранён ${keys.prices}` : "не задан";
}
keysForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {};
  for (const name of ["read", "prices"]) {
    const v = keysForm.elements[name].value.trim();
    if (v) body[name] = v;
  }
  if (!Object.keys(body).length) return;
  try {
    showKeys(await api("PUT", "/api/keys", body));
    keysForm.reset();
    setStatus("Ключи сохранены");
    document.getElementById("btn-check").click();
  } catch (err) {
    alert(err.message);
  }
});
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    await api("PUT", "/api/settings", values);
    setStatus("Настройки сохранены");
    await loadProducts();
  } catch (err) {
    alert(err.message);
  }
});
document.getElementById("btn-check").addEventListener("click", async () => {
  const out = document.getElementById("check-result");
  out.textContent = "Проверяю…";
  try {
    const res = await api("GET", "/api/wb/check");
    out.textContent = Object.entries(res).map(([k, v]) => `${k}: ${v}`).join("\n");
  } catch (err) {
    out.textContent = err.message;
  }
});

// Первый запуск без ключа — сразу на вкладку с полем для ключа
(async () => {
  try {
    const keys = await api("GET", "/api/keys");
    if (!keys.read) {
      document.querySelector('.tab[data-tab="settings"]').click();
      setStatus("Вставьте ключ WB, чтобы загрузить данные");
    }
    await loadProducts();
  } catch (err) {
    setStatus(err.message);
  }
})();
