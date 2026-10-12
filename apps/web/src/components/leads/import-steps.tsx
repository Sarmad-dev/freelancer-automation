"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  CircleMinus,
  Copy,
  Plus,
  RefreshCw,
  type LucideIcon,
} from "lucide-react";
import {
  Badge,
  Button,
  Field,
  Notice,
  Select,
  Table,
  TableContainer,
  Td,
  Th,
  cn,
} from "@freelancer-os/ui";
import {
  DUPLICATE_RULE,
  FIELD_GROUPS,
  SAMPLE_CSV_HREF,
  STRATEGIES,
  actionMeta,
  duplicateColumnErrors,
  errorReportHref,
  fieldLabel,
  formatMb,
  hasErrorReport,
  hasRequiredField,
  importButtonLabel,
  importableCount,
  plural,
  resultItems,
  summaryItems,
  suppressedText,
  type FieldKey,
  type Mapping,
  type RowAction,
  type Strategy,
} from "./import-model";
import type { ImportJobOut, ImportPreview } from "./lead-model";

export type Step = "upload" | "map" | "review" | "importing" | "done";

const STEP_LABELS = ["Upload", "Map columns", "Review", "Import"] as const;
const STEP_INDEX: Record<Step, number> = { upload: 0, map: 1, review: 2, importing: 3, done: 3 };

