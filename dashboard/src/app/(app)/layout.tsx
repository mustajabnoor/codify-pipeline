import { Suspense } from "react";

import { signOut } from "@/app/actions";
import { AppNav, NavLinks } from "@/components/app-nav";
import { Button } from "@/components/ui/button";
import { requireMember } from "@/lib/auth";

/** Shell for every signed-in screen. The frame is static; the user's email
 * and each page's data stream in behind Suspense boundaries. */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[14rem_1fr]">
      <aside className="hidden border-r p-4 md:flex md:flex-col md:gap-6">
        <span className="px-3 font-semibold">Codify Pipeline</span>
        <nav aria-label="Main">
          <Suspense fallback={<NavLinks variant="sidebar" pathname={null} />}>
            <AppNav variant="sidebar" />
          </Suspense>
        </nav>
      </aside>

      <div className="flex min-w-0 flex-col pb-16 md:pb-0">
        <header className="flex h-14 items-center justify-between gap-2 border-b px-4">
          <span className="font-semibold md:invisible">Pipeline</span>
          <Suspense>
            <Account />
          </Suspense>
        </header>
        <main className="flex-1 p-4 md:p-6">{children}</main>
      </div>

      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 border-t bg-background pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        <Suspense fallback={<NavLinks variant="tabs" pathname={null} />}>
          <AppNav variant="tabs" />
        </Suspense>
      </nav>
    </div>
  );
}

async function Account() {
  const { email } = await requireMember();
  return (
    <form action={signOut} className="flex items-center gap-2">
      <span className="hidden text-sm text-muted-foreground sm:inline">{email}</span>
      <Button type="submit" variant="ghost" size="sm">
        Sign out
      </Button>
    </form>
  );
}
