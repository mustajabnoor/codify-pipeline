// Public Supabase settings (safe in the browser; RLS protects the data).
// The service-role key is never used by the dashboard (CLAUDE.md §11).
export function supabaseEnv(): { url: string; anonKey: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY (see dashboard/README.md)",
    );
  }
  return { url, anonKey };
}
