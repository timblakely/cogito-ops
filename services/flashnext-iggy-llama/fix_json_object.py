"""Recognize an empty JSON schema as JSON-object mode in the pinned Qwen parser."""
from pathlib import Path
import sys

source = Path(sys.argv[1]) / "common/chat.cpp"
text = source.read_text()
start = text.index("static common_chat_params common_chat_params_init_qwen3_coder(")
end = text.index("\nstatic common_chat_params", start + 1)
section = text[start:end]
before = "auto has_response_format = inputs.json_schema.is_object() && !inputs.json_schema.empty();"
after = "auto has_response_format = inputs.json_schema.is_object();"
assert section.count(before) == 1, "Pinned Qwen parser differs; review before applying"
source.write_text(text[:start] + section.replace(before, after) + text[end:])
