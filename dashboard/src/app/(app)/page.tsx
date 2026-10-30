import type { Metadata } from "next";
import { Suspense } from "react";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { requireMember } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = { title: "Today" };

// KPI cards and the top-leads list arrive in 3.4.
export default function TodayPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Today</h1>
      <Suspense fallback={<Counts loading />}>
        <LeadCounts />
      </Suspense>
    </div>
  );
}

async function LeadCounts() {
  await requireMember();
  const supabase = await createClient();
  const count = async (status?: "new") => {
    let query = supabase.from("leads").select("id", { count: "exact", head: true });
    if (status) query = query.eq("status", status);
    const { count, error } = await query;
    if (error) throw new Error(error.message);
    return count ?? 0;
  };
  const [total, fresh] = await Promise.all([count(), count("new")]);
  return <Counts total={total} fresh={fresh} />;
}

function Counts({ total, fresh, loading }: { total?: number; fresh?: number; loading?: boolean }) {
  const show = (n?: number) => (loading ? "…" : n);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Card>
        <CardHeader>
          <CardDescription>Leads waiting for review</CardDescription>
          <CardTitle className="text-3xl tabular-nums">{show(fresh)}</CardTitle>
        </CardHeader>
      </Card>
      <Card>
        <CardHeader>
          <CardDescription>Leads in the pipeline</CardDescription>
          <CardTitle className="text-3xl tabular-nums">{show(total)}</CardTitle>
        </CardHeader>
      </Card>
    </div>
  );
}
