// Only the public URL and anon key are used here: every query runs as the
// signed-in user and is limited by the database's row level security. The
// service-role key must never appear in the dashboard (CI checks this).
export function supabaseEnv(): { url: string; anonKey: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY (see dashboard/.env.example)",
    );
  }
  return { url, anonKey };
}
