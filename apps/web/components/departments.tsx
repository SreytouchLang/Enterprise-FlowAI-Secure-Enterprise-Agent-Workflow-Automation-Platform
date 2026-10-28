"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BriefcaseBusiness,
  Building2,
  CheckCheck,
  FileText,
  Landmark,
  Plus,
  Scale,
  Send,
  UsersRound,
} from "lucide-react";
import { useState } from "react";
import {
  api,
  businessRequest,
  dateTime,
  Document,
  human,
  Item,
  jsonText,
  list,
  Page,
} from "@/lib/api";
import {
  Badge,
  Busy,
  DataTable,
  ErrorState,
  Field,
  Heading,
  Loading,
} from "./common";
import { useToast, useUser } from "./providers";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { InvoiceFields } from "./invoice-fields";
import { BusinessMetrics } from "./business-metrics";
const domains = [
  {
    key: "finance",
    name: "Finance",
    icon: Landmark,
    path: "/finance/invoices",
    description:
      "Extract and validate invoices, then route records for human approval.",
    create: "Process invoice",
  },
  {
    key: "hr",
    name: "Human Resources",
    icon: UsersRound,
    path: "/hr/onboardings",
    description:
      "Guide employee onboarding and track the tasks that make a strong start.",
    create: "Start onboarding",
  },
  {
    key: "legal",
    name: "Legal",
    icon: Scale,
    path: "/legal/reviews",
    description:
      "Review structured contract analysis and compare authorized agreements.",
    create: "Analyze contract",
  },
  {
    key: "operations",
    name: "Operations",
    icon: Building2,
    path: "/operations/properties",
    description:
      "Normalize property records and resolve conflicts before human review.",
    create: "Import property",
  },
];
const invoiceExample = {
  vendor_name: "",
  invoice_number: "",
  invoice_date: "",
  due_date: "",
  currency: "USD",
  subtotal: "0.00",
  tax: "0.00",
  total: "0.00",
  line_items: [
    { description: "", quantity: "1", unit_price: "0.00", amount: "0.00" },
  ],
};
const sourcesExample = [
  {
    name: "Source A",
    fields: {
      address: "",
      city: "",
      bedrooms: 2,
      bathrooms: 1,
      status: "available",
    },
  },
  {
    name: "Source B",
    fields: {
      address: "",
      city: "",
      bedrooms: 3,
      bathrooms: 1,
      status: "available",
    },
  },
];
export function Departments() {
  const { data: user } = useUser();
  const client = useQueryClient();
  const toast = useToast();
  const [domain, setDomain] = useState("");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Item | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobProgress, setJobProgress] = useState("");
  const [department, setDepartment] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [comparison, setComparison] = useState("");
  const [mode, setMode] = useState("extract");
  const [provider, setProvider] = useState("openai");
  const [employee, setEmployee] = useState("");
  const [email, setEmail] = useState("");
  const [startDate, setStartDate] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [json, setJson] = useState("");
  const [comment, setComment] = useState("");
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateJson, setTemplateJson] = useState(
    '[{"title":"Read company handbook","required_document":"Handbook acknowledgment"},{"title":"Complete security training"}]',
  );
  const [templateId, setTemplateId] = useState("");
  const [editingTemplate, setEditingTemplate] = useState<string | null>(null);
  const [invoiceEdit, setInvoiceEdit] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summary, setSummary] = useState<unknown>(null);
  const current =
    domains.find(
      (d) =>
        d.key ===
        (domain ||
          user?.departments
            .map((d) => d.name.toLowerCase())
            .map((n) => (n.includes("human") ? "hr" : n))[0]),
    ) || domains[0];
  const dep =
    department ||
    user?.departments.find(
      (d) =>
        d.name.toLowerCase().includes(current.key) ||
        (current.key === "hr" && d.name.toLowerCase().includes("human")),
    )?.id ||
    user?.departments[0]?.id ||
    "";
  const records = useQuery({
    queryKey: ["department", current.key, dep],
    queryFn: () =>
      api<Page<Item>>(
        `${current.path}?department_id=${encodeURIComponent(dep)}&limit=100`,
      ),
    enabled: !!dep,
  });
  const docs = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<Page<Document>>("/documents?limit=100"),
  });
  const templates = useQuery({
    queryKey: ["hr-templates", dep],
    queryFn: () =>
      api<Page<Item>>(`/hr/templates?department_id=${encodeURIComponent(dep)}`),
    enabled: current.key === "hr" && !!dep,
  });
  const availableDocs = list(docs.data).filter((d) => d.department_id === dep);
  function newRecord() {
    setMode("extract");
    setTemplateId("");
    setDocumentId("");
    setComparison("");
    setJson(
      jsonText(current.key === "operations" ? sourcesExample : invoiceExample),
    );
    setOpen(true);
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      let body: Record<string, unknown> = { department_id: dep };
      let path = current.path;
      if (current.key === "finance") {
        if (mode === "manual") {
          path += "/manual";
          body = {
            ...body,
            ...(documentId ? { document_id: documentId } : {}),
            data: JSON.parse(json),
          };
        } else body = { ...body, document_id: documentId, provider };
      } else if (current.key === "legal")
        body = {
          ...body,
          document_id: documentId,
          provider,
          ...(comparison ? { comparison_document_id: comparison } : {}),
        };
      else if (current.key === "hr")
        body = {
          ...body,
          employee_name: employee,
          employee_email: email,
          start_date: startDate,
          ...(templateId ? { template_id: templateId } : {}),
        };
      else
        body = { ...body, property_id: propertyId, sources: JSON.parse(json) };
      setJobProgress("Submitting request…");
      const result = await businessRequest<Item>(path, body, (job) =>
        setJobProgress(`${human(job.status)} · Job ${job.id.slice(0, 8)}`),
      );
      setOpen(false);
      setSelected(result);
      setInvoiceEdit(false);
      if (current.key === "operations")
        setJson(jsonText(result.normalized || {}));
      toast("Record created.");
      client.invalidateQueries({ queryKey: ["department", current.key] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to create record", true);
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  async function submit() {
    if (!selected) return;
    setBusy(true);
    try {
      const result = await api<Item>(`${current.path}/${selected.id}/submit`, {
        method: "POST",
      });
      setSelected(result);
      toast("Submitted for review.");
      client.invalidateQueries({ queryKey: ["department", current.key] });
      client.invalidateQueries({ queryKey: ["approvals"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to submit record", true);
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  async function complete(task: Item) {
    setBusy(true);
    try {
      const result = await api<Item>(`/hr/tasks/${task.id}`, {
        method: "PATCH",
        body: { completed: !task.completed },
      });
      setSelected((old) =>
        old
          ? {
              ...old,
              tasks: (old.tasks as Item[]).map((t) =>
                t.id === task.id
                  ? { ...t, ...result, completed: !task.completed }
                  : t,
              ),
            }
          : old,
      );
      client.invalidateQueries({ queryKey: ["department", "hr"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update task", true);
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  async function describeProperty() {
    if (!selected) return;
    setBusy(true);
    try {
      const result = await api<{ description: string }>(
        `/operations/properties/${selected.id}/description`,
        { method: "POST" },
      );
      setSelected((old) =>
        old ? { ...old, generated_description: result.description } : old,
      );
      toast("Description generated from reviewed fields.");
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Unable to generate description",
        true,
      );
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  async function resolve() {
    if (!selected) return;
    setBusy(true);
    try {
      const result = await api<Item>(
        `/operations/properties/${selected.id}/review`,
        {
          method: "POST",
          body: { resolved_fields: JSON.parse(json), comment },
        },
      );
      setSelected(result);
      toast("Property review saved.");
      client.invalidateQueries({ queryKey: ["department", "operations"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to save review", true);
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  async function saveTemplate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api(
        editingTemplate ? `/hr/templates/${editingTemplate}` : "/hr/templates",
        {
          method: editingTemplate ? "PUT" : "POST",
          body: {
            department_id: dep,
            name: templateName,
            tasks: JSON.parse(templateJson),
          },
        },
      );
      toast("Onboarding template saved.");
      setTemplateName("");
      setEditingTemplate(null);
      client.invalidateQueries({ queryKey: ["hr-templates", dep] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to save template", true);
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  async function saveInvoice() {
    if (!selected) return;
    setBusy(true);
    try {
      const result = await api<Item>(`/finance/invoices/${selected.id}`, {
        method: "PATCH",
        body: JSON.parse(json),
      });
      setSelected(result);
      setInvoiceEdit(false);
      toast("Invoice fields updated and revalidated.");
      client.invalidateQueries({ queryKey: ["department", "finance"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to update invoice", true);
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  async function summarize(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      setJobProgress("Submitting request…");
      const result = await businessRequest(
        "/hr/summarize",
        { document_id: documentId, provider },
        (job) =>
          setJobProgress(`${human(job.status)} · Job ${job.id.slice(0, 8)}`),
      );
      setSummary(result);
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Unable to summarize document",
        true,
      );
    } finally {
      setBusy(false);
      setJobProgress("");
    }
  }
  return (
    <>
      <Heading
        title="Department hub"
        description="Purpose-built workflows for the way each team works."
      />
      <div className="department-cards">
        {domains.map((d) => (
          <button
            key={d.key}
            className={`department-tab ${current.key === d.key ? "active" : ""}`}
            onClick={() => {
              setDomain(d.key);
              setDepartment("");
              setSelected(null);
            }}
          >
            <d.icon size={20} />
            {d.name}
          </button>
        ))}
      </div>
      <BusinessMetrics departmentId={dep} domain={current.key} />
      <div className="section-heading">
        <div>
          <h2>{current.name} workspace</h2>
          <p>{current.description}</p>
        </div>
        <div className="inline-actions">
          {current.key === "hr" && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTemplatesOpen(true)}
              >
                Task templates
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setSummaryOpen(true);
                  setSummary(null);
                  setDocumentId("");
                }}
              >
                Summarize document
              </Button>
            </>
          )}
          <Button onClick={newRecord} disabled={!dep}>
            <Plus size={15} />
            {current.create}
          </Button>
        </div>
      </div>
      {current.key === "legal" && (
        <div className="notice">
          <Scale size={18} />
          <span>
            AI analysis supports your review. It does not constitute legal
            advice or replace qualified legal judgment.
          </span>
        </div>
      )}
      {current.key === "finance" && (
        <p className="text-muted" style={{ marginBottom: 18 }}>
          This workspace prepares and approves invoice records. No payments are
          executed.
        </p>
      )}
      {!dep ? (
        <ErrorState
          error={
            new Error("Your account is not assigned to a business department.")
          }
        />
      ) : records.isPending ? (
        <Loading />
      ) : records.error ? (
        <ErrorState error={records.error} retry={() => records.refetch()} />
      ) : (
        <DataTable
          items={list(records.data)}
          filterKey={(r) => jsonText(r)}
          onRow={(r) => {
            setSelected(r);
            setInvoiceEdit(false);
            setJson(jsonText(r.normalized || r.normalized_fields || {}));
            setComment("");
          }}
          columns={[
            {
              key: "title",
              label:
                current.key === "hr"
                  ? "Employee"
                  : current.key === "operations"
                    ? "Property"
                    : "Record",
              render: (r) => (
                <span className="table-primary">
                  <FileText size={17} />
                  {String(
                    r.employee_name ||
                      r.property_id ||
                      r.invoice_number ||
                      (r.data as Record<string, unknown>)?.invoice_number ||
                      r.title ||
                      r.document_name ||
                      r.id.slice(0, 12),
                  )}
                </span>
              ),
            },
            {
              key: "status",
              label: "Status",
              render: (r) => (
                <Badge
                  value={
                    r.status ||
                    r.approval_status ||
                    r.processing_status ||
                    "recorded"
                  }
                />
              ),
            },
            {
              key: "created",
              label: "Created",
              render: (r) => dateTime(r.created_at),
            },
            {
              key: "info",
              label:
                current.key === "finance"
                  ? "Total"
                  : current.key === "hr"
                    ? "Tasks"
                    : "Details",
              render: (r) =>
                current.key === "finance"
                  ? `${String(r.currency || (r.data as Record<string, unknown>)?.currency || "")} ${String(r.total || (r.data as Record<string, unknown>)?.total || "—")}`
                  : current.key === "hr"
                    ? `${((r.tasks as Item[]) || []).filter((t) => t.completed).length} / ${((r.tasks as Item[]) || []).length} complete`
                    : human(
                        r.processing_status || r.review_status || "Available",
                      ),
            },
          ]}
        />
      )}
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!busy) setOpen(next);
        }}
        title={current.create}
        description={current.description}
      >
        <form className="form-stack" onSubmit={create}>
          <Field label="Department">
            <select
              value={dep}
              onChange={(e) => setDepartment(e.target.value)}
              required
            >
              {user?.departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </Field>
          {current.key === "finance" && (
            <Field label="Entry method">
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="extract">
                  Extract from an uploaded invoice
                </option>
                <option value="manual">Enter validated invoice fields</option>
              </select>
            </Field>
          )}
          {(current.key === "finance" || current.key === "legal") && (
            <>
              <Field
                label={
                  mode === "manual"
                    ? "Source document (optional)"
                    : "Source document"
                }
              >
                <select
                  value={documentId}
                  required={mode !== "manual"}
                  onChange={(e) => setDocumentId(e.target.value)}
                >
                  <option value="">Choose an uploaded document</option>
                  {availableDocs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name || d.filename} · {d.status}
                    </option>
                  ))}
                </select>
              </Field>
              {!(current.key === "finance" && mode === "manual") && (
                <Field label="AI provider">
                  <select
                    value={provider}
                    onChange={(e) => setProvider(e.target.value)}
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </Field>
              )}
              <p className="text-muted">
                Upload your source in the Document center first. Processing must
                complete before extraction.
              </p>
            </>
          )}
          {current.key === "finance" && mode === "manual" && (
            <InvoiceFields value={json} onChange={setJson} />
          )}
          {current.key === "legal" && (
            <Field label="Compare with another contract (optional)">
              <select
                value={comparison}
                onChange={(e) => setComparison(e.target.value)}
              >
                <option value="">No comparison</option>
                {availableDocs
                  .filter((d) => d.id !== documentId)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name || d.filename}
                    </option>
                  ))}
              </select>
            </Field>
          )}
          {current.key === "hr" && (
            <>
              <Field label="Employee name">
                <input
                  value={employee}
                  onChange={(e) => setEmployee(e.target.value)}
                  required
                  maxLength={200}
                />
              </Field>
              <Field label="Employee email">
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </Field>
              <Field label="Start date">
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  required
                />
              </Field>
              <Field label="Onboarding template">
                <select
                  value={templateId}
                  onChange={(e) => setTemplateId(e.target.value)}
                >
                  <option value="">Default checklist</option>
                  {list(templates.data).map((t) => (
                    <option key={t.id} value={t.id}>
                      {String(t.name)}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          )}
          {current.key === "operations" && (
            <>
              <Field label="Property identifier">
                <input
                  value={propertyId}
                  onChange={(e) => setPropertyId(e.target.value)}
                  required
                  placeholder="PROP-001"
                />
              </Field>
              <Field
                label="Source records (JSON array)"
                hint="Use source names and their field values. Conflicts are reported for human review."
              >
                <textarea
                  className="code-editor"
                  value={json}
                  onChange={(e) => setJson(e.target.value)}
                  required
                  spellCheck={false}
                />
              </Field>
            </>
          )}
          <div className="form-actions">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button disabled={busy}>
              {busy ? <Busy>{jobProgress || "Working…"}</Busy> : current.create}
            </Button>
          </div>
        </form>
      </Dialog>
      <Dialog
        open={!!selected}
        onOpenChange={() => setSelected(null)}
        title={`${current.name} record`}
        description="Review stored results and complete the appropriate next action."
      >
        {selected && (
          <>
            <div className="inline-actions" style={{ marginBottom: 18 }}>
              <Badge
                value={
                  selected.status ||
                  selected.approval_status ||
                  selected.processing_status ||
                  "recorded"
                }
              />
              {selected.is_demo ? (
                <span className="text-muted">Seeded demonstration data</span>
              ) : null}
            </div>
            {current.key === "hr" && Array.isArray(selected.tasks) && (
              <div style={{ marginBottom: 22 }}>
                <h3>Onboarding checklist</h3>
                {(selected.tasks as Item[]).map((task) => (
                  <label
                    key={task.id}
                    className={`task-item ${task.completed ? "completed" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={Boolean(task.completed)}
                      disabled={busy}
                      onChange={() => complete(task)}
                    />
                    <span>
                      {String(task.title)}
                      {task.required_document ? (
                        <small className="text-muted">
                          {" "}
                          · {String(task.required_document)}
                        </small>
                      ) : null}
                    </span>
                  </label>
                ))}
              </div>
            )}
            <pre>{jsonText(selected)}</pre>
            {current.key === "finance" &&
              String(selected.approval_status) === "not_submitted" && (
                <div className="form-stack">
                  {invoiceEdit ? (
                    <>
                      <InvoiceFields value={json} onChange={setJson} />
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={saveInvoice}
                      >
                        Save and validate corrections
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setJson(jsonText(selected.extracted));
                        setInvoiceEdit(true);
                      }}
                    >
                      Review and correct extracted fields
                    </Button>
                  )}
                </div>
              )}
            {current.key === "operations" && (
              <div className="form-stack">
                <Field label="Resolved property fields (JSON)">
                  <textarea
                    className="code-editor"
                    value={json}
                    onChange={(e) => setJson(e.target.value)}
                  />
                </Field>
                <Field label="Review comment">
                  <textarea
                    rows={2}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                  />
                </Field>
                <div className="form-actions">
                  <Button
                    variant="outline"
                    disabled={
                      busy || String(selected.status) === "needs_review"
                    }
                    onClick={describeProperty}
                  >
                    Generate factual description
                  </Button>
                  <Button disabled={busy || !comment.trim()} onClick={resolve}>
                    {busy ? (
                      <Busy />
                    ) : (
                      <>
                        <CheckCheck size={15} />
                        Save human review
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}
            {(current.key === "finance" || current.key === "hr") && (
              <div className="form-actions">
                <Button
                  disabled={
                    busy ||
                    [
                      "approved",
                      "pending",
                      "pending_approval",
                      "rejected",
                    ].includes(
                      String(selected.approval_status || selected.status),
                    )
                  }
                  onClick={submit}
                >
                  {busy ? (
                    <Busy />
                  ) : (
                    <>
                      <Send size={15} />
                      Submit for approval
                    </>
                  )}
                </Button>
              </div>
            )}
          </>
        )}
      </Dialog>
      <Dialog
        open={templatesOpen}
        onOpenChange={setTemplatesOpen}
        title="Onboarding task templates"
        description="Configure repeatable checklists for new employees."
      >
        {templates.isPending ? (
          <Loading />
        ) : templates.error ? (
          <ErrorState error={templates.error} />
        ) : (
          <ul className="plain-list">
            {list(templates.data).map((t) => (
              <li key={t.id}>
                <BriefcaseBusiness
                  size={14}
                  style={{ display: "inline", marginRight: 8 }}
                />
                {String(t.name)}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setEditingTemplate(t.id);
                    setTemplateName(String(t.name));
                    setTemplateJson(jsonText(t.tasks));
                  }}
                >
                  Edit
                </Button>
                <pre>{jsonText(t.tasks)}</pre>
              </li>
            ))}
          </ul>
        )}
        <form className="form-stack" onSubmit={saveTemplate}>
          <Field label="Template name">
            <input
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              required
            />
          </Field>
          <Field label="Tasks (JSON array)">
            <textarea
              className="code-editor"
              value={templateJson}
              onChange={(e) => setTemplateJson(e.target.value)}
              required
            />
          </Field>
          <Button disabled={busy}>
            {busy ? <Busy /> : "Save task template"}
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={summaryOpen}
        onOpenChange={(next) => {
          if (!busy) setSummaryOpen(next);
        }}
        title="Summarize an HR document"
        description="The assistant can access only documents allowed by your department and document permissions."
      >
        <form className="form-stack" onSubmit={summarize}>
          <Field label="Source document">
            <select
              value={documentId}
              onChange={(e) => setDocumentId(e.target.value)}
              required
            >
              <option value="">Choose document</option>
              {availableDocs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name || d.filename}
                </option>
              ))}
            </select>
          </Field>
          <Button disabled={busy}>
            {busy ? (
              <Busy>{jobProgress || "Working…"}</Busy>
            ) : (
              "Generate summary"
            )}
          </Button>
        </form>
        {summary !== null && <pre>{jsonText(summary)}</pre>}
      </Dialog>
    </>
  );
}
