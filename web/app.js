const STATUS = {
  active: "在售",
  deprecated: "已弃用",
  retiring: "即将下线",
  preview: "预览",
};

const state = {
  data: null,
  ccy: "CNY",
  region: "all",
  status: "all",
  query: "",
  vendors: new Set(),
  sortKey: "vendor",
  sortDir: "asc",
};

const app = document.querySelector("#app");

function h(tag, props, children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (value == null || value === false) return;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  });
  (children || []).forEach((child) => {
    node.append(child instanceof Node ? child : document.createTextNode(child == null ? "" : String(child)));
  });
  return node;
}

function trimNumber(value) {
  const text = String(value);
  if (!text.includes(".")) return text;
  return text.replace(/0+$/, "").replace(/\.$/, "");
}

function money(value, currency) {
  const amount = trimNumber(value);
  return currency === "CNY" ? `¥${amount}` : `$${amount}`;
}

function vendorOf(id) {
  return state.data.vendors.find((vendor) => vendor.id === id);
}

function contextRank(model) {
  const tokens = model.context.window_tokens;
  if (Number.isInteger(tokens)) return tokens;
  const label = String(model.context.window_label || "");
  if (/^\d+$/.test(label)) return Number(label);
  const matched = label.match(/^(\d+(?:\.\d+)?)(万|M|K)$/i);
  if (!matched) return -1;
  const number = Number(matched[1]);
  const unit = matched[2].toUpperCase();
  if (unit === "万") return number * 10000;
  if (unit === "M") return number * 1000000;
  return number * 1000;
}

function contextLabel(model) {
  if (model.context.window_tokens_exact && Number.isInteger(model.context.window_tokens)) {
    return model.context.window_tokens.toLocaleString("zh-CN");
  }
  return model.context.window_label || "未标明";
}

function shownAmount(model, side) {
  const key = state.ccy === "CNY" ? `cny_${side}_per_1m` : `usd_${side}_per_1m`;
  return model.conversion[key];
}

function converted(model) {
  return model.billing.currency !== state.ccy;
}

function priceCell(model, side) {
  const amount = money(shownAmount(model, side), state.ccy);
  const children = [amount];
  if (converted(model)) children.push(h("span", { class: "mark" }, ["折算"]));
  return h("td", { class: "num" }, children);
}

function cacheAmount(model) {
  const raw = model.billing.headline.cache_hit_input_per_1m;
  if (!raw) return "—";
  const rate = Number(state.data.fx.rate);
  const value = Number(raw);
  if (!Number.isFinite(value) || !Number.isFinite(rate) || rate === 0) return "—";
  const convertedValue = model.billing.currency === state.ccy
    ? value
    : model.billing.currency === "USD"
      ? value * rate
      : value / rate;
  return money(convertedValue.toFixed(6), state.ccy);
}

function matches(model) {
  if (state.region !== "all" && model.region !== state.region) return false;
  if (state.status !== "all" && model.status !== state.status) return false;
  if (state.vendors.size && !state.vendors.has(model.vendor)) return false;
  if (!state.query) return true;
  const vendor = vendorOf(model.vendor);
  const haystack = [
    model.display_name_zh,
    model.display_name_en,
    model.id,
    model.api_model_id,
    vendor && vendor.name_zh,
    vendor && vendor.name_en,
  ].join(" ").toLowerCase();
  return haystack.includes(state.query.toLowerCase());
}

function sorted(models) {
  const direction = state.sortDir === "asc" ? 1 : -1;
  const vendorOrder = Object.fromEntries(state.data.vendors.map((vendor) => [vendor.id, vendor.order]));
  return models.slice().sort((a, b) => {
    let result = 0;
    if (state.sortKey === "name") result = a.display_name_zh.localeCompare(b.display_name_zh, "zh");
    else if (state.sortKey === "context") result = contextRank(a) - contextRank(b);
    else if (state.sortKey === "input") result = Number(shownAmount(a, "input")) - Number(shownAmount(b, "input"));
    else if (state.sortKey === "output") result = Number(shownAmount(a, "output")) - Number(shownAmount(b, "output"));
    else if (state.sortKey === "verified") result = a.verified_at.localeCompare(b.verified_at);
    else result = (vendorOrder[a.vendor] || 0) - (vendorOrder[b.vendor] || 0) || a.display_name_zh.localeCompare(b.display_name_zh, "zh");
    return result * direction;
  });
}

