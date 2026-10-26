/** Reconciled synthetic in-memory reporting contract; no API or database. */
export function premiumFixture({ days = 1, start = "2028-02-01", empty = false, name = "Synthetic employee ñ", historical = false } = {}) {
  const format = cents => `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
  const cents = value => BigInt(value.replace(".", ""));
  const dates = Array.from({ length: days }, (_, i) => new Date(Date.parse(start) + i * 86400000).toISOString().slice(0, 10));
  const period = { start, end: dates.at(-1) };
  const methods = ["cash", "gcash", "sd", "incentive", "finance"];
  const menus = [
    { menu_id: 1, offerings: [{ menu_item_id: 1, dish_id: 1, item_name: "Synthetic vegetable", category: "vegetable", unit_price: "50.00" }, { menu_item_id: 2, dish_id: 2, item_name: "Extra Rice", category: "extra_rice", unit_price: "15.00" }] },
    { menu_id: 2, offerings: [{ menu_item_id: 3, dish_id: 3, item_name: "Synthetic non-vegetable", category: "non_vegetable", unit_price: "75.00" }, { menu_item_id: 4, dish_id: 2, item_name: "Extra Rice", category: "extra_rice", unit_price: "15.00" }] },
  ];
  const orders = [];
  let lineId = 1;
  function add(dayIndex, visitor = false, noSD = false) {
    const menu = menus[dayIndex % 2], id = orders.length + 1;
    const items = menu.offerings.map((o, i) => {
      const price = historical && dayIndex === 0 && i === 0 ? "50.01" : o.unit_price;
      return { order_item_id: lineId++, line_number: i + 1, source_menu_item_id: o.menu_item_id, item_name: historical && dayIndex === 0 && i === 0 ? "Historical renamed vegetable" : o.item_name, category: o.category, unit_price: price, quantity: 1, line_total: price };
    });
    const total = items.reduce((sum, i) => sum + cents(i.line_total), 0n);
    const allocations = visitor ? [{ category: "finance", amount: format(total) }] : noSD ? [{ category: "cash", amount: format(total) }] :
      dayIndex % 4 === 0 ? [{ category: "cash", amount: format(total - 3000n) }, { category: "sd", amount: "30.00" }] :
      [{ category: ["cash", "gcash", "incentive", "finance"][dayIndex % 4], amount: format(total) }];
    orders.push({ order_id: id, service_date: dates[dayIndex], menu_id: menu.menu_id, customer_type: visitor ? "visitor" : "employee",
      employee_number: visitor ? null : noSD ? "00009999" : "00001234", visitor_id: visitor ? 1 : null,
      customer_name: visitor ? "Synthetic guest" : noSD ? "Synthetic employee without SD" : name,
      position: visitor ? null : "Synthetic position", campaign: visitor ? null : dayIndex > 3 ? "Synthetic changed campaign" : "Synthetic original campaign",
      line_of_business: visitor ? null : "Synthetic LOB", items, allocations, total: format(total) });
  }
  if (!empty) { dates.forEach((_, i) => add(i)); add(days - 1, true); add(days - 1, false, true); }
  const sdOrders = orders.filter(o => o.allocations.some(a => a.category === "sd")).map(o => ({
    order_id: o.order_id, service_date: o.service_date, employee_number: o.employee_number, customer_name: o.customer_name,
    position: o.position, campaign: o.campaign, line_of_business: o.line_of_business, sd_amount: o.allocations.find(a => a.category === "sd").amount,
  }));
  const total = format(orders.reduce((s, o) => s + cents(o.total), 0n));
  const payments = data => methods.map(category => ({ category, amount: format(data.flatMap(o => o.allocations).filter(a => a.category === category).reduce((s, a) => s + cents(a.amount), 0n)) }));
  const items = new Map();
  for (const i of orders.flatMap(o => o.items)) {
    const key = JSON.stringify([i.source_menu_item_id, i.item_name, i.category, i.unit_price]);
    const previous = items.get(key) ?? { source_menu_item_id: i.source_menu_item_id, item_name: i.item_name, category: i.category, unit_price: i.unit_price, quantity: 0, amount: "0.00" };
    items.set(key, { ...previous, quantity: previous.quantity + i.quantity, amount: format(cents(previous.amount) + cents(i.line_total)) });
  }
  const campaigns = new Map();
  for (const o of sdOrders) campaigns.set(o.campaign, (campaigns.get(o.campaign) ?? 0n) + cents(o.sd_amount));
  return { sales: { period, recognized_sales: total, received_order_count: orders.length,
    meal_quantity: orders.flatMap(o => o.items).filter(i => i.category !== "extra_rice").reduce((s, i) => s + i.quantity, 0), item_quantity: orders.flatMap(o => o.items).reduce((s, i) => s + i.quantity, 0), items: [...items.values()],
    categories: ["vegetable", "non_vegetable", "extra_rice"].map(category => ({ category, quantity: [...items.values()].filter(i => i.category === category).reduce((s, i) => s + i.quantity, 0), amount: format([...items.values()].filter(i => i.category === category).reduce((s, i) => s + cents(i.amount), 0n)) })) },
    payments: { period, totals: payments(orders), total },
    salary_deduction: { period, orders: sdOrders, total: format(sdOrders.reduce((s, o) => s + cents(o.sd_amount), 0n)), employees: sdOrders.length ? [{ employee_number: "00001234", order_count: sdOrders.length, sd_amount: format(sdOrders.reduce((s, o) => s + cents(o.sd_amount), 0n)) }] : [] },
    export_details: { period, orders, menus: menus.filter(m => dates.some((_, i) => i % 2 + 1 === m.menu_id)),
      menu_dates: dates.map((service_date, i) => ({ service_date, assigned_menu_id: i % 2 + 1, recorded_menu_ids: [...new Set(orders.filter(o => o.service_date === service_date).map(o => o.menu_id))] })),
      daily: dates.map(service_date => { const rows = orders.filter(o => o.service_date === service_date); const total = format(rows.reduce((s, o) => s + cents(o.total), 0n)); return { service_date, recognized_sales: total, received_order_count: rows.length, meal_quantity: rows.length, item_quantity: rows.length * 2, payments: payments(rows), allocated_total: total, allocation_difference: "0.00" }; }),
      sd_campaigns: [...campaigns].map(([campaign, amount]) => ({ campaign, sd_amount: format(amount) })),
    },
  };
}
