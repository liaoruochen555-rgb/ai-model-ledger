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

const NICKNAMES = {
  deepseek: "deepseek ds 深度求索",
  qwen: "qwen 千问 通义 通义千问 tongyi",
  moonshot: "kimi moonshot 月之暗面",
  zhipu: "glm 智谱 zhipu bigmodel",
  openai: "gpt openai chatgpt",
  anthropic: "claude anthropic",
  google: "gemini google 谷歌",
  xai: "grok xai",
};

const CHIP = {
  deepseek: "DeepSeek",
  qwen: "千问",
  moonshot: "Kimi",
  zhipu: "智谱",
  openai: "GPT",
  anthropic: "Claude",
  google: "Gemini",
  xai: "Grok",
};

function trimNumber(value) {
  const text = String(value);
  if (!text.includes(".")) return text;
  return text.replace(/0+$/, "").replace(/\.$/, "");
}

function displayPlaces(exact) {
  const amount = Math.abs(Number(exact));
  if (!Number.isFinite(amount) || amount >= 0.1) return 2;
  if (amount >= 0.01) return 3;
  return 4;
}

function roundHalfUp(value, places) {
  const text = String(value).trim();
  const negative = text.startsWith("-");
  const raw = negative ? text.slice(1) : text;
  const [whole, frac = ""] = raw.split(".");
  const padded = (frac + "0".repeat(places + 1)).slice(0, places + 1);
  let body = BigInt((whole || "0") + padded.slice(0, places));
  if (padded[places] >= "5") body += 1n;
  const digits = body.toString().padStart(places + 1, "0");
  const head = digits.slice(0, digits.length - places) || "0";
  const tail = digits.slice(-places);
  const out = places ? `${head}.${tail}` : head;
  return negative ? `-${out}` : out;
}

function shownFigure(exact, isConverted) {
  return isConverted ? roundHalfUp(exact, displayPlaces(exact)) : trimNumber(exact);
}

function money(value, currency) {
  const amount = trimNumber(value);
  return currency === "CNY" ? `¥${amount}` : `$${amount}`;
}

function priceLabel(exact, currency, isConverted) {
  const symbol = currency === "CNY" ? "¥" : "$";
  const figure = shownFigure(exact, isConverted);
  return {
    text: `${symbol}${figure}`,
    title: isConverted
      ? `精确折算 ${symbol}${trimNumber(exact)}。不是厂商账单金额。`
      : "厂商账单币种",
  };
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

function figureCell(text, title, isConverted) {
  return h("td", { class: "num", title: title || undefined }, [
    h("span", { class: "figure" }, [text]),
    h("span", { class: "mark" }, [isConverted ? "折算" : ""]),
  ]);
}

function priceCell(model, side) {
  const exact = shownAmount(model, side);
  const isConverted = converted(model);
  const label = priceLabel(exact, state.ccy, isConverted);
  return figureCell(label.text, label.title, isConverted);
}

function cacheExact(model) {
  const raw = model.billing.headline.cache_hit_input_per_1m;
  if (!raw) return null;
  if (model.billing.currency === state.ccy) return raw;
  const rate = state.data.fx.rate;
  const negative = false;
  const product = model.billing.currency === "USD"
    ? mulDiv(raw, rate, "1")
    : mulDiv(raw, "1", rate);
  return product;
}

function mulDiv(amount, numer, denom) {
  const scale = 1000000n;
  const toInt = (text) => {
    const [whole, frac = ""] = String(text).split(".");
    const padded = (frac + "000000").slice(0, 6);
    return BigInt(whole || "0") * scale + BigInt(padded);
  };
  const value = (toInt(amount) * toInt(numer)) / toInt(denom);
  const whole = value / scale;
  const frac = (value % scale).toString().padStart(6, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : `${whole}`;
}

function cacheCell(model) {
  const exact = cacheExact(model);
  if (!exact) return figureCell("—", "", false);
  const isConverted = converted(model);
  const label = priceLabel(exact, state.ccy, isConverted);
  return figureCell(label.text, label.title, isConverted);
}

function matches(model) {
  if (state.region !== "all" && model.region !== state.region) return false;
  if (state.status !== "all" && model.status !== state.status) return false;
  if (state.vendors.size && !state.vendors.has(model.vendor)) return false;
  const terms = state.query.toLowerCase().trim()
    .split(/[\s]+|(?<=[\u4e00-\u9fff])(?=[a-z0-9])|(?<=[a-z0-9])(?=[\u4e00-\u9fff])/)
    .filter(Boolean);
  if (!terms.length) return true;
  const vendor = vendorOf(model.vendor);
  const haystack = [
    model.display_name_zh,
    model.display_name_en,
    model.id,
    model.api_model_id,
    model.family,
    vendor && vendor.name_zh,
    vendor && vendor.name_en,
    NICKNAMES[model.vendor],
    CHIP[model.vendor],
  ].join(" ").toLowerCase();
  return terms.every((term) => haystack.includes(term));
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
    else {
      const statusRank = { active: 0, preview: 1, retiring: 2, deprecated: 3 };
      result = (vendorOrder[a.vendor] || 0) - (vendorOrder[b.vendor] || 0)
        || (statusRank[a.status] ?? 9) - (statusRank[b.status] ?? 9)
        || a.display_name_zh.localeCompare(b.display_name_zh, "zh");
    }
    return result * direction;
  });
}

