import { describe, expect, it } from "vitest";
import { diffToPatch, formFromProfile, type ProfileOut } from "./profile-model";

const PROFILE: ProfileOut = {
  role_title: "Developer",
  summary: null,
  services: ["Audits", "Builds"],
  skills: [],
  industries: [],
  differentiators: [],
  excluded_customers: [],
  target_clients: null,
  portfolio_urls: ["https://example.com"],
  years_experience: 8,
  experience_summary: null,
  pricing_guidance: null,
  preferred_cta: null,
  tone: "friendly",
  tone_notes: null,
  business_goal: null,
  business_goal_notes: null,
  version: 3,
  updated_at: "2026-10-12T00:00:00Z",
  timezone: "UTC",
  completeness: { filled: 4, total: 10, missing: [] },
};

describe("profile form model", () => {
  it("round-trips a profile into form state", () => {
    const f = formFromProfile(PROFILE);
    expect(f.services).toBe("Audits\nBuilds");
    expect(f.years_experience).toBe("8");
    expect(f.summary).toBe("");
  });

  it("an untouched form produces an empty patch", () => {
    const f = formFromProfile(PROFILE);
    expect(diffToPatch(f, { ...f })).toEqual({});
  });

  it("cosmetic whitespace is not a change", () => {
    const f = formFromProfile(PROFILE);
    expect(
      diffToPatch(f, { ...f, role_title: "  Developer ", services: "Audits\n\n  Builds  \n" }),
    ).toEqual({});
  });

  it("sends only the fields that changed, shaped for the API", () => {
    const f = formFromProfile(PROFILE);
    const patch = diffToPatch(f, {
      ...f,
      services: "Audits\nBuilds\nReviews",
      years_experience: "",
      tone: "",
      pricing_guidance: "Quote after a call",
    });
    expect(patch).toEqual({
      services: ["Audits", "Builds", "Reviews"],
      years_experience: null,
      tone: null,
      pricing_guidance: "Quote after a call",
    });
  });

  it("clearing a text field sends an empty string (the API clears it)", () => {
    const f = formFromProfile({ ...PROFILE, summary: "Hello" });
    expect(diffToPatch(f, { ...f, summary: "" })).toEqual({ summary: "" });
  });
});
