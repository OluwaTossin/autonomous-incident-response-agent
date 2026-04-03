"""Gradio triage console mounted at ``/ui`` (requires ``uv sync --extra ui``)."""

from __future__ import annotations

import html
import json
from typing import Any

from fastapi import FastAPI
from pydantic import ValidationError

from app.agent.nodes import parse_incident_payload
from app.api.n8n_routes import record_triage_feedback
from app.api.triage_execution import run_full_triage
from app.rag.config import project_root
from app.ui.triage_display import format_triage_card, pretty_json


def _default_incident_json() -> str:
    p = project_root() / "examples" / "sample_incident_payload.json"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip() + "\n"
    return '{\n  "alert_title": "Example",\n  "service_name": "api"\n}\n'


def with_gradio_ui(app: FastAPI) -> FastAPI:
    """Return ``app`` with Gradio mounted at ``/ui``."""
    import gradio as gr

    def run_click(text: str) -> tuple[Any, Any, Any, Any]:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            html_err = (
                f'<div style="padding:16px;border-radius:10px;background:#fef2f2;color:#991b1b;'
                f'font-family:system-ui,sans-serif;"><strong>Invalid JSON</strong><br/>{html.escape(str(e), quote=True)}</div>'
            )
            return (html_err, "", "", gr.update(interactive=False))
        if not isinstance(raw, dict):
            html_err = (
                '<div style="padding:16px;border-radius:10px;background:#fef2f2;color:#991b1b;'
                'font-family:system-ui,sans-serif;"><strong>Error</strong><br/>Root must be a JSON object.</div>'
            )
            return (html_err, "", "", gr.update(interactive=False))
        try:
            incident = parse_incident_payload(raw).model_dump(mode="json")
        except ValidationError as e:
            errs = json.dumps(e.errors(), indent=2)
            html_err = (
                f'<div style="padding:16px;border-radius:10px;background:#fff7ed;color:#9a3412;'
                f'font-family:system-ui,sans-serif;"><strong>Validation</strong>'
                f'<pre style="white-space:pre-wrap;font-size:12px;">{html.escape(errs, quote=True)}</pre></div>'
            )
            return (html_err, "", "", gr.update(interactive=False))
        try:
            out = run_full_triage(incident)
        except Exception as ex:
            html_err = (
                f'<div style="padding:16px;border-radius:10px;background:#fef2f2;color:#991b1b;'
                f'font-family:system-ui,sans-serif;"><strong>Triage failed</strong><br/>{html.escape(repr(ex), quote=True)}</div>'
            )
            return (html_err, "", "", gr.update(interactive=False))
        tid = str(out.get("triage_id", ""))
        return (
            format_triage_card(out),
            pretty_json(out),
            tid,
            gr.update(interactive=True),
        )

    def feedback_click(
        tid: str,
        diag_ok: bool,
        actions_ok: bool,
        notes: str,
    ) -> Any:
        tid_stripped = (tid or "").strip()
        if not tid_stripped:
            gr.Warning("Run triage first or paste a triage_id.")
            return gr.update(interactive=True)
        payload: dict[str, Any] = {
            "triage_id": tid_stripped,
            "diagnosis_correct": diag_ok,
            "actions_useful": actions_ok,
            "notes": (notes or "").strip(),
        }
        st = record_triage_feedback(payload)
        status = st.get("status", "unknown")
        if status == "logged":
            gr.Success("Feedback saved — linked to audit trail.")
        elif status == "skipped":
            gr.Warning("Feedback logging disabled (N8N_TRIAGE_FEEDBACK_DISABLE).")
        else:
            gr.Error("Could not write feedback file.")
        return gr.update(interactive=False)

    def copy_tid_feedback(tid: str) -> None:
        if not (tid or "").strip():
            gr.Warning("No triage_id yet — run triage first.")
            return
        gr.Info("triage_id copied to clipboard.")

    sample = _default_incident_json()

    # Themes live under ``gr.themes`` on most builds; some installs only expose ``gradio.themes``.
    theme = None
    themes_mod = getattr(gr, "themes", None)
    if themes_mod is not None and hasattr(themes_mod, "Soft"):
        try:
            theme = themes_mod.Soft(primary_hue="orange")
        except (TypeError, AttributeError):
            theme = None
    if theme is None:
        try:
            from gradio.themes import Soft as _SoftTheme

            theme = _SoftTheme(primary_hue="orange")
        except ImportError:
            theme = None

    block_kw: dict[str, Any] = {"title": "Incident triage"}
    if theme is not None:
        block_kw["theme"] = theme

    with gr.Blocks(**block_kw) as demo:
        gr.Markdown(
            "<div style=\"max-width:880px;\">"
            "# Incident triage\n"
            "<p style=\"color:#4b5563;font-size:15px;line-height:1.5;margin-top:0;\">"
            "Paste <strong>incident JSON</strong> (same shape as <code>POST /triage</code>). "
            "Same LangGraph pipeline and audit log as the API.</p>"
            "<p style=\"margin-bottom:0;\">"
            "<a href=\"/docs\" target=\"_blank\" rel=\"noopener noreferrer\" "
            "style=\"font-weight:600;color:#ea580c;\">OpenAPI docs</a>"
            " · <a href=\"/\" target=\"_blank\" rel=\"noopener noreferrer\" "
            "style=\"font-weight:600;color:#ea580c;\">Service discovery JSON</a>"
            " · <a href=\"/health\" target=\"_blank\" rel=\"noopener noreferrer\" "
            "style=\"color:#6b7280;\">Health</a>"
            "</p></div>"
        )

        incident_in = gr.Textbox(
            label="Incident JSON",
            value=sample,
            lines=12,
            max_lines=24,
        )
        run_btn = gr.Button("Run triage", variant="primary", size="lg")

        result_html = gr.HTML(
            value='<p style="color:#9ca3af;font-family:system-ui,sans-serif;">'
            "Run triage to see summary, severity, confidence, and grouped evidence.</p>"
        )

        with gr.Accordion("Raw JSON (full API response)", open=False):
            raw_code = gr.Code(
                language="json",
                lines=18,
                interactive=False,
                value="",
            )

        gr.Markdown("### Feedback · joins audit via `triage_id`")
        with gr.Row():
            tid_box = gr.Textbox(
                label="triage_id",
                placeholder="Populated after each triage run",
                lines=1,
                scale=4,
            )
            copy_btn = gr.Button("Copy triage_id", scale=1, variant="secondary")

        with gr.Row():
            diag = gr.Checkbox(label="Diagnosis correct", value=True)
            actions = gr.Checkbox(label="Actions useful", value=True)
        notes = gr.Textbox(label="Notes", lines=2, placeholder="Optional context for your team / eval set…")
        fb_btn = gr.Button("Submit feedback", variant="primary", interactive=False)
        gr.Markdown(
            value='<p style="color:#9ca3af;font-size:12px;margin:0;">'
            "After submit, the button locks until you run triage again.</p>"
        )

        run_btn.click(
            fn=run_click,
            inputs=[incident_in],
            outputs=[result_html, raw_code, tid_box, fb_btn],
        )
        copy_btn.click(
            fn=copy_tid_feedback,
            inputs=[tid_box],
            outputs=[],
            js="(tid) => { if (tid) navigator.clipboard.writeText(String(tid)); }",
        )
        fb_btn.click(
            fn=feedback_click,
            inputs=[tid_box, diag, actions, notes],
            outputs=[fb_btn],
        )

    return gr.mount_gradio_app(app, demo, path="/ui")
