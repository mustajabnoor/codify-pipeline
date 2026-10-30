import { Activity, List, type LucideIcon, Sun } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

// Screens are added here as they ship.
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Today", icon: Sun },
  { href: "/leads", label: "Leads", icon: List },
  { href: "/health", label: "Health", icon: Activity },
];
