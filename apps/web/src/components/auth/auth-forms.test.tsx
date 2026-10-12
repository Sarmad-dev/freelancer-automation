import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ForgotPasswordForm, ResetPasswordForm } from "./password-reset-forms";
import { SignInForm } from "./sign-in-form";
import { SignUpForm } from "./sign-up-form";

const hardNavigate = vi.fn();
vi.mock("@/lib/navigation", () => ({ hardNavigate: (p: string) => hardNavigate(p) }));

const ME = {
  user: { id: "u", email: "a@example.com", display_name: "A", email_verified: false },
  workspaces: [],
};

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fn = vi.fn(async () =>
    status === 204 ? new Response(null, { status }) : Response.json(body, { status, headers }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}
const sent = (fn: ReturnType<typeof vi.fn>) => {
  const req = (fn.mock.calls[0] as unknown as [Request])[0];
  return req
    .clone()
    .json()
    .then((body) => ({ req, body: body as Record<string, unknown> }));
};

beforeEach(() => {
  hardNavigate.mockClear();
  vi.unstubAllGlobals();
});

describe("SignInForm", () => {
  it("signs in and navigates to the sanitised destination", async () => {
    const user = userEvent.setup();
    const fn = mockFetch(200, ME);
    render(<SignInForm next="/leads" passwordResetEnabled />);
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/leads"));
    const { req, body } = await sent(fn);
    expect(new URL(req.url).pathname).toBe("/api/v1/auth/sign-in");
    expect(req.headers.get("x-requested-with")).toBe("freelancer-os");
    expect(body).toEqual({ email: "a@example.com", password: "correct horse battery" });
  });

  it("shows a generic error and keeps the user on the page", async () => {
    const user = userEvent.setup();
    mockFetch(401, {
      error: { code: "invalid_credentials", message: "Incorrect email or password." },
    });
    render(<SignInForm next="/" passwordResetEnabled />);
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(hardNavigate).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("explains rate limiting using Retry-After", async () => {
    const user = userEvent.setup();
    mockFetch(
      429,
      { error: { code: "rate_limited", message: "Too many attempts." } },
      { "retry-after": "90" },
    );
    render(<SignInForm next="/" passwordResetEnabled />);
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 2 minutes");
  });

  it("handles network failures", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    render(<SignInForm next="/" passwordResetEnabled />);
    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Can't reach the server/);
  });

  it("shows session-expired and password-reset notices; hides forgot link when unavailable", () => {
    const { rerender } = render(
      <SignInForm next="/" notice="expired" passwordResetEnabled={false} />,
    );
    expect(screen.getByText("Your session has ended")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Forgot/ })).toBeNull();
    rerender(<SignInForm next="/" notice="reset" passwordResetEnabled />);
    expect(screen.getByText("Password updated")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Forgot/ })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("password can be revealed and masks by default", async () => {
    const user = userEvent.setup();
    render(<SignInForm next="/" passwordResetEnabled />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(input).toHaveAttribute("type", "text");
  });
});

describe("SignUpForm", () => {
  it("creates the account and continues to onboarding", async () => {
    const user = userEvent.setup();
    const fn = mockFetch(201, ME);
    render(<SignUpForm />);
    await user.type(screen.getByLabelText("Your name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/onboarding"));
    expect((await sent(fn)).body).toMatchObject({ display_name: "Ada", email: "ada@example.com" });
  });

  it("maps server field errors onto the right inputs", async () => {
    const user = userEvent.setup();
    mockFetch(422, {
      error: {
        code: "validation_error",
        message: "x",
        fields: { password: "Use at least 12 characters." },
      },
    });
    render(<SignUpForm />);
    await user.type(screen.getByLabelText("Your name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    const pw = await screen.findByLabelText("Password");
    await waitFor(() => expect(pw).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText("Use at least 12 characters.")).toBeInTheDocument();
    expect(hardNavigate).not.toHaveBeenCalled();
  });

  it("explains an already-registered email", async () => {
    const user = userEvent.setup();
    mockFetch(409, {
      error: {
        code: "email_in_use",
        message: "An account with this email already exists. Try signing in.",
        fields: { email: "Already registered." },
      },
    });
    render(<SignUpForm />);
    await user.type(screen.getByLabelText("Your name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
    expect(screen.getByText("Already registered.")).toBeInTheDocument();
  });
});

describe("password reset forms", () => {
  it("forgot-password always shows the same neutral confirmation", async () => {
    const user = userEvent.setup();
    mockFetch(202, { status: "accepted" });
    render(<ForgotPasswordForm />);
    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/If an account exists/)).toBeInTheDocument();
  });

  it("reset sends the token from the link and returns to sign-in", async () => {
    const user = userEvent.setup();
    const fn = mockFetch(204, null);
    render(<ResetPasswordForm token={"t".repeat(30)} />);
    await user.type(screen.getByLabelText("New password"), "a brand new passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/sign-in?reset=1"));
    expect((await sent(fn)).body).toEqual({
      token: "t".repeat(30),
      password: "a brand new passphrase",
    });
  });

  it("an invalid link is explained", async () => {
    const user = userEvent.setup();
    mockFetch(400, {
      error: {
        code: "invalid_token",
        message: "This reset link is invalid or has expired. Request a new one.",
      },
    });
    render(<ResetPasswordForm token={"t".repeat(30)} />);
    await user.type(screen.getByLabelText("New password"), "a brand new passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or has expired");
    expect(hardNavigate).not.toHaveBeenCalled();
  });
});
