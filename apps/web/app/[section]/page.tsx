import { notFound } from "next/navigation";
import { Agents } from "@/components/agents";
import { Approvals } from "@/components/approvals";
import { Departments } from "@/components/departments";
import { Documents } from "@/components/documents";
import {
  Analytics,
  Audit,
  Notifications,
  Settings,
} from "@/components/management";
import { Workflows } from "@/components/workflows";
import { Jobs } from "@/components/jobs";
import { Workspace } from "@/components/workspace";
const pages = {
  jobs: Jobs,
  workspace: Workspace,
  agents: Agents,
  approvals: Approvals,
  departments: Departments,
  documents: Documents,
  analytics: Analytics,
  audit: Audit,
  notifications: Notifications,
  settings: Settings,
  workflows: Workflows,
};
export function generateStaticParams() {
  return Object.keys(pages).map((section) => ({ section }));
}
export default async function SectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!Object.hasOwn(pages, section)) notFound();
  const Page = pages[section as keyof typeof pages];
  return <Page />;
}
