"use client";

import { useState, useTransition } from "react";

import { Switch } from "@/components/ui/switch";

import { setAiEnabled, setPlatformEnabled, type SwitchResult } from "./actions";

function SavingSwitch({
  checked,
  disabled,
  label,
  save,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  save: (on: boolean) => Promise<SwitchResult>;
}) {
  const [on, setOn] = useState(checked);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const change = (next: boolean) => {
    setOn(next);
    setError(null);
    startTransition(async () => {
      const result = await save(next);
      if (!result.ok) {
        setOn(!next);
        setError(result.error ?? "Could not save.");
      }
    });
  };

  return (
    <span className="flex flex-col items-end gap-1">
      <Switch checked={on} disabled={disabled || pending} onCheckedChange={change} aria-label={label} />
      {error && (
        <span role="alert" className="text-right text-xs text-destructive">
          {error}
        </span>
      )}
    </span>
  );
}

export function PlatformSwitch({
  platformKey,
  name,
  enabled,
  available,
}: {
  platformKey: string;
  name: string;
  enabled: boolean;
  available: boolean;
}) {
  return (
    <SavingSwitch
      checked={available && enabled}
      disabled={!available}
      label={available ? `Collect from ${name}` : `${name} is not available yet`}
      save={(on) => setPlatformEnabled(platformKey, on)}
    />
  );
}

export function AiSwitch({ enabled }: { enabled: boolean }) {
  return <SavingSwitch checked={enabled} label="Use the Claude API" save={setAiEnabled} />;
}