function filterQuery() {
  const params = new URLSearchParams();
  if (state.ccy !== "CNY") params.set("ccy", state.ccy);
  if (state.region !== "all") params.set("region", state.region);
  if (state.status !== "all") params.set("status", state.status);
  if (state.query) params.set("q", state.query);
  if (state.vendors.size) params.set("vendor", [...state.vendors].join(","));
  if (state.sortKey !== "vendor") params.set("sort", state.sortKey);
  if (state.sortDir !== "asc") params.set("dir", state.sortDir);
  return params.toString();
}

function writeHash() {
  const query = filterQuery();
  const next = query ? `#/?${query}` : "#/";
  if (location.hash !== next) location.hash = next;
}

function modelHash(id) {
  const query = filterQuery();
  const path = `#/m/${encodeURIComponent(id)}`;
  return query ? `${path}?${query}` : path;
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
  if (status === "active") return null;
  return h("span", { class: "status" }, [STATUS[status] || status]);
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
    h("h2", {}, ["没有匹配的模型"]),
    h("p", {}, ["当前筛选下没有条目。"]),
    h("button", { type: "button", class: "linkish", onclick: clearFilters }, ["清除筛选"]),
  ]);
}

function mount(nodes) {
  app.replaceChildren(...nodes.filter((node) => node != null && node !== false));
}

