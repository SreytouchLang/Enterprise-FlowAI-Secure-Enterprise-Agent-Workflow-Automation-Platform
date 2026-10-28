"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  FileText,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useState } from "react";
import { api, Citation, dateTime, Document, list, Page } from "@/lib/api";
import {
  Badge,
  Busy,
  DataTable,
  Empty,
  ErrorState,
  Field,
  Heading,
  Loading,
} from "./common";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { useToast, useUser } from "./providers";
export function Documents() {
  const client = useQueryClient();
  const toast = useToast();
  const { data: user } = useUser();
  const [upload, setUpload] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [department, setDepartment] = useState("");
  const [visibility, setVisibility] = useState("department");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState<Document | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Citation[] | null>(null);
  const [searchError, setSearchError] = useState<Error | null>(null);
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<Page<Document>>("/documents?limit=100"),
    refetchInterval: 15000,
  });
  const detail = useQuery({
    queryKey: ["document", selected?.id],
    queryFn: () => api<Document>(`/documents/${selected?.id}`),
    enabled: !!selected,
  });
  const dep = department || user?.departments[0]?.id || "";
  async function submitUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !dep) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("department_id", dep);
      form.append("visibility", visibility);
      await api("/documents/upload", { method: "POST", body: form });
      toast("Document uploaded. Processing will run in the background.");
      setUpload(false);
      setFile(null);
      client.invalidateQueries({ queryKey: ["documents"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Upload failed", true);
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!deleting) return;
    setBusy(true);
    try {
      await api(`/documents/${deleting.id}`, { method: "DELETE" });
      toast("Document deleted.");
      setDeleting(null);
      setSelected(null);
      client.invalidateQueries({ queryKey: ["documents"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Delete failed", true);
    } finally {
      setBusy(false);
    }
  }
  async function reindex(document: Document) {
    setBusy(true);
    try {
      await api(`/documents/${document.id}/reindex`, { method: "POST" });
      toast("Reindex requested.");
      client.invalidateQueries({ queryKey: ["documents"] });
      client.invalidateQueries({ queryKey: ["document", document.id] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Reindex failed", true);
    } finally {
      setBusy(false);
    }
  }
  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || !dep) return;
    setBusy(true);
    setSearchError(null);
    try {
      const response = await api<{ items: Citation[] }>("/search", {
        method: "POST",
        body: { query, department_id: dep, limit: 10 },
      });
      setResults(response.items);
    } catch (e) {
      setSearchError(e instanceof Error ? e : new Error("Search failed"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Document center"
        description="Your team’s knowledge, organized and accessible to the right people."
        action={
          <Button onClick={() => setUpload(true)}>
            <Upload size={16} />
            Upload document
          </Button>
        }
      />
      <form
        className="panel content-card"
        style={{ marginBottom: 23 }}
        onSubmit={search}
      >
        <div className="inline-actions">
          <div className="search-field" style={{ maxWidth: "none" }}>
            <Search size={17} />
            <input
              aria-label="Semantic document search"
              placeholder="Search across your department’s knowledge…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select
            aria-label="Search department"
            value={dep}
            onChange={(e) => setDepartment(e.target.value)}
          >
            {user?.departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
          <Button disabled={busy || !query.trim() || !dep} type="submit">
            {busy ? <Busy /> : "Search knowledge"}
          </Button>
          {results !== null && (
            <Button
              variant="ghost"
              type="button"
              onClick={() => setResults(null)}
            >
              Clear
            </Button>
          )}
        </div>
      </form>
      {searchError && <ErrorState error={searchError} />}{" "}
      {results !== null && (
        <div className="panel content-card" style={{ marginBottom: 23 }}>
          <h2>Knowledge search results</h2>
          {results.length ? (
            results.map((r, i) => (
              <div
                key={`${r.chunk_id}-${i}`}
                className="document-preview"
                style={{ marginBottom: 12 }}
              >
                <button
                  className="text-link"
                  onClick={() => setSelected({ id: r.document_id } as Document)}
                >
                  <FileText size={14} />
                  {r.document_name} · {r.location}
                </button>
                <p className="prose-text" style={{ marginTop: 10 }}>
                  {r.excerpt}
                </p>
              </div>
            ))
          ) : (
            <Empty
              title="No matching knowledge"
              description="Try a different query or upload an authorized source document."
            />
          )}
        </div>
      )}
      {documents.isPending ? (
        <Loading />
      ) : documents.error ? (
        <ErrorState error={documents.error} retry={() => documents.refetch()} />
      ) : (
        <DataTable
          items={list(documents.data)}
          filterKey={(d) => `${d.name || d.filename} ${d.status}`}
          onRow={setSelected}
          columns={[
            {
              key: "name",
              label: "Document",
              render: (d) => (
                <span className="table-primary">
                  <FileText size={17} />
                  {d.name || d.filename || "Untitled document"}
                </span>
              ),
            },
            {
              key: "status",
              label: "Processing",
              render: (d) => <Badge value={d.status} />,
            },
            { key: "visibility", label: "Access", render: (d) => d.visibility },
            {
              key: "created",
              label: "Uploaded",
              render: (d) => dateTime(d.created_at),
            },
            {
              key: "actions",
              label: "Actions",
              render: (d) => (
                <div className="table-actions">
                  <Button asChild variant="ghost" size="icon">
                    <a
                      href={`/api/v1/documents/${d.id}/download`}
                      aria-label={`Download ${d.name || d.filename}`}
                    >
                      <Download size={15} />
                    </a>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={
                      d.owner_id !== user?.id &&
                      !user?.permissions.includes("documents:delete")
                    }
                    aria-label={`Delete ${d.name || d.filename}`}
                    onClick={() => setDeleting(d)}
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
              ),
            },
          ]}
        />
      )}
      <Dialog
        open={upload}
        onOpenChange={setUpload}
        title="Add to your knowledge"
        description="Upload a PDF, text, Markdown, or Word document. Access is checked before storage and retrieval."
      >
        <form className="form-stack" onSubmit={submitUpload}>
          <Field label="Document">
            <input
              type="file"
              className="file-input"
              required
              accept=".pdf,.txt,.md,.docx,.csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </Field>
          <div className="form-grid">
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
            <Field label="Visibility">
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value)}
              >
                <option value="department">
                  Authorized department members
                </option>
                <option value="private">Private to me</option>
              </select>
            </Field>
          </div>
          <div className="form-actions">
            <Button
              variant="outline"
              type="button"
              onClick={() => setUpload(false)}
            >
              Cancel
            </Button>
            <Button disabled={busy || !file || !dep}>
              {busy ? (
                <Busy />
              ) : (
                <>
                  <Upload size={15} />
                  Upload document
                </>
              )}
            </Button>
          </div>
        </form>
      </Dialog>
      <Dialog
        open={!!selected}
        onOpenChange={() => setSelected(null)}
        title={
          detail.data?.name ||
          detail.data?.filename ||
          selected?.name ||
          "Document details"
        }
      >
        {detail.isPending ? (
          <Loading />
        ) : detail.error ? (
          <ErrorState error={detail.error} />
        ) : (
          detail.data && (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Processing status</dt>
                  <dd>
                    <Badge value={detail.data.status} />
                  </dd>
                </div>
                <div>
                  <dt>Access</dt>
                  <dd>{detail.data.visibility}</dd>
                </div>
                <div>
                  <dt>Uploaded</dt>
                  <dd>{dateTime(detail.data.created_at)}</dd>
                </div>
                <div>
                  <dt>Versions</dt>
                  <dd>{detail.data.versions?.length ?? 1}</dd>
                </div>
              </dl>
              {(detail.data.error || detail.data.error_code) && (
                <p className="danger-text">
                  {detail.data.error || detail.data.error_code}
                </p>
              )}
              <div className="document-preview prose-text">
                {detail.data.extracted_text ||
                  detail.data.text ||
                  detail.data.preview ||
                  "A text preview will appear once document processing completes."}
              </div>
              <div className="form-actions">
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => reindex(detail.data!)}
                >
                  <RefreshCw size={14} />
                  Reindex
                </Button>
                <Button asChild>
                  <a href={`/api/v1/documents/${detail.data.id}/download`}>
                    <Download size={15} />
                    Download original
                  </a>
                </Button>
              </div>
            </>
          )
        )}
      </Dialog>
      <Dialog
        open={!!deleting}
        onOpenChange={() => setDeleting(null)}
        title="Delete this document?"
        description="The original file and its searchable content will be removed. This action cannot be undone."
      >
        <p className="prose-text">{deleting?.name || deleting?.filename}</p>
        <div className="form-actions">
          <Button variant="outline" onClick={() => setDeleting(null)}>
            Cancel
          </Button>
          <Button variant="destructive" disabled={busy} onClick={remove}>
            {busy ? <Busy /> : "Delete document"}
          </Button>
        </div>
      </Dialog>
    </>
  );
}