function writeHash() {
  const params = new URLSearchParams();
  if (state.ccy !== "CNY") params.set("ccy", state.ccy);
  if (state.region !== "all") params.set("region", state.region);
  if (state.status !== "all") params.set("status", state.status);
  if (state.query) params.set("q", state.query);
  if (state.vendors.size) params.set("vendor", [...state.vendors].join(","));
  if (state.sortKey !== "vendor") params.set("sort", state.sortKey);
  if (state.sortDir !== "asc") params.set("dir", state.sortDir);
  const query = params.toString();
  const next = query ? `#/?${query}` : "#/";
  if (location.hash !== next) location.hash = next;
}

function readHash() {
  const raw = (location.hash || "#/").replace(/^#/, "");
  const [path, queryString] = raw.split("?");
  const params = new URLSearchParams(queryString || "");
  const search = new URLSearchParams(location.search);
  search.forEach((value, key) => params.set(key, value));
  state.ccy = params.get("ccy") === "USD" ? "USD" : "CNY";
  state.region = params.get("region") === "cn" || params.get("region") === "global" ? params.get("region") : "all";
  state.status = ["active", "deprecated", "retiring", "preview"].includes(params.get("status")) ? params.get("status") : "all";
  state.query = params.get("q") || "";
  state.vendors = new Set((params.get("vendor") || "").split(",").filter(Boolean));
  state.sortKey = ["vendor", "name", "context", "input", "output", "verified"].includes(params.get("sort")) ? params.get("sort") : "vendor";
  state.sortDir = params.get("dir") === "desc" ? "desc" : "asc";
  if (params.get("model")) return params.get("model");
  return path.startsWith("/m/") ? decodeURIComponent(path.slice(3)) : null;
}

function statusTag(status) {
  if (status === "active") return h("span", { class: "tag" }, ["在售"]);
  const kind = status === "deprecated" || status === "retiring" ? "tag bad" : "tag ok";
  return h("span", { class: kind }, [STATUS[status] || status]);
}

function clearFilters() {
  state.region = "all";
  state.status = "all";
  state.query = "";
  state.vendors = new Set();
  state.ccy = "CNY";
  state.sortKey = "vendor";
  state.sortDir = "asc";
  writeHash();
}

function emptyState() {
  return h("div", { class: "empty", role: "status" }, [
    h("h2", {}, ["没有符合条件的模型"]),
    h("p", {}, ["筛选是空的。账本不会为了把表填满而补一条没有来源的价格。"]),
    h("button", { type: "button", class: "text-button solid", onclick: clearFilters }, ["清除筛选"]),
  ]);
}

function mount(nodes) {
  app.replaceChildren(...nodes.filter((node) => node != null && node !== false));
}

function renderCatalog() {
  const fx = state.data.fx;
  const visible = sorted(state.data.models.filter(matches));
  const columns = [
    ["vendor", "厂商"],
    ["name", "模型"],
    ["context", "上下文"],
    ["input", "输入 / 百万"],
    ["output", "输出 / 百万"],
    ["verified", "核验"],
  ];
  const head = h("tr", {}, columns.map(([key, label]) => {
    const props = {};
    if (state.sortKey === key) props["aria-sort"] = state.sortDir === "asc" ? "ascending" : "descending";
    return h("th", props, [h("button", { type: "button", onclick: () => sortBy(key) }, [label])]);
  }).concat([h("th", {}, ["缓存命中"])]));

  const body = h("tbody", {}, visible.map((model) => {
    const vendor = vendorOf(model.vendor);
    const open = () => { location.hash = `#/m/${encodeURIComponent(model.id)}`; };
    return h("tr", { tabindex: "0", onclick: open, onkeydown: (event) => {
      if (event.key === "Enter") open();
    } }, [
      h("td", {}, [vendor ? vendor.name_zh : model.vendor, h("span", { class: "sub" }, [model.region === "cn" ? "国内" : "海外"])]),
      h("td", {}, [
        h("a", { class: "name", href: `#/m/${encodeURIComponent(model.id)}` }, [model.display_name_zh]),
        h("span", { class: "sub" }, [model.id]),
      ]),
      h("td", {}, [contextLabel(model)]),
      priceCell(model, "input"),
      priceCell(model, "output"),
      h("td", {}, [model.verified_at, model.status === "active" ? "" : h("span", { class: "sub" }, [statusTag(model.status)])]),
      h("td", { class: "num" }, [cacheAmount(model), converted(model) && model.billing.headline.cache_hit_input_per_1m ? h("span", { class: "mark" }, ["折算"]) : ""]),
    ]);
  }));

  const cards = h("div", { class: "cards" }, visible.map((model) => {
    const vendor = vendorOf(model.vendor);
    return h("article", { class: "card", tabindex: "0", onclick: () => { location.hash = `#/m/${encodeURIComponent(model.id)}`; } }, [
      h("h2", {}, [model.display_name_zh]),
      h("div", {}, [vendor ? vendor.name_zh : model.vendor, " · ", model.id]),
      h("dl", {}, [
        h("dt", {}, ["输入"]), h("dd", {}, [money(shownAmount(model, "input"), state.ccy)]),
        h("dt", {}, ["输出"]), h("dd", {}, [money(shownAmount(model, "output"), state.ccy)]),
        h("dt", {}, ["上下文"]), h("dd", {}, [contextLabel(model)]),
        h("dt", {}, ["状态"]), h("dd", {}, [STATUS[model.status] || model.status]),
      ]),
    ]);
  }));

  mount([
    h("section", { class: "lede" }, [
      h("div", {}, [
        h("h1", {}, ["官方标价，按核验日入账"]),
        h("p", {}, ["国产模型放在前面。每一行都能点开来源。入口价是标准实时价里最低的常规档，分档、峰谷和限期价都留在模型页，不做成一个平均数。"]),
      ]),
      h("div", { class: "stats" }, [
        stat(String(state.data.models.length), "收录模型"),
        stat(String(state.data.vendors.length), "厂商"),
        stat(state.data.snapshot_date, "本份快照"),
      ]),
    ]),
    h("details", { class: "fx-line" }, [
      h("summary", {}, [`折算使用 ${fx.rate_date} 中间价：1 美元 = ${fx.rate} 元。与账单币种不同的数字不能对账。`]),
      h("p", {}, [fx.method_zh]),
    ]),
    h("div", { class: "toolbar" }, [
      h("label", { class: "search-label" }, [
        h("span", { class: "visually-hidden" }, ["搜索模型或厂商"]),
        h("input", {
        class: "search",
        type: "search",
        placeholder: "搜索模型或厂商",
        value: state.query,
        oninput: (event) => {
          state.query = event.target.value;
          state.restoreSearch = true;
          writeHash();
        },
      }),
      ]),
      h("div", { class: "segment", role: "group", "aria-label": "显示币种" }, [
        toggle("CNY", "人民币"),
        toggle("USD", "美元"),
      ]),
      h("div", { class: "segment", role: "group", "aria-label": "区域" }, [
        regionButton("all", "全部"),
        regionButton("cn", "国内"),
        regionButton("global", "海外"),
      ]),
    ]),
    h("div", { class: "toolbar" }, [
      h("div", { class: "chips" }, state.data.vendors.map((vendor) => h("button", {
        type: "button",
        "aria-pressed": state.vendors.has(vendor.id) ? "true" : "false",
        onclick: () => {
          if (state.vendors.has(vendor.id)) state.vendors.delete(vendor.id);
          else state.vendors.add(vendor.id);
          writeHash();
        },
      }, [vendor.name_zh]))),
      h("span", { class: "result-count", "aria-live": "polite" }, [`显示 ${visible.length} / ${state.data.models.length}`]),
    ]),
    h("div", { class: "table-wrap" }, [h("table", {}, [
      h("caption", { class: "visually-hidden" }, ["模型官方入口价。价格可按列排序。"]),
      h("thead", {}, [head]),
      body,
    ])]),
    cards,
    visible.length ? null : emptyState(),
  ]);
  const search = app.querySelector(".search");
  if (state.restoreSearch && search) {
    search.focus();
    const end = search.value.length;
    search.setSelectionRange(end, end);
    state.restoreSearch = false;
  }
}

function stat(value, label) {
  return h("div", { class: "stat" }, [h("b", {}, [value]), h("span", {}, [label])]);
}

function toggle(ccy, label) {
  return h("button", {
    type: "button",
    "aria-pressed": state.ccy === ccy ? "true" : "false",
    onclick: () => { state.ccy = ccy; writeHash(); },
  }, [label]);
}

function regionButton(region, label) {
  return h("button", {
    type: "button",
    "aria-pressed": state.region === region ? "true" : "false",
    onclick: () => { state.region = region; writeHash(); },
  }, [label]);
}

function sortBy(key) {
  if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
  else {
    state.sortKey = key;
    state.sortDir = key === "input" || key === "output" ? "asc" : "asc";
  }
  writeHash();
}

function renderModel(id) {
  const model = state.data.models.find((item) => item.id === id);
  if (!model) {
    mount([
      h("div", { class: "empty", role: "alert" }, [
        h("h2", {}, ["没有这个模型"]),
        h("p", {}, [`「${id}」不在本份快照里。可能是链接写错了，也可能这条价格没能在官方页上核到，所以没有入账。`]),
        h("a", { class: "text-button solid", href: "#/" }, ["返回价格表"]),
      ]),
    ]);
    return;
  }
  const vendor = vendorOf(model.vendor);
  const original = model.billing.currency;
  mount([
    h("p", {}, [h("a", { class: "back", href: "#/" }, ["← 返回价格表"])]),
    h("div", { class: "detail-top" }, [
      h("div", {}, [
        h("h1", {}, [model.display_name_zh]),
        h("p", {}, [vendor ? `${vendor.name_zh} · ${vendor.name_en}` : model.vendor, " · ", model.deployment_zh]),
      ]),
      statusTag(model.status),
    ]),
    h("div", { class: "facts" }, [
      fact("入口输入", money(model.billing.headline.input_per_1m, original)),
      fact("入口输出", money(model.billing.headline.output_per_1m, original)),
      fact("账单币种", original === "CNY" ? "人民币" : "美元"),
      fact("上下文", contextLabel(model)),
    ]),
    h("p", { class: "fx-line" }, [
      `${model.billing.headline.label_zh}。${model.billing.price_covers_zh}`,
      ` 折算：输入 ${money(model.conversion.cny_input_per_1m, "CNY")} / ${money(model.conversion.usd_input_per_1m, "USD")}，`,
      `输出 ${money(model.conversion.cny_output_per_1m, "CNY")} / ${money(model.conversion.usd_output_per_1m, "USD")}。`,
      "与账单币种不同的那个数不能拿去对账。",
    ]),
    model.billing.scheduled ? h("div", { class: "callout warn" }, [
      h("strong", {}, [`${model.billing.scheduled.effective_on} 起的页面标价`]),
      `输入 ${money(model.billing.scheduled.input_per_1m, original)}，输出 ${money(model.billing.scheduled.output_per_1m, original)}。${model.billing.scheduled.note_zh}`,
    ]) : null,
    model.billing.promotion ? h("div", { class: "callout warn" }, [
      h("strong", {}, [model.billing.promotion.label_zh]),
      model.billing.promotion.note_zh,
    ]) : null,
    h("h2", { class: "section-title" }, ["分档"]),
    tierTable(model),
    (model.billing.alternate_lists || []).length ? h("h2", { class: "section-title" }, ["厂商另行公布的币种"]) : null,
    ...(model.billing.alternate_lists || []).map((item) => h("div", { class: "callout" }, [
      h("strong", {}, [item.label_zh]),
      `输入 ${money(item.input_per_1m, item.currency)}，输出 ${money(item.output_per_1m, item.currency)}。${item.note_zh} `,
      h("a", { href: item.source_url, rel: "noreferrer" }, ["来源"]),
    ])),
    h("h2", { class: "section-title" }, ["价格历史"]),
    h("p", {}, [historyIntro(model)]),
    h("ol", { class: "timeline" }, model.history.map((row, index) => h("li", {}, [
      h("time", { datetime: row.effective_on || row.observed_at }, [historyWhen(row)]),
      h("div", {}, [historyLine(model.history, index)]),
      h("div", {}, [row.note_zh]),
    ]))),
    h("h2", { class: "section-title" }, ["核验"]),
    h("div", { class: "note" }, [
      h("p", {}, [model.notes_zh]),
      h("p", {}, [model.context.note_zh]),
      model.release ? h("p", {}, [`发布信息（${model.release.precision === "month" ? "精确到月" : "精确到日"}）：${model.release.note_zh}`]) : h("p", {}, ["已核验的页面没有给出可引用的发布日期，本条故意留空。"]),
      h("p", {}, ["页面位置：", model.source.section_zh || "未注明"]),
      h("p", {}, ["来源：", h("a", { href: model.source.url, rel: "noreferrer" }, [model.source.title_zh]), `，检索于 ${model.source.retrieved_at}，核验于 ${model.verified_at}。`]),
    ]),
  ]);
}

function historyIntro(model) {
  if (model.history.length <= 1) {
    return "这条目前只有一次核验。没有更早的官方数字，就不画折线，也不回填。";
  }
  return "下面每一条都来自官方页面上写明的单价。更早的那条如果标了生效日，日期是厂商公告的日期，检索日另写在说明里。";
}

function historyWhen(row) {
  if (row.effective_on && row.effective_on !== row.observed_at) {
    return `${row.effective_on} 生效 · ${row.retrieved_at || row.observed_at} 检索`;
  }
  return row.observed_at;
}

function historyLine(rows, index) {
  const row = rows[index];
  const currency = row.billing.currency;
  const input = money(row.billing.headline.input_per_1m, currency);
  const output = money(row.billing.headline.output_per_1m, currency);
  const base = `${kindLabel(row.kind)} · 输入 ${input} · 输出 ${output}`;
  if (index === 0) return base;
  const previous = rows[index - 1].billing.headline;
  const inputMove = moveWord(previous.input_per_1m, row.billing.headline.input_per_1m);
  const outputMove = moveWord(previous.output_per_1m, row.billing.headline.output_per_1m);
  return `${base} · 相对上一条，输入${inputMove}，输出${outputMove}`;
}

function moveWord(before, after) {
  const left = Number(before);
  const right = Number(after);
  if (right < left) return "下调";
  if (right > left) return "上调";
  return "未变";
}

function fact(label, value) {
  return h("div", { class: "fact" }, [h("span", {}, [label]), value]);
}

function kindLabel(kind) {
  return {
    initial: "首次建档",
    historical: "公告里的更早标价",
    price_change: "价格变化",
    correction: "勘误追加",
  }[kind] || kind;
}

function tierTable(model) {
  const tiers = model.billing.tiers || [];
  const currency = model.billing.currency;
  const rows = tiers.map((tier) => h("tr", {}, [
    h("td", {}, [tier.label_zh, tier.is_headline ? h("span", { class: "sub" }, ["入口档"]) : ""]),
    h("td", {}, [tier.applies_when_zh || ""]),
    h("td", { class: "num" }, [money(tier.input_per_1m, currency)]),
    h("td", { class: "num" }, [money(tier.output_per_1m, currency)]),
    h("td", { class: "num" }, [tier.cache_hit_input_per_1m ? money(tier.cache_hit_input_per_1m, currency) : "—"]),
    h("td", { class: "num" }, [tier.list_input_per_1m ? `${money(tier.list_input_per_1m, currency)} / ${money(tier.list_output_per_1m, currency)}` : "—"]),
  ]));
  return h("div", { class: "table-wrap", style: "display:block" }, [
    h("table", {}, [
      h("thead", {}, [h("tr", {}, ["档位", "适用条件", "输入", "输出", "缓存命中输入", "原价（输入/输出）"].map((label) => h("th", {}, [label])))]),
      h("tbody", {}, rows),
    ]),
  ]);
}

function render() {
  if (!state.data) return;
  const modelId = readHash();
  document.title = modelId ? `${modelId} · 大模型 API 价格账本` : "大模型 API 价格账本";
  if (modelId) renderModel(modelId);
  else renderCatalog();
}

fetch("data.json")
  .then((response) => {
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  })
  .then((data) => {
    state.data = data;
    render();
  })
  .catch(() => {
    mount([
      h("div", { class: "empty", role: "alert" }, [
        h("h2", {}, ["账本没有载入"]),
        h("p", {}, ["浏览器没有读到 data.json。静态站需要先在仓库根目录运行 ai-model-ledger build，再用本地服务器打开 site/，不要直接双击 HTML。"]),
        h("button", { type: "button", class: "text-button solid", onclick: () => location.reload() }, ["重试"]),
      ]),
    ]);
  });

window.addEventListener("hashchange", render);
