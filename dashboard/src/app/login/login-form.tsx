"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { type LoginState, sendCode, verifyCode } from "./actions";

export function LoginForm({ next, linkError }: { next: string; linkError: boolean }) {
  const [state, action, sending] = useActionState(sendCode, {
    step: "email",
    email: "",
    next,
    error: linkError ? "That sign-in link is invalid or has expired. Request a new one." : undefined,
  } satisfies LoginState);

  if (state.step === "code") return <CodeForm sent={state} />;

  return (
    <form action={action} className="space-y-4">
      <input type="hidden" name="next" value={next} />
      <div className="space-y-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          defaultValue={state.email}
        />
      </div>
      {state.error && <p className="text-sm text-destructive">{state.error}</p>}
      <Button type="submit" className="w-full" disabled={sending}>
        {sending ? "Sending…" : "Email me a sign-in link"}
      </Button>
    </form>
  );
}

/** After the email step: open the link, or type the code from the same email. */
function CodeForm({ sent }: { sent: LoginState }) {
  const [state, action, verifying] = useActionState(verifyCode, sent);
  return (
    <form action={action} className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {sent.message} Open it on this device, or enter the code from the email.
      </p>
      <div className="space-y-2">
        <Label htmlFor="code">Code</Label>
        <Input id="code" name="code" inputMode="numeric" autoComplete="one-time-code" required />
      </div>
      {state.error && <p className="text-sm text-destructive">{state.error}</p>}
      <Button type="submit" className="w-full" disabled={verifying}>
        {verifying ? "Checking…" : "Sign in"}
      </Button>
    </form>
  );
}
