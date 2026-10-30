"use client";

import { Check, Copy, X } from "lucide-react";
import { useState, useTransition } from "react";

import { NativeSelect } from "@/components/native-select";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { LEAD_STATUSES, type LeadStatus, STATUS_LABELS } from "@/lib/labels";
import { DRAFT_MAX_WORDS, SIGN_OFF, wordCount } from "@/lib/outreach";

import { type ActionResult, saveDraft, setStatus } from "./actions";

export type ReviewDraft = {
  id: string;
  channel: string;
  status: string;
  subject: string;
  body: string; // editable text, sign-off removed
  aiBody: string; // the agent's original, sign-off removed
  edited: boolean;
  editable: boolean;
};

/** Approve / reject / status, plus the draft editor. They share state so
 * approving with unsaved edits saves them first. */
export function LeadReview({ leadId, status, draft }: { leadId: string; status: LeadStatus; draft: ReviewDraft | null }) {
  const [subject, setSubject] = useState(draft?.subject ?? "");
  const [body, setBody] = useState(draft?.body ?? "");
  const [result, setResult] = useState<ActionResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [pending, startTransition] = useTransition();

  // Compared trimmed: that is how a draft is saved.
  const dirty = Boolean(draft) && (subject.trim() !== draft?.subject || body.trim() !== draft?.body);
  const edits = draft && dirty ? { outreachId: draft.id, subject, body } : undefined;
  const words = wordCount(body);

  const act = (work: () => Promise<ActionResult>) =>
    startTransition(async () => {
      setResult(null);
      setResult(await work());
    });

  async function copy() {
    const text = `${subject ? `Subject: ${subject}\n\n` : ""}${body.trim()}\n\n${SIGN_OFF}`;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Review</CardTitle>
        <CardDescription>Approving marks the lead and its draft as ready. Nothing is sent from here.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-wrap items-end gap-2">
          {status !== "approved" && (
            <Button disabled={pending} onClick={() => act(() => setStatus(leadId, "approved", edits))}>
              <Check /> {edits ? "Save & approve" : "Approve"}
            </Button>
          )}
          {status !== "rejected" && (
            <Button variant="outline" disabled={pending} onClick={() => act(() => setStatus(leadId, "rejected"))}>
              <X /> Reject
            </Button>
          )}
          <label className="ml-auto flex flex-col gap-1 text-xs text-muted-foreground">
            Status
            <NativeSelect
              value={status}
              disabled={pending}
              onChange={(e) => act(() => setStatus(leadId, e.target.value as LeadStatus))}
            >
              {LEAD_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </NativeSelect>
          </label>
        </div>

        {draft ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="font-medium">
                Draft · {draft.channel.replace("_", " ")} · {draft.status}
                {draft.edited && <span className="font-normal text-muted-foreground"> · edited</span>}
              </span>
              <Button variant="ghost" size="sm" onClick={copy}>
                <Copy /> {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <div className="space-y-2">
              <Label htmlFor="subject">Subject</Label>
              <Input
                id="subject"
                value={subject}
                disabled={!draft.editable}
                onChange={(e) => setSubject(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="body">Message</Label>
              <Textarea
                id="body"
                value={body}
                rows={10}
                disabled={!draft.editable}
                onChange={(e) => setBody(e.target.value)}
              />
              <p className="whitespace-pre-line rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">{SIGN_OFF}</p>
              <p className={words > DRAFT_MAX_WORDS ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
                {words} words{words > DRAFT_MAX_WORDS ? ` (over ${DRAFT_MAX_WORDS}; keep first emails short)` : ""} · the
                sign-off with the opt-out line is always added
              </p>
            </div>
            {draft.editable && (
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={!dirty || pending}
                  onClick={() => act(() => saveDraft(leadId, { outreachId: draft.id, subject, body }))}
                >
                  Save draft
                </Button>
                {dirty && (
                  <Button
                    variant="ghost"
                    disabled={pending}
                    onClick={() => {
                      setSubject(draft.subject);
                      setBody(draft.body);
                    }}
                  >
                    Discard changes
                  </Button>
                )}
              </div>
            )}
            {draft.edited && (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted-foreground">Original AI draft</summary>
                <p className="mt-2 whitespace-pre-line text-muted-foreground">{draft.aiBody}</p>
              </details>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No draft: the AI scored this lead as a reject.</p>
        )}

        {result && (
          <p role="status" className={result.ok ? "text-sm text-muted-foreground" : "text-sm text-destructive"}>
            {result.ok ? "Saved." : result.error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
