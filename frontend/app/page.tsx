"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { listLibrary } from "@/lib/api";

const DISMISS_KEY = "notebookai.welcome.dismissed";

/**
 * Root redirector. Decides between the welcome flow and Read mode based
 * on the (a) backend library scan and (b) the localStorage dismissal flag.
 *
 * The decision is purely client-side because both inputs require runtime
 * access to the API + the browser's storage. SSR would just render the
 * loading shell.
 */
export default function HomePage() {
  const router = useRouter();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["library"],
    queryFn: listLibrary,
    retry: 0,
  });

  useEffect(() => {
    if (isLoading) return;
    const dismissed =
      typeof window !== "undefined" &&
      window.localStorage.getItem(DISMISS_KEY) === "true";
    const empty = !isError && (data ?? []).length === 0;
    if (empty && !dismissed) {
      router.replace("/welcome");
    } else {
      router.replace("/read");
    }
  }, [data, isLoading, isError, router]);

  return <div className="flex-1" data-testid="home-loading" />;
}
