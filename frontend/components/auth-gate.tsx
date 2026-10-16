"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "../lib/api";
import { fetchCurrentUser } from "../lib/auth";
import { GlobalLoader } from "./global-loader";

function skipKey(userId?: string) {
  return userId ? `onboarding_skipped:${userId}` : "onboarding_skipped";
}

const PUBLIC_PATHS = new Set(["/login", "/signup", "/accept-invite", "/approve-member"]);

export function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const path = pathname.replace(/\/$/, "") || "/";
        if (PUBLIC_PATHS.has(path)) {
          if (!cancelled) setReady(true);
          return;
        }

        const current = await fetchCurrentUser();
        if (cancelled) return;
        if (!current) {
          window.location.replace("/login/");
          return;
        }

        // Dedicated onboarding route — let the page handle the wizard.
        if (path === "/onboarding") {
          try {
            const status = await api<{ needs_onboarding?: boolean }>(
              "/api/onboarding/status",
            );
            const skipped = window.localStorage.getItem(skipKey(current.id)) === "1";
            if (!cancelled && !status.needs_onboarding && skipped) {
              window.location.replace("/dashboard");
              return;
            }
            if (!cancelled && !status.needs_onboarding) {
              window.location.replace("/dashboard");
              return;
            }
          } catch {
            // stay on onboarding if status fails
          }
          if (!cancelled) setReady(true);
          return;
        }

        try {
          const status = await api<{ needs_onboarding?: boolean }>(
            "/api/onboarding/status",
          );
          const skipped = window.localStorage.getItem(skipKey(current.id)) === "1";
          if (!cancelled && status.needs_onboarding && !skipped) {
            window.location.replace("/onboarding");
            return;
          }
        } catch {
          // ignore status failures; still show app
        }
        if (!cancelled) setReady(true);
      } catch {
        if (!cancelled) setReady(true);
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (!ready) {
    return <GlobalLoader active label="Loading InfraLens" />;
  }

  return <>{children}</>;
}
