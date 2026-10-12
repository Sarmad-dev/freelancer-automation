import type { BadgeTone } from "@freelancer-os/ui";
import type { ImportJobOut, ImportMapping, ImportPreview } from "./lead-model";

export type FieldKey = keyof ImportMapping;
/** What the wizard edits: field -> the CSV column's header text (or "" / null / missing = not imported). */
export type Mapping = Partial<Record<FieldKey, string | null>>;
export type Strategy = "skip" | "update";
export type RowAction = ImportPreview["rows"][number]["action"];

/** 2 MB, as the API counts it (2,000,000 characters). UTF-8 is at least one byte per character. */
export const MAX_BYTES = 2_000_000;
export const MAX_ROWS = 5_000;
export const MAX_COLUMNS = 60;

export interface FieldDef {
  key: FieldKey;
  label: string;
  hint?: string;
}

export const FIELD_GROUPS: readonly { id: string; label: string; fields: readonly FieldDef[] }[] = [
  {
    id: "contact",
    label: "The person",
    fields: [
      { key: "name", label: "Contact name", hint: "Full name." },
      { key: "email", label: "Email" },
      { key: "role", label: "Job title", hint: "The person's role, e.g. “Head of Design”." },
      { key: "phone", label: "Phone" },
    ],
  },
  {
    id: "company",
    label: "Their company",
    fields: [
      { key: "company", label: "Company" },
      { key: "website", label: "Company website" },
      { key: "company_size", label: "Company size" },
      { key: "industry", label: "Industry" },
      { key: "location", label: "Location" },
    ],
  },
  {
    id: "lead",
    label: "The lead",
    fields: [
      { key: "title", label: "Lead title", hint: "A short name for the opportunity." },
      { key: "source", label: "Source" },
      { key: "notes", label: "Notes" },
      { key: "budget", label: "Budget", hint: "Low, medium or high." },
      { key: "tags", label: "Tags", hint: "Several tags can be separated by ; | or ,." },
      { key: "status", label: "Status" },
      { key: "next_action", label: "Next action" },
    ],
  },
];

export const ALL_FIELDS: readonly FieldDef[] = FIELD_GROUPS.flatMap((g) => g.fields);

const FIELD_LABELS: Record<string, string> = Object.fromEntries(
  ALL_FIELDS.map((f) => [f.key, f.label]),
);

/** Unknown keys (a newer API) fall back to the key itself, never to something invented. */
export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key;
}

export const STRATEGIES: readonly { value: Strategy; label: string; description: string }[] = [
  {
    value: "skip",
    label: "Skip duplicates",
    description: "Leave the records you already have exactly as they are.",
  },
  {
    value: "update",
    label: "Update existing records",
    description:
      "Fill in and overwrite fields with the values from your file. Empty cells never erase anything. Tags are only added, never removed. A known contact without a lead gets one.",
  },
];

export const DUPLICATE_RULE =
  "A row is a duplicate when its email matches a contact you already have. A row without an email is a duplicate when a lead with the same title and company already exists. Repeats inside the same file count too.";

/* ---------- File checks (before any request) ---------- */

export function formatMb(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function checkFileSize(size: number): string | null {
  if (size <= 0) {
    return "That file is empty. Choose a CSV with a header row and at least one row of data.";
  }
  if (size > MAX_BYTES) return `That file is ${formatMb(size)}; the limit is 2 MB.`;
  return null;
}

export function checkContent(text: string): string | null {
  if (!text.trim()) {
    return "That file is empty. Choose a CSV with a header row and at least one row of data.";
  }
  if (text.length > MAX_BYTES) {
    return `That file is ${formatMb(text.length)}; the limit is 2 MB.`;
  }
  return null;
}

/* ---------- Mapping helpers ---------- */

/** The API wants every field present: the column header, or null. */
export function cleanMapping(mapping: Mapping): ImportMapping {
  const out: ImportMapping = {};
  for (const f of ALL_FIELDS) out[f.key] = mapping[f.key]?.trim() ? mapping[f.key]! : null;
  return out;
}

export function hasRequiredField(mapping: Mapping): boolean {
  return Boolean(mapping.name || mapping.email || mapping.company);
}

/** A column may feed one field only. Returns messages for every field after the first that claims a column. */
export function duplicateColumnErrors(mapping: Mapping): Partial<Record<FieldKey, string>> {
  const owner = new Map<string, FieldKey>();
  const errors: Partial<Record<FieldKey, string>> = {};
  for (const f of ALL_FIELDS) {
    const column = mapping[f.key];
    if (!column) continue;
    const first = owner.get(column);
    if (first) errors[f.key] = `This column is already used for “${fieldLabel(first)}”.`;
    else owner.set(column, f.key);
  }
  return errors;
}

/* ---------- Sample values (read from the in-memory file, never sent anywhere) ---------- */

/** Reads the first records of a CSV (quotes, doubled quotes and newlines inside quotes handled). */
function firstRecords(content: string, delimiter: string, max: number): string[][] {
  const text = content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
  const records: string[][] = [];
  let record: string[] = [];
  let cell = "";
  let quoted = false;
  const endRecord = () => {
    record.push(cell.trim());
    cell = "";
    if (record.some((c) => c !== "")) records.push(record);
    record = [];
  };
  for (let i = 0; i < text.length && records.length < max; i++) {
    const ch = text[i]!;
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = false;
      } else cell += ch;
    } else if (ch === '"' && cell === "") quoted = true;
    else if (ch === delimiter) {
      record.push(cell.trim());
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      endRecord();
    } else cell += ch;
  }
  if (records.length < max && (cell !== "" || record.length > 0)) endRecord();
  return records.slice(0, max);
}

