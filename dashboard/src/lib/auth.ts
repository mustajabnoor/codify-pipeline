import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import { createClient } from "@/lib/supabase/server";

export type Member = { email: string };

/** The signed-in team member, once per request. Signed-out visitors go to
 * /login; signed-in accounts that aren't in team_members go to /no-access.
 * Every page and action calls this; the database enforces the same rule. */
export const requireMember = cache(async (): Promise<Member> => {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const email = data?.claims?.email;
  if (typeof email !== "string" || !email) redirect("/login");

  const { data: isMember, error } = await supabase.rpc("is_team_member");
  if (error) throw new Error(`Could not check team access: ${error.message}`);
  if (!isMember) redirect("/no-access");
  return { email: email.toLowerCase() };
});
