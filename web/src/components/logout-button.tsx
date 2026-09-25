"use client";

import { LogOut } from "lucide-react";

export function LogoutButton({ csrfToken }: { csrfToken: string }) {
  async function logout() {
    const response = await fetch("/auth/logout", {
      method: "POST",
      headers: { "x-csrf-token": csrfToken },
      cache: "no-store",
    });
    if (response.redirected) window.location.assign(response.url);
  }

  return (
    <button className="icon-command" type="button" onClick={() => void logout()}>
      <LogOut aria-hidden="true" size={17} />
      <span>Sign out</span>
    </button>
  );
}
