"use client";

import { useEffect } from "react";

export default function Page() {
  useEffect(() => {
    window.location.replace("/dashboard/");
  }, []);
  return (
    <main className="p-6">
      <a href="/dashboard/">Estate overview</a>
    </main>
  );
}
