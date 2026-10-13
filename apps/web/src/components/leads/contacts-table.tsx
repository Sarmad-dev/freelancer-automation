"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import {
  Badge,
  Button,
  Drawer,
  EmptyState,
  Field,
  Input,
  Notice,
  Select,
  Table,
  TableContainer,
  Td,
  Th,
  useToast,
} from "@freelancer-os/ui";
import { browserApi, toFailure } from "@/lib/api-client";
import { describeFailure, type MutationFailure } from "@/lib/mutation-error";
import { formatDate } from "@/lib/safe-url";
import { ContactFields, type CompanyChoice } from "./contact-form";
import {
  ARCHIVED_FILTERS,
  CONTACTS_PATH,
  DEFAULT_SORT,
  PAGE_SIZE,
  createBody,
  detailHref,
  emptyForm,
  hasContactFilters,
  isManualSource,
  mailHref,
  pageHref,
  sortHref,
  sortState,
  type ContactForm,
  type ContactQuery,
  type SortField,
} from "./contact-model";
import { DoNotContactBadge, SampleBadge } from "./lead-badges";
import type { ContactOut } from "./lead-model";

const linkButton =
  "inline-flex h-8 items-center rounded-md border border-line bg-elevated px-3 text-[13px] font-medium text-fg";

function SortHeader({
  query,
  field,
  children,
}: {
  query: ContactQuery;
  field: SortField;
  children: ReactNode;
}) {
  const state = sortState(query, field);
  return (
    <Th sort={state}>
      <Link
        href={sortHref(query, field)}
        className="inline-flex items-center gap-1 underline-offset-4 hover:text-fg hover:underline"
      >
        {children}
        <span aria-hidden>{state === "ascending" ? "↑" : state === "descending" ? "↓" : ""}</span>
      </Link>
    </Th>
  );
}

