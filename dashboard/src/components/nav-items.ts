import { Activity, List, type LucideIcon, SlidersHorizontal, Sun } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

// Screens are added here as they ship.
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Today", icon: Sun },
  { href: "/leads", label: "Leads", icon: List },
  { href: "/sources", label: "Sources", icon: SlidersHorizontal },
  { href: "/health", label: "Health", icon: Activity },
];
