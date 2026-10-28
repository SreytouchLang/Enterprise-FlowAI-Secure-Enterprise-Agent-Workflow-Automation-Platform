"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, UserRound, UserRoundCog } from "lucide-react";
import { useState } from "react";
import { api, Department, list, Page } from "@/lib/api";
import { Badge, Busy, DataTable, ErrorState, Field, Loading } from "./common";
import { useToast, useUser } from "./providers";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
type Member = {
  id: string;
  name: string;
  email: string;
  active: boolean;
  roles: string[];
  memberships: { department_id: string; role: string }[];
};
export function Members() {
  const { data: user } = useUser();
  const enabled = !!user?.permissions.includes("members:manage");
  const admin = !!user?.permissions.includes("platform:admin");
  const query = useQuery({
    queryKey: ["members"],
    queryFn: () => api<Page<Member>>("/users"),
    enabled,
  });
  const departments = useQuery({
    queryKey: ["departments"],
    queryFn: () => api<Page<Department>>("/departments"),
    enabled,
  });
  const toast = useToast();
  const client = useQueryClient();
  const [create, setCreate] = useState(false);
  const [selected, setSelected] = useState<Member | null>(null);
  const [subject, setSubject] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [department, setDepartment] = useState("");
  const [role, setRole] = useState("employee");
  const [busy, setBusy] = useState(false);
  const [deactivate, setDeactivate] = useState(false);
  async function onboard(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/users", { method: "POST", body: { subject, name, email } });
      toast(
        "Identity onboarded. Assign a department to grant business access.",
      );
      setCreate(false);
      setSubject("");
      setName("");
      setEmail("");
      client.invalidateQueries({ queryKey: ["members"] });
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Unable to onboard identity",
        true,
      );
    } finally {
      setBusy(false);
    }
  }
  async function membership(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    try {
      await api(`/users/${selected.id}/membership`, {
        method: "PUT",
        body: { department_id: department, role },
      });
      toast("Department membership updated.");
      setSelected(null);
      client.invalidateQueries({ queryKey: ["members"] });
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Unable to update membership",
        true,
      );
    } finally {
      setBusy(false);
    }
  }
  async function removeMembership(id: string) {
    if (!selected) return;
    setBusy(true);
    try {
      await api(`/users/${selected.id}/membership/${id}`, { method: "DELETE" });
      setSelected((old) =>
        old
          ? {
              ...old,
              memberships: old.memberships.filter(
                (m) => m.department_id !== id,
              ),
            }
          : old,
      );
      toast("Department access removed.");
      client.invalidateQueries({ queryKey: ["members"] });
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Unable to remove membership",
        true,
      );
    } finally {
      setBusy(false);
    }
  }
  async function toggleActive() {
    if (!selected) return;
    setBusy(true);
    try {
      await api(`/users/${selected.id}`, {
        method: "PATCH",
        body: { active: !selected.active },
      });
      toast(
        selected.active
          ? "Account deactivated and application sessions revoked."
          : "Account activated.",
      );
      setDeactivate(false);
      setSelected(null);
      client.invalidateQueries({ queryKey: ["members"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to update account", true);
    } finally {
      setBusy(false);
    }
  }
  if (!enabled) return null;
  return (
    <section style={{ marginTop: 28 }}>
      <div className="section-heading">
        <div>
          <h2>Team members</h2>
          <p>
            Explicit department memberships determine access to business data.
          </p>
        </div>
        {admin && (
          <Button variant="outline" onClick={() => setCreate(true)}>
            <Plus size={15} />
            Onboard identity
          </Button>
        )}
      </div>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorState error={query.error} />
      ) : (
        <DataTable
          items={list(query.data)}
          filterKey={(m) => `${m.name} ${m.email}`}
          onRow={(m) => {
            setSelected(m);
            setDepartment(
              m.memberships[0]?.department_id ||
                list(departments.data)[0]?.id ||
                "",
            );
            setRole(m.memberships[0]?.role || "employee");
          }}
          columns={[
            {
              key: "name",
              label: "Member",
              render: (m) => (
                <span className="table-primary">
                  <UserRound size={16} />
                  {m.name}
                </span>
              ),
            },
            { key: "email", label: "Email", render: (m) => m.email },
            {
              key: "status",
              label: "Account",
              render: (m) => <Badge value={m.active ? "active" : "disabled"} />,
            },
            {
              key: "departments",
              label: "Memberships",
              render: (m) =>
                m.memberships
                  .map(
                    (x) =>
                      `${list(departments.data).find((d) => d.id === x.department_id)?.name || x.department_id} (${x.role.replaceAll("_", " ")})`,
                  )
                  .join(", ") || "No department access",
            },
          ]}
        />
      )}
      <Dialog
        open={create}
        onOpenChange={setCreate}
        title="Onboard an identity"
        description="Create the account in your organization’s identity provider first, then link its OIDC subject here."
      >
        <form className="form-stack" onSubmit={onboard}>
          <Field label="Identity provider subject (sub)">
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              required
              maxLength={255}
            />
          </Field>
          <Field label="Display name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={150}
            />
          </Field>
          <Field label="Email">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>
          <div className="form-actions">
            <Button disabled={busy}>
              {busy ? <Busy /> : "Onboard identity"}
            </Button>
          </div>
        </form>
      </Dialog>
      <Dialog
        open={!!selected && !deactivate}
        onOpenChange={() => setSelected(null)}
        title={`Manage ${selected?.name || "member"}`}
        description="Grant only the department role needed for this person’s work."
      >
        {selected && (
          <>
            <ul className="plain-list">
              {selected.memberships.map((m) => (
                <li key={m.department_id} className="inline-actions">
                  <span style={{ flex: 1 }}>
                    {list(departments.data).find(
                      (d) => d.id === m.department_id,
                    )?.name || m.department_id}{" "}
                    · {m.role.replaceAll("_", " ")}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => removeMembership(m.department_id)}
                  >
                    Remove access
                  </Button>
                </li>
              ))}
            </ul>
            <form
              className="form-stack"
              style={{ marginTop: 20 }}
              onSubmit={membership}
            >
              <Field label="Department">
                <select
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  required
                >
                  {list(departments.data).map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Role">
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="employee">Employee</option>
                  <option value="manager">Manager</option>
                  {admin && (
                    <option value="department_admin">
                      Department administrator
                    </option>
                  )}
                  <option value="auditor">Auditor</option>
                </select>
              </Field>
              <div className="form-actions">
                {admin && selected.id !== user?.id && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() => setDeactivate(true)}
                  >
                    {selected.active
                      ? "Deactivate account"
                      : "Activate account"}
                  </Button>
                )}
                <Button disabled={busy || !department}>
                  {busy ? (
                    <Busy />
                  ) : (
                    <>
                      <UserRoundCog size={15} />
                      Save membership
                    </>
                  )}
                </Button>
              </div>
            </form>
          </>
        )}
      </Dialog>
      <Dialog
        open={deactivate}
        onOpenChange={setDeactivate}
        title={
          selected?.active
            ? "Deactivate this account?"
            : "Activate this account?"
        }
        description={
          selected?.active
            ? "The user will lose application access and existing application sessions will be revoked."
            : "The user will regain application access using their assigned department memberships."
        }
      >
        <div className="form-actions">
          <Button variant="outline" onClick={() => setDeactivate(false)}>
            Cancel
          </Button>
          <Button
            variant={selected?.active ? "destructive" : "default"}
            disabled={busy}
            onClick={toggleActive}
          >
            {busy ? <Busy /> : "Confirm account change"}
          </Button>
        </div>
      </Dialog>
    </section>
  );
}
