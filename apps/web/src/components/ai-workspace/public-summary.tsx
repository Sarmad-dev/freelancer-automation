import type { components } from "@freelancer-os/contracts";
import { safeExternalUrl } from "@/lib/safe-url";

type Summary = components["schemas"]["ProfileSummary"];

/**
 * The public-facing professional summary, rendered as plain text. Every value is a React text node
 * (escaped), links are re-validated to http(s), and external links get rel="noopener noreferrer nofollow".
 */
export function PublicSummary({ summary }: { summary: Summary }) {
  const empty =
    !summary.headline &&
    !summary.intro &&
    summary.sections.length === 0 &&
    summary.links.length === 0;
  return (
    <div className="flex flex-col gap-4 text-sm">
      {empty ? (
        <p className="text-muted">
          Nothing to show yet. Fill in your role and services and this preview will be built from
          exactly what you enter.
        </p>
      ) : (
        <>
          {summary.headline ? (
            <p className="text-base font-semibold text-fg">{summary.headline}</p>
          ) : null}
          {summary.intro ? <p className="text-fg">{summary.intro}</p> : null}
          {summary.sections.map((section) => (
            <section key={section.title} aria-label={section.title}>
              <h3 className="text-xs font-medium tracking-wide text-muted uppercase">
                {section.title}
              </h3>
              <ul className="mt-1 list-disc pl-5 text-fg">
                {section.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ))}
          {summary.links.length > 0 ? (
            <section aria-label="Links">
              <h3 className="text-xs font-medium tracking-wide text-muted uppercase">Portfolio</h3>
              <ul className="mt-1 flex flex-col gap-1">
                {summary.links.map((link) => {
                  const href = safeExternalUrl(link);
                  return (
                    <li key={link} className="break-all">
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer nofollow"
                          className="text-fg underline underline-offset-4"
                        >
                          {link}
                        </a>
                      ) : (
                        <span className="text-muted">{link} (not a valid link)</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
        </>
      )}
      {summary.omitted.length > 0 ? (
        <p className="border-t border-line pt-3 text-[13px] text-muted">
          Not included yet: {summary.omitted.map((o) => o.label).join(", ")}. Nothing is filled in
          for you.
        </p>
      ) : null}
      <p className="text-[13px] text-muted">
        Private and never shown here: {summary.private_fields_excluded.join(", ")}.
      </p>
    </div>
  );
}