export function StepList({ step }: { step: Step }) {
  const current = STEP_INDEX[step];
  return (
    <ol aria-label="Import steps" className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
      {STEP_LABELS.map((label, i) => {
        const finished = i < current || step === "done";
        const here = i === current && step !== "done";
        return (
          <li
            key={label}
            {...(here ? { "aria-current": "step" as const } : {})}
            className={cn(
              "flex items-center gap-2",
              here ? "font-semibold text-fg" : finished ? "text-fg" : "text-muted",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "flex size-6 items-center justify-center rounded-full border text-xs",
                here ? "border-accent bg-accent text-on-accent" : "border-line bg-elevated",
              )}
            >
              {finished ? <Check className="size-3.5" /> : i + 1}
            </span>
            <span>
              {label}
              <span className="sr-only">
                {here ? " (current step)" : finished ? " (done)" : " (not started)"}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** A step's heading. It takes focus when the step is entered so keyboard and screen-reader users land on it. */
function StepHeading({ id, children, focus }: { id: string; children: ReactNode; focus: boolean }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus) ref.current?.focus();
  }, [focus]);
  return (
    <h2 id={id} ref={ref} tabIndex={-1} className="text-lg font-semibold text-fg outline-none">
      {children}
    </h2>
  );
}

/* ---------- 1. Upload ---------- */

export function UploadStep({
  focus,
  busy,
  error,
  file,
  onFile,
  onContinue,
}: {
  focus: boolean;
  busy: boolean;
  error: string | null;
  file: { name: string; size: number } | null;
  onFile: (file: File) => void;
  onContinue: (() => void) | null;
}) {
  const [dragging, setDragging] = useState(false);
  const drop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (busy) return;
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0]) onFile(files[0]);
  };
  return (
    <section aria-labelledby="import-upload-heading" className="flex flex-col gap-4">
      <StepHeading id="import-upload-heading" focus={focus}>
        Choose a CSV file
      </StepHeading>
      <p className="text-sm text-muted">
        Up to 5,000 rows, 60 columns and 2 MB. Commas, semicolons, tabs and pipes all work. The file
        must be UTF-8 text. Nothing is fetched from the web. Only the data in your file is used.
      </p>
      {error ? (
        <Notice tone="danger" title="That file can't be used">
          {error}
        </Notice>
      ) : null}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
        className={cn(
          "flex flex-col gap-3 rounded-lg border-2 border-dashed p-5",
          dragging ? "border-accent bg-accent/10" : "border-line bg-canvas",
        )}
      >
        <Field label="CSV file" hint="Choose a file, or drop one anywhere in this box.">
          {(p) => (
            <input
              {...p}
              type="file"
              accept=".csv,text/csv,text/plain"
              disabled={busy}
              onChange={(e) => {
                const chosen = e.target.files?.[0];
                if (chosen) onFile(chosen);
                e.target.value = "";
              }}
              className="block w-full text-sm text-fg file:mr-3 file:h-9 file:cursor-pointer file:rounded-md file:border file:border-line file:bg-elevated file:px-4 file:text-sm file:font-medium file:text-fg"
            />
          )}
        </Field>
        {dragging ? <p className="text-sm font-medium text-fg">Drop the file to use it.</p> : null}
      </div>
      <div role="status" aria-busy={busy} className="text-sm text-muted">
        {busy ? (
          <span>Checking {file ? `“${file.name}”` : "your file"}…</span>
        ) : file && !error ? (
          <span>
            Selected file: <strong className="text-fg">{file.name}</strong> ({formatMb(file.size)})
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {onContinue ? (
          <Button onClick={onContinue} disabled={busy}>
            Continue with this file
          </Button>
        ) : null}
        <a
          href={SAMPLE_CSV_HREF}
          download="sample-leads.csv"
          className="text-sm underline underline-offset-4"
        >
          Download a sample CSV
        </a>
      </div>
    </section>
  );
}

/* ---------- 2. Map columns ---------- */

export function MapStep({
  focus,
  busy,
  fileName,
  preview,
  mapping,
  samples,
  problem,
  error,
  onChange,
  onBack,
  onContinue,
}: {
  focus: boolean;
  busy: boolean;
  fileName: string;
  preview: ImportPreview;
  mapping: Mapping;
  samples: Record<string, string[]>;
  problem: string | null;
  error: string | null;
  onChange: (field: FieldKey, column: string) => void;
  onBack: () => void;
  onContinue: () => void;
}) {
  const duplicates = duplicateColumnErrors(mapping);
  const hasDuplicates = Object.keys(duplicates).length > 0;
  const missingRequired = !hasRequiredField(mapping);
  return (
    <section aria-labelledby="import-map-heading" className="flex flex-col gap-4">
      <StepHeading id="import-map-heading" focus={focus}>
        Match your columns
      </StepHeading>
      <p className="text-sm text-muted">
        {fileName} has {preview.total_rows.toLocaleString("en")}{" "}
        {plural(preview.total_rows, "row", "rows")} and {preview.headers.length}{" "}
        {plural(preview.headers.length, "column", "columns")}. Choose which column feeds each field,
        or leave a field on “Don’t import”. Map at least one of name, email or company. A column can
        feed only one field.
      </p>
      {problem ? (
        <Notice tone="danger" title="This mapping can't be used">
          {problem}
        </Notice>
      ) : null}
      {error ? (
        <Notice tone="danger" title="Couldn't check your columns">
          {error}
        </Notice>
      ) : null}
      {missingRequired && !problem ? (
        <Notice tone="warning" title="Map at least one of name, email or company">
          Without one of these there is nothing to name a record by.
        </Notice>
      ) : null}
      {FIELD_GROUPS.map((group) => (
        <fieldset key={group.id} className="flex flex-col gap-3" disabled={busy}>
          <legend className="mb-1 text-sm font-semibold text-fg">{group.label}</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            {group.fields.map((f) => {
              const column = mapping[f.key] ?? "";
              const values = column ? samples[column] : undefined;
              const sample = !column
                ? "Not imported."
                : values && values.length > 0
                  ? `First rows: ${values.map((v) => (v ? `“${v}”` : "(empty)")).join(" · ")}`
                  : "No sample available.";
              const dup = duplicates[f.key];
              return (
                <Field
                  key={f.key}
                  label={f.label}
                  hint={[f.hint, sample].filter(Boolean).join(" ")}
                  {...(dup ? { error: dup } : {})}
                >
                  {(p) => (
                    <Select {...p} value={column} onChange={(e) => onChange(f.key, e.target.value)}>
                      <option value="">Don’t import</option>
                      {preview.headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              );
            })}
          </div>
        </fieldset>
      ))}
      <div role="status" aria-busy={busy} className="text-sm text-muted">
        {busy ? "Checking your rows…" : ""}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onBack} disabled={busy}>
          Back
        </Button>
        <Button onClick={onContinue} disabled={busy || missingRequired || hasDuplicates}>
          Continue
        </Button>
      </div>
    </section>
  );
}

/* ---------- 3. Review ---------- */

const ACTION_ICONS: Record<RowAction, LucideIcon> = {
  create: Plus,
  update: RefreshCw,
  skip_duplicate: Copy,
  error: AlertTriangle,
};

function ActionBadge({ action }: { action: string }) {
  const meta = actionMeta(action);
  const Icon = ACTION_ICONS[action as RowAction] ?? CircleMinus;
  return (
    <Badge tone={meta.tone} icon={<Icon className="size-3" />}>
      {meta.label}
    </Badge>
  );
}

export function ReviewStep({
  focus,
  busy,
  fileName,
  preview,
  strategy,
  banner,
  onStrategy,
  onBack,
  onImport,
}: {
  focus: boolean;
  busy: boolean;
  fileName: string;
  preview: ImportPreview;
  strategy: Strategy;
  banner: { title: string; text: string } | null;
  onStrategy: (s: Strategy) => void;
  onBack: () => void;
  onImport: () => void;
}) {
  const importable = importableCount(preview);
  const shownRows = preview.rows.length;
  return (
    <section
      aria-labelledby="import-review-heading"
      aria-busy={busy}
      className="flex flex-col gap-5"
    >
      <StepHeading id="import-review-heading" focus={focus}>
        Review before importing
      </StepHeading>
      <p className="text-sm text-muted">
        Nothing has been saved yet. This is what importing {fileName} would do.
      </p>
      {banner ? (
        <Notice tone="danger" title={banner.title}>
          {banner.text}
        </Notice>
      ) : null}

      <fieldset className="flex flex-col gap-3" disabled={busy}>
        <legend className="text-sm font-semibold text-fg">
          If a row matches something you already have
        </legend>
        <p className="text-[13px] text-muted">{DUPLICATE_RULE}</p>
        <div className="flex flex-col gap-3">
          {STRATEGIES.map((s) => (
            <label
              key={s.value}
              className="flex cursor-pointer items-start gap-3 rounded-md border border-line p-3 text-sm"
            >
              <input
                type="radio"
                name="duplicate-strategy"
                value={s.value}
                checked={strategy === s.value}
                onChange={() => onStrategy(s.value)}
                aria-describedby={`strategy-${s.value}`}
                className="mt-0.5 size-4"
              />
              <span>
                <span className="block font-medium text-fg">{s.label}</span>
                <span id={`strategy-${s.value}`} className="block text-[13px] text-muted">
                  {s.description}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div role="status" aria-busy={busy} className="text-sm text-muted">
        {busy ? "Updating the preview…" : ""}
      </div>

      <ul
        aria-label="Summary"
        className="grid grid-cols-2 gap-3 sm:grid-cols-4"
        data-testid="import-summary"
      >
        {summaryItems(preview.counts).map((item) => {
          const [count, ...rest] = item.text.split(" ");
          return (
            <li key={item.key} className="rounded-lg border border-line bg-canvas p-3">
              <span className="block text-2xl font-semibold text-fg">{count}</span>{" "}
              <span className="text-[13px] text-muted">{rest.join(" ")}</span>
            </li>
          );
        })}
      </ul>

      {preview.suppressed > 0 ? (
        <Notice tone="warning" title="Do-not-contact list">
          {suppressedText(preview.suppressed)}
        </Notice>
      ) : null}

      {preview.rows.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-fg">Rows</h3>
          <TableContainer>
            <Table>
              <caption className="sr-only">
                The first {shownRows} of {preview.total_rows} rows and what will happen to each
              </caption>
              <thead>
                <tr>
                  <Th>Row</Th>
                  <Th>What will happen</Th>
                  <Th>Values</Th>
                  <Th>Notes</Th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row}>
                    <Td className="align-top whitespace-nowrap">{r.row}</Td>
                    <Td className="align-top">
                      <ActionBadge action={r.action} />
                    </Td>
                    <Td className="align-top">
                      <dl className="flex max-w-md flex-col gap-0.5 text-[13px]">
                        {Object.entries(r.values).map(([k, v]) => (
                          <div key={k} className="flex gap-1.5">
                            <dt className="shrink-0 text-muted">{fieldLabel(k)}:</dt>
                            <dd className="break-words">{v}</dd>
                          </div>
                        ))}
                      </dl>
                    </Td>
                    <Td className="align-top text-[13px]">
                      <ul className="flex max-w-xs flex-col gap-0.5">
                        {r.issues.map((t, i) => (
                          <li key={`i${i}`} className="break-words">
                            <span className="font-medium">Problem:</span> {t}
                          </li>
                        ))}
                        {r.warnings.map((t, i) => (
                          <li key={`w${i}`} className="break-words">
                            <span className="font-medium">Heads up:</span> {t}
                          </li>
                        ))}
                        {r.note ? <li className="break-words text-muted">{r.note}</li> : null}
                      </ul>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
          <p className="text-[13px] text-muted">
            {preview.total_rows > shownRows
              ? `Showing the first ${shownRows} of ${preview.total_rows.toLocaleString("en")} rows.`
              : `Showing all ${shownRows} ${plural(shownRows, "row", "rows")}.`}
          </p>
        </div>
      ) : null}

      {preview.errors.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-fg">Rows that won’t be imported</h3>
          <TableContainer>
            <Table>
              <caption className="sr-only">Problems found in the file</caption>
              <thead>
                <tr>
                  <Th>Row</Th>
                  <Th>Type</Th>
                  <Th>Column</Th>
                  <Th>Problem</Th>
                  <Th>Value</Th>
                </tr>
              </thead>
              <tbody>
                {preview.errors.map((e, i) => (
                  <tr key={`${e.row}-${e.column}-${i}`}>
                    <Td className="whitespace-nowrap">{e.row}</Td>
                    <Td className="whitespace-nowrap">
                      {e.kind === "skipped" ? "Skipped duplicate" : "Problem"}
                    </Td>
                    <Td className="break-words">{e.column}</Td>
                    <Td className="break-words">{e.message}</Td>
                    <Td className="max-w-xs break-words">{e.value}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
          {preview.errors_truncated ? (
            <p className="text-[13px] text-muted">
              Showing the first {preview.errors.length} problems. More were found than can be shown
              here. The error report you can download after importing lists every one.
            </p>
          ) : null}
        </div>
      ) : null}

      {importable === 0 ? (
        <Notice tone="warning" title="Nothing to import">
          Every row is a duplicate or has a problem, so importing would not change anything.{" "}
          {strategy === "skip" && preview.counts.skip_duplicate > 0
            ? "Choose “Update existing records” to fill in what you already have, or go back and fix the mapping."
            : "Go back to fix the mapping, or choose another file."}
        </Notice>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={onBack} disabled={busy}>
          Back
        </Button>
        <Button onClick={onImport} disabled={busy || importable === 0}>
          {importButtonLabel(importable)}
        </Button>
      </div>
    </section>
  );
}

/* ---------- 4. Importing / done ---------- */

export function ProgressStep({ rows }: { rows: number }) {
  return (
    <section aria-labelledby="import-progress-heading" className="flex flex-col gap-4">
      <StepHeading id="import-progress-heading" focus>
        Importing your leads
      </StepHeading>
      <div role="status" aria-busy="true" className="flex flex-col gap-3">
        <p className="text-sm text-muted">
          Importing {rows.toLocaleString("en")} {plural(rows, "row", "rows")}… keep this tab open.
        </p>
        <div
          role="progressbar"
          aria-label="Importing"
          className="h-2 w-full max-w-md animate-pulse rounded-full bg-accent/60"
        />
      </div>
    </section>
  );
}

export function DoneStep({
  workspaceId,
  job,
  onAnother,
}: {
  workspaceId: string;
  job: ImportJobOut;
  onAnother: () => void;
}) {
  return (
    <section aria-labelledby="import-done-heading" className="flex flex-col gap-4">
      <StepHeading id="import-done-heading" focus>
        Import finished
      </StepHeading>
      <p className="text-sm text-muted">
        {job.filename}: {job.total_rows.toLocaleString("en")}{" "}
        {plural(job.total_rows, "row was", "rows were")} read.
      </p>
      <ul aria-label="Result" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {resultItems(job).map((text) => {
          const [count, ...rest] = text.split(" ");
          return (
            <li key={text} className="rounded-lg border border-line bg-canvas p-3">
              <span className="block text-2xl font-semibold text-fg">{count}</span>{" "}
              <span className="text-[13px] text-muted">{rest.join(" ")}</span>
            </li>
          );
        })}
      </ul>
      {job.suppressed ? (
        <Notice tone="warning" title="Do-not-contact list">
          {suppressedText(job.suppressed)}
        </Notice>
      ) : null}
      {hasErrorReport(job) ? (
        <Notice tone="info" title="Some rows were not imported">
          The error report lists each skipped duplicate and each row with a problem.{" "}
          {job.errors_truncated ? "It is cut short for very long lists. " : ""}
          <a
            href={errorReportHref(workspaceId, job.id)}
            download
            className="underline underline-offset-4"
          >
            Download error report (CSV)
          </a>
        </Notice>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href="/leads"
          className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-on-accent"
        >
          View leads
        </Link>
        <Button variant="secondary" onClick={onAnother}>
          Import another file
        </Button>
      </div>
    </section>
  );
}
