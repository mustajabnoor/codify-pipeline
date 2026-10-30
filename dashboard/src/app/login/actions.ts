"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { safeNext } from "@/lib/redirect";
import { createClient } from "@/lib/supabase/server";

export type LoginState = {
  step: "email" | "code";
  email: string;
  next: string;
  message?: string;
  error?: string;
};

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Emails a sign-in link (and a 6-digit code, if the Supabase email template
 * includes it). Only existing accounts can sign in: no sign-ups from here. */
export async function sendCode(_prev: LoginState, form: FormData): Promise<LoginState> {
  const email = String(form.get("email") ?? "").trim().toLowerCase();
  const next = safeNext(form.get("next"));
  if (!EMAIL.test(email)) return { step: "email", email, next, error: "Enter a valid email." };

  const origin = (await headers()).get("origin") ?? "";
  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: {
      shouldCreateUser: false,
      emailRedirectTo: `${origin}/auth/callback?next=${encodeURIComponent(next)}`,
    },
  });
  // Unknown addresses get the same answer, so the form doesn't reveal who has access.
  if (error && error.status === 429) {
    return { step: "email", email, next, error: "Too many attempts. Wait a minute and try again." };
  }
  return {
    step: "code",
    email,
    next,
    message: "If this email has access, a sign-in link is on its way.",
  };
}

/** Signs in with the 6-digit code from the email (handy in the installed app,
 * where links open in the browser instead). */
export async function verifyCode(prev: LoginState, form: FormData): Promise<LoginState> {
  const token = String(form.get("code") ?? "").replace(/\s/g, "");
  if (!/^\d{6,10}$/.test(token)) return { ...prev, message: undefined, error: "Enter the code from the email." };

  const supabase = await createClient();
  const { error } = await supabase.auth.verifyOtp({ email: prev.email, token, type: "email" });
  if (error) return { ...prev, message: undefined, error: "That code is wrong or has expired." };
  redirect(prev.next);
}
