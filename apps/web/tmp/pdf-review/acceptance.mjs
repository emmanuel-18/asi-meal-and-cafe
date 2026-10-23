import { readFileSync, writeFileSync } from 'node:fs';
import { downloadReport } from '../../src/lib/report-export.ts';

globalThis.fetch = async () => new Response(readFileSync(new URL('../../public/fonts/OpenSans-Regular.ttf', import.meta.url)));
const period = { start: '2040-02-01', end: '2040-02-29' };
const categories = ['vegetable', 'non_vegetable', 'extra_rice'];
const prices = [50, 75, 15];
const items = Array.from({length: 36}, (_, i) => {
  const category = i % 3, quantity = i % 4 + 1, price = prices[category];
  return { item_name: `Synthetic ${category === 0 ? 'Vegetable' : category === 1 ? 'Non-Vegetable' : 'Extra Rice'} ${String(i + 1).padStart(2, '0')} with a Long Recorded Dish Name for Wrapping Review and Additional Descriptive Words to Verify Multiple Lines and a Further Extended Synthetic Description for Layout Testing`, category: categories[category], unit_price: price.toFixed(2), quantity, amount: (price * quantity).toFixed(2) };
});
const total = items.reduce((sum, item) => sum + Number(item.amount), 0);
const categoryTotals = categories.map(category => { const selected = items.filter(item => item.category === category); return { category, quantity: selected.reduce((sum, item) => sum + item.quantity, 0), amount: selected.reduce((sum, item) => sum + Number(item.amount), 0).toFixed(2) }; });
const orders = Array.from({length: 45}, (_, i) => ({ order_id: i + 1, service_date: '2040-02-20', employee_number: String(i + 1).padStart(6, '0'), customer_name: 'Synthetic Alexandra Montserrat de la Cruz Example', position: 'Synthetic Operations Specialist', campaign: 'Synthetic International Customer Support Campaign Extended Name', line_of_business: 'Synthetic Service', sd_amount: '10.00' }));
const payments = [{category:'cash',amount:(total-700).toFixed(2)}, {category:'gcash',amount:'200.00'}, {category:'sd',amount:'450.00'}, {category:'incentive',amount:'0.00'}, {category:'finance',amount:'50.00'}];
const bundle = { sales: {period, recognized_sales: total.toFixed(2), received_order_count:45, meal_quantity: categoryTotals[0].quantity + categoryTotals[1].quantity, item_quantity: items.reduce((sum, item) => sum + item.quantity, 0), categories:categoryTotals, items}, payments:{period,total:total.toFixed(2),totals:payments}, salary_deduction:{period,total:'450.00',employees:[],orders} };
const pdf = await downloadReport(bundle, 'monthly', 'pdf');
writeFileSync(new URL('./populated-acceptance.pdf', import.meta.url), Buffer.from(pdf.document.output('arraybuffer')));
let blob;
URL.createObjectURL = value => { blob = value; return 'blob:synthetic'; };
URL.revokeObjectURL = () => {};
globalThis.document = { createElement: () => ({click() {}}) };
await downloadReport(bundle, 'monthly', 'excel');
writeFileSync(new URL('./populated-acceptance.xlsx', import.meta.url), Buffer.from(await blob.arrayBuffer()));
console.log(JSON.stringify({pages: pdf.document.getNumberOfPages(), items:items.length, recognized_sales:total, categoryTotals, payments, sd_orders:orders.length}));