export function ContactsTable({
  workspaceId,
  contacts,
  total,
  query,
  companies,
  canEdit,
}: {
  workspaceId: string;
  contacts: ContactOut[];
  total: number;
  query: ContactQuery;
  companies: CompanyChoice[];
  canEdit: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const filtered = hasContactFilters(query);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // A company filter must stay selectable even if it is not among the companies offered.
  const filterCompanyKnown = !query.companyId || companies.some((c) => c.id === query.companyId);

  return (
    <div className="flex flex-col gap-5">
      {!canEdit ? (
        <Notice tone="info" title="View only">
          Only the workspace owner can add, edit or archive contacts.
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <form
          action={CONTACTS_PATH}
          method="get"
          role="search"
          aria-label="Filter contacts"
          className="flex flex-1 flex-wrap items-end gap-3"
        >
          {query.sort !== DEFAULT_SORT ? (
            <input type="hidden" name="sort" value={query.sort} />
          ) : null}
          <Field label="Search" className="min-w-48 flex-1 sm:max-w-xs">
            {(p) => (
              <Input
                {...p}
                name="q"
                type="search"
                defaultValue={query.q}
                maxLength={100}
                placeholder="Name, email or role"
              />
            )}
          </Field>
          <Field label="Company">
            {(p) => (
              <Select {...p} name="company_id" defaultValue={query.companyId}>
                <option value="">All companies</option>
                {filterCompanyKnown ? null : (
                  <option value={query.companyId}>Selected company</option>
                )}
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Show">
            {(p) => (
              <Select {...p} name="archived" defaultValue={query.archived}>
                {ARCHIVED_FILTERS.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="secondary">
            Apply
          </Button>
          {filtered ? (
            <Link
              href={CONTACTS_PATH}
              className="inline-flex h-9 items-center px-2 text-sm text-muted underline underline-offset-4 hover:text-fg"
            >
              Clear filters
            </Link>
          ) : null}
        </form>
        {canEdit ? <Button onClick={() => setAdding(true)}>New contact</Button> : null}
      </div>

      {contacts.length === 0 ? (
        query.page > 1 && total > 0 ? (
          <EmptyState
            title="Nothing on this page"
            description="There are fewer contacts than that."
          >
            <Link href={pageHref(query, 1)} className={linkButton}>
              Back to the first page
            </Link>
          </EmptyState>
        ) : filtered ? (
          <EmptyState
            title="No contacts match those filters"
            description="Try a different search, or clear the filters."
          >
            <Link href={CONTACTS_PATH} className={linkButton}>
              Clear filters
            </Link>
          </EmptyState>
        ) : (
          <EmptyState
            title="No contacts yet"
            description="Add the people you might work with, import a CSV, or start from the sample data."
          >
            {canEdit ? (
              <Button onClick={() => setAdding(true)}>Add your first contact</Button>
            ) : null}
          </EmptyState>
        )
      ) : (
        <TableContainer>
          <Table>
            <caption className="sr-only">
              Contacts, {total} in total. Use the Name, Email and Updated column headings to change
              the order.
            </caption>
            <thead>
              <tr>
                <SortHeader query={query} field="full_name">
                  Name
                </SortHeader>
                <SortHeader query={query} field="email">
                  Email
                </SortHeader>
                <Th>Role</Th>
                <Th>Company</Th>
                <Th>Leads</Th>
                <Th>Source</Th>
                <SortHeader query={query} field="updated_at">
                  Updated
                </SortHeader>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) => (
                <ContactRow key={c.id} contact={c} />
              ))}
            </tbody>
          </Table>
        </TableContainer>
      )}

      {contacts.length > 0 ? (
        <nav aria-label="Pagination" className="flex items-center justify-between gap-4 text-sm">
          <p className="text-muted">
            Page {query.page} of {pageCount} · {total} {total === 1 ? "contact" : "contacts"}
          </p>
          <div className="flex gap-2">
            {query.page > 1 ? (
              <Link rel="prev" href={pageHref(query, query.page - 1)} className={linkButton}>
                Previous
              </Link>
            ) : null}
            {query.page < pageCount ? (
              <Link rel="next" href={pageHref(query, query.page + 1)} className={linkButton}>
                Next
              </Link>
            ) : null}
          </div>
        </nav>
      ) : null}

      {adding ? (
        <NewContactDrawer
          workspaceId={workspaceId}
          companies={companies}
          onClose={() => setAdding(false)}
        />
      ) : null}
    </div>
  );
}

function ContactRow({ contact: c }: { contact: ContactOut }) {
  const mail = c.do_not_contact ? null : mailHref(c.email);
  return (
    <tr>
      <Td className="max-w-xs font-medium">
        <div className="flex flex-wrap items-center gap-1.5">
          <Link href={detailHref(c.id)} className="break-words underline underline-offset-4">
            {c.full_name}
          </Link>
          {c.is_sample ? <SampleBadge /> : null}
          {c.archived_at ? <Badge>Archived</Badge> : null}
          {c.do_not_contact ? <DoNotContactBadge /> : null}
        </div>
      </Td>
      <Td className="max-w-56 break-all">
        {c.email ? (
          mail ? (
            <a href={mail} className="underline underline-offset-4">
              {c.email}
            </a>
          ) : (
            <span>{c.email}</span>
          )
        ) : (
          <span className="text-muted">
            <span aria-hidden>—</span>
            <span className="sr-only">No email</span>
          </span>
        )}
      </Td>
      <Td className="max-w-48 break-words">
        {c.role_title ?? <span className="text-muted">—</span>}
      </Td>
      <Td className="max-w-48 break-words">
        {c.company_id && c.company_name ? (
          <Link href={`/leads/companies/${c.company_id}`} className="underline underline-offset-4">
            {c.company_name}
          </Link>
        ) : (
          <span className="text-muted">—</span>
        )}
      </Td>
      <Td className="whitespace-nowrap tabular-nums">
        {c.lead_count > 0 ? (
          <Link href={`/leads?contact_id=${c.id}`} className="underline underline-offset-4">
            {c.lead_count} <span className="sr-only">leads for {c.full_name}</span>
          </Link>
        ) : (
          <span>0</span>
        )}
      </Td>
      <Td className="max-w-40 break-words text-muted">
        {isManualSource(c.source) ? "Manual" : c.source}
      </Td>
      <Td className="whitespace-nowrap text-muted">
        <time dateTime={c.updated_at}>{formatDate(c.updated_at)}</time>
      </Td>
    </tr>
  );
}

/* ---------- New contact ---------- */

function NewContactDrawer({
  workspaceId,
  companies,
  onClose,
}: {
  workspaceId: string;
  companies: CompanyChoice[];
  onClose: () => void;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [form, setForm] = useState<ContactForm>(emptyForm());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<MutationFailure | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.full_name.trim()) {
      setErrors({ full_name: "Enter a name." });
      setBanner({
        title: "Some fields need attention",
        text: "Fix the highlighted fields and try again.",
      });
      return;
    }
    setPending(true);
    setBanner(null);
    setErrors({});
    try {
      const { error, response } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/contacts",
        {
          params: { path: { workspace_id: workspaceId } },
          body: createBody(form),
        },
      );
      if (response.ok) {
        toast({ title: "Contact added", description: form.full_name.trim(), tone: "success" });
        router.refresh();
        onClose();
        return;
      }
      const out = describeFailure(error, response, "contact");
      if (out) {
        setBanner(out.failure);
        setErrors(out.fields);
      }
    } catch {
      setBanner({ title: "That didn't work", text: toFailure(undefined).message });
    }
    setPending(false);
  }

  return (
    <Drawer
      open
      onOpenChange={(open) => !open && onClose()}
      title="New contact"
      description="Only the name is required."
      className="w-[min(30rem,100vw-2rem)]"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="contact-create" disabled={pending}>
            Add contact
          </Button>
        </>
      }
    >
      <form
        id="contact-create"
        onSubmit={submit}
        noValidate
        className="flex flex-col gap-4"
        aria-label="New contact"
      >
        {banner ? (
          <Notice tone="danger" title={banner.title}>
            {banner.text}
          </Notice>
        ) : null}
        <ContactFields
          form={form}
          setForm={setForm}
          errors={errors}
          companies={companies}
          idPrefix="create"
        />
      </form>
    </Drawer>
  );
}
