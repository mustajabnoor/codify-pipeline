import type { Metadata } from "next";
import { Suspense } from "react";

import { signOut } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = { title: "No access" };

export default function NoAccessPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>No access</CardTitle>
          <CardDescription>
            <Suspense fallback="This account">
              <SignedInAs />
            </Suspense>{" "}
            isn&apos;t on the team list. Ask the owner to add it to <code>team_members</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form action={signOut}>
            <Button type="submit" variant="outline" className="w-full">
              Sign out
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

async function SignedInAs() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const email = data?.claims?.email;
  return typeof email === "string" ? email : "This account";
}
