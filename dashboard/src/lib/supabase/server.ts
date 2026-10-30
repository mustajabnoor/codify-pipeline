import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import type { Database } from "@/lib/database.types";

import { supabaseEnv } from "./env";

/** Supabase client for Server Components, Server Actions and Route Handlers,
 * acting as the signed-in user (session from cookies). */
export async function createClient() {
  const { url, anonKey } = supabaseEnv();
  const cookieStore = await cookies();
  return createServerClient<Database>(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Server Components can't set cookies; the proxy refreshes the
          // session on every request, so this is safe to ignore.
        }
      },
    },
  });
}
