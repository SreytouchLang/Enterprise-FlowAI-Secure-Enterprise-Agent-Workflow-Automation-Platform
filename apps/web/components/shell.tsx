"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  Bell,
  BookOpen,
  Bot,
  Building2,
  ChartNoAxesCombined,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  FileText,
  GitBranch,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError, clearSession } from "@/lib/api";
import { useToast, useUser } from "./providers";
import { Button } from "./ui/button";
import { ErrorState, Loading } from "./common";
const navigation = [
  { label: "Overview", href: "/", icon: LayoutDashboard },
  { label: "AI workspace", href: "/workspace", icon: MessageSquare },
  { label: "Agents", href: "/agents", icon: Bot },
  { label: "Workflows", href: "/workflows", icon: GitBranch },
  { label: "Document center", href: "/documents", icon: FileText },
  { label: "Approvals", href: "/approvals", icon: ShieldCheck },
];
const management = [
  { label: "Background jobs", href: "/jobs", icon: RefreshCw },
  { label: "Department hub", href: "/departments", icon: Building2 },
  { label: "Analytics", href: "/analytics", icon: ChartNoAxesCombined },
  { label: "Audit log", href: "/audit", icon: Activity },
  { label: "Settings", href: "/settings", icon: Settings2 },
];
const routePermissions: Record<string, string> = {
  "/": "analytics:read",
  "/workspace": "conversations:write",
  "/agents": "agents:read",
  "/workflows": "workflows:read",
  "/documents": "documents:read",
  "/approvals": "approvals:read",
  "/departments": "workflows:read",
  "/analytics": "analytics:read",
  "/audit": "audit:read",
  "/jobs": "workflows:read",
};
export function Shell({ children }: { children: React.ReactNode }) {
  const { data: user, error, isPending, refetch } = useUser();
  const pathname = usePathname();
  const router = useRouter();
  const [mobile, setMobile] = useState(false);
  const [dark, setDark] = useState(false);
  const toast = useToast();
  useEffect(() => {
    const saved = localStorage.getItem("ef-theme");
    const isDark = saved === "dark";
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
    setDark(isDark);
  }, []);
  useEffect(() => {
    if (
      user &&
      pathname === "/" &&
      !user.permissions.includes("analytics:read")
    ) {
      router.replace(
        user.permissions.includes("agents:read")
          ? "/agents"
          : user.permissions.includes("audit:read")
            ? "/audit"
            : "/settings",
      );
    }
  }, [user, pathname, router]);
  const allowed = (href: string) =>
    !routePermissions[href] ||
    !!user?.permissions.includes(routePermissions[href]);
  function theme() {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    localStorage.setItem("ef-theme", next ? "dark" : "light");
  }
  async function logout() {
    try {
      const result = await api<{ logout_url?: string }>("/auth/logout", {
        method: "POST",
      });
      clearSession();
      window.location.assign(result?.logout_url || "/");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not sign out", true);
    }
  }
  if (isPending)
    return (
      <div className="auth-screen">
        <div className="brand-mark">
          <GitBranch />
        </div>
        <h2>EnterpriseFlow AI</h2>
        <p>Connecting to your secure workspace…</p>
        <div className="auth-loader" />
      </div>
    );
  if (!user)
    return (
      <div className="login-screen">
        <section className="login-story">
          <Link href="/" className="brand">
            <span className="brand-mark">
              <GitBranch size={23} />
            </span>
            <span>
              EnterpriseFlow<span className="brand-ai">AI</span>
            </span>
          </Link>
          <div>
            <p className="eyebrow">YOUR TEAM. WORKING FORWARD.</p>
            <h1>
              Intelligent work.
              <br />
              Human oversight.
            </h1>
            <p>
              A shared workspace for knowledge, purpose-built agents, and
              workflows your team can trust.
            </p>
            <div className="login-capabilities">
              <span>
                <BookOpen />
                Grounded in your knowledge
              </span>
              <span>
                <ShieldCheck />
                Governed by your permissions
              </span>
              <span>
                <GitBranch />
                Designed for your processes
              </span>
            </div>
          </div>
          <small>EnterpriseFlow AI · Secure enterprise automation</small>
        </section>
        <section className="login-form">
          <div className="login-card">
            <span className="icon-tile">
              <Building2 size={24} />
            </span>
            <h2>Welcome to your workspace</h2>
            <p>
              Sign in with your organization’s identity provider to continue.
            </p>
            {error && !(error instanceof ApiError && error.status === 401) && (
              <ErrorState error={error} retry={() => refetch()} />
            )}
            <Button asChild>
              <a href="/api/v1/auth/login">
                Continue with SSO <ArrowUpRight size={17} />
              </a>
            </Button>
            <div className="login-note">
              <ShieldCheck size={16} />
              <span>
                Your organization manages your account, department access, and
                permissions.
              </span>
            </div>
          </div>
        </section>
      </div>
    );
  const current =
    [
      ...navigation,
      ...management,
      { href: "/notifications", label: "Notifications" },
    ].find((n) => n.href === pathname)?.label || "Workspace";
  return (
    <div className="app-layout">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={`sidebar ${mobile ? "sidebar-open" : ""}`}>
        <Link href="/" className="brand">
          <span className="brand-mark">
            <GitBranch size={21} />
          </span>
          <span>
            EnterpriseFlow<span className="brand-ai">AI</span>
          </span>
        </Link>
        <div className="workspace-selector">
          <span className="workspace-avatar">EF</span>
          <div>
            <strong>Enterprise workspace</strong>
            <small>
              {user.departments.map((d) => d.name).join(", ") ||
                "Platform administration"}
            </small>
          </div>
          <ChevronDown size={14} />
        </div>
        <p className="nav-caption">WORKSPACE</p>
        <nav aria-label="Main navigation">
          {navigation
            .filter((n) => allowed(n.href))
            .map((n) => (
              <Link
                key={n.href}
                href={n.href}
                onClick={() => setMobile(false)}
                className={`nav-item ${pathname === n.href ? "active" : ""}`}
              >
                <n.icon size={18} />
                <span>{n.label}</span>
                {pathname === n.href && <span className="active-dot" />}
              </Link>
            ))}
        </nav>
        <p className="nav-caption management-caption">MANAGE</p>
        <nav aria-label="Management navigation">
          {management
            .filter((n) => allowed(n.href))
            .map((n) => (
              <Link
                key={n.href}
                href={n.href}
                onClick={() => setMobile(false)}
                className={`nav-item ${pathname === n.href ? "active" : ""}`}
              >
                <n.icon size={18} />
                <span>{n.label}</span>
              </Link>
            ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-card">
            <ShieldCheck size={18} />
            <div>
              <strong>Built for trust</strong>
              <p>
                Department access enforced
                <br />
                at every step.
              </p>
            </div>
          </div>
          <a
            className="nav-item"
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
          >
            <CircleHelp size={17} />
            <span>API documentation</span>
            <ArrowUpRight size={13} />
          </a>
          <button className="user-profile" onClick={logout} title="Sign out">
            <span className="avatar">
              {user.name?.slice(0, 2).toUpperCase() || "EF"}
            </span>
            <div>
              <strong>{user.name}</strong>
              <small>
                {user.roles.map((r) => r.replaceAll("_", " ")).join(", ")}
              </small>
            </div>
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <div className="main-wrap">
        <header className="topbar">
          <div className="breadcrumbs">
            <Button
              variant="ghost"
              size="icon"
              className="mobile-toggle"
              aria-label="Open navigation"
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={19} /> : <Menu size={19} />}
            </Button>
            <Building2 size={16} />
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{current}</strong>
          </div>
          <div className="topbar-actions">
            <span className="access-pill">
              <ShieldCheck size={13} />
              Permission-aware workspace
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={theme}
              aria-label={
                dark ? "Switch to light theme" : "Switch to dark theme"
              }
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </Button>
            <Button asChild variant="ghost" size="icon">
              <Link href="/notifications" aria-label="Notifications">
                <Bell size={18} />
              </Link>
            </Button>
            <Link
              href="/settings"
              className="avatar small-avatar"
              aria-label="Your profile"
            >
              {user.name?.slice(0, 2).toUpperCase() || "EF"}
            </Link>
          </div>
        </header>
        <main id="main" className="main-content">
          {pathname === "/" && !allowed("/") ? <Loading /> : children}
        </main>
        <footer className="footer">
          <span>
            <Sparkles size={13} />
            EnterpriseFlow AI
          </span>
          <span>Intelligence with accountability</span>
        </footer>
      </div>
    </div>
  );
}
