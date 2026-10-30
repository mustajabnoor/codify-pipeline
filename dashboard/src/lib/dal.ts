import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import { createClient } from "@/lib/supabase/server";

/** The signed-in team member, or a redirect: to /login without a session, to
 * /not-authorized for an account that isn't in team_members. Call it in every
 * page and Server Action that reads or writes data (Next.js recommends checks
 * close to the data, not only in layouts). RLS enforces the same rule in the
 * database. */
export const requireMember = cache(async () => {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const email = data?.claims?.email;
  if (!data?.claims?.sub || typeof email !== "string") redirect("/login");

  // RLS only lets team members read team_members, so a non-member gets no row.
  const { data: member } = await supabase
    .from("team_members")
    .select("email, display_name")
    .eq("email", email.toLowerCase())
    .maybeSingle();
  if (!member) redirect("/not-authorized");

  return { supabase, email, displayName: member.display_name ?? email };
});