/** column header -> its values in the first `count` data rows. */
export function sampleValues(
  content: string,
  delimiter: string,
  headers: readonly string[],
  count = 3,
): Record<string, string[]> {
  const records = firstRecords(content, delimiter, count + 1);
  const head = records[0];
  const out: Record<string, string[]> = {};
  if (!head) return out;
  for (const header of headers) {
    const index = head.indexOf(header);
    if (index < 0) continue;
    out[header] = records.slice(1).map((r) => (r[index] ?? "").slice(0, 60));
  }
  return out;
}

/* ---------- Sample file ---------- */

export const SAMPLE_CSV =
  "Name,Email,Company,Website,Industry,Notes,Tags\r\n" +
  "Ada Example,ada@acme-studio.example,Acme Studio Example,https://acme-studio.example,Design,Asked about a site refresh,design;priority\r\n" +
  "Sam Sample,sam@northwind.example,Northwind Example,https://northwind.example,Software,Met at a meetup,software\r\n" +
  "Priya Placeholder,priya@lumen.example,Lumen Example,https://lumen.example,Marketing,Wants a monthly retainer,marketing;retainer\r\n";

export const SAMPLE_CSV_HREF = `data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE_CSV)}`;

/* ---------- Review helpers ---------- */

export const ACTION_META: Record<RowAction, { label: string; tone: BadgeTone }> = {
  create: { label: "Will be created", tone: "success" },
  update: { label: "Will update", tone: "info" },
  skip_duplicate: { label: "Duplicate, skipped", tone: "neutral" },
  error: { label: "Has a problem", tone: "danger" },
};

export function actionMeta(action: string): { label: string; tone: BadgeTone } {
  return ACTION_META[action as RowAction] ?? { label: action, tone: "neutral" };
}

export function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

/** Words, not colour: "12 will be created", "3 will update", ... */
export function summaryItems(counts: ImportPreview["counts"]): { key: RowAction; text: string }[] {
  return [
    { key: "create", text: `${counts.create} will be created` },
    { key: "update", text: `${counts.update} will update` },
    {
      key: "skip_duplicate",
      text: `${counts.skip_duplicate} ${plural(counts.skip_duplicate, "duplicate", "duplicates")} skipped`,
    },
    {
      key: "error",
      text: `${counts.error} ${plural(counts.error, "row has a problem", "rows have problems")}`,
    },
  ];
}

export function importableCount(preview: Pick<ImportPreview, "counts">): number {
  return preview.counts.create + preview.counts.update;
}

export function importButtonLabel(n: number): string {
  return `Import ${n} ${plural(n, "lead", "leads")}`;
}

export function suppressedText(n: number): string {
  return n === 1
    ? "1 row is on your do-not-contact list: it will be imported but never emailed."
    : `${n} rows are on your do-not-contact list: they will be imported but never emailed.`;
}

export function hasErrorReport(job: Pick<ImportJobOut, "error_count" | "skipped_count">): boolean {
  return job.error_count + job.skipped_count > 0;
}

export function errorReportHref(workspaceId: string, jobId: string): string {
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/imports/${encodeURIComponent(jobId)}/errors.csv`;
}

export function resultItems(job: ImportJobOut): string[] {
  return [
    `${job.created_count} created`,
    `${job.updated_count} updated`,
    `${job.skipped_count} ${plural(job.skipped_count, "duplicate", "duplicates")} skipped`,
    `${job.error_count} ${plural(job.error_count, "row", "rows")} with problems`,
  ];
}
