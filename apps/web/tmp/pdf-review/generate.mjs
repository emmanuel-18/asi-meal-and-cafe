import { readFileSync, writeFileSync } from 'node:fs';
import { downloadReport } from '../../src/lib/report-export.ts';

globalThis.fetch = async () => new Response(readFileSync(new URL('../../public/fonts/OpenSans-Regular.ttf', import.meta.url)));
const period = { start: '2040-02-01', end: '2040-02-29' };
const orders = Array.from({length: 45}, (_, i) => ({ order_id: i + 1, service_date: '2040-02-20', employee_number: `SYN-${String(i + 1).padStart(4, '0')}`, customer_name: 'Synthetic Alexandra Montserrat de la Cruz Example', position: 'Synthetic Operations Specialist', campaign: 'Synthetic International Customer Support Campaign Extended Name', line_of_business: 'Synthetic Service', sd_amount: '10.00' }));
const bundle = {
  sales: { period, recognized_sales: '1000.00', received_order_count: 45, meal_quantity: 45, item_quantity: 50, categories: [{category:'vegetable', quantity:20, amount:'400.00'}, {category:'non_vegetable', quantity:25, amount:'600.00'}, {category:'extra_rice', quantity:5, amount:'0.00'}], items: [] },
  payments: {period, total:'1000.00', totals:[{category:'cash',amount:'300.00'}, {category:'gcash',amount:'200.00'}, {category:'sd',amount:'450.00'}, {category:'incentive',amount:'0.00'}, {category:'finance',amount:'50.00'}]},
  salary_deduction: {period, total:'450.00', employees:[], orders}
};
const result = await downloadReport(bundle, 'monthly', 'pdf');
writeFileSync(new URL('./synthetic-report.pdf', import.meta.url), Buffer.from(result.document.output('arraybuffer')));
console.log(`Pages: ${result.document.getNumberOfPages()}`);
