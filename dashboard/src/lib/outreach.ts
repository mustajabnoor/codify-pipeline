// Must match SIGN_OFF in agent/core/models.py (a test checks this). The agent
// appends it to every draft; it carries the opt-out line every draft must have
// (CLAUDE.md §11), so the editor keeps it fixed below the editable text.
export const SIGN_OFF = "— Mustajab, Codify Labs\n\nNot relevant? Reply 'no' and I won't follow up.";
export const DRAFT_MAX_WORDS = 100;

/** The editable part of a stored draft (the sign-off removed). */
export function draftBody(stored: string | null | undefined): string {
  const text = (stored ?? "").replace(/\r\n/g, "\n").trimEnd();
  return text.endsWith(SIGN_OFF) ? text.slice(0, -SIGN_OFF.length).trimEnd() : text;
}

/** What gets stored: the edited text plus the sign-off, exactly as the agent writes it. */
export function withSignOff(body: string): string {
  return `${body.replace(/\r\n/g, "\n").trim()}\n\n${SIGN_OFF}`;
}

export function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}
