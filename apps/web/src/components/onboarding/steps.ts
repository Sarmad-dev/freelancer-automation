import type { OnboardingState } from "@freelancer-os/contracts";

export type StepId = OnboardingState["steps"][number]["id"];
export type Profile = OnboardingState["profile"];

/** Editable form values per step (strings so inputs stay controlled; parsed on submit). */
export interface Draft {
  role_title: string;
  summary: string;
  services: string;
  skills: string;
  description: string;
  industries: string;
  urls: string;
  years: string;
  experience_summary: string;
  tone: string;
  tone_notes: string;
  timezone: string;
  goal: string;
  goal_notes: string;
}

export const STEP_COPY: Record<string, { title: string; description: string }> = {
  role: {
    title: "What do you do?",
    description:
      "Your role and a one-line summary. You'll review this before it's ever used in a draft.",
  },
  services: {
    title: "Which services do you offer?",
    description: "These decide which leads fit and what your outreach can truthfully mention.",
  },
  skills: {
    title: "What are your key skills?",
    description: "Tools, languages and methods you're confident using.",
  },
  target_clients: {
    title: "Who do you want to work with?",
    description: "Describe your ideal client in a sentence or two.",
  },
  industries: {
    title: "Which industries?",
    description: "Optional. Leave blank if you work across the board.",
  },
  portfolio: {
    title: "Where can clients see your work?",
    description: "Optional. Public links only (website, case studies, profiles).",
  },
  experience: {
    title: "How much experience do you have?",
    description: "Optional, but helps with credibility. Only facts you can stand behind.",
  },
  tone: {
    title: "How should your messages sound?",
    description: "Pick the tone drafts should aim for.",
  },
  timezone: {
    title: "What's your time zone?",
    description: "Used for follow-up reminders and when emails are scheduled.",
  },
  goal: { title: "What's your main goal?", description: "We'll tune recommendations to it." },
};

export const TONES = [
  ["professional", "Professional", "Polished and to the point"],
  ["friendly", "Friendly", "Warm and conversational"],
  ["direct", "Direct", "Short and straightforward"],
  ["warm", "Warm", "Personable and encouraging"],
  ["concise", "Concise", "As brief as possible"],
  ["formal", "Formal", "Traditional business tone"],
] as const;

export const GOALS = [
  ["find_new_clients", "Find new clients"],
  ["organize_pipeline", "Keep my pipeline organized"],
  ["automate_follow_ups", "Automate follow-ups"],
  ["win_larger_projects", "Win larger projects"],
  ["other", "Something else"],
] as const;

export function draftFromProfile(p: Profile): Draft {
  return {
    role_title: p.role_title ?? "",
    summary: p.summary ?? "",
    services: p.services.join("\n"),
    skills: p.skills.join("\n"),
    description: p.target_clients ?? "",
    industries: p.industries.join("\n"),
    urls: p.portfolio_urls.join("\n"),
    years: p.years_experience === null ? "" : String(p.years_experience),
    experience_summary: p.experience_summary ?? "",
    tone: p.tone ?? "",
    tone_notes: p.tone_notes ?? "",
    timezone: p.timezone,
    goal: p.business_goal ?? "",
    goal_notes: p.business_goal_notes ?? "",
  };
}

const lines = (v: string) =>
  v
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

/** Build the API payload for a step. Server-side validation is authoritative; this only shapes data. */
export function payloadFor(step: string, d: Draft) {
  switch (step) {
    case "role":
      return { step: "role", role_title: d.role_title, summary: d.summary } as const;
    case "services":
      return { step: "services", services: lines(d.services) } as const;
    case "skills":
      return { step: "skills", skills: lines(d.skills) } as const;
    case "target_clients":
      return { step: "target_clients", description: d.description } as const;
    case "industries":
      return { step: "industries", industries: lines(d.industries) } as const;
    case "portfolio":
      return { step: "portfolio", urls: lines(d.urls) } as const;
    case "experience":
      return {
        step: "experience",
        years: d.years.trim() === "" ? -1 : Number(d.years),
        summary: d.experience_summary,
      } as const;
    case "tone":
      return {
        step: "tone",
        tone: d.tone as (typeof TONES)[number][0],
        notes: d.tone_notes,
      } as const;
    case "timezone":
      return { step: "timezone", timezone: d.timezone } as const;
    case "goal":
      return {
        step: "goal",
        goal: d.goal as (typeof GOALS)[number][0],
        notes: d.goal_notes,
      } as const;
    default:
      throw new Error(`Unknown step ${step}`);
  }
}

/** API error field names that belong to each step's inputs (for mapping server errors to fields). */
export const FIELD_FOR_API: Record<string, keyof Draft> = {
  role_title: "role_title",
  summary: "summary",
  services: "services",
  skills: "skills",
  description: "description",
  industries: "industries",
  urls: "urls",
  years: "years",
  tone: "tone",
  notes: "tone_notes",
  timezone: "timezone",
  goal: "goal",
};
