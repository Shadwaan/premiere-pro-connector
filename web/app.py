"""Local web UI (FastAPI) over the auto-cut engine — PRD §4 req 9 / §9 Q6.

ONE self-contained page (inline CSS/JS, no build step). It is a THIN layer: it only collects
an uploaded FCP7 XML + parameters and calls ``engine.pipeline.run_autocut`` — the exact same
function the CLI uses, so the output is byte-identical. No LLM, no outbound network.

Run locally (the machine must hold the media/audio referenced by the XML):
    pip install -r requirements-web.txt
    uvicorn web.app:app          # then open http://localhost:8000
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from starlette.background import BackgroundTask

from engine.pipeline import AutocutParams, MasterAudioNotFound, run_autocut

app = FastAPI(title="Premiere Pro Connector — local auto-cut")

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Auto-cut — Premiere Pro Connector</title>
<style>
  :root { color-scheme: dark light; }
  body { font: 15px/1.5 system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.4rem; margin-bottom: .2rem; }
  p.sub { color: #888; margin-top: 0; }
  fieldset { border: 1px solid #8884; border-radius: 8px; margin: 1rem 0; padding: 1rem; }
  legend { padding: 0 .4rem; color: #888; font-size: .85rem; }
  label { display: block; margin: .6rem 0 .2rem; font-weight: 600; }
  .hint { font-weight: 400; color: #888; font-size: .85rem; }
  input, select { width: 100%; padding: .5rem; border-radius: 6px; border: 1px solid #8886; background: transparent; color: inherit; box-sizing: border-box; }
  .row { display: flex; gap: 1rem; } .row > div { flex: 1; }
  button { margin-top: 1rem; padding: .7rem 1.2rem; font-size: 1rem; border-radius: 8px; border: 0; background: #3b82f6; color: #fff; cursor: pointer; }
  button:disabled { opacity: .6; cursor: progress; }
  #status { margin-top: 1rem; padding: .7rem; border-radius: 6px; white-space: pre-wrap; }
  #status.ok { background: #16a34a22; } #status.err { background: #dc262622; }
</style></head><body>
<h1>DJ multicam auto-cut</h1>
<p class="sub">Upload a synced Premiere <b>FCP7 XML</b>, set the knobs, get a beat-cut multicam
XML back. Runs locally — your footage is never uploaded; the engine reads the media from the
paths inside the XML on <i>this</i> machine.</p>

<form id="f">
  <fieldset><legend>Input</legend>
    <label>Synced sequence (FCP7 XML) <span class="hint">File ▸ Export ▸ Final Cut Pro XML</span></label>
    <input type="file" name="file" accept=".xml" required>
    <label>Master audio <span class="hint">optional — only if the audio path in the XML isn't on this machine</span></label>
    <input type="file" name="master_audio" accept="audio/*,.wav,.mp3,.aif,.aiff">
  </fieldset>

  <fieldset><legend>Edit parameters (no LLM — these are the engine knobs)</legend>
    <div class="row">
      <div><label>Snap switches to</label>
        <select name="snap">
          <option value="downbeat" selected>downbeat (the bar's "1")</option>
          <option value="beat">beat (finer)</option>
          <option value="phrase">phrase (every N downbeats)</option>
        </select></div>
      <div><label>Phrase length <span class="hint">downbeats, phrase mode</span></label>
        <input type="number" name="phrase_downbeats" min="1" step="1" placeholder="2"></div>
    </div>
    <div class="row">
      <div><label>Min shot length <span class="hint">seconds</span></label>
        <input type="number" name="min_shot_len_s" min="0.1" step="0.1" placeholder="(brief default)"></div>
      <div><label>Max shot length <span class="hint">seconds</span></label>
        <input type="number" name="max_shot_len_s" min="0.5" step="0.5" placeholder="8.0"></div>
    </div>
    <label>Brief <span class="hint">optional keywords, e.g. "fast cuts on the drop, hold on the hook"</span></label>
    <input type="text" name="brief" placeholder="fast cuts on the drop, hold on the hook">
    <label>Seed <span class="hint">angle-scorer seed (deterministic)</span></label>
    <input type="number" name="seed" min="0" step="1" value="1">
  </fieldset>

  <button type="submit" id="go">Run auto-cut</button>
</form>
<div id="status"></div>

<script>
const form = document.getElementById('f'), status = document.getElementById('status'), go = document.getElementById('go');
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  go.disabled = true; status.className = ''; status.textContent = 'Processing… analyzing the master audio (this can take a while for a long track).';
  try {
    const res = await fetch('/process', { method: 'POST', body: new FormData(form) });
    if (!res.ok) { status.textContent = await res.text(); status.className = 'err'; return; }
    const blob = await res.blob();
    let name = 'autocut.xml';
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/); if (m) name = m[1];
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    status.textContent = 'Done — downloaded ' + name + '. Import it into Premiere via File ▸ Import.';
    status.className = 'ok';
  } catch (err) { status.textContent = 'Error: ' + err; status.className = 'err'; }
  finally { go.disabled = false; }
});
</script>
</body></html>
"""


def _num(value: str, cast):
    value = (value or "").strip()
    return cast(value) if value else None


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.post("/process")
async def process(
    file: UploadFile = File(...),
    master_audio: UploadFile | None = File(None),
    snap: str = Form("downbeat"),
    min_shot_len_s: str = Form(""),
    max_shot_len_s: str = Form(""),
    phrase_downbeats: str = Form(""),
    brief: str = Form(""),
    seed: str = Form("1"),
):
    workdir = Path(tempfile.mkdtemp(prefix="ppc_web_"))
    try:
        in_xml = workdir / (Path(file.filename or "input.xml").name)
        in_xml.write_bytes(await file.read())

        master_path = None
        if master_audio is not None and master_audio.filename:
            ma = workdir / Path(master_audio.filename).name
            ma.write_bytes(await master_audio.read())
            master_path = str(ma)

        params = AutocutParams(
            brief=(brief.strip() or None),
            snap=(snap.strip() or None),
            min_shot_len_s=_num(min_shot_len_s, float),
            max_shot_len_s=_num(max_shot_len_s, float),
            phrase_downbeats=_num(phrase_downbeats, int),
            seed=_num(seed, int) or 1,
            master_audio_path=master_path,
        )
        stem = Path(file.filename or "sequence").stem or "sequence"
        out_xml = workdir / f"{stem}_autocut.xml"
        run_autocut(str(in_xml), str(out_xml), params=params)
    except MasterAudioNotFound as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return PlainTextResponse(
            "Master audio not found on this machine:\n"
            f"  {e.path}\n\n"
            "This app must run where the footage/audio live. Use the optional "
            "'Master audio' picker above to supply the track, then run again.",
            status_code=400,
        )
    except Exception as e:  # noqa: BLE001 - surface any engine error to the user
        shutil.rmtree(workdir, ignore_errors=True)
        return PlainTextResponse(f"Processing failed: {e}", status_code=400)

    return FileResponse(
        out_xml,
        media_type="application/xml",
        filename=out_xml.name,
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )
