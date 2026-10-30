// The team works in Asia/Karachi; "today" and every displayed time use it.
export const TEAM_TZ = "Asia/Karachi";

/** Minutes the zone is ahead of UTC at `at` (Karachi: +300, no DST). */
export function tzOffsetMinutes(at: Date, timeZone: string = TEAM_TZ): number {
  const name = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "longOffset" })
    .formatToParts(at)
    .find((p) => p.type === "timeZoneName")?.value;
  const match = name?.match(/GMT([+-])(\d{2}):?(\d{2})?/);
  if (!match) return 0; // "GMT" alone means UTC
  const minutes = Number(match[2]) * 60 + Number(match[3] ?? 0);
  return match[1] === "-" ? -minutes : minutes;
}

/** Start of the team's calendar day containing `now`, as a UTC instant. */
export function startOfTeamDay(now: Date, timeZone: string = TEAM_TZ): Date {
  const offset = tzOffsetMinutes(now, timeZone);
  const local = new Date(now.getTime() + offset * 60_000);
  const midnightLocal = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate());
  return new Date(midnightLocal - offset * 60_000);
}

const dateTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: TEAM_TZ,
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** "Thu 30 Oct, 11:36" in Karachi time. */
export function formatDateTime(iso: string | Date): string {
  return dateTime.format(typeof iso === "string" ? new Date(iso) : iso).replace(" at ", ", ");
}

/** "just now", "5 min ago", "3 h ago", "2 days ago". */
export function formatAgo(iso: string | Date, now: Date = new Date()): string {
  const then = typeof iso === "string" ? new Date(iso) : iso;
  const minutes = Math.round((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function hoursBetween(a: Date, b: Date): number {
  return Math.abs(b.getTime() - a.getTime()) / 3_600_000;
}
