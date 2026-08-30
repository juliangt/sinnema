"""Visor HTML del entregable: convierte el JSON de salida en una página legible.

Es la capa de presentación para humanos del ``SeriesDeliverable``: episodios
con sus escenas (narración, prompt de imagen, dirección de movimiento),
capítulos descartados, score de calidad y glosario de lore. Sin dependencias
de frontend: HTML+CSS generados en el servidor y contenido escapado.

El entregable 1.1 añade el ``alcance`` de la corrida (badge en la cabecera) y
los ``adjuntos`` por episodio (acordeones JSON por rol). Los bloques sin
artefacto (specs de video, dictámenes, lore) se omiten, como el patrón
``sin auditoría``.
"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, List

#: Etiqueta humana de cada hito del alcance (``SeriesDeliverable.alcance``).
ETIQUETAS_ALCANCE = {
    "plan": "plan",
    "guion": "guion",
    "guion_final": "guion final",
    "auditado": "auditado",
    "produccion": "producción",
}


def _esc(texto: Any) -> str:
    return html.escape(str(texto if texto is not None else ""))


_CSS = """
:root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --tx:#e8eaf0;
        --tx2:#9aa3b5; --ac:#7aa2ff; --ok:#5ad19a; --warn:#f0b45f; }
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--tx);
       font:15px/1.55 -apple-system, 'Segoe UI', Roboto, sans-serif;
       max-width:880px; margin:0 auto; padding:32px 20px 80px; }
h1 { font-size:1.5rem; margin-bottom:4px; }
.meta { color:var(--tx2); margin-bottom:20px; }
.stats { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:28px; }
.stat { background:var(--panel); border:1px solid var(--line); border-radius:10px;
        padding:10px 16px; }
.stat b { font-size:1.15rem; display:block; }
.stat span { color:var(--tx2); font-size:.8rem; }
.ep { background:var(--panel); border:1px solid var(--line); border-radius:12px;
      padding:18px 20px; margin-bottom:18px; }
.ep h2 { font-size:1.05rem; margin-bottom:2px; }
.ep .sub { color:var(--tx2); font-size:.85rem; margin-bottom:12px; }
.badge { display:inline-block; border-radius:6px; padding:1px 8px; font-size:.75rem;
         margin-left:8px; vertical-align:middle; }
