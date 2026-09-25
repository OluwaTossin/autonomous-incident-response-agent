import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { AwsIntegrationCreate } from "@/components/aws-integration-create";
import { AwsIntegrationOnboarding } from "@/components/aws-integration-onboarding";
import type { AwsIntegration, AwsTrustInstructions } from "@/lib/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const integration: AwsIntegration = {
  integration_id: "integration-1", provider: "aws", display_name: "Production AWS",
  aws_account_id: "123456789012", role_arn: "arn:aws:iam::123456789012:role/aira-read",
  enabled_regions: ["eu-west-2"], state: "ready", version: 3,
  created_at: "2026-09-25T12:00:00Z", updated_at: "2026-09-25T12:01:00Z", disabled_at: null,
  verification: { assume_role_passed: true, account_identity_passed: true, succeeded: true,
    verified_at: "2026-09-25T12:01:00Z", error_code: null, summary: null,
    checks: [{ capability: "aws_cloudwatch_logs_read", region: "eu-west-2", passed: true, error_code: null, summary: null }] },
};
const trust: AwsTrustInstructions = {
  trusted_principal_arn: "arn:aws:iam::111122223333:role/aira-hosted-api",
  external_id: "external-id", required_sts_action: "sts:AssumeRole",
  expected_role_arn_format: "arn:aws:iam::<account>:role/<role>",
  trust_policy: { Version: "2012-10-17" }, permission_policy: { Version: "2012-10-17" },
};

describe("AWS integration onboarding", () => {
  it("shows trust, identity, capability, and management controls", () => {
    const html = renderToStaticMarkup(<AwsIntegrationOnboarding initialIntegration={integration} trust={trust} organizationId="org" workspaceId="workspace" csrfToken="csrf" canManage />);
    expect(html).toContain("ExternalId");
    expect(html).toContain("sts:AssumeRole");
    expect(html).toContain("AWS account identity");
    expect(html).toContain("Verify connection");
    expect(html).toContain("Application intake is ready");
    expect(html).toContain("Deployment target pending");
    expect(html).not.toContain("SecretAccessKey");
  });

  it("hides mutations for read-only users and labels create fields", () => {
    const readOnly = renderToStaticMarkup(<AwsIntegrationOnboarding initialIntegration={integration} trust={trust} organizationId="org" workspaceId="workspace" csrfToken="csrf" canManage={false} />);
    const create = renderToStaticMarkup(<AwsIntegrationCreate organizationId="org" workspaceId="workspace" csrfToken="csrf" />);
    expect(readOnly).not.toContain("Verify connection");
    expect(readOnly).toContain("read-only");
    expect(create).toContain("AWS account ID");
    expect(create).toContain("No access keys");
  });
});
