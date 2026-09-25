import { redirect } from "next/navigation";

export default async function OrganizationPage({ params }: { params: Promise<{ organizationId: string }> }) {
  const { organizationId } = await params;
  redirect(`/app/orgs/${organizationId}/workspaces`);
}
