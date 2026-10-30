"use server";

import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";

export type LoginState = { error: string | null; email: string };

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");
  if (!email || !password) return { error: "Enter your email and password.", email };

  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) {
    // Same message for unknown email and wrong password; anything else (Supabase
    // unreachable, rate limit) must not look like a typo.
    if (error.code === "invalid_credentials") return { error: "Wrong email or password.", email };
    if (error.status === 429) return { error: "Too many attempts. Wait a minute and try again.", email };
    console.error("sign-in failed:", error.name, error.code ?? "", error.message);
    return { error: "Couldn't reach the sign-in service. Try again in a moment.", email };
  }
  redirect("/");
}

export async function logout() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}
