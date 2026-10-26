/** Generate acceptance artifacts from in-memory fixtures only. */
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { buildPremiumExcel } from "../src/lib/premium-excel.ts";
import { premiumFixture } from "../tests/fixtures/premium-report.mjs";

if (!process.argv[2]) throw new Error("Usage: node scripts/generate-premium-excel.mjs <new-artifact-directory>");
const folder = resolve(process.argv[2]);
await mkdir(folder, { recursive: true });
const manifest = [];
for (const [name, mode, options] of [
  ["daily", "daily", { start: "2026-10-23", historical: true }],
  ["weekly", "weekly", { days: 7, start: "2026-10-19", historical: true }],
  ["monthly", "monthly", { days: 31, start: "2026-10-01" }],
  ["custom-32-days", "custom", { days: 32, historical: true }],
  ["long-text", "custom", { days: 8, name: "Synthetic ñ 長 employee with a long recorded name ".repeat(5) }],
  ["empty", "daily", { empty: true }],
]) {
  const bundle = premiumFixture(options);
  const path = resolve(folder, `${name}.xlsx`);
  await writeFile(path, await buildPremiumExcel(bundle, mode), { flag: "wx" });
  manifest.push({ path, days: bundle.export_details.daily.length, total: bundle.sales.recognized_sales, sd: bundle.salary_deduction.total });
}
await writeFile(resolve(folder, "manifest.json"), JSON.stringify(manifest, null, 2), { flag: "wx" });
console.log(JSON.stringify(manifest, null, 2));
