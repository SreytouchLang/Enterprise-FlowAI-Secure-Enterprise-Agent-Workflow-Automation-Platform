"use client";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Inbox,
  LoaderCircle,
  RefreshCw,
  Search,
} from "lucide-react";
import { useState } from "react";
import { Button } from "./ui/button";
import { ApiError, human } from "@/lib/api";
export function Heading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow || "ENTERPRISE WORKSPACE"}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {action}
    </div>
  );
}
export function Loading() {
  return (
    <div aria-label="Loading content" aria-busy="true" className="loading-grid">
      {[0, 1, 2].map((i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  );
}
export function ErrorState({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={22} />
      <div>
        <strong>
          {error instanceof ApiError && error.status === 403
            ? "Access restricted"
            : "We couldn’t load this information"}
        </strong>
        <p>
          {error instanceof Error
            ? error.message
            : "An unexpected error occurred."}
        </p>
      </div>
      {retry && (
        <Button variant="outline" size="sm" onClick={retry}>
          <RefreshCw size={14} />
          Retry
        </Button>
      )}
    </div>
  );
}
export function Empty({
  title = "Nothing here yet",
  description = "New activity will appear here.",
  action,
}: {
  title?: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Inbox size={24} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Badge({ value }: { value: unknown }) {
  const label = human(value);
  return (
    <span
      className={`badge badge-${String(value).toLowerCase().replaceAll(" ", "_")}`}
    >
      <span />
      {label}
    </span>
  );
}
export function Busy({ children }: { children?: React.ReactNode }) {
  return (
    <>
      <LoaderCircle size={15} className="spin" />
      {children || "Working…"}
    </>
  );
}
export function Field({
  label,
  error,
  children,
  hint,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
      {error && (
        <small className="field-error" role="alert">
          {error}
        </small>
      )}
    </label>
  );
}
export function DataTable<T extends { id: string }>({
  items,
  columns,
  filterKey,
  emptyTitle = "No records found",
  onRow,
  pagination,
  search: remoteSearch,
  loading = false,
}: {
  items: T[];
  columns: {
    key: string;
    label: string;
    render: (item: T) => React.ReactNode;
  }[];
  filterKey?: (item: T) => string;
  emptyTitle?: string;
  onRow?: (item: T) => void;
  pagination?: {
    page: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
  };
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
  };
  loading?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const filtered = pagination ? items : items.filter(
    (i) =>
      !filterKey || filterKey(i).toLowerCase().includes(search.toLowerCase()),
  );
  const size = pagination?.pageSize ?? 8;
  const total = pagination?.total ?? filtered.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const current = pagination?.page ?? Math.min(page, pages - 1);
  const visible = pagination ? filtered : filtered.slice(current * size, (current + 1) * size);
  const changePage = pagination?.onPageChange ?? setPage;
  const searchValue = remoteSearch?.value ?? search;
  return (
    <div className="panel table-panel" aria-busy={loading}>
      {(filterKey || remoteSearch || pagination) && (
        <div className="table-toolbar">
          {(filterKey || remoteSearch) && (
          <div className="search-field">
            <Search size={16} />
            <input
              aria-label="Filter records"
              placeholder={remoteSearch?.placeholder ?? "Search records…"}
              value={searchValue}
              onChange={(e) => {
                if (remoteSearch) {
                  remoteSearch.onChange(e.target.value);
                  return;
                }
                setSearch(e.target.value);
                setPage(0);
              }}
            />
          </div>
          )}
          <span aria-live="polite">{loading ? "Loading records…" : `${total} records`}</span>
        </div>
      )}
      {loading ? <Loading /> : visible.length ? (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c.key}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                    <tr key={item.id}>
                      {columns.map((c, index) => (
                        <td key={c.key}>
                          {index === 0 && onRow ? (
                            <button
                              className="table-link"
                              onClick={() => onRow(item)}
                            >
                              {c.render(item)}
                            </button>
                          ) : (
                            c.render(item)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <Empty
          title={emptyTitle}
          description={
            searchValue
              ? "Try a different search term."
              : "Records will appear after your team starts working."
          }
        />
      )}
      {!loading && (total > 0 || current > 0) && <div className="pagination">
            <span>
              Showing {visible.length ? current * size + 1 : 0}–
              {visible.length ? current * size + visible.length : 0} of{" "}
              {total}
            </span>
            <div>
              <Button
                variant="outline"
                size="icon"
                aria-label="Previous page"
                disabled={current === 0}
                onClick={() => changePage(current - 1)}
              >
                <ArrowLeft size={14} />
              </Button>
              <span>
                {current + 1} / {pages}
              </span>
              <Button
                variant="outline"
                size="icon"
                aria-label="Next page"
                disabled={current + 1 >= pages}
                onClick={() => changePage(current + 1)}
              >
                <ArrowRight size={14} />
              </Button>
            </div>
          </div>}
    </div>
  );
}
