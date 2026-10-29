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
    if (b.dataset.tab === "reports") loadReport();
    if (b.dataset.tab === "promotions") loadPromotions();
    if (b.dataset.tab === "settings") loadSettings();
  })
);

// --- горизонтальная прокрутка сверху таблицы ---

// Полоса прокрутки таблицы внизу длинного списка не видна: дублируем её над таблицей и держим в связке с настоящей.
function addTopScroll(gridId) {
  const grid = document.getElementById(gridId);
  const bar = document.createElement("div");
  bar.className = "top-scroll";
  const inner = document.createElement("div");
  bar.appendChild(inner);
  const wrap = document.createElement("div");
  wrap.className = "grid-wrap";
  grid.parentNode.insertBefore(wrap, grid);
  wrap.append(bar, grid);
  let lock = false;
  const viewport = () => grid.querySelector(".ag-body-horizontal-scroll-viewport");
  const sync = () => {
    const vp = viewport();
    if (!vp) return;
    inner.style.width = vp.scrollWidth + "px";
    bar.style.display = vp.scrollWidth > vp.clientWidth + 1 ? "block" : "none";
  };
  bar.addEventListener("scroll", () => {
    const vp = viewport();
    if (!vp || lock) return;
    lock = true;
    vp.scrollLeft = bar.scrollLeft;
    lock = false;
  });
  grid.addEventListener("scroll", (e) => {
    if (!e.target.classList?.contains("ag-body-horizontal-scroll-viewport") || lock) return;
    lock = true;
    bar.scrollLeft = e.target.scrollLeft;
    lock = false;
  }, true);
  new ResizeObserver(sync).observe(grid);
  setInterval(sync, 1000); // ширина меняется при показе колонок и перетаскивании границ
  sync();
}

// --- товары ---

// цена для клиента сейчас и после вступления в самую выгодную акцию (цена до скидки та же, меняется скидка)
function clientPrices(r) {
  const seller = num(r.current?.seller_price);
  const k = r.site_price && seller ? num(r.site_price) / seller : r.spp != null ? (100 - num(r.spp)) / 100 : null;
  const now = r.site_price ? num(r.site_price) : k && seller ? Math.round(seller * k) : null;
  const best = r.promo_best;
  const plan = best && !best.in_action ? num(best.plan_seller_price) : null;
  const promo = plan != null && k ? Math.round(plan * k) : null;
  const diff = promo != null && now != null ? promo - now : null;
  const loss = best?.status === "loss" ? ", убыток" : "";
  const advice =
    promo != null && diff < 0 && now
      ? `поставить цену для клиента ${promo} ₽ (${Math.round((diff / now) * 1000) / 10}%): маржа ${Math.round(num(best.profit))} ₽${loss}`
      : null;
  return {
    promo_advice_client: advice,
    client_profit: promo != null ? num(best.profit) : null,
    client_margin: promo != null ? num(best.margin_pct) : null,
    client_now: now,
    client_promo: promo,
    client_diff: diff,
    client_diff_pct: diff != null && now ? Math.round((diff / now) * 10000) / 100 : null,
    promo_disc: best?.in_action ? "уже участвует" : best && best.discount_pct != null ? `${Math.round(num(best.discount_pct))}% (сейчас ${Math.round(num(r.discount_pct))}%)` : null,
  };
}

const flatten = (r) => ({
  ...r,
  cost: num(r.cost),
  price: num(r.price),
  discount_pct: num(r.discount_pct),
  calc_price: num(r.calc_price),
  calc_discount_pct: num(r.calc_discount_pct),
  cur_seller_price: num(r.current?.seller_price),
  spp: num(r.spp),
  buyer_price: r.spp == null || r.current?.seller_price == null ? null : Math.round(num(r.current.seller_price) * (100 - num(r.spp))) / 100,
  cur_commission: num(r.current?.commission),
  cur_logistics: num(r.current?.logistics),
  cur_tax: num(r.current?.tax),
  cur_profit: num(r.current?.profit),
  cur_margin: num(r.current?.margin_pct),
  cur_roi: num(r.current?.roi_pct),
  calc_seller_price: num(r.calc?.seller_price),
  site_price: num(r.site_price),
  // во сколько раз цена на сайте отличается от цены продавца: СПП и всё, что WB добавляет сам
  site_k: r.site_price && r.current?.seller_price ? num(r.site_price) / num(r.current.seller_price) : r.spp != null ? (100 - num(r.spp)) / 100 : null,
  target_site_price:
    r.calc?.seller_price && (r.site_price && r.current?.seller_price ? true : r.spp != null)
      ? Math.round(num(r.calc.seller_price) * (r.site_price && r.current?.seller_price ? num(r.site_price) / num(r.current.seller_price) : (100 - num(r.spp)) / 100))
      : null,
  ...clientPrices(r),
  calc_profit: num(r.calc?.profit),
  calc_margin: num(r.calc?.margin_pct),
  calc_roi: num(r.calc?.roi_pct),
  // что изменится относительно нынешней цены: цена продавца (₽, %) и маржа (₽, п.п.)
  d_price: r.calc && r.current ? Math.round((num(r.calc.seller_price) - num(r.current.seller_price)) * 100) / 100 : null,
  d_price_pct: r.calc && r.current && num(r.current.seller_price) ? Math.round(((num(r.calc.seller_price) / num(r.current.seller_price)) - 1) * 10000) / 100 : null,
  d_profit: r.calc && r.current ? Math.round((num(r.calc.profit) - num(r.current.profit)) * 100) / 100 : null,
  d_margin: r.calc && r.current ? Math.round((num(r.calc.margin_pct) - num(r.current.margin_pct)) * 100) / 100 : null,
  promo_best_name: r.promo_best?.name ?? null,
  promo_best_price: num(r.promo_best?.price),
  promo_best_discount: num(r.promo_best?.discount_pct),
  promo_delta: num(r.promo_best?.delta_seller),
  promo_advice: (r.promo_best && clientPrices(r).promo_advice_client) ?? r.promo_best?.advice ?? r.promo_note ?? null,
  promo_best_profit: num(r.promo_best?.profit),
  promo_best_margin: num(r.promo_best?.margin_pct),
  promo_best_roi: num(r.promo_best?.roi_pct),
  status: r.calc?.status || r.current?.status || null,
  missing_text: (r.missing || []).join(", "),
});

const editable = { editable: true, cellClass: "cell-edit", type: "numericColumn" };

// Ссылка на страницу товара на Wildberries, открывается в новой вкладке. Строка «Итого» остаётся текстом.
const wbUrl = (nm) => `https://www.wildberries.ru/catalog/${nm}/detail.aspx`;
function wbAnchor(nm) {
  const a = document.createElement("a");
  a.href = wbUrl(nm);
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}
const wbLink = (p) => {
  if (!/^\d+$/.test(String(p.value ?? ""))) return p.valueFormatted ?? p.value ?? "";
  const a = wbAnchor(p.value);
  a.textContent = p.value;
  return a;
};
const photoCell = (p) => {
  if (!p.value) return "";
  const a = wbAnchor(p.data.nm_id);
  const img = document.createElement("img");
  img.className = "thumb";
  img.src = p.value;
  img.loading = "lazy";
  img.alt = "";
  img.onerror = () => img.remove();
  a.append(img);
  return a;
};

