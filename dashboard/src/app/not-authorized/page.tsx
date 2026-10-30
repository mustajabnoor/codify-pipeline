import type { Metadata } from "next";

import { logout } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "Not authorized" };

// A signed-in account that isn't in team_members lands here (src/lib/dal.ts).
export default function NotAuthorizedPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">Not authorized</CardTitle>
          <CardDescription>
            This account isn&apos;t on the Codify Pipeline team. Ask the owner to add your email
            to <code>team_members</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form action={logout}>
            <Button type="submit" variant="outline" className="w-full">
              Sign out
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
