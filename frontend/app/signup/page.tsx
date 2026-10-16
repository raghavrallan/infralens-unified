"use client";

import { FormEvent, useState } from "react";
import { api } from "../../lib/api";

export default function SignupPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api("/api/signup", {
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          name: String(form.get("name") || ""),
          orgName: String(form.get("orgName") || ""),
          email: String(form.get("email") || ""),
          password: String(form.get("password") || ""),
        }),
      });
      window.location.href = "/dashboard/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the organization.");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <p className="text-sm font-bold text-[#E2773C]">IF</p>
      <h1 className="mt-2 text-3xl font-semibold">Create an organization</h1>
      <p className="mt-2 text-sm text-[#717171]">This account only sees the organization it creates.</p>
      <form className="mt-6 space-y-3" onSubmit={onSubmit}>
        <label className="block text-sm">Your name<input name="name" required className="mt-1 h-11 w-full rounded-2xl border px-3" /></label>
        <label className="block text-sm">Organization<input name="orgName" required className="mt-1 h-11 w-full rounded-2xl border px-3" /></label>
        <label className="block text-sm">Email<input name="email" type="email" required className="mt-1 h-11 w-full rounded-2xl border px-3" /></label>
        <label className="block text-sm">Password<input name="password" type="password" required minLength={8} className="mt-1 h-11 w-full rounded-2xl border px-3" /></label>
        {error ? <p className="text-sm text-red-700">{error}</p> : null}
        <button type="submit" disabled={busy} className="h-11 w-full rounded-2xl bg-[#E2773C] font-semibold text-white">
          {busy ? "Creating…" : "Create organization"}
        </button>
      </form>
      <a href="/login/" className="mt-4 text-sm font-semibold text-[#E2773C]">Sign in</a>
    </main>
  );
}
