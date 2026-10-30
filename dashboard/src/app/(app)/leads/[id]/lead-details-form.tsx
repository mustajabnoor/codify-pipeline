"use client";

import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { type ActionResult, saveDetails } from "./actions";

type Details = { owner: string; followUp: string; notes: string };

export function LeadDetailsForm({ leadId, initial }: { leadId: string; initial: Details }) {
  const [details, setDetails] = useState(initial);
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, startTransition] = useTransition();
  const dirty = (Object.keys(initial) as (keyof Details)[]).some((k) => details[k] !== initial[k]);
  const set = (key: keyof Details) => (e: { target: { value: string } }) =>
    setDetails((d) => ({ ...d, [key]: e.target.value }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Follow-up &amp; notes</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            startTransition(async () => setResult(await saveDetails(leadId, details)));
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="owner">Owner</Label>
              <Input id="owner" value={details.owner} onChange={set("owner")} maxLength={100} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="follow-up">Follow up on</Label>
              <Input id="follow-up" type="date" value={details.followUp} onChange={set("followUp")} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="notes">Notes</Label>
            <Textarea id="notes" rows={4} value={details.notes} onChange={set("notes")} />
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" variant="secondary" disabled={!dirty || pending}>
              Save
            </Button>
            {result && (
              <span role="status" className={result.ok ? "text-sm text-muted-foreground" : "text-sm text-destructive"}>
                {result.ok ? "Saved." : result.error}
              </span>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