// СПП меняется часто: показываем время значения, старше суток — серым с пометкой
const sppCell = (p) => {
  if (p.value == null) return "—";
  const span = document.createElement("span");
  const at = p.data.spp_at ? new Date(p.data.spp_at) : null;
  const stale = !at || Date.now() - at.getTime() > 24 * 3600 * 1000;
  const when = at ? at.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
  span.textContent = `${p.value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
  const small = document.createElement("small");
  small.className = stale ? "spp-at stale" : "spp-at";
  small.textContent = ` · ${when}${stale ? " устар." : ""}`;
  span.append(small);
  return span;
};

// Цена на сайте с временем, когда её видели: старше суток — серым
const sitePriceCell = (p) => {
  if (p.value == null) return "—";
  const span = document.createElement("span");
  const at = p.data.site_price_at ? new Date(p.data.site_price_at) : null;
  const stale = !at || Date.now() - at.getTime() > 24 * 3600 * 1000;
  span.textContent = rub(p);
  const small = document.createElement("small");
  small.className = stale ? "spp-at stale" : "spp-at";
  small.textContent = at ? ` · ${at.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}` : "";
  span.append(small);
  return span;
};

const productColumns = [
  { headerName: "Фото", field: "photo", pinned: "left", width: 64, sortable: false, filter: false, cellRenderer: photoCell },
  { headerName: "Артикул WB", field: "nm_id", cellRenderer: wbLink, pinned: "left", width: 120 },
  { headerName: "Арт. продавца", field: "vendor_code", pinned: "left", width: 120 },
  { headerName: "Название", field: "title", width: 200 },
  { headerName: "Бренд", field: "brand", width: 110 },
  { headerName: "Предмет", field: "subject", width: 120 },
  { headerName: "Ост. FBO", field: "stock_fbo", width: 90, type: "numericColumn", sort: "desc" },
  { headerName: "Ост. FBS", field: "stock_fbs", width: 90, type: "numericColumn" },
  { headerName: "Продано за период", field: "sold_net_qty", width: 110, type: "numericColumn" },
  { headerName: "Себест.", field: "cost", width: 100, valueFormatter: rub, ...editable },
  {
    headerName: "Цена для клиента и акция",
    children: [
      { headerName: "Цена для клиента сейчас", field: "client_now", width: 120, valueFormatter: (p) => (p.value == null ? "—" : rub(p)), type: "numericColumn", headerTooltip: "Цена на сайте для покупателя (с СПП). Если цены на сайте нет, считается по СПП" },
      { headerName: "Рекомендуемая цена для клиента (акция)", field: "client_promo", width: 150, valueFormatter: (p) => (p.value == null ? "—" : rub(p)), type: "numericColumn", cellClass: (p) => (p.value != null && p.data.client_diff < 0 ? "cell-promo" : ""), headerTooltip: "Какая будет цена для покупателя, если вступить в самую выгодную акцию. Двойной щелчок отправляет эту цену в WB (скидка подберётся сама)" },
      { headerName: "Маржа по этой цене, ₽", field: "client_profit", width: 110, valueFormatter: (p) => (p.value == null ? "—" : rub(p)), cellClass: signClass, type: "numericColumn", headerTooltip: "Маржа в рублях, если поставить рекомендуемую цену" },
      { headerName: "Маржа по этой цене, %", field: "client_margin", width: 110, valueFormatter: (p) => (p.value == null ? "—" : pct(p)), cellClass: signClass, type: "numericColumn" },
      { headerName: "Разница, ₽", field: "client_diff", width: 100, valueFormatter: (p) => (p.value == null ? "—" : rub(p)), cellClass: signClass, type: "numericColumn", headerTooltip: "Минус: цена для клиента понижается" },
      { headerName: "Разница, %", field: "client_diff_pct", width: 100, valueFormatter: (p) => (p.value == null ? "—" : pct(p)), cellClass: signClass, type: "numericColumn" },
      { headerName: "Акция", field: "promo_best_name", width: 150, valueFormatter: (p) => (p.value == null ? "" : p.value) },
      { headerName: "Желаемая цена на сайте", field: "target_site_price", width: 130, valueFormatter: rub, ...editable, cellClass: "cell-edit cell-target", headerTooltip: "Введите цену, которую хотите видеть на сайте (как «Цена с СПП»). Программа сама подберёт скидку и покажет, на сколько изменятся цена и маржа" },
    ],
  },
  {
    headerName: "Сейчас в WB",
    children: [
      { headerName: "Цена до скидки", field: "price", width: 110, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Скидка", field: "discount_pct", width: 80, valueFormatter: pct, type: "numericColumn" },
      { headerName: "Цена продавца", field: "cur_seller_price", width: 110, valueFormatter: rub, type: "numericColumn" },
      { headerName: "СПП", field: "spp", width: 110, cellRenderer: sppCell, type: "numericColumn", headerTooltip: "Справочно. СПП из самого свежего заказа и время этого заказа. WB отдаёт СПП только по сделанным заказам" },
      { headerName: "Цена на сайте (Москва)", field: "site_price", width: 130, cellRenderer: sitePriceCell, type: "numericColumn", headerTooltip: "Справочно. Цена для покупателя в Москве на сайте WB. Обновляется кнопкой «Обновить цены на сайте»" },
      { headerName: "Цена с СПП", field: "buyer_price", width: 100, valueFormatter: (p) => (p.value == null ? "—" : rub(p)), type: "numericColumn" },
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
      { headerName: "Новая цена до скидки", field: "calc_price", width: 130, valueFormatter: rub, ...editable, headerTooltip: "Цена до скидки, а не цена на сайте. Чтобы ввести цену, которую увидит покупатель, пользуйтесь «Желаемой ценой на сайте»" },
      { headerName: "Новая скидка", field: "calc_discount_pct", width: 100, valueFormatter: pct, ...editable },
      { headerName: "Цена продавца", field: "calc_seller_price", width: 110, valueFormatter: rub, type: "numericColumn" },
      { headerName: "Маржа, ₽", field: "calc_profit", width: 100, valueFormatter: rub, cellClass: signClass, type: "numericColumn" },
      { headerName: "Маржа, %", field: "calc_margin", width: 90, valueFormatter: pct, cellClass: signClass, type: "numericColumn" },
      { headerName: "ROI", field: "calc_roi", width: 90, valueFormatter: pct, type: "numericColumn" },
      { headerName: "Изменение цены продавца, ₽", field: "d_price", width: 120, valueFormatter: rub, cellClass: signClass, type: "numericColumn", headerTooltip: "Минус: цена продавца понижается. Сравнивается новая цена продавца с нынешней" },
      { headerName: "Изменение цены продавца, %", field: "d_price_pct", width: 120, valueFormatter: pct, cellClass: signClass, type: "numericColumn" },
      { headerName: "Изменение маржи, ₽", field: "d_profit", width: 110, valueFormatter: rub, cellClass: signClass, type: "numericColumn", headerTooltip: "Новая маржа в рублях минус нынешняя" },
      { headerName: "Изменение маржи, п.п.", field: "d_margin", width: 110, valueFormatter: pct, cellClass: signClass, type: "numericColumn", headerTooltip: "Новая маржа в % минус нынешняя, в процентных пунктах" },
    ],
  },
  {
    headerName: "Акции",
    children: [
      { headerName: "Текущая акция", field: "promo_current", width: 160 },
      {
        headerName: "Выгодная акция",
        colId: "promo_best_name_full",
        field: "promo_best_name",
        width: 170,
        valueFormatter: (p) => (p.value == null ? "" : p.value + (p.data.promo_best?.in_action ? " (участвует)" : "")),
        headerTooltip: "Акция с самой высокой ценой продавца после скидки среди акций без убытка",
      },
      { headerName: "Что сделать для вступления", field: "promo_advice", width: 340, wrapText: true, autoHeight: false, tooltipField: "promo_advice", headerTooltip: "Если цена выше порога акции, здесь написано, на сколько её понизить и какая будет маржа" },
      { headerName: "Изменить цену продавца, ₽", field: "promo_delta", width: 120, valueFormatter: rub, cellClass: signClass, type: "numericColumn", headerTooltip: "Минус: цену нужно понизить, чтобы вступить в акцию" },
      { headerName: "Цена до скидки для вступления", field: "promo_best_price", width: 130, valueFormatter: rub, type: "numericColumn", headerTooltip: "Цена до скидки, которую нужно поставить, чтобы вступить в выгодную акцию" },
      { headerName: "Скидка для вступления", field: "promo_best_discount", width: 100, valueFormatter: pct, type: "numericColumn" },
      { headerName: "Маржа в акции, ₽", field: "promo_best_profit", width: 110, valueFormatter: rub, cellClass: signClass, type: "numericColumn" },
      { headerName: "Маржа в акции, %", field: "promo_best_margin", width: 100, valueFormatter: pct, cellClass: signClass, type: "numericColumn" },
      { headerName: "ROI в акции", field: "promo_best_roi", width: 90, valueFormatter: pct, type: "numericColumn" },
    ],
  },
  { headerName: "Не хватает данных", field: "missing_text", width: 200, cellClass: "missing" },
];

// Блоки колонок для окна «Колонки»: что выводить и что закреплять слева. Выбор помнится в браузере.
const COLUMN_BLOCKS = [
  { id: "photo", label: "Фото", cols: ["photo"], show: true, pin: true },
  { id: "nm", label: "Артикул WB", cols: ["nm_id"], show: true, pin: true },
  { id: "vendor", label: "Артикул продавца", cols: ["vendor_code"], show: true, pin: true },
  { id: "names", label: "Название / Бренд / Предмет", cols: ["title", "brand", "subject"], show: true, pin: false },
  { id: "stocks", label: "Остатки FBO / FBS", cols: ["stock_fbo", "stock_fbs"], show: true, pin: false },
  { id: "sold", label: "Продано за период", cols: ["sold_net_qty"], show: true, pin: false },
  { id: "cost", label: "Себестоимость", cols: ["cost"], show: true, pin: false },
  { id: "client", label: "Цена для клиента и акция", cols: ["client_now", "client_promo", "client_profit", "client_margin", "client_diff", "client_diff_pct", "promo_best_name", "target_site_price"], show: true, pin: false },
  { id: "prices", label: "Служебное: цена до скидки и скидка", cols: ["price", "discount_pct", "calc_price", "calc_discount_pct"], show: false, pin: false },
  { id: "now", label: "Цены и маржа сейчас в WB", cols: ["cur_seller_price", "spp", "site_price", "buyer_price", "cur_commission", "cur_logistics", "cur_tax", "cur_profit", "cur_margin", "cur_roi"], show: true, pin: false },
  { id: "new", label: "Новая цена (расчёт)", cols: ["calc_seller_price", "calc_profit", "calc_margin", "calc_roi", "d_price", "d_price_pct", "d_profit", "d_margin"], show: true, pin: false },
  { id: "promo", label: "Акции: текущая и выгодная", cols: ["promo_current", "promo_best_name_full", "promo_advice", "promo_delta", "promo_best_price", "promo_best_discount", "promo_best_profit", "promo_best_margin", "promo_best_roi"], show: true, pin: false },
  { id: "missing", label: "Не хватает данных", cols: ["missing_text"], show: true, pin: false },
];
const COLS_KEY = "torpeda.columns";

function loadColumnPrefs() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(COLS_KEY) || "{}"); } catch { /* без сохранённого вида */ }
  return Object.fromEntries(COLUMN_BLOCKS.map((b) => [b.id, { show: saved[b.id]?.show ?? b.show, pin: saved[b.id]?.pin ?? b.pin }]));
}

function applyColumnPrefs(prefs) {
  const state = COLUMN_BLOCKS.flatMap((b) => b.cols.map((c) => ({ colId: c, hide: !prefs[b.id].show, pinned: prefs[b.id].pin ? "left" : null })));
  productsGrid.applyColumnState({ state });
}

let hideNoStock = true;
let onlyLoss = false;
let onlyChanged = false;

addTopScroll("grid-products");
const productsGrid = agGrid.createGrid(document.getElementById("grid-products"), {
  columnDefs: productColumns,
  rowHeight: 56,
  defaultColDef: { sortable: true, filter: true, resizable: true, wrapHeaderText: true, autoHeaderHeight: true },
  suppressColumnVirtualisation: true,
  localeText: RU,
  getRowId: (p) => String(p.data.nm_id),
  rowSelection: "single",
  rowClassRules: {
    "row-loss": (p) => p.data?.status === "loss",
    "row-risk": (p) => p.data?.status === "risk",
  },
  isExternalFilterPresent: () => hideNoStock || onlyLoss || onlyChanged,
  doesExternalFilterPass: (n) =>
    (!hideNoStock || stockTotal(n.data) > 0) &&
    (!onlyLoss || ["loss", "risk"].includes(n.data.status)) && (!onlyChanged || n.data.calc_price !== null),
  stopEditingWhenCellsLoseFocus: true,
  onCellValueChanged: saveCell,
  onCellDoubleClicked: sendPromoPrice,
});

applyColumnPrefs(loadColumnPrefs());

const stockTotal = (r) => (r.stock_fbo || 0) + (r.stock_fbs || 0);

async function loadProducts() {
  const rows = (await api("GET", "/api/products")).map(flatten);
  productsGrid.setGridOption("rowData", rows);
  updateSummary(rows);
}

function updateSummary(rows) {
  const loss = rows.filter((r) => r.status === "loss").length;
  const risk = rows.filter((r) => r.status === "risk").length;
  const changed = rows.filter((r) => r.calc_price !== null).length;
  const noStock = rows.filter((r) => stockTotal(r) === 0).length;
  document.getElementById("summary").textContent = `Товаров: ${rows.length} (без остатка: ${noStock}) · убыточных: ${loss} · в зоне риска: ${risk} · с новой ценой: ${changed}`;
}

async function saveCell(e) {
  const nm = e.data.nm_id;
  const value = e.newValue === "" || e.newValue === null ? null : Number(String(e.newValue).replace(",", "."));
  try {
    if (e.colDef.field === "cost") {
      if (value === null) return;
      await api("PUT", `/api/products/${nm}/cost`, { cost: value });
    } else if (e.colDef.field === "target_site_price") {
      // цена до скидки остаётся нынешней, меняется только скидка (WB принимает целые %): берём ближайшую к желаемой цене
      if (value === null) {
        await api("PUT", `/api/products/${nm}/calc-price`, { price: null, discount_pct: null });
      } else {
        const k = e.data.site_k; // во сколько раз цена на сайте отличается от цены продавца
        if (!k) throw new Error("Нет ни цены на сайте, ни СПП: нажмите «Обновить цены на сайте» или «Обновить СПП».");
        if (!e.data.price) throw new Error("Нет нынешней цены товара из WB: нажмите «Загрузить из WB».");
        const discount = Math.min(99, Math.max(0, Math.round(100 * (1 - value / k / e.data.price))));
        await api("PUT", `/api/products/${nm}/calc-price`, { price: e.data.price, discount_pct: discount });
      }
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
document.getElementById("hide-no-stock").addEventListener("change", (e) => { hideNoStock = e.target.checked; productsGrid.onFilterChanged(); });
document.getElementById("only-loss").addEventListener("change", (e) => { onlyLoss = e.target.checked; productsGrid.onFilterChanged(); });
document.getElementById("only-changed").addEventListener("change", (e) => { onlyChanged = e.target.checked; productsGrid.onFilterChanged(); });

// --- окно «Акции WB» ---

const promoDialog = document.getElementById("promo-dialog");
document.getElementById("btn-promo-list").addEventListener("click", async () => {
  const list = await api("GET", "/api/promotions");
  const noList = list.filter((p) => !p.items_total).length;
  const fromFiles = list.filter((p) => p.from_file).length;
  document.getElementById("promo-hint").textContent = list.length
    ? `Загружено акций: ${list.length}, из них из файлов: ${fromFiles}${fromFiles ? "" : " (файлы акций ещё не загружены: кнопка «Загрузить акции из файлов…»)"}. По ${noList} из них WB не отдаёт список товаров (в основном автоакции), поэтому цену для вступления программа посчитать не может. По остальным WB показывает только товары, приглашённые в акцию.`
    : "Акции ещё не загружены: нажмите синхронизацию в «Настройках».";
  const dt = (v) => (v ? new Date(v).toLocaleDateString("ru-RU") : "—");
  document.getElementById("promo-body").innerHTML = list.map((p) => `<tr>
    <td>${esc(p.name)}${p.from_file ? " (файл)" : ""}</td><td>${p.type === "auto" ? "авто" : esc(p.type || "обычная")}</td>
    <td>${dt(p.start_at)} — ${dt(p.end_at)}</td>
    <td>${p.items_total || "WB не отдаёт список"}</td><td>${p.items_total ? p.items_in_action : "—"}</td></tr>`).join("");
  promoDialog.showModal();
});
document.getElementById("promo-close").addEventListener("click", () => promoDialog.close());

// --- окно «Колонки» ---

const colsDialog = document.getElementById("columns-dialog");
function openColumns() {
  const prefs = loadColumnPrefs();
  document.getElementById("columns-body").innerHTML = COLUMN_BLOCKS.map(
    (b) => `<tr><td>${esc(b.label)}</td>
      <td><input type="checkbox" data-id="${b.id}" data-k="show" ${prefs[b.id].show ? "checked" : ""}></td>
      <td><input type="checkbox" data-id="${b.id}" data-k="pin" ${prefs[b.id].pin ? "checked" : ""}></td></tr>`
  ).join("");
  colsDialog.showModal();
}
document.getElementById("btn-columns").addEventListener("click", openColumns);
document.getElementById("columns-body").addEventListener("change", (e) => {
  const prefs = loadColumnPrefs();
  prefs[e.target.dataset.id][e.target.dataset.k] = e.target.checked;
  try { localStorage.setItem(COLS_KEY, JSON.stringify(prefs)); } catch { /* вид не сохранится, но применится */ }
  applyColumnPrefs(prefs);
});
document.getElementById("columns-reset").addEventListener("click", () => {
  try { localStorage.removeItem(COLS_KEY); } catch { /* нечего сбрасывать */ }
  applyColumnPrefs(loadColumnPrefs());
  openColumns();
});
document.getElementById("columns-close").addEventListener("click", () => colsDialog.close());

// --- калькулятор справа: выбранный товар в трёх вариантах цены ---

const CALC_ROWS = [
  ["Цена до скидки", (r, x) => x.price],
  ["Скидка, %", (r, x) => x.discount],
  ["Цена продавца", (r, x) => x.res?.seller_price],
  ["СПП, %", (r) => r.spp],
  ["Цена с СПП", (r, x) => (x.res?.seller_price != null && r.spp != null ? num(x.res.seller_price) * (1 - num(r.spp) / 100) : null)],
  ["Комиссия", (r, x) => x.res?.commission],
  ["Логистика", (r, x) => x.res?.logistics],
  ["Эквайринг", (r, x) => x.res?.acquiring],
  ["Хранение", (r, x) => x.res?.storage],
  ["Налог", (r, x) => x.res?.tax],
  ["Себестоимость", (r, x) => x.res?.cost],
  ["Маржа, ₽", (r, x) => x.res?.profit, true],
  ["ROI, %", (r, x) => x.res?.roi_pct, true],
  ["Маржинальность, %", (r, x) => x.res?.margin_pct, true],
];
const fmt = (v) => (v == null ? "—" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 }));

function showCalculator(r) {
  const variants = [
    { title: "Текущая", price: r.price, discount: r.discount_pct, res: r.current },
    { title: "Новая", price: r.calc_price, discount: r.calc_discount_pct ?? (r.calc_price != null ? r.discount_pct : null), res: r.calc },
    { title: r.promo_best ? `Акция «${r.promo_best.name}»` : "Акция", price: r.promo_best?.price, discount: r.promo_best?.discount_pct, res: r.promo_best },
  ];
  const head = `<tr><th></th>${variants.map((v) => `<th>${esc(v.title)}</th>`).join("")}</tr>`;
  const body = CALC_ROWS.map(([label, get, signed]) => {
    const cells = variants.map((v) => {
      const val = get(r, v);
      const cls = signed && val != null ? (num(val) < 0 ? "neg" : "pos") : "";
      return `<td class="${cls}">${fmt(val)}</td>`;
    });
    return `<tr><th>${label}</th>${cells.join("")}</tr>`;
  }).join("");
  document.getElementById("calc-title").textContent = `${r.vendor_code || ""} · ${r.nm_id}`;
  document.getElementById("calc-table").innerHTML = head + body;
  const promos = r.promos || [];
  document.getElementById("calc-promos").innerHTML = promos.length
    ? `<h4>Что поставить, чтобы вступить в акцию</h4><table class="calc-promos"><tr><th>Акция</th><th>Цена до скидки</th><th>Скидка</th><th>Изменить, ₽</th><th>Маржа, ₽</th><th>Маржа, %</th></tr>${promos
        .map((p) => `<tr class="${p.status === "loss" ? "neg" : ""}"><td>${esc(p.name)}${p.in_action ? " ✓" : ""}</td><td>${fmt(p.price)}</td><td>${fmt(p.discount_pct)}</td><td>${p.in_action ? "уже в акции" : fmt(p.delta_seller)}</td><td>${fmt(p.profit)}</td><td>${fmt(p.margin_pct)}</td></tr>`)
        .join("")}</table><p class="hint">✓ товар уже участвует. «Изменить» это разница цены продавца: минус значит цену надо понизить. Красным: в этой акции маржа отрицательная.</p>`
    : `<p class="missing">${esc(r.promo_note || "")}</p>`;
  document.getElementById("calc-missing").textContent = r.missing_text ? `Не хватает: ${r.missing_text}` : "";
  document.getElementById("calc-panel").hidden = false;
}
productsGrid.addEventListener("rowClicked", (e) => showCalculator(e.data));
document.getElementById("calc-close").addEventListener("click", () => { document.getElementById("calc-panel").hidden = true; });

// --- «Новая цена» по акциям ---

document.getElementById("btn-recalc-promos").addEventListener("click", async (e) => {
  if (!confirm("Заполнить колонку «Новая цена» по самым выгодным акциям? Убыточные акции и товары без себестоимости пропускаются. В WB ничего не отправляется.")) return;
  e.target.disabled = true;
  try {
    const r = await api("POST", "/api/prices/recalc-promos");
    await loadProducts();
    setStatus(`По акциям: новая цена у ${r.changed}, убыточных акций ${r.loss}, без себестоимости ${r.no_cost}, без акций ${r.no_promo}`);
  } catch (err) {
    alert(err.message);
  } finally {
    e.target.disabled = false;
  }
});

// --- загрузка из WB ---

const syncPanel = document.getElementById("sync-panel");
function showSyncSteps(now, done) {
  syncPanel.hidden = false;
  document.getElementById("sync-now").textContent = now;
  document.getElementById("sync-done").innerHTML = done
    .map((line) => {
      const cls = line.includes("ошибка") ? "err" : line.includes("пустым списком") ? "warn" : "";
      return `<li class="${cls}">${esc(line)}</li>`;
    })
    .join("");
}
document.getElementById("sync-close").addEventListener("click", () => { syncPanel.hidden = true; });

document.getElementById("btn-sync").addEventListener("click", async (e) => {
  e.target.disabled = true;
  setStatus("Загружаю из WB…");
  showSyncSteps("Начинаю загрузку из WB…", []);
  const timer = setInterval(async () => {
    try {
      const p = await api("GET", "/api/wb/sync-progress");
      if (p.running && p.step) showSyncSteps(`Шаг ${p.index} из ${p.total}: ${p.step}…`, p.done);
    } catch { /* ход загрузки не критичен */ }
  }, 1500);
  try {
    const res = await api("POST", "/api/wb/sync");
    const errors = res.summary.filter((line) => line.includes("ошибка"));
    showSyncSteps(errors.length ? "Загрузка закончена, есть ошибки:" : "Загрузка закончена:", res.summary);
    setStatus(errors.length ? "Загружено с ошибками, подробности ниже" : "Данные загружены");
    await loadProducts();
  } catch (err) {
    setStatus("");
    showSyncSteps("Загрузка не удалась:", [err.message]);
  } finally {
    clearInterval(timer);
    e.target.disabled = false;
  }
});

// --- предпросмотр и отправка цен ---

const dialog = document.getElementById("preview-dialog");
let pending = null;

const previewGrid = agGrid.createGrid(document.getElementById("grid-preview"), {
  columnDefs: [
    { headerName: "Артикул WB", field: "nm_id", cellRenderer: wbLink, width: 110 },
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

// Двойной щелчок по «Рекомендуемой цене для клиента (акция)» отправляет её в WB (скидка подбирается сама)
const promoSendDialog = document.getElementById("promo-send-dialog");
const promoNoAsk = () => { try { return localStorage.getItem("torpeda.promoNoAsk") === "1"; } catch { return false; } };
let promoBusy = false;

async function sendPromoPrice(e) {
  if (e.colDef.field !== "client_promo" || promoBusy) return;
  const r = e.data;
  if (r.client_promo == null || !(r.client_diff < 0)) return;
  promoBusy = true;
  try {
    const prev = await api("POST", "/api/prices/preview", { promo_nm_ids: [r.nm_id] });
    if (!prev.items.length) return setStatus(`${r.nm_id}: цена уже стоит, отправлять нечего`);
    const text = `Артикул ${r.nm_id}: ${r.client_now} ₽ → ${r.client_promo} ₽ (${r.client_diff_pct}%), маржа ${rub({ value: num(prev.items[0].after.profit) })}. Отправить?`;
    if (!promoNoAsk()) {
      document.getElementById("promo-send-text").textContent = text;
      document.getElementById("promo-send-noask").checked = false;
      const yes = await new Promise((resolve) => {
        const done = (v) => { promoSendDialog.close(); resolve(v); };
        document.getElementById("promo-send-yes").onclick = () => done(true);
        document.getElementById("promo-send-cancel").onclick = () => done(false);
        promoSendDialog.addEventListener("cancel", () => resolve(false), { once: true });
        promoSendDialog.showModal();
      });
      if (!yes) return;
      if (document.getElementById("promo-send-noask").checked) {
        try { localStorage.setItem("torpeda.promoNoAsk", "1"); } catch { /* без запоминания будет спрашивать */ }
      }
    }
    const items = prev.items.map(({ nm_id, old_price, old_discount, new_price, new_discount }) => ({ nm_id, old_price, old_discount, new_price, new_discount }));
    const res = await api("POST", "/api/prices/send", { items, confirm_token: prev.confirm_token });
    setStatus(res.status === "sent" ? `Артикул ${r.nm_id}: цена ${r.client_promo} ₽ отправлена в WB, задача ${res.wb_task_id}. Запись в «Журнале цен».` : `Артикул ${r.nm_id}: WB не принял цену: ${res.error}`);
    if (res.status !== "sent") alert("WB не принял цену: " + res.error);
    await loadProducts();
  } catch (err) {
    alert(err.message);
  } finally {
    promoBusy = false;
  }
}

// --- журнал ---

const historyGrid = agGrid.createGrid(document.getElementById("grid-history"), {
  columnDefs: [
    { headerName: "Когда", field: "sent_at", width: 170, valueFormatter: (p) => new Date(p.value).toLocaleString("ru-RU") },
    { headerName: "Артикул WB", field: "nm_id", cellRenderer: wbLink, width: 120 },
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

const ALERT_STATUS = { new: "не возвращена", reverted: "возвращена", skipped: "пропущено", error: "ошибка" };
const alertsGrid = agGrid.createGrid(document.getElementById("grid-alerts"), {
  columnDefs: [
    { headerName: "Когда заметили", field: "detected_at", width: 170, valueFormatter: (p) => new Date(p.value + "Z").toLocaleString("ru-RU") },
    { headerName: "Артикул WB", field: "nm_id", cellRenderer: wbLink, width: 120 },
    { headerName: "Было", valueGetter: (p) => `${num(p.data.old_price)} ₽ / ${num(p.data.old_discount_pct)}%`, width: 150 },
    { headerName: "Стало (WB)", valueGetter: (p) => `${num(p.data.new_price)} ₽ / ${num(p.data.new_discount_pct)}%`, width: 150 },
    { headerName: "Статус", valueGetter: (p) => (p.data.restored && p.data.status !== "reverted" ? "цена прежняя" : ALERT_STATUS[p.data.status] || p.data.status), width: 130 },
    { headerName: "Примечание", field: "note", width: 280 },
    {
      headerName: "",
      width: 150,
      sortable: false,
      filter: false,
      cellRenderer: (p) => {
        if (p.data.restored) return "";
        const b = document.createElement("button");
        b.textContent = "Вернуть прежнюю";
        b.addEventListener("click", () => openPreview({ revert_alert_ids: [p.data.id] }));
        return b;
      },
    },
  ],
  defaultColDef: { sortable: true, filter: true, resizable: true, wrapHeaderText: true, autoHeaderHeight: true },
  localeText: RU,
});
const revertBox = document.getElementById("revert-autopromo");

async function loadHistory() {
  historyGrid.setGridOption("rowData", await api("GET", "/api/prices/history"));
  alertsGrid.setGridOption("rowData", await api("GET", "/api/price-alerts"));
  revertBox.checked = (await api("GET", "/api/settings")).revert_autopromo === "1";
}
revertBox.addEventListener("change", async () => {
  await api("PUT", "/api/settings", { revert_autopromo: revertBox.checked ? "1" : "0" });
  if (revertBox.checked) checkPrices(true);
});
async function checkPrices(show) {
  try {
    const r = await api("POST", "/api/prices/check");
    if (show && r.revert) alert(`Возвращено цен: ${r.revert.reverted}, пропущено: ${r.revert.skipped}` + (r.revert.error ? `\nОшибка WB: ${r.revert.error}` : ""));
    else if (show) alert(r.new_alerts ? `Есть невозвращённые изменения цен от WB: ${r.new_alerts}` : "Цены в WB не менялись без вас");
  } catch (err) {
    if (show) alert(err.message);
  }
  loadHistory();
}
document.getElementById("btn-price-check").addEventListener("click", () => checkPrices(true));
setInterval(() => checkPrices(false), 10 * 60 * 1000);
document.getElementById("btn-history-refresh").addEventListener("click", loadHistory);

// --- акции ---

addTopScroll("grid-promo");
const promoGrid = agGrid.createGrid(document.getElementById("grid-promo"), {
  columnDefs: [
    { headerName: "Артикул WB", field: "nm_id", cellRenderer: wbLink, width: 120 },
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
  rowSelection: "single",
  rowClassRules: { "row-loss": (p) => p.data.promo?.status === "loss", "row-risk": (p) => p.data.promo?.status === "risk" },
});

const BEST = "best";
const bestCols = [
  { headerName: "Артикул WB", field: "nm_id", cellRenderer: wbLink, width: 120 },
  { headerName: "Арт. продавца", field: "vendor_code", width: 120 },
  { headerName: "Самая выгодная акция", valueGetter: (p) => p.data.promo_best.name, width: 210 },
  { headerName: "Всего акций", valueGetter: (p) => p.data.promos.length, width: 90 },
  { headerName: "Участвует", valueGetter: (p) => (p.data.promo_best.in_action ? "да" : "нет"), width: 90 },
  { headerName: "Цена продавца сейчас", valueGetter: (p) => num(p.data.promo_best.cur_seller_price), valueFormatter: rub, width: 130 },
  { headerName: "Цена для вступления", valueGetter: (p) => num(p.data.promo_best.plan_seller_price), valueFormatter: rub, width: 130 },
  { headerName: "Понизить, ₽", valueGetter: (p) => (p.data.promo_best.delta_seller == null ? null : Math.max(0, -num(p.data.promo_best.delta_seller))), valueFormatter: rub, width: 110 },
  { headerName: "Понизить, %", valueGetter: (p) => (p.data.promo_best.delta_pct == null ? null : Math.max(0, -num(p.data.promo_best.delta_pct))), valueFormatter: pct, width: 110 },
  { headerName: "Цена до скидки / скидка", valueGetter: (p) => `${rub({ value: num(p.data.promo_best.price) })} / ${Math.round(num(p.data.promo_best.discount_pct))}%`, width: 170 },
  { headerName: "Прибыль, ₽", valueGetter: (p) => num(p.data.promo_best.profit), valueFormatter: rub, cellClass: signClass, width: 110 },
  { headerName: "Маржа, %", valueGetter: (p) => num(p.data.promo_best.margin_pct), valueFormatter: pct, width: 100 },
  { headerName: "ROI, %", valueGetter: (p) => num(p.data.promo_best.roi_pct), valueFormatter: pct, width: 90 },
  { headerName: "Что сделать", valueGetter: (p) => clientPrices(p.data).promo_advice_client ?? p.data.promo_best.advice, width: 320 },
];
const promoCols = promoGrid.getColumnDefs();
const promoSelect = document.getElementById("promo-select");
async function loadPromotions() {
  const promos = await api("GET", "/api/promotions");
  promoSelect.innerHTML =
    `<option value="${BEST}">Лучшая акция по каждому товару</option>` +
    promos
    .map((p) => `<option value="${p.id}">${p.name} (${(p.start_at || "").slice(0, 10)} — ${(p.end_at || "").slice(0, 10)})</option>`)
    .join("");
  if (promos.length) await loadPromotion(promoSelect.value || BEST);
  else promoGrid.setGridOption("rowData", []);
}
async function loadPromotion(id) {
  if (id === BEST) {
    const rows = await api("GET", "/api/promotions-best");
    const loss = rows.filter((r) => r.promo_best.status === "loss").length;
    document.getElementById("promo-info").textContent = `Товаров с ценой для вступления: ${rows.length} · в убыток: ${loss}`;
    promoGrid.setGridOption("columnDefs", bestCols);
    promoGrid.setGridOption("rowData", rows);
    return;
  }
  promoGrid.setGridOption("columnDefs", promoCols);
  const data = await api("GET", `/api/promotions/${id}`);
  const loss = data.items.filter((i) => i.promo?.status === "loss").length;
  document.getElementById("promo-info").textContent = `Товаров: ${data.items.length} · в убыток в акции: ${loss}`;
  promoGrid.setGridOption("rowData", data.items);
}
promoSelect.addEventListener("change", () => loadPromotion(promoSelect.value));

const promoFiles = document.getElementById("promo-files");
for (const id of ["btn-promo-upload", "btn-promo-upload-2"]) document.getElementById(id).addEventListener("click", () => promoFiles.click());

const promoResult = document.getElementById("promo-result-dialog");
document.getElementById("promo-result-close").addEventListener("click", () => promoResult.close());
function showPromoResult(html) {
  document.getElementById("promo-result-body").innerHTML = html;
  promoResult.showModal();
}

async function uploadPromoFiles(files) {
  const xlsx = [...files].filter((f) => /\.xlsx$/i.test(f.name));
  if (!xlsx.length) {
    showPromoResult("<p>Нужны файлы Excel (.xlsx) из кабинета WB.</p>");
    return;
  }
  const form = new FormData();
  for (const f of xlsx) form.append("files", f);
  try {
    const res = await fetch("/api/promotions/import", { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    const data = await res.json();
    const bad = data.files.filter((f) => f.error);
    showPromoResult(
      `<p class="big">Загружено акций: ${data.promotions}, строк товаров: ${data.items}</p>` +
        (bad.length ? `<p>Не загрузились:</p><ul>${bad.map((f) => `<li>${esc(f.file)}: ${esc(f.error)}</li>`).join("")}</ul>` : "") +
        "<p>Теперь на вкладке «Товары» нажмите «Пересчитать цены по акциям»: цены для вступления попадут в «Новую цену».</p>"
    );
    await loadPromotions();
    await loadProducts();
  } catch (e) {
    showPromoResult("<p>Не получилось загрузить акции: " + esc(e.message) + "</p>");
  }
}
promoFiles.addEventListener("change", () => {
  const files = [...promoFiles.files];
  promoFiles.value = "";
  uploadPromoFiles(files);
});

// файлы можно просто бросить мышью в окно программы
window.addEventListener("dragover", (e) => { if (e.dataTransfer?.types?.includes("Files")) e.preventDefault(); });
window.addEventListener("drop", (e) => {
  if (!e.dataTransfer?.files?.length) return;
  e.preventDefault();
  uploadPromoFiles(e.dataTransfer.files);
});

// --- отчёты ---

const intFmt = (p) => (p.value === null || p.value === undefined || p.value === "" ? "" : Number(p.value).toLocaleString("ru-RU"));
const dateFmt = (p) => (p.value ? new Date(p.value).toLocaleDateString("ru-RU") : "");
const KIND = {
  text: {},
  date: { valueFormatter: dateFmt, width: 100 },
  int: { valueFormatter: intFmt, type: "numericColumn", width: 115 },
  num: { valueFormatter: (p) => (p.value === null || p.value === undefined || p.value === "" ? "" : Number(p.value).toLocaleString("ru-RU", { maximumFractionDigits: 1 })), type: "numericColumn", width: 115 },
  money: { valueFormatter: rub, type: "numericColumn", width: 135 },
  pct: { valueFormatter: pct, type: "numericColumn", width: 100 },
};
const reportGrid = agGrid.createGrid(document.getElementById("grid-report"), {
  columnDefs: [],
  // cellDataType: false — иначе строка «Итого» в числовой колонке артикула показывается как ошибка
  defaultColDef: { sortable: true, filter: true, resizable: true, wrapHeaderText: true, autoHeaderHeight: true, cellDataType: false },
  localeText: { ...RU, noRowsToShow: "Нет данных за эти даты. Загрузите их из WB кнопкой справа сверху." },
  getRowStyle: (p) => (p.node.rowPinned ? { fontWeight: 600 } : null),
  onCellValueChanged: savePlanCell,
});
// какие кнопки загрузки показывать у отчёта; для остатков дни продаж считаются по заказам
const ORDERS_SYNC = ["btn-orders-sync"];
const SYNC_BUTTONS = {
  orders_sales: ORDERS_SYNC, buyout: ORDERS_SYNC, delivery_time: ORDERS_SYNC, spp: ORDERS_SYNC, plan_fact: ORDERS_SYNC,
  stocks: ORDERS_SYNC, abc: ["btn-orders-sync", "btn-report-sync"],
  funnel: ["btn-funnel-sync"], storage: ["btn-services-sync"], acceptance: ["btn-services-sync"],
  ads: ["btn-ads-sync"], ad_costs: ["btn-ads-sync"], detail: ["btn-report-sync", "btn-ads-sync"],
  geography: ORDERS_SYNC, joint_sales: ORDERS_SYNC, coefficients: ["btn-coef-sync"], price_history: [],
};
const reportFrom = document.getElementById("report-from");
const reportTo = document.getElementById("report-to");
const reportParams = () => {
  const [name, group] = document.getElementById("report-select").value.split("|");
  const q = new URLSearchParams({ date_from: reportFrom.value, date_to: reportTo.value });
  if (group) q.set("group", group);
  return { name, q };
};

async function initReportDates() {
  if (reportFrom.value) return;
  const r = await api("GET", "/api/reports/range");
  const last = [r.date_to, r.orders_to].filter(Boolean).sort().pop();
  const to = last ? new Date(last) : new Date();
  const from = new Date(to);
  from.setDate(from.getDate() - 29);
  reportTo.value = to.toISOString().slice(0, 10);
  reportFrom.value = from.toISOString().slice(0, 10);
}

async function loadReport() {
  await initReportDates();
  const { name, q } = reportParams();
  const shown = SYNC_BUTTONS[name] || ["btn-report-sync"];
  for (const id of ["btn-report-sync", "btn-orders-sync", "btn-funnel-sync", "btn-services-sync", "btn-ads-sync", "btn-coef-sync"]) {
    document.getElementById(id).hidden = !shown.includes(id);
  }
  setStatus("Считаю отчёт…");
  try {
    const data = await api("GET", `/api/reports/${name}?${q}`);
    reportGrid.setGridOption("columnDefs", data.columns.map((c) => ({
      field: c.field,
      headerName: c.header,
      ...KIND[c.kind],
      ...(c.editable ? { editable: (p) => !p.node.rowPinned, cellClass: "cell-edit", valueParser: (p) => (p.newValue === "" || p.newValue === null ? null : Number(String(p.newValue).replace(/\s/g, "").replace(",", "."))) } : {}),
      ...(c.kind === "text" ? { width: c.field === "reason" || c.field === "oper" ? 260 : 140 } : {}),
      ...(c.field === "profit" || c.field === "profit_per_unit" ? { cellClass: signClass } : {}),
      ...(c.field === "nm_id" ? { cellRenderer: wbLink } : {}),
    })));
    reportGrid.setGridOption("rowData", data.rows);
    reportGrid.setGridOption("pinnedTopRowData", data.totals ? [data.totals] : []);
    document.getElementById("report-notes").textContent = data.notes.join(" ");
    setStatus(`${data.title}: строк ${data.rows.length}`);
  } catch (err) {
    setStatus(err.message);
  }
}
async function savePlanCell(e) {
  if (!["plan_qty", "plan_revenue"].includes(e.colDef.field)) return;
  const v = e.newValue;
  if (v !== null && (Number.isNaN(v) || v < 0)) {
    alert("План должен быть числом не меньше нуля.");
    e.node.setDataValue(e.colDef.field, e.oldValue);
    return;
  }
  const r = e.data;
  try {
    await api("PUT", "/api/plans", {
      month: r.month,
      nm_id: typeof r.nm_id === "number" ? r.nm_id : 0,
      qty: r.plan_qty === null || r.plan_qty === undefined ? null : Math.round(r.plan_qty),
      revenue: r.plan_revenue ?? null,
    });
    setStatus("План сохранён");
    await loadReport();
  } catch (err) {
    alert(err.message);
  }
}
document.getElementById("btn-report").addEventListener("click", loadReport);
document.getElementById("report-select").addEventListener("change", loadReport);
document.getElementById("btn-report-xlsx").addEventListener("click", () => {
  const { name, q } = reportParams();
  window.location = `/api/reports/${name}.xlsx?${q}`;
});
document.getElementById("btn-report-sync").addEventListener("click", async (e) => {
  e.target.disabled = true;
  setStatus("Загружаю финотчёты из WB… WB отдаёт их медленно, подождите");
  try {
    const res = await api("POST", "/api/wb/sync-report", { date_from: reportFrom.value, date_to: reportTo.value });
    setStatus(`Загружено строк финотчётов: ${res.rows}`);
    await loadReport();
  } catch (err) {
    setStatus("");
    alert(err.message);
  } finally {
    e.target.disabled = false;
  }
});

document.getElementById("btn-orders-sync").addEventListener("click", async (e) => {
  e.target.disabled = true;
  const limit = new Date();
  limit.setDate(limit.getDate() - 89);
  const from = reportFrom.value && new Date(reportFrom.value) > limit ? reportFrom.value : limit.toISOString().slice(0, 10);
  setStatus("Загружаю заказы и продажи из WB…");
  try {
    const res = await api("POST", "/api/wb/sync-orders", { date_from: from, date_to: reportTo.value || new Date().toISOString().slice(0, 10) });
    setStatus(`Загружено: заказов ${res.orders}, продаж и возвратов ${res.sales}`);
    await loadReport();
  } catch (err) {
    setStatus("");
    alert(err.message);
  } finally {
    e.target.disabled = false;
  }
});

async function syncPeriod(e, url, waiting, done) {
  e.target.disabled = true;
  setStatus(waiting);
  try {
    const res = await api("POST", url, { date_from: reportFrom.value, date_to: reportTo.value });
    setStatus(done(res));
    await loadReport();
  } catch (err) {
    setStatus("");
    alert(err.message);
  } finally {
    e.target.disabled = false;
  }
}
document.getElementById("btn-funnel-sync").addEventListener("click", (e) =>
  syncPeriod(e, "/api/wb/sync-funnel", "Загружаю воронку из WB…", (r) => `Воронка: карточек ${r.rows}`));
document.getElementById("btn-ads-sync").addEventListener("click", (e) =>
  syncPeriod(e, "/api/wb/sync-ads", "Загружаю рекламу из WB… Это может занять несколько минут",
    (r) => `Реклама: кампаний ${r.campaigns}, строк статистики ${r.stats}, списаний ${r.costs}`));
document.getElementById("btn-coef-sync").addEventListener("click", (e) =>
  syncPeriod(e, "/api/wb/sync-coefficients", "Загружаю коэффициенты приёмки из WB…", (r) => `Коэффициентов: ${r.rows}`));
document.getElementById("btn-services-sync").addEventListener("click", (e) =>
  syncPeriod(e, "/api/wb/sync-services", "Загружаю хранение и приёмку из WB… Это может занять несколько минут",
    (r) => `Загружено строк: хранение ${r.storage}, приёмка ${r.acceptance}`));

// --- настройки ---

const form = document.getElementById("settings-form");
async function loadSettings() {
  const s = await api("GET", "/api/settings");
  for (const [k, v] of Object.entries(s)) if (form.elements[k]) form.elements[k].value = v;
  showKeys(await api("GET", "/api/keys"));
  loadSyncLog();
}

const keysForm = document.getElementById("keys-form");
function showKeys(keys) {
  for (const name of ["read", "prices"]) {
    const el = document.getElementById(`key-${name}-current`);
    const info = (keys.info || {})[name];
    if (!keys[name] || !info) {
      el.className = "key-now";
      el.textContent = "Сейчас: ключ не задан";
      continue;
    }
    const lines = [`Сейчас используется ключ, окончание ${keys[name]}`, ...info.summary];
    if (info.source !== "программа") lines.push(`Взят из: ${info.source}. Сохраните ключ здесь, и программа будет брать его.`);
    if (info.text) lines.push(info.text);
    el.className = `key-now ${info.ok ? "good" : "bad"}`;
    el.innerHTML = lines.map((l) => `<div>${esc(l)}</div>`).join("");
  }
}
function keysResult(text, ok) {
  const el = document.getElementById("keys-result");
  el.className = ok ? "good" : "bad";
  el.textContent = text;
}
for (const btn of document.querySelectorAll(".key-clear")) {
  btn.addEventListener("click", async () => {
    if (!confirm("Удалить сохранённый ключ из программы?")) return;
    try {
      showKeys(await api("PUT", "/api/keys", { [btn.dataset.key]: "" }));
      keysResult("Ключ удалён из программы.", true);
    } catch (err) {
      keysResult(err.message, false);
    }
  });
}
keysForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {};
  for (const name of ["read", "prices"]) {
    const v = keysForm.elements[name].value.replace(/\s+/g, "");
    if (v) body[name] = v;
  }
  if (!Object.keys(body).length) {
    keysResult("Поле пустое: вставьте ключ и нажмите «Сохранить ключи».", false);
    return;
  }
  try {
    const keys = await api("PUT", "/api/keys", body);
    showKeys(keys);
    keysForm.reset();
    const done = Object.keys(body).map((name) => {
      const info = keys.info[name];
      return `Ключ принят: окончание ${keys[name]}, ${info.summary.join(", ").toLowerCase()}.`;
    });
    keysResult(done.join(" "), true);
    setStatus("Ключи сохранены");
    document.getElementById("btn-check").click();
  } catch (err) {
    keysResult(err.message, false);
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

// «Обновить СПП»: свежие заказы за сутки. Галочка «каждый час» работает, пока программа открыта.
async function syncSpp() {
  setStatus("Обновляю СПП…");
  try {
    const res = await api("POST", "/api/wb/sync-spp");
    await loadProducts();
    setStatus(`СПП обновлена: заказов за сутки ${res.orders}`);
  } catch (err) {
    setStatus(`СПП: ${err.message}`);
  }
}
document.getElementById("btn-spp").addEventListener("click", syncSpp);

async function syncSitePrices() {
  setStatus("Смотрю цены на сайте WB…");
  try {
    const res = await api("POST", "/api/wb/sync-site-prices");
    await loadProducts();
    setStatus(`Цены на сайте обновлены: товаров ${res.products}`);
  } catch (err) {
    setStatus(`Цены на сайте: ${err.message}`);
  }
}
document.getElementById("btn-site-prices").addEventListener("click", syncSitePrices);
function showMpstatsKey(res) {
  document.getElementById("mpstats-key-current").textContent = res.set
    ? `Сейчас используется токен, окончание …${res.tail} (${res.source})`
    : "Токен не задан";
  if (res.text) document.getElementById("mpstats-key-result").textContent = res.text;
}
async function mpstatsKey(method, url, body, waiting) {
  const result = document.getElementById("mpstats-key-result");
  result.textContent = waiting;
  try {
    showMpstatsKey(await api(method, url, body));
  } catch (err) {
    result.textContent = err.message;
  }
}
document.getElementById("btn-mpstats-save").addEventListener("click", async () => {
  const field = document.getElementById("mpstats-token");
  const token = field.value.replace(/\s+/g, "");
  if (!token) {
    document.getElementById("mpstats-key-result").textContent = "Поле пустое: вставьте токен и нажмите «Сохранить и проверить токен».";
    return;
  }
  await mpstatsKey("PUT", "/api/mpstats/key", { token }, "Сохраняю и проверяю…");
  field.value = "";
});
document.getElementById("btn-mpstats-clear").addEventListener("click", () =>
  mpstatsKey("PUT", "/api/mpstats/key", { token: "" }, "Удаляю…"),
);
api("GET", "/api/mpstats/key").then(showMpstatsKey).catch(() => {});

async function loadMpstats() {
  const result = document.getElementById("mpstats-result");
  const table = document.getElementById("mpstats-table");
  const skus = document.getElementById("mpstats-skus").value.trim();
  const days = Number(document.getElementById("mpstats-days").value) || 30;
  result.textContent = "Загружаю из MPSTATS, это может занять минуту…";
  table.innerHTML = "";
  try {
    const res = await api("GET", `/api/mpstats?days=${days}&skus=${encodeURIComponent(skus)}`);
    const n = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 0 }));
    const head = ["Артикул", "Товар", "Продажи, шт.", "Было → стало (две половины)", "Выручка, ₽", "Цена: сейчас", "мин–макс", "У нас на сайте", "Остаток", "Дней без остатка"];
    const body = res.rows.map((r) => [
      r.sku,
      r.name,
      n(r.sales),
      `${n(r.sales_first_half)} → ${n(r.sales_second_half)}`,
      n(r.revenue),
      n(r.price_last),
      `${n(r.price_min)}–${n(r.price_max)}`,
      n(r.our_site_price),
      n(r.balance_last),
      n(r.days_out_of_stock),
    ]);
    const tr = (cells, tag) => `<tr>${cells.map((c) => `<${tag}></${tag}>`).join("")}</tr>`;
    table.innerHTML = tr(head, "th") + body.map((b) => tr(b, "td")).join("");
    table.querySelectorAll("tr").forEach((row, i) => {
      const cells = i === 0 ? head : body[i - 1];
      row.querySelectorAll("th,td").forEach((cell, j) => (cell.textContent = cells[j]));
    });
    result.textContent = `Готово: артикулов ${res.rows.length}, период ${days} дн.`;
  } catch (err) {
    result.textContent = err.message;
  }
}
document.getElementById("btn-mpstats").addEventListener("click", loadMpstats);
const sppHourly = document.getElementById("spp-hourly");
let sppTimer = null;
function setSppHourly(on) {
  clearInterval(sppTimer);
  sppTimer = on ? setInterval(async () => { await syncSpp(); await syncSitePrices(); }, 3600 * 1000) : null;
  try {
    localStorage.setItem("sppHourly", on ? "1" : "");
  } catch {}
}
try {
  sppHourly.checked = localStorage.getItem("sppHourly") === "1";
} catch {}
setSppHourly(sppHourly.checked);
sppHourly.addEventListener("change", () => setSppHourly(sppHourly.checked));

document.getElementById("btn-bulk-cost").addEventListener("click", () => {
  document.querySelector('.tab[data-tab="settings"]').click();
  document.getElementById("bulk-cost").scrollIntoView({ behavior: "smooth" });
});

document.getElementById("bulk-cost-save").addEventListener("click", async () => {
  const out = document.getElementById("bulk-cost-result");
  const cost = Number(document.getElementById("bulk-cost-value").value);
  if (!(cost >= 0) || document.getElementById("bulk-cost-value").value === "") {
    out.textContent = "Введите сумму себестоимости.";
    return;
  }
  const all = document.querySelector('input[name="bulk-cost-who"]:checked').value === "all";
  const question = all
    ? `Записать себестоимость ${cost} руб ВСЕМ товарам? Прежние значения будут заменены (их можно вернуть кнопкой «Вернуть прошлое»).`
    : `Записать себестоимость ${cost} руб товарам, у которых её нет?`;
  if (!confirm(question)) return;
  try {
    const res = await api("POST", "/api/costs/bulk", { cost, only_empty: !all, past_too: document.getElementById("bulk-cost-past").checked });
    out.textContent = `Записано товаров: ${res.written}.`;
    await loadProducts();
  } catch (err) {
    out.textContent = err.message;
  }
});

document.getElementById("bulk-cost-undo").addEventListener("click", async () => {
  const out = document.getElementById("bulk-cost-result");
  if (!confirm("Отменить последнюю массовую запись себестоимости?")) return;
  try {
    const res = await api("POST", "/api/costs/undo");
    out.textContent = `Прежняя себестоимость возвращена, товаров: ${res.restored}.`;
    await loadProducts();
  } catch (err) {
    out.textContent = err.message;
  }
});

document.getElementById("costs-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const out = document.getElementById("costs-result");
  out.textContent = "Загружаю…";
  const body = new FormData();
  body.append("file", file);
  try {
    const resp = await fetch("/api/costs/import", { method: "POST", body });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) throw new Error((data && data.detail) || `Ошибка ${resp.status}`);
    const lines = [`Обновлено: ${data.updated}`, `Без изменений: ${data.unchanged}`];
    if (data.not_found.length) lines.push(`Нет в таблице товаров: ${data.not_found.length} (${data.not_found.slice(0, 10).join(", ")})`);
    if (data.errors.length) lines.push(...data.errors.slice(0, 10));
    out.textContent = lines.join("\n");
    await loadProducts();
  } catch (err) {
    out.textContent = err.message;
  }
  e.target.value = "";
});

api("GET", "/api/info").then((i) => {
  document.getElementById("version").textContent = `версия ${i.version}`;
  document.getElementById("app-info").textContent = `Версия программы: ${i.version}. Запущена из папки: ${i.app_dir}`;
  document.getElementById("data-dir").textContent = `Ключи, себестоимость и журнал цен хранятся в папке ${i.data_dir}. Обновление программы их не стирает.`;
});

// --- обновление программы кнопкой ---

const btnUpdate = document.getElementById("btn-update");
api("GET", "/api/update/check")
  .then((u) => {
    if (u.available) {
      btnUpdate.textContent = u.build ? `Доступна сборка ${u.build}: обновить` : "Есть новая версия: обновить";
      btnUpdate.classList.add("primary");
    }
  })
  .catch(() => { /* без интернета кнопка остаётся обычной */ });

const isNetworkError = (err) => err instanceof TypeError;

// После перезапуска ждём, пока программа снова ответит, и перезагружаем страницу
function waitForRestart() {
  const started = Date.now();
  let gone = false;
  setStatus("Перезапускаю и обновляю, это около минуты…");
  btnUpdate.disabled = true;
  const timer = setInterval(async () => {
    try {
      await api("GET", "/api/info");
      if (gone || Date.now() - started > 15000) { clearInterval(timer); location.reload(); }
    } catch {
      gone = true; // программа остановилась и ещё не поднялась
    }
    if (Date.now() - started > 180000) {
      clearInterval(timer);
      btnUpdate.disabled = false;
      setStatus("");
      alert("Программа не запустилась за 3 минуты. Откройте чёрное окно «Торпеда» или запустите start.bat вручную.");
    }
  }, 3000);
}

btnUpdate.addEventListener("click", async () => {
  btnUpdate.disabled = true;
  let restarting = false;
  try {
    const u = await api("GET", "/api/update/check");
    if (!u.available) {
      setStatus("У вас последняя версия");
      return;
    }
    if (!confirm("Программа перезапустится и поставит новую версию. Это займёт около минуты. Продолжить?")) return;
    restarting = true;
    await api("POST", "/api/update/restart");
  } catch (err) {
    if (restarting && isNetworkError(err)) {
      // программа закрылась раньше, чем успела ответить: так и задумано, ждём запуска
    } else if (isNetworkError(err)) {
      offlineBar.hidden = false;
      wasOffline = true;
      return;
    } else {
      alert(err.message);
      return;
    }
  } finally {
    if (!restarting) btnUpdate.disabled = false;
  }
  if (restarting) waitForRestart();
});

// Если программа остановилась (закрыто чёрное окно, перезагрузка), страница об этом говорит и сама оживает
const offlineBar = document.getElementById("offline-bar");
let wasOffline = false;
setInterval(async () => {
  try {
    await api("GET", "/api/info");
    if (wasOffline) location.reload();
  } catch (err) {
    if (!isNetworkError(err)) return;
    wasOffline = true;
    offlineBar.hidden = false;
  }
}, 10000);

// --- что пошло не так ---

const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
async function loadSyncLog() {
  const rows = await api("GET", "/api/sync-log");
  document.getElementById("sync-log").innerHTML = rows.length
    ? rows.map((r) => `<tr><td>${r.ok ? "✅" : "❌"}</td><td>${esc(r.section)}</td><td>${new Date(r.at).toLocaleString("ru-RU")}</td><td>${esc(r.message)}</td></tr>`).join("")
    : "<tr><td>Загрузок ещё не было. Нажмите «Загрузить из WB».</td></tr>";
}
document.getElementById("btn-sync-log").addEventListener("click", loadSyncLog);
document.getElementById("btn-diagnose-stocks").addEventListener("click", async (e) => {
  const out = document.getElementById("diagnose-result");
  e.target.disabled = true;
  out.textContent = "Спрашиваю WB…";
  try {
    const [res, key] = await Promise.all([api("GET", "/api/wb/diagnose/stocks"), api("GET", "/api/wb/token-info")]);
    const claims = Object.entries(key.claims || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("\n");
    out.innerHTML = `<div class="diag ${key.ok ? "good" : "bad"}"><b>Свойства ключа для данных</b> (сам ключ не показывается)${key.text ? ": " + esc(key.text) : ""}
      ${(key.summary || []).map((line) => `<div>${esc(line)}</div>`).join("")}
      <pre>${esc(claims) || "нет данных"}</pre></div>` + res.map((r) => `<div class="diag ${r.rows ? "good" : "bad"}"><b>${esc(r.what)}</b>: ${esc(r.explanation)}
      <pre>Запрос: ${esc(r.request)}\nОтвет WB (код ${r.status}): ${esc(r.answer) || "пусто"}</pre></div>`).join("");
  } catch (err) {
    out.textContent = err.message;
  } finally {
    e.target.disabled = false;
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
