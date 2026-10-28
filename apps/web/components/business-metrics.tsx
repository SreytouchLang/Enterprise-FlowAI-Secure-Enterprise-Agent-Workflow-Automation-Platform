"use client";
import { useQuery } from "@tanstack/react-query";
import { api, human } from "@/lib/api";
import { ErrorState, Loading } from "./common";
type BusinessOverview = {
  finance: Record<string, number | null>;
  hr: Record<string, number | null>;
  operations: Record<string, number | null>;
  includes_seeded_demonstration_data: boolean;
};
export function BusinessMetrics({
  departmentId,
  domain,
}: {
  departmentId: string;
  domain: string;
}) {
  const query = useQuery({
    queryKey: ["business-overview", departmentId],
    queryFn: () =>
      api<BusinessOverview>(
        `/business/overview?department_id=${encodeURIComponent(departmentId)}`,
      ),
    enabled: !!departmentId && domain !== "legal",
    refetchInterval: 15000,
  });
  if (domain === "legal" || !departmentId) return null;
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  const metrics = query.data?.[domain as "finance" | "hr" | "operations"];
  return metrics ? (
    <>
      <div className="metric-grid">
        {Object.entries(metrics).map(([key, value]) => (
          <div key={key} className="metric-card">
            <div style={{ textTransform: "capitalize" }}>{human(key)}</div>
            <strong>
              {value === null
                ? "—"
                : new Intl.NumberFormat(undefined, {
                    maximumFractionDigits: 1,
                  }).format(value)}
            </strong>
            <small>
              {key.endsWith("_ms")
                ? "Milliseconds · recorded processing"
                : "From stored department records"}
            </small>
          </div>
        ))}
      </div>
      {query.data?.includes_seeded_demonstration_data && (
        <p className="text-muted" style={{ marginBottom: 20 }}>
          These department totals include clearly labeled synthetic
          demonstration records.
        </p>
      )}
    </>
  ) : null;
}
