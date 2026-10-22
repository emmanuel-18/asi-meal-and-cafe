import type { Employee, RequestApi, Role } from "./api.ts";

export const pageSize = 20;
export const maxUpload = 8 * 1024 * 1024;
export const canImport = (role: Role) => role === "admin" || role === "super_admin";

export function fileError(file: Pick<File, "name" | "size"> | null): string {
  if (!file) return "Select a CSV file.";
  if (!/\.csv$/i.test(file.name)) return "Select a file with a .csv extension.";
  if (file.size > maxUpload) return "The file must be 8 MiB or smaller.";
  return "";
}

export function searchEmployees(request: RequestApi, query: string, page: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ q: query.trim(), limit: String(pageSize), offset: String(page * pageSize) });
  return request<Employee[]>(`/api/employees?${params}`, { signal });
}

export type ImportResult = { import_id: number; status: "completed" | "failed"; total_rows: number;
  inserted_rows: number; updated_rows: number; unchanged_rows: number; rejected_rows: number;
  file_error_code: string | null; errors: { row_number: number; issues: { field: string; code: string }[] }[]; errors_truncated: boolean };

export async function uploadEmployees(request: RequestApi, file: File): Promise<ImportResult> {
  const error = fileError(file);
  if (error) throw new Error(error);
  const result = await request<ImportResult>("/api/employees/import", { method: "POST", csv: file });
  if (!result || !["completed", "failed"].includes(result.status) || ![result.import_id, result.total_rows, result.inserted_rows,
    result.updated_rows, result.unchanged_rows, result.rejected_rows].every(value => Number.isSafeInteger(value) && value >= 0) ||
    !Array.isArray(result.errors) || typeof result.errors_truncated !== "boolean") throw new Error("The import result could not be confirmed.");
  return result;
}

export async function submitImport(request: RequestApi, file: File, guard: { current: boolean }, onCompleted: () => void) {
  if (guard.current) return null;
  guard.current = true;
  try {
    const result = await uploadEmployees(request, file);
    if (result.status === "completed") onCompleted();
    return result;
  } finally { guard.current = false; }
}

const fields: Record<string, string> = { employee_number: "Employee number", full_name: "Full name", position: "Position", campaign: "Campaign", line_of_business: "Line of business", record: "Record" };
const issues: Record<string, string> = { REQUIRED: "is required", INVALID_TEXT: "contains invalid text", SURROUNDING_WHITESPACE: "has surrounding whitespace", DUPLICATE_EMPLOYEE_NUMBER: "is duplicated", ROW_WIDTH: "has the wrong number of columns", BATCH_NOT_APPLIED: "was not applied because the batch failed" };
const fileErrors: Record<string, string> = { INVALID_ENCODING: "The file must use UTF-8 encoding.", EMPTY_EXPORT: "The export contains no data records.", INVALID_HEADERS: "The CSV headers do not match the required export.", INVALID_CSV: "The CSV structure is invalid.", VALIDATION_FAILED: "Some records failed validation.", APPLY_FAILED: "The import could not be applied.", AUTHORIZATION_CHANGED: "Authorization changed during the import." };
export const fileErrorMessage = (code: string | null) => code ? fileErrors[code] ?? "The import failed." : "";
export function issueMessage(issue: { field: string; code: string }): string {
  return `${fields[issue?.field] ?? "Record"} ${issues[issue?.code] ?? "has a validation error"}.`;
}
