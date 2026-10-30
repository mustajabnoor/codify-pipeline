import type { NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/proxy";

export async function proxy(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  // Everything except Next internals, the PWA manifest and static images.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest|icon.*\\.png|apple-icon.*\\.png).*)",
  ],
};
