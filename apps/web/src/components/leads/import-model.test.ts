import { describe, expect, it } from "vitest";
import {
  SAMPLE_CSV,
  SAMPLE_CSV_HREF,
  checkContent,
  checkFileSize,
  cleanMapping,
  duplicateColumnErrors,
  errorReportHref,
  hasErrorReport,
  hasRequiredField,
  importButtonLabel,
  sampleValues,
  summaryItems,
  suppressedText,
} from "./import-model";

describe("file checks", () => {
  it("rejects empty and oversized files with plain wording", () => {
    expect(checkFileSize(0)).toMatch(/empty/);
    expect(checkFileSize(3_400_000)).toBe("That file is 3.4 MB; the limit is 2 MB.");
    expect(checkFileSize(2_000_000)).toBeNull();
    expect(checkContent("  \n ")).toMatch(/empty/);
    expect(checkContent("a,b\n1,2")).toBeNull();
  });
});

describe("mapping helpers", () => {
  it("sends every field, null when not imported", () => {
    const out = cleanMapping({ name: "Name", email: "", company: null });
    expect(out.name).toBe("Name");
    expect(out.email).toBeNull();
    expect(out.company).toBeNull();
    expect(Object.keys(out)).toHaveLength(16);
  });

  it("needs one of name, email or company", () => {
    expect(hasRequiredField({ notes: "Notes" })).toBe(false);
    expect(hasRequiredField({ email: "Email" })).toBe(true);
  });

  it("flags a column used twice, once", () => {
    const errors = duplicateColumnErrors({ name: "Name", email: "Name", company: "Company" });
    expect(Object.keys(errors)).toEqual(["email"]);
    expect(errors.email).toContain("Contact name");
  });
});

describe("sampleValues", () => {
  it("reads quoted values, doubled quotes and newlines inside quotes", () => {
    const csv =
      '﻿Name;Notes\r\n"Ada; A";"said ""hi""\nthere"\r\n\r\nSam;plain\r\nLin;x\r\nZed;y\r\n';
    const out = sampleValues(csv, ";", ["Name", "Notes"], 3);
    expect(out.Name).toEqual(["Ada; A", "Sam", "Lin"]);
    expect(out.Notes).toEqual(['said "hi"\nthere', "plain", "x"]);
  });

  it("handles short files and missing columns", () => {
    expect(sampleValues("A,B\n1", ",", ["A", "B", "C"])).toEqual({ A: ["1"], B: [""] });
    expect(sampleValues("", ",", ["A"])).toEqual({});
  });
});

describe("summary text", () => {
  it("uses words with correct plurals", () => {
    const items = summaryItems({ create: 12, update: 3, skip_duplicate: 1, error: 1 }).map(
      (i) => i.text,
    );
    expect(items).toEqual([
      "12 will be created",
      "3 will update",
      "1 duplicate skipped",
      "1 row has a problem",
    ]);
    expect(
      summaryItems({ create: 0, update: 0, skip_duplicate: 2, error: 2 }).map((i) => i.text),
    ).toEqual([
      "0 will be created",
      "0 will update",
      "2 duplicates skipped",
      "2 rows have problems",
    ]);
    expect(importButtonLabel(1)).toBe("Import 1 lead");
    expect(importButtonLabel(15)).toBe("Import 15 leads");
    expect(suppressedText(3)).toContain("3 rows are on your do-not-contact list");
  });

  it("builds the error report link and knows when one exists", () => {
    expect(errorReportHref("w1", "j1")).toBe("/api/v1/workspaces/w1/imports/j1/errors.csv");
    expect(hasErrorReport({ error_count: 0, skipped_count: 0 })).toBe(false);
    expect(hasErrorReport({ error_count: 0, skipped_count: 2 })).toBe(true);
  });
});

describe("sample file", () => {
  it("is clearly fictional and downloadable as a data URL", () => {
    expect(SAMPLE_CSV.split("\r\n")[0]).toBe("Name,Email,Company,Website,Industry,Notes,Tags");
    expect(SAMPLE_CSV).toContain("@acme-studio.example");
    expect(SAMPLE_CSV_HREF.startsWith("data:text/csv;charset=utf-8,")).toBe(true);
  });
});
