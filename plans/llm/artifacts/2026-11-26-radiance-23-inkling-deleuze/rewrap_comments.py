#!/usr/bin/env python3
"""Re-wrap over-long comment lines in a YAML file to the file's own column width.

This file's convention (radiance-deleuze.yaml at main: every line <= 80 columns
except the image pin) is worth keeping, and prose added by an agent is what
breaks it. Safety rules, all enforced:

  * only comment lines (`^\\s*#`) are ever touched, and only inside --from/--to;
  * a run is rewritten only if some line in it is longer than --over, so comments
    someone else wrapped stay exactly as they are;
  * an empty comment line (`#`) stays a paragraph break; a bullet (`#  - ...`)
    stays a bullet, re-wrapped with its own continuation indent;
  * the script REFUSES if any non-comment line would change, and re-parses the
    result with PyYAML, so a stray indent cannot silently alter the ConfigMap.

Rewrapping inside the fleet ConfigMap changes its bytes, so regenerate
manual/radiance-23-preflight.py's embedded copy afterwards
(plans/llm/artifacts/2026-11-26-radiance-23-inkling-deleuze/gen_preflight.py) and re-run the byte-equality gate.

    python3 rewrap_comments.py <file> --from N --to M [--width 80] [--check]
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("--width", type=int, default=80)
ap.add_argument("--over", type=int, default=84)
ap.add_argument("--from", dest="frm", type=int, default=1)
ap.add_argument("--to", dest="to", type=int, default=10 ** 9)
ap.add_argument("--check", action="store_true")
ap.add_argument("--no-yaml", action="store_true",
              help="python files: skip the YAML re-parse (the non-comment-line guard still runs)")
a = ap.parse_args()

p = Path(a.path)
lines = p.read_text().split("\n")
pat = re.compile(r"^(\s*)#(.*)$")


def fill(words, prefix, width):
    out, cur = [], prefix
    for w in words:
        if cur.strip() and len(cur) + 1 + len(w) > width:
            out.append(cur.rstrip())
            cur = prefix
        cur += w + " "
    out.append(cur.rstrip())
    return out


def wrap_para(body, indent, width):
    """One prose paragraph: fill words under `# ` at the run's indent.

    Bullets are never re-flowed: this file's lists (`#  - ...`, `#    ...`) carry
    their own alignment and joining them would silently merge two list items into
    one claim, so callers skip runs containing them instead.
    """
    return fill(body.split(), indent + "# ", a.width)


out, i, changed = [], 0, 0
while i < len(lines):
    m = pat.match(lines[i])
    in_range = a.frm <= i + 1 <= a.to
    if not (m and in_range):
        out.append(lines[i])
        i += 1
        continue
    indent = m.group(1)
    run = []
    j = i
    while j < len(lines):
        mm = pat.match(lines[j])
        if not mm or mm.group(1) != indent or not a.frm <= j + 1 <= a.to:
            break
        run.append(mm.group(2).strip())
        j += 1
    if max((len(indent + "# " + b) if b else len(indent + "#")) for b in run) <= a.over:
        out.extend(lines[i:j])          # nobody needs this rewrapped
        i = j
        continue
    if any(b.startswith("- ") or re.match(r"^-[^-]", b) for b in run):
        out.extend(lines[i:j])          # a list: its items stay separate lines
        i = j
        continue
    new_run, para = [], []
    for b in run:
        if b == "":
            if para:
                new_run += wrap_para(" ".join(para), indent, a.width)
                para = []
            new_run.append(indent + "#")
        else:
            para.append(b)
    if para:
        new_run += wrap_para(" ".join(para), indent, a.width)
    out.extend(new_run)
    if new_run != lines[i:j]:
        changed += 1
    i = j

src = "\n".join(out)
before = [l for l in lines if not pat.match(l)]
after = [l for l in out if not pat.match(l)]
if before != after:
    sys.exit("REFUSED: a non-comment line would change")
docs = None
if not a.no_yaml:
    try:
        docs = list(yaml.safe_load_all(src))
    except yaml.YAMLError as e:
        sys.exit("REFUSED: result does not parse (%s)" % e)
over = sum(1 for n, l in enumerate(out, 1) if a.frm <= n <= a.to and len(l) > a.over)
print("%s: %d comment block(s) re-wrapped to %d columns; %d line(s) still over %d; %d -> %d lines"
      % (p.name, changed, a.width, over, a.over, len(lines), len(out)))
if a.check:
    sys.exit(0)
p.write_text(src)
print("wrote %s%s" % (p.name, "" if a.no_yaml else " (%d docs parse)" % len([d for d in docs if d])))