function renderCatalog() {
  const fx = state.data.fx;
  const visible = sorted(state.data.models.filter(matches));
  const columns = [
    ["name", "模型"],
    ["input", "输入"],
    ["output", "输出"],
  ];
  const head = h("tr", {}, columns.map(([key, label]) => {
    const props = {};
    if (state.sortKey === key) props["aria-sort"] = state.sortDir === "asc" ? "ascending" : "descending";
    const thClass = key === "input" || key === "output" ? "num" : "";
    const button = h("button", { type: "button", onclick: () => sortBy(key) }, [label]);
    if (key === "name") return h("th", { class: thClass, ...props }, [button]);
    return h("th", { class: thClass, ...props }, [button, h("span", { class: "mark", "aria-hidden": "true" }, [""])]);
  }).concat([
    h("th", { class: "num" }, ["缓存", h("span", { class: "mark", "aria-hidden": "true" }, [""])]),
    h("th", {}, ["厂商"]),
  ]));

  const body = h("tbody", {}, visible.map((model) => {
    const vendor = vendorOf(model.vendor);
    const open = () => { location.hash = modelHash(model.id); };
    return h("tr", {
      class: model.status === "active" ? "" : "is-quiet",
      tabindex: "0",
      onclick: open,
      onkeydown: (event) => {
        if (event.key === "Enter") open();
      },
    }, [
      h("td", { class: "model-col", title: model.id }, [
        h("a", { class: "name", href: modelHash(model.id) }, [model.display_name_zh]),
        h("span", { class: "sub" }, [model.id, model.status === "active" ? "" : ` · ${STATUS[model.status] || model.status}`]),
      ]),
      priceCell(model, "input"),
      priceCell(model, "output"),
      cacheCell(model),
      h("td", {}, [CHIP[model.vendor] || (vendor ? vendor.name_zh : model.vendor)]),
    ]);
  }));

  mount([
    h("header", { class: "intro" }, [
      h("p", { class: "meta" }, [
        `${state.data.models.length} 个模型 · ${state.ccy === "CNY" ? "人民币" : "美元"} · 每百万 tokens · 中间价 ${fx.rate_date}：1 美元 = ${fx.rate} 元`,
      ]),
      h("p", { class: "legend" }, ["没写「折算」的是账单价。写了的是中间价换算，不能对账。点模型名可看精确值和来源。"]),
    ]),
    h("div", { class: "filters" }, [
    h("div", { class: "toolbar" }, [
      h("label", { class: "search-label" }, [
        h("span", { class: "visually-hidden" }, ["搜索模型或厂商"]),
        h("input", {
          class: "search",
          type: "search",
          enterkeyhint: "search",
          placeholder: "搜千问、DeepSeek、Kimi、Claude、GPT",
          value: state.query,
          oninput: (event) => {
            state.query = event.target.value;
            state.caret = event.target.selectionStart;
            state.restoreSearch = true;
            writeHash();
          },
        }),
      ]),
      h("div", { class: "choices", role: "group", "aria-label": "显示币种" }, [
        toggle("CNY", "人民币"),
        toggle("USD", "美元"),
      ]),
      h("div", { class: "choices", role: "group", "aria-label": "区域" }, [
        regionButton("cn", "国内"),
        regionButton("global", "海外"),
        regionButton("all", "全部"),
      ]),
    ]),
    h("div", { class: "toolbar" }, [
      h("div", { class: "choices vendors" }, state.data.vendors.map((vendor) => h("button", {
        type: "button",
        title: vendor.name_zh,
        "aria-pressed": state.vendors.has(vendor.id) ? "true" : "false",
        onclick: () => {
          if (state.vendors.has(vendor.id)) state.vendors.delete(vendor.id);
          else state.vendors.add(vendor.id);
          writeHash();
        },
      }, [CHIP[vendor.id] || vendor.name_zh]))),
      h("span", { class: "result-count", "aria-live": "polite" }, [`${visible.length} / ${state.data.models.length}`]),
    ]),
    ]),
    h("div", { class: "table-wrap catalog" }, [
      h("table", {}, [
        h("caption", { class: "visually-hidden" }, ["模型官方入口价。价格可按列排序。"]),
        h("thead", {}, [head]),
        body,
      ]),
      visible.length ? null : emptyState(),
    ]),
  ]);
  const search = app.querySelector(".search");
  if (state.restoreSearch && search) {
    search.focus();
    const caret = Number.isInteger(state.caret) ? state.caret : search.value.length;
    search.setSelectionRange(caret, caret);
    state.restoreSearch = false;
  }
  const filters = app.querySelector(".filters");
  document.documentElement.style.setProperty("--filters-h", filters ? `${filters.offsetHeight}px` : "0px");
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
        h("a", { href: "#/" }, ["返回价格表"]),
      ]),
    ]);
    return;
  }
  const vendor = vendorOf(model.vendor);
  const original = model.billing.currency;
  const billName = original === "CNY" ? "人民币" : "美元";
  const cnyIn = priceLabel(model.conversion.cny_input_per_1m, "CNY", original !== "CNY");
  const cnyOut = priceLabel(model.conversion.cny_output_per_1m, "CNY", original !== "CNY");
  const cache = model.billing.headline.cache_hit_input_per_1m;
  mount([
    h("p", {}, [h("a", { class: "back", href: filterQuery() ? `#/?${filterQuery()}` : "#/" }, ["返回价格表"])]),
    h("h1", { class: "model" }, [model.display_name_zh, statusTag(model.status)]),
    h("p", { class: "byline" }, [
      (CHIP[model.vendor] || (vendor ? vendor.name_zh : model.vendor)),
      " · ",
      model.api_model_id,
      " · ",
      h("a", { href: model.source.url, target: "_blank", rel: "noreferrer noopener" }, ["官方标价页"]),
    ]),
    h("dl", { class: "keyline" }, [
      fact(original === "CNY" ? "输入" : "输入（账单）", money(model.billing.headline.input_per_1m, original)),
      fact(original === "CNY" ? "输出" : "输出（账单）", money(model.billing.headline.output_per_1m, original)),
      fact("缓存命中", cache ? money(cache, original) : "—"),
      fact("账单币种", billName),
    ]),
    h("p", { class: "legend" }, [
      original === "CNY"
        ? `上面是人民币账单价。折成美元约 ${priceLabel(model.conversion.usd_input_per_1m, "USD", true).text} / ${priceLabel(model.conversion.usd_output_per_1m, "USD", true).text}，不能对账。`
        : `上面是美元账单价。表上的人民币是折算：输入 ${cnyIn.text}、输出 ${cnyOut.text}。精确值 ${money(model.conversion.cny_input_per_1m, "CNY")} / ${money(model.conversion.cny_output_per_1m, "CNY")}。`,
      ` ${model.billing.headline.label_zh}。`,
    ]),
    (model.billing.tiers || []).length > 1 ? h("h2", { class: "section-title" }, ["分档"]) : null,
    (model.billing.tiers || []).length > 1 ? tierTable(model) : null,
    model.billing.scheduled ? h("p", { class: "aside" }, [
      `${model.billing.scheduled.effective_on} 起，账单价改为输入 ${money(model.billing.scheduled.input_per_1m, original)}、输出 ${money(model.billing.scheduled.output_per_1m, original)}。`,
    ]) : null,
    model.billing.promotion ? h("p", { class: "aside" }, [
      `${model.billing.promotion.label_zh}。`,
    ]) : null,
    h("details", { class: "more" }, [
      h("summary", {}, ["说明、历史和核验"]),
      h("div", { class: "note" }, [
        h("p", {}, [model.billing.price_covers_zh]),
        h("p", {}, [model.notes_zh]),
        h("p", {}, [`上下文 ${contextLabel(model)}。${model.context.note_zh}`]),
        model.release ? h("p", {}, [model.release.note_zh]) : null,
        h("p", {}, ["页面位置：", model.source.section_zh || "未注明"]),
        h("p", {}, ["核验 ", model.verified_at, "。", model.deployment_zh]),
        ...(model.billing.alternate_lists || []).map((item) => h("p", {}, [
          `${item.label_zh}：输入 ${money(item.input_per_1m, item.currency)}，输出 ${money(item.output_per_1m, item.currency)}。`,
          h("a", { href: item.source_url, target: "_blank", rel: "noreferrer noopener" }, ["另一张官方价目"]),
        ])),
        h("p", {}, [historyIntro(model)]),
        historyTable(model),
      ]),
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
  return h("div", {}, [h("dt", {}, [label]), h("dd", {}, [value])]);
}

function historyTable(model) {
  const rows = model.history.map((row, index) => {
    const currency = row.billing.currency;
    return h("tr", {}, [
      h("td", {}, [historyWhen(row)]),
      h("td", {}, [kindLabel(row.kind), index ? `，输入${moveWord(model.history[index - 1].billing.headline.input_per_1m, row.billing.headline.input_per_1m)}，输出${moveWord(model.history[index - 1].billing.headline.output_per_1m, row.billing.headline.output_per_1m)}` : ""]),
      h("td", { class: "num" }, [money(row.billing.headline.input_per_1m, currency)]),
      h("td", { class: "num" }, [money(row.billing.headline.output_per_1m, currency)]),
      h("td", {}, [row.note_zh]),
    ]);
  });
  return h("div", { class: "table-wrap" }, [
    h("table", {}, [
      h("thead", {}, [h("tr", {}, ["日期", "记录", "输入", "输出", "说明"].map((label) => h("th", {}, [label])))]),
      h("tbody", {}, rows),
    ]),
  ]);
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
  return h("div", { class: "table-wrap" }, [
    h("table", {}, [
      h("thead", {}, [h("tr", {}, ["档位", "适用条件", "输入", "输出", "缓存命中输入", "原价（输入/输出）"].map((label) => h("th", {}, [label])))]),
      h("tbody", {}, rows),
    ]),
  ]);
}

function render() {
  if (!state.data) return;
  const modelId = readHash();
  document.body.classList.toggle("sheet", !modelId);
  const opened = modelId && state.data.models.find((item) => item.id === modelId);
  document.title = opened ? `${opened.display_name_zh} · 大模型 API 价格账本` : "大模型 API 价格账本";
  if (modelId) {
    renderModel(modelId);
    document.documentElement.style.setProperty("--filters-h", "0px");
  } else renderCatalog();
}

window.addEventListener("resize", () => {
  const filters = app.querySelector(".filters");
  document.documentElement.style.setProperty("--filters-h", filters ? `${filters.offsetHeight}px` : "0px");
});

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
