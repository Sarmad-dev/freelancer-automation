"use client";

import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { useToast } from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure } from "@/lib/mutation-error";
import {
  checkContent,
  checkFileSize,
  cleanMapping,
  sampleValues,
  type FieldKey,
  type Mapping,
  type Strategy,
} from "./import-model";
import {
  DoneStep,
  MapStep,
  ProgressStep,
  ReviewStep,
  StepList,
  UploadStep,
  type Step,
} from "./import-steps";
import type { ImportJobOut, ImportPreview } from "./lead-model";

type Outcome = { ok: true; data: ImportPreview } | { ok: false; message: string } | null;

/** The API writes `invalid_csv` / `invalid_mapping` messages for end users; prefer them over generic text. */
function messageFor(error: unknown, response: Response): string {
  const f = toFailure(error, response);
  return f.fields.content ?? f.fields.mapping ?? f.message;
}

export function ImportWizard({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const { toast } = useToast();
  const [step, setStep] = useState<Step>("upload");
  const [navigated, setNavigated] = useState(false);
  const [file, setFile] = useState<{ name: string; size: number } | null>(null);
  // The CSV text lives in memory only. It is never put in a URL, storage or a log.
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [strategy, setStrategy] = useState<Strategy>("skip");
  const [busy, setBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [mappingProblem, setMappingProblem] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ title: string; text: string } | null>(null);
  const [result, setResult] = useState<ImportJobOut | null>(null);
  // State updates are asynchronous; the ref makes "one request at a time" hold even for a double click.
  const inFlight = useRef(false);

  const samples = useMemo(
    () => (preview ? sampleValues(content, preview.delimiter, preview.headers) : {}),
    [content, preview],
  );

  function go(next: Step) {
    setNavigated(true);
    setBanner(null);
    setStep(next);
  }

  /** One preview request. Null = the session expired (already redirecting). */
  async function requestPreview(
    text: string,
    map: Mapping | null,
    strat: Strategy,
  ): Promise<Outcome> {
    try {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/imports/preview",
        {
          params: { path: { workspace_id: workspaceId } },
          body: {
            content: text,
            duplicate_strategy: strat,
            ...(map ? { mapping: cleanMapping(map) } : {}),
          },
        },
      );
      if (response.ok && data) return { ok: true, data };
      if (!describeFailure(error, response)) return null;
      return { ok: false, message: messageFor(error, response) };
    } catch {
      return { ok: false, message: toFailure(undefined).message };
    }
  }

  async function chooseFile(chosen: File) {
    if (inFlight.current) return;
    setUploadError(null);
    setMapError(null);
    setFile(null);
    setPreview(null);
    setContent("");
    const tooBig = checkFileSize(chosen.size);
    if (tooBig) {
      setUploadError(tooBig);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setFile({ name: chosen.name, size: chosen.size });
    try {
      let text: string;
      try {
        text = await chosen.text();
      } catch {
        setFile(null);
        setUploadError("That file couldn't be read. Try saving it again as a CSV.");
        return;
      }
      const problem = checkContent(text);
      if (problem) {
        setFile(null);
        setUploadError(problem);
        return;
      }
      const out = await requestPreview(text, null, strategy);
      if (!out) return;
      if (!out.ok) {
        setFile(null);
        setUploadError(out.message);
        return;
      }
      setContent(text);
      setPreview(out.data);
      setMapping({ ...out.data.suggested_mapping });
      setMappingProblem(out.data.mapping_problem);
      go("map");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function continueFromMap() {
    if (inFlight.current || !preview) return;
    inFlight.current = true;
    setBusy(true);
    setMapError(null);
    setBanner(null);
    try {
      const out = await requestPreview(content, mapping, strategy);
      if (!out) return;
      if (!out.ok) {
        setMapError(out.message);
        return;
      }
      setPreview(out.data);
      setMappingProblem(out.data.mapping_problem);
      if (!out.data.mapping_problem) go("review");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function changeStrategy(next: Strategy) {
    if (inFlight.current || next === strategy) return;
    inFlight.current = true;
    setBusy(true);
    setBanner(null);
    try {
      const out = await requestPreview(content, mapping, next);
      if (!out) return;
      if (!out.ok) {
        setBanner({ title: "Couldn't update the preview", text: out.message });
        return;
      }
      setStrategy(next);
      setPreview(out.data);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function runImport() {
    if (inFlight.current || !preview || !file) return;
    inFlight.current = true;
    setBusy(true);
    setBanner(null);
    go("importing");
    try {
      const { data, error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/imports",
        {
          params: { path: { workspace_id: workspaceId } },
          body: {
            content,
            mapping: cleanMapping(mapping),
            duplicate_strategy: strategy,
            filename: file.name.slice(0, 200),
          },
        },
      );
      if (response.ok && data) {
        setResult(data);
        go("done");
        toast({
          title: "Import finished",
          description: `${data.created_count} created, ${data.updated_count} updated.`,
          tone: "success",
        });
        router.refresh();
        return;
      }
      go("review");
      if (describeFailure(error, response)) {
        setBanner({
          title: "The import didn't run",
          text: `${messageFor(error, response)} Your file and choices are still here.`,
        });
      }
    } catch {
      go("review");
      setBanner({
        title: "The import didn't run",
        text: `${toFailure(undefined).message} Your file and choices are still here.`,
      });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function reset() {
    setFile(null);
    setContent("");
    setPreview(null);
    setMapping({});
    setStrategy("skip");
    setUploadError(null);
    setMapError(null);
    setMappingProblem(null);
    setBanner(null);
    setResult(null);
    go("upload");
  }

  function setColumn(field: FieldKey, column: string) {
    setMapping((m) => ({ ...m, [field]: column || null }));
    setMappingProblem(null);
    setMapError(null);
  }

  return (
    <div className="flex flex-col gap-6 rounded-lg border border-line bg-surface p-5">
      <StepList step={step} />
      {step === "upload" ? (
        <UploadStep
          focus={navigated}
          busy={busy}
          error={uploadError}
          file={file}
          onFile={(f) => void chooseFile(f)}
          onContinue={preview && file && !uploadError ? () => go("map") : null}
        />
      ) : null}
      {step === "map" && preview && file ? (
        <MapStep
          focus={navigated}
          busy={busy}
          fileName={file.name}
          preview={preview}
          mapping={mapping}
          samples={samples}
          problem={mappingProblem}
          error={mapError}
          onChange={setColumn}
          onBack={() => go("upload")}
          onContinue={() => void continueFromMap()}
        />
      ) : null}
      {step === "review" && preview && file ? (
        <ReviewStep
          focus={navigated}
          busy={busy}
          fileName={file.name}
          preview={preview}
          strategy={strategy}
          banner={banner}
          onStrategy={(s) => void changeStrategy(s)}
          onBack={() => go("map")}
          onImport={() => void runImport()}
        />
      ) : null}
      {step === "importing" && preview ? <ProgressStep rows={preview.total_rows} /> : null}
      {step === "done" && result ? (
        <DoneStep workspaceId={workspaceId} job={result} onAnother={reset} />
      ) : null}
    </div>
  );
}
