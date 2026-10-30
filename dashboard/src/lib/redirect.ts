/** A post-login destination from the URL, limited to paths on this site. */
export function safeNext(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  if (value.startsWith("/login") || value.startsWith("/auth/")) return "/";
  return value;
}
