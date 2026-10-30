import type { Metadata } from "next";
import { Suspense } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { safeNext } from "@/lib/redirect";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <main className="flex min-h-dvh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Codify Pipeline</CardTitle>
          <CardDescription>Sign in with your team email.</CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense>
            <Form searchParams={searchParams} />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}

async function Form({ searchParams }: Pick<PageProps<"/login">, "searchParams">) {
  const params = await searchParams;
  return <LoginForm next={safeNext(params.next)} linkError={params.error === "link"} />;
}
