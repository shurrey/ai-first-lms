"use client";

import { useState } from "react";

/** Labelled password input with a show/hide toggle; paste and password managers are left alone (WCAG 3.3.8). */
export function PasswordField({
  id,
  label,
  autoComplete,
  value,
  onChange,
  minLength,
  describedBy,
}: {
  id: string;
  label: string;
  autoComplete: "current-password" | "new-password";
  value: string;
  onChange: (v: string) => void;
  minLength?: number;
  describedBy?: string;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-gray-900">
        {label}
      </label>
      <div className="flex gap-2">
        <input
          id={id}
          name={id}
          type={visible ? "text" : "password"}
          autoComplete={autoComplete}
          required
          minLength={minLength}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={describedBy}
          className="min-w-0 flex-1 rounded-lg border border-gray-500 px-3 py-2 text-sm text-gray-900 outline-none focus:border-[#1a73e8] focus:ring-2 focus:ring-[#1a73e8]/40"
        />
        <button
          type="button"
          aria-controls={id}
          aria-pressed={visible}
          onClick={() => setVisible((v) => !v)}
          className="shrink-0 rounded-lg border border-gray-500 px-3 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1a73e8]"
        >
          {visible ? "Hide" : "Show"}
          <span className="sr-only"> {label.toLowerCase()}</span>
        </button>
      </div>
    </div>
  );
}
