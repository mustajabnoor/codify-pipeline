import { type LucideIcon, Sun } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

// Screens are added here as they ship (Leads in 3.2, Health in 3.4).
export const NAV_ITEMS: NavItem[] = [{ href: "/", label: "Today", icon: Sun }];