.badge.ok { background:#17352a; color:var(--ok); }
.badge.forzado { background:#3a2f16; color:var(--warn); }
.badge.sin-qa { background:#20263a; color:#9aa3b5; }
.badge.alcance { background:#1c2440; color:var(--ac); margin-left:0; }
.adjunto { border:1px solid var(--line); border-radius:8px; padding:8px 12px;
           margin-top:8px; background:#10131a; }
.adjunto summary { cursor:pointer; color:var(--ac); font-size:.82rem; font-weight:600; }
.adjunto pre { background:#0c0f15; border:1px solid var(--line); border-radius:8px;
  padding:8px 12px; font:12px/1.5 ui-monospace, Menlo, monospace; color:#b9c2d8;
  white-space:pre-wrap; margin-top:8px; max-height:320px; overflow-y:auto; }
.escena { border-top:1px solid var(--line); padding:12px 0; }
.escena .num { color:var(--ac); font-weight:600; font-size:.8rem; }
.escena p { margin:4px 0; }
.prompt { background:#10131a; border:1px solid var(--line); border-radius:8px;
          padding:8px 12px; font:12.5px/1.5 ui-monospace, Menlo, monospace;
          color:#b9c2d8; margin-top:6px; white-space:pre-wrap; }
.prompt b { color:var(--tx2); font-weight:600; }
.fallo { background:var(--panel); border:1px solid #4a2a2a; border-radius:12px;
         padding:14px 18px; margin-bottom:12px; color:var(--warn); }
.lore { background:var(--panel); border:1px solid var(--line); border-radius:12px;
        padding:16px 20px; margin-top:28px; }
.lore h2 { font-size:1rem; margin-bottom:10px; }
.lore li { margin-bottom:6px; color:var(--tx2); }
.lore li b { color:var(--tx); }
a { color:var(--ac); }
"""


def _render_adjuntos(adjuntos: List[dict]) -> str:
    """Adjuntos del episodio como acordeones JSON, uno por rol."""
    if not adjuntos:
        return ""
    bloques = "".join(
        f"<details class='adjunto'><summary>adjunto · {_esc(a.get('rol'))}</summary>"
        f"<pre>{_esc(json.dumps(a.get('artefacto', {}), ensure_ascii=False, indent=2))}"
        f"</pre></details>"
        for a in adjuntos
    )
    return f"<div style='margin-top:10px'>{bloques}</div>"


def render_deliverable_html(deliverable: Dict[str, Any]) -> str:
    """Construye la página HTML completa a partir del entregable en dict."""
    episodios: List[dict] = deliverable.get("episodes", []) or []
    fallos: List[dict] = deliverable.get("failed_chapters", []) or []
    lore: List[dict] = deliverable.get("lore_glossary", []) or []
    total = deliverable.get("total_chapters_planned", len(episodios))
    alcance = deliverable.get("alcance", "produccion")
    badge_alcance = (
        f'<span class="badge alcance">alcance: '
        f"{_esc(ETIQUETAS_ALCANCE.get(alcance, alcance))}</span>"
    )

    bloques = []
    for ep in episodios:
        audit = ep.get("audit")
        if ep.get("forced_acceptance"):
            badge = '<span class="badge forzado">aceptado forzado</span>'
        elif audit is None:
            badge = '<span class="badge sin-qa">sin auditoría</span>'
        else:
            badge = '<span class="badge ok">aprobado</span>'
        score = f'QA {audit.get("overall_score", "?")}/10 · ' if audit else ""
        escenas = []
        for esc in ep.get("scenes", []):
            num = esc.get("scene_number", "?")
            prompt_bloque = (
                f"<div class='prompt'><b>imagen:</b> {_esc(esc.get('image_prompt'))}\n"
                f"<b>movimiento:</b> {_esc(esc.get('motion_direction'))}</div>"
                if esc.get("image_prompt")
                else ""
            )
            escenas.append(
                f'<div class="escena"><span class="num">ESCENA {num}'
                f' · {esc.get("duration_seconds", "?")} s</span>'
                f"<p>{_esc(esc.get('narration'))}</p>"
                f"<p><i>{_esc(esc.get('on_screen_text'))}</i></p>"
                f"{prompt_bloque}</div>"
            )
        bloques.append(
            f'<div class="ep"><h2>{ep.get("order_index", 0):02d}. '
            f"{_esc(ep.get('title'))}{badge}</h2>"
            f'<div class="sub">{score}'
            f"{_esc(ep.get('hook'))}</div>{''.join(escenas)}"
            f"<p style='margin-top:10px'><b>CTA:</b> {_esc(ep.get('call_to_action'))}</p>"
            f"{_render_adjuntos(ep.get('adjuntos', []) or [])}</div>"
        )

    bloques_fallos = "".join(
        f'<div class="fallo">✕ <b>{_esc(f.get("title"))}</b> — '
        f"{_esc(f.get('reason'))}</div>"
        for f in fallos
    )
    # Bloques sin artefacto se omiten (mismo patrón que "sin auditoría").
    bloque_lore = (
        f"<div class='lore'><h2>Glosario de continuidad (lore)</h2><ul>"
        + "".join(
            f"<li><b>{_esc(l.get('term'))}</b> — {_esc(l.get('definition'))} "
            f"<i>({ _esc(l.get('chapter_id'))})</i></li>"
            for l in lore
        )
        + "</ul></div>"
        if lore
        else ""
    )
    nota_plan = (
        '<div class="lore"><h2>Alcance "plan"</h2>'
        "La corrida planificó la serie y terminó sin guiones ni episodios: "
        "este entregable es solo el outline.</div>"
        if alcance == "plan"
        else ""
    )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(deliverable.get('series_title'))} · Sinnema</title>
<style>{_CSS}</style></head><body>
<h1>{_esc(deliverable.get('series_title'))} {badge_alcance}</h1>
<div class="meta">Proyecto <b>{_esc(deliverable.get('project_id'))}</b> ·
Tema: {_esc(deliverable.get('topic'))} · Audiencia: {_esc(deliverable.get('audience'))}</div>
<div class="stats">
  <div class="stat"><b>{len(episodios)}/{total}</b><span>episodios aprobados</span></div>
  <div class="stat"><b>{deliverable.get('average_quality_score', 0)}/10</b><span>score medio</span></div>
  <div class="stat"><b>{len(lore)}</b><span>términos de lore</span></div>
</div>
{nota_plan}
{''.join(bloques)}
{bloques_fallos}
{bloque_lore}
</body></html>"""
