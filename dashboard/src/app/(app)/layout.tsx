import { LogOut } from "lucide-react";
import { Suspense } from "react";

import { logout } from "@/app/actions";
import { SideNav, TabBar } from "@/components/nav";
import { Button } from "@/components/ui/button";
import { requireMember } from "@/lib/dal";

// Shell for signed-in pages. Each page calls requireMember() itself (layouts
// don't re-run on navigation); the shell streams first and only the name waits
// for the session (Next.js "auth and streaming").
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-full flex-1">
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col gap-6 border-r px-3 py-5 md:flex">
        <div className="px-3 font-semibold">Codify Pipeline</div>
        <SideNav />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between gap-3 border-b px-4 md:px-8">
          <span className="font-semibold md:hidden">Codify Pipeline</span>
          <span className="hidden truncate text-sm text-muted-foreground md:block">
            <Suspense fallback={null}>
              <SignedInAs />
            </Suspense>
          </span>
          <form action={logout}>
            <Button type="submit" variant="ghost" size="sm">
              <LogOut />
              Sign out
            </Button>
          </form>
        </header>
        <main className="flex-1 px-4 py-6 pb-24 md:px-8 md:pb-8">{children}</main>
      </div>
      <TabBar />
    </div>
  );
}

async function SignedInAs() {
  const { displayName } = await requireMember();
  return <>{displayName}</>;
}
