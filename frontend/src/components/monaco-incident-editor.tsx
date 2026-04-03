"use client";

import Editor from "@monaco-editor/react";
import { useEffect, useState } from "react";

type Props = {
  value: string;
  onChange: (value: string) => void;
  height?: string;
  readOnly?: boolean;
};

/** JSON editor; Monaco loads client-only via @monaco-editor/react. */
export function MonacoIncidentEditor({
  value,
  onChange,
  height = "min(40vh, 360px)",
  readOnly = false,
}: Props) {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(mq.matches);
    const fn = () => setDark(mq.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  const theme = dark ? "vs-dark" : "light";

  return (
    <Editor
      height={height}
      defaultLanguage="json"
      theme={theme}
      value={value}
      onChange={(v) => onChange(v ?? "")}
      options={{
        readOnly,
        minimap: { enabled: false },
        fontSize: 13,
        wordWrap: "on",
        scrollBeyondLastLine: false,
        tabSize: 2,
        formatOnPaste: !readOnly,
      }}
    />
  );
}
