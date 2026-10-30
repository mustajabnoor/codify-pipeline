"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

import { NAV_ITEMS } from "./nav-items";

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/** Sidebar links on desktop, bottom tab bar on phones. */
export function AppNav({ variant }: { variant: "sidebar" | "tabs" }) {
  const pathname = usePathname();
  return <NavLinks variant={variant} pathname={pathname} />;
}

/** Same links with nothing highlighted, shown until the pathname is known. */
export function NavLinks({ variant, pathname }: { variant: "sidebar" | "tabs"; pathname: string | null }) {
  return (
    <ul className={variant === "tabs" ? "flex" : "space-y-1"}>
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <li key={href} className={variant === "tabs" ? "flex-1" : undefined}>
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-md text-sm font-medium transition-colors",
                variant === "tabs"
                  ? "flex-col gap-1 py-2 text-xs"
                  : "px-3 py-2 hover:bg-accent hover:text-accent-foreground",
                active ? "text-foreground" : "text-muted-foreground",
                active && variant === "sidebar" && "bg-accent",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
