"""kz-verify <file> [--json] [--c2patool PATH]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import verify

LABELS = {
    "trainedAlgorithmicMedia": "fully AI-generated",
    "compositeSynthetic": "composite with AI-generated elements",
    "compositeWithTrainedAlgorithmicMedia": "AI edit of captured material",
}


def text(r: dict) -> str:
    wm, c = r["watermark"], r["c2pa"]
    lines = [f"{r['file']}: {'AI marking FOUND' if r['ai_marked'] else 'no AI marking found'}"]
    if wm.get("detected"):
        ident = wm.get("id") or wm.get("bits")
        extra = f", p={wm['probability']}" if "probability" in wm else ""
        lines.append(f"  watermark: yes ({wm['method']}{extra}), id {ident}")
    else:
        lines.append(f"  watermark: no{(' (' + wm['note'] + ')') if wm.get('note') else ''}")
    if not c.get("checked"):
        lines.append(f"  C2PA: not checked ({c.get('note')})")
    elif not c.get("manifest"):
        lines.append("  C2PA: no manifest (platforms and re-encoding remove it; the watermark remains)")
    else:
        lines.append(f"  C2PA: {c['state']}, source: {LABELS.get(c['digital_source_type'], c['digital_source_type'])}")
        lines.append(f"  signed by Tom Langer kz Root CA: {'yes' if c['issued_by_tom_langer_kz'] else 'NO'}"
                     f"{', at ' + c['signed_at'] if c.get('signed_at') else ''}")
        if c.get("failures"):
            lines.append(f"  manifest failures: {', '.join(c['failures'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="kz-verify", description="Check the AI labelling of a file (Tom Langer, EU AI Act Art. 50(2)).")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--c2patool", help="path to c2patool if it is not on PATH")
    p.add_argument("--version", action="version", version=f"kz-verify {__version__}")
    a = p.parse_args(argv)
    r = verify(Path(a.file), a.c2patool)
    print(json.dumps(r, indent=2, ensure_ascii=False) if a.json else text(r))
    return 0 if r["ai_marked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
