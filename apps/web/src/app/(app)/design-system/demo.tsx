"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Plus, Trash2 } from "lucide-react";
import {
  Badge,
  Button,
  Checkbox,
  ConfirmDialog,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  FilterChips,
  Input,
  Modal,
  Notice,
  PageHeader,
  Pagination,
  PermissionDeniedState,
  Select,
  Table,
  TableContainer,
  TableSkeleton,
  TableToolbar,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Td,
  Textarea,
  Th,
  Tooltip,
  useToast,
  type FilterChip,
} from "@freelancer-os/ui";

const SWATCHES = [
  ["Canvas", "bg-canvas"],
  ["Sidebar", "bg-sidebar"],
  ["Surface", "bg-surface"],
  ["Elevated", "bg-elevated"],
  ["Accent", "bg-accent"],
  ["Success", "bg-success"],
  ["Warning", "bg-warning"],
  ["Danger", "bg-danger"],
  ["Info", "bg-info"],
] as const;

// Fictional sample rows for the table pattern. Not real data.
const SAMPLE = Array.from({ length: 23 }, (_, i) => ({
  id: i + 1,
  name: ["Northwind Studio", "Fabrikam Labs", "Contoso Works", "Tailspin Co."][i % 4] + ` ${i + 1}`,
  stage: (["New", "Contacted", "Replied", "Qualified"] as const)[i % 4],
  fit: 40 + ((i * 13) % 60),
}));

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`ds-${title}`} className="flex flex-col gap-4">
      <h2 id={`ds-${title}`} className="border-b border-line pb-2 text-lg font-semibold text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

export function DesignSystemDemo() {
  const { toast } = useToast();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [chips, setChips] = useState<FilterChip[]>([
    { id: "stage", label: "Stage: Replied" },
    { id: "fit", label: "Fit ≥ 60" },
  ]);
  const [page, setPage] = useState(1);
  const pageSize = 5;
  const [selected, setSelected] = useState<number[]>([]);

  const rows = useMemo(
    () =>
      SAMPLE.filter(
        (r) =>
          r.name.toLowerCase().includes(query.toLowerCase()) &&
          (!chips.some((c) => c.id === "stage") || r.stage === "Replied") &&
          (!chips.some((c) => c.id === "fit") || r.fit >= 60),
      ),
    [query, chips],
  );
  const visible = rows.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="flex flex-col gap-10">
      <PageHeader
        title="Design system"
        description="Internal reference for tokens, components and page patterns. Only available in development."
        badge={<Badge tone="warning">Dev only</Badge>}
      />

      <Section title="Colour tokens">
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {SWATCHES.map(([name, cls]) => (
            <li
              key={name}
              className="flex items-center gap-3 rounded-md border border-line bg-surface p-2"
            >
              <span aria-hidden className={`size-8 rounded-sm border border-line ${cls}`} />
              <span className="text-sm text-fg">{name}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Buttons and badges">
        <div className="flex flex-wrap items-center gap-3">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">
            <Trash2 className="size-4" aria-hidden /> Delete
          </Button>
          <Button disabled>Disabled</Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge>Neutral</Badge>
          <Badge tone="accent">Active</Badge>
          <Badge tone="success" icon={<CheckCircle2 className="size-3" />}>
            Succeeded
          </Badge>
          <Badge tone="warning">Waiting approval</Badge>
          <Badge tone="danger">Failed</Badge>
          <Badge tone="info">Demo data</Badge>
        </div>
      </Section>

      <Section title="Form controls">
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()}>
          <Field label="Company name" hint="As it appears on their website." required>
            {(p) => <Input {...p} placeholder="Northwind Studio" />}
          </Field>
          <Field label="Contact email" error="Enter a valid email address.">
            {(p) => <Input {...p} type="email" defaultValue="not-an-email" />}
          </Field>
          <Field label="Stage">
            {(p) => (
              <Select {...p} defaultValue="new">
                <option value="new">New</option>
                <option value="contacted">Contacted</option>
              </Select>
            )}
          </Field>
          <Field label="Notes">{(p) => <Textarea {...p} />}</Field>
          <Checkbox label="Add to follow-up queue" description="Creates a task due in 3 days." />
          <Checkbox label="Disabled option" disabled />
        </form>
      </Section>

      <Section title="Tabs and tooltip">
        <Tabs defaultValue="overview">
          <TabsList aria-label="Example tabs">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
          </TabsList>
          <TabsContent value="overview">
            <Tooltip content="Supplementary hint" side="top">
              <Button variant="secondary">Hover or focus me</Button>
            </Tooltip>
          </TabsContent>
          <TabsContent value="activity">
            <p className="text-sm text-muted">Activity timeline goes here.</p>
          </TabsContent>
        </Tabs>
      </Section>

      <Section title="Overlays and toasts">
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => setModalOpen(true)}>
            Open dialog
          </Button>
          <Button variant="secondary" onClick={() => setDrawerOpen(true)}>
            Open drawer
          </Button>
          <Button variant="danger" onClick={() => setConfirmOpen(true)}>
            Confirm destructive action
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              toast({
                title: "Lead saved",
                description: "Northwind Studio was updated.",
                tone: "success",
              })
            }
          >
            Success toast
          </Button>
          <Button
            variant="secondary"
            onClick={() =>
              toast({
                title: "Import failed",
                description: "Row 4 has no email address.",
                tone: "danger",
              })
            }
          >
            Error toast
          </Button>
        </div>
        <Modal
          open={modalOpen}
          onOpenChange={setModalOpen}
          title="Add a note"
          description="Notes are visible only in your workspace."
          footer={<Button onClick={() => setModalOpen(false)}>Save note</Button>}
        >
          <Field label="Note">{(p) => <Textarea {...p} />}</Field>
        </Modal>
        <Drawer
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          title="Quick edit lead"
          description="Changes apply when you save."
          footer={<Button onClick={() => setDrawerOpen(false)}>Save</Button>}
        >
          <Field label="Name">{(p) => <Input {...p} defaultValue="Northwind Studio 1" />}</Field>
        </Drawer>
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title="Archive this lead?"
          description="The lead is hidden from lists and stops receiving follow-ups. You can restore it later."
          confirmLabel="Archive lead"
          destructive
          onConfirm={() => toast({ title: "Lead archived", tone: "info" })}
        />
      </Section>

      <Section title="Table pattern (sample data)">
        <Notice tone="info" title="Sample data">
          Rows below are fictional and exist only to demonstrate the pattern.
        </Notice>
        <TableToolbar
          searchLabel="Search leads"
          searchPlaceholder="Search leads…"
          searchValue={query}
          onSearchChange={(v) => {
            setQuery(v);
            setPage(1);
          }}
          selectedCount={selected.length}
          bulkActions={
            <Button size="sm" variant="secondary" onClick={() => setSelected([])}>
              Clear selection
            </Button>
          }
          actions={
            <Button size="sm">
              <Plus className="size-4" aria-hidden /> Add lead
            </Button>
          }
        />
        <FilterChips
          chips={chips}
          onRemove={(id) => {
            setChips((c) => c.filter((x) => x.id !== id));
            setPage(1);
          }}
          onClear={() => {
            setChips([]);
            setPage(1);
          }}
        />
        {visible.length === 0 ? (
          <EmptyState
            title="No leads match these filters"
            description="Try removing a filter or searching for something else."
          />
        ) : (
          <TableContainer role="region" aria-label="Sample leads table">
            <Table>
              <thead>
                <tr>
                  <Th className="w-10">
                    <span className="sr-only">Select</span>
                  </Th>
                  <Th sort="ascending">Company</Th>
                  <Th>Stage</Th>
                  <Th>Fit</Th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={r.id}>
                    <Td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${r.name}`}
                        checked={selected.includes(r.id)}
                        onChange={(e) =>
                          setSelected((s) =>
                            e.target.checked ? [...s, r.id] : s.filter((x) => x !== r.id),
                          )
                        }
                      />
                    </Td>
                    <Td>{r.name}</Td>
                    <Td>
                      <Badge tone={r.stage === "Replied" ? "success" : "neutral"}>{r.stage}</Badge>
                    </Td>
                    <Td>{r.fit}/100</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
        )}
        <Pagination
          page={page}
          pageSize={pageSize}
          total={rows.length}
          onPageChange={setPage}
          noun="leads"
        />
      </Section>

      <Section title="Page states">
        <div className="grid gap-4 lg:grid-cols-2">
          <EmptyState
            title="No leads yet"
            description="Add your first lead or import a CSV to get started."
          >
            <Button size="sm">Add lead</Button>
          </EmptyState>
          <ErrorState onRetry={() => toast({ title: "Retrying…", tone: "info" })} detail="a1b2c3" />
          <PermissionDeniedState />
          <TableSkeleton rows={4} columns={3} />
        </div>
      </Section>
    </div>
  );
}
