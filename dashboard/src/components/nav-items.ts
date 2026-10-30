import { List, type LucideIcon, Sun } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

// Screens are added here as they ship (Health in 3.4).
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Today", icon: Sun },
  { href: "/leads", label: "Leads", icon: List },
];
