"use client";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api, ApiError, dateTime, human } from "@/lib/api";
import { Empty, ErrorState, Loading } from "./common";
import { useUser } from "./providers";
import { Button } from "./ui/button";
type Report = Record<string, unknown> & {
  evaluated_at: string;
  mode: string;
  notes: string[];
};
export function Evaluation() {
  const { data: user } = useUser();
  const enabled = !!user?.permissions.includes("platform:admin");
  const query = useQuery({
    queryKey: ["evaluation-latest"],
    queryFn: () => api<Report>("/evaluations/latest"),
    enabled,
    retry: false,
  });
  if (!enabled) return null;
  return (
    <section className="panel content-card" style={{ marginTop: 24 }}>
      <div className="section-heading">
        <div>
          <h2>Offline fixture evaluation</h2>
          <p>
            Scheduled checks against synthetic inputs. These scores do not
            measure live-model answer quality.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>
          <RefreshCw size={13} />
          Refresh
        </Button>
      </div>
      {query.isPending ? (
        <Loading />
      ) : query.error instanceof ApiError && query.error.status === 404 ? (
        <Empty
          title="No evaluation report yet"
          description="The latest scheduled offline report will appear here after the evaluation worker completes."
        />
      ) : query.error ? (
        <ErrorState error={query.error} />
      ) : (
        query.data && (
          <>
            <dl className="detail-grid">
              <div>
                <dt>Evaluated</dt>
                <dd>{dateTime(query.data.evaluated_at)}</dd>
              </div>
              <div>
                <dt>Mode</dt>
                <dd>{human(query.data.mode)}</dd>
              </div>
            </dl>
            <div className="settings-grid">
              {Object.entries(query.data)
                .filter(([, value]) => typeof value === "number")
                .map(([key, value]) => (
                  <div key={key} className="settings-row">
                    <span>{human(key)}</span>
                    <strong>{String(value)}</strong>
                  </div>
                ))}
            </div>
            <ul className="plain-list">
              {query.data.notes.map((note) => (
                <li key={note} className="text-muted">
                  {note}
                </li>
              ))}
            </ul>
          </>
        )
      )}
    </section>
  );
}
