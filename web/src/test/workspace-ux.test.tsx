import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import { AppShell } from "@/components/app-shell";
import { WorkspaceCreateForm } from "@/components/workspace-create-form";
import { WorkspaceSettingsForm } from "@/components/workspace-settings-form";
import type { BootstrapOrganization, WorkspaceDetail } from "@/lib/types";

const organization: BootstrapOrganization = {
  organization_id: "org-1",
  name: "Example Operations",
  slug: "example-operations",
  role: "admin",
  membership_state: "active",
  permissions: ["workspace.read", "workspace.create", "workspace.update"],
  workspaces: [{ workspace_id: "workspace-1", name: "Production", slug: "production" }],
};

const detail: WorkspaceDetail = {
  workspace: {
    workspace_id: "workspace-1", organization_id: "org-1", name: "Production", slug: "production",
    description: "Production operations", state: "active", version: 4,
    created_at: "2026-09-25T12:00:00Z", updated_at: "2026-09-25T12:00:00Z",
  },
  configuration: { schema_version: 1, version: 3, rag_top_k: 8, llm_temperature: 0.2, updated_at: "2026-09-25T12:00:00Z" },
};

describe("organization and workspace UX", () => {
  it("shows authoritative role and active workspace context", () => {
    const html = renderToStaticMarkup(<AppShell organizations={[organization]} organization={organization} workspace={detail.workspace} user={{ displayName: "Amina", email: "amina@example.com" }} csrfToken="csrf"><p>Content</p></AppShell>);
    expect(html).toContain("Example Operations");
    expect(html).toContain("admin");
    expect(html).toContain("Production");
    expect(html).toContain("Settings");
    expect(html).not.toContain("csrf");
  });

  it("renders only allowlisted workspace configuration controls", () => {
    const html = renderToStaticMarkup(<WorkspaceSettingsForm detail={detail} csrfToken="csrf" />);
    expect(html).toContain("Retrieval results");
    expect(html).toContain("LLM temperature");
    expect(html).toContain("Archive workspace");
    expect(html).not.toMatch(/api key|secret|credential/i);
  });

  it("provides bounded workspace creation fields", () => {
    const html = renderToStaticMarkup(<WorkspaceCreateForm organizationId="org-1" csrfToken="csrf" />);
    expect(html).toContain('maxLength="200"');
    expect(html).toContain('maxLength="100"');
    expect(html).toContain("Create workspace");
  });
});
