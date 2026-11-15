import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

REVISION = "5ca1df1d2436bd1ab270b169c5ea6c47aad23641"
REPO = "peasantsmith/GLM-5.3-Flash-Maya-GGUF"
FILES = [
    ("GLM-5.3-Flash-Maya-M-IQ2_S-00001-of-00003.gguf", 47678327584,
     "3f740d1b1022b4a0ddad50cd861bb071dd415bde94afa1292d0476641186c638"),
    ("GLM-5.3-Flash-Maya-M-IQ2_S-00002-of-00003.gguf", 47820244896,
     "285951d2afa0cd98285b03d0dc4aa68d83daf1a6f4a2594fe40b0cdd27ade485"),
    ("GLM-5.3-Flash-Maya-M-IQ2_S-00003-of-00003.gguf", 20504990688,
     "ebf1ce713f71207747e10eeebed87597969d8b5e1d9dd817420d2c2f7ca51e0e"),
]
CHUNK = 8 << 20
DRAIN = 256 << 20


def log(message):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + message
    print(line, flush=True)
    if os.environ.get("STAGING_LOG"):
        with open(os.environ["STAGING_LOG"], "a") as out:
            out.write(line + "\n")


def drain(file):
    file.flush()
    os.fsync(file.fileno())
    os.posix_fadvise(file.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as src:
        while data := src.read(CHUNK):
            result.update(data)
            os.posix_fadvise(src.fileno(), 0, src.tell(), os.POSIX_FADV_DONTNEED)
    return result.hexdigest()


def verified(path, size, want):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Existing path is not a regular file; preserved: {path}")
    if metadata.st_size != size:
        raise ValueError(f"Existing file has wrong size; preserved: {path}")
    got = sha256(path)
    if got != want:
        raise ValueError(f"Existing complete file has wrong SHA256; preserved: {path}")
    log(f"SHA256 PASS {path} bytes={size} sha256={got}")
    return True


def download(url, target, size, want):
    partial = target.with_name(target.name + ".partial")
    for attempt in range(8):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > size:
            raise ValueError(f"Oversized partial preserved: {partial}")
        if offset == size:
            break
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if offset:
                    expected = f"bytes {offset}-"
                    if response.status != 206 or not response.headers.get("Content-Range", "").startswith(expected):
                        raise ValueError("Server ignored resume range; refusing a duplicate full download")
                elif response.status != 200:
                    raise ValueError(f"Unexpected initial HTTP status {response.status}")
                log(f"DOWNLOAD {target.name} offset={offset} bytes={size} attempt={attempt + 1}")
                with partial.open("ab") as out:
                    since_drain = 0
                    next_progress = offset + (1 << 30)
                    while data := response.read(CHUNK):
                        if out.tell() + len(data) > size:
                            raise ValueError("Response exceeded pinned artifact size")
                        out.write(data)
                        since_drain += len(data)
                        if since_drain >= DRAIN:
                            drain(out)
                            since_drain = 0
                        if out.tell() >= next_progress:
                            log(f"PROGRESS {target.name} {out.tell()}/{size}")
                            next_progress = out.tell() + (1 << 30)
                    drain(out)
            if partial.stat().st_size != size:
                raise OSError("Response ended before pinned artifact size")
            break
        except (urllib.error.URLError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == 7:
                raise
            retry_after = exc.headers.get("Retry-After", "0") if isinstance(exc, urllib.error.HTTPError) else "0"
            delay = max(min(20 * 2 ** attempt, 300), int(retry_after) if retry_after.isdigit() else 0)
            log(f"RETRY {type(exc).__name__}: {exc}; sleep={delay}")
            time.sleep(delay)
    if not verified(partial, size, want):
        raise ValueError(f"Incomplete artifact preserved: {partial}")
    partial.replace(target)


def copy_verified(source, target, size, want):
    partial = target.with_name(target.name + ".partial")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        raise ValueError(f"Oversized copy partial preserved: {partial}")
    log(f"LAN COPY {source} -> {target} offset={offset}")
    with source.open("rb") as src, partial.open("ab") as out:
        src.seek(offset)
        since_drain = 0
        while data := src.read(CHUNK):
            out.write(data)
            since_drain += len(data)
            if since_drain >= DRAIN:
                drain(out)
                os.posix_fadvise(src.fileno(), 0, src.tell(), os.POSIX_FADV_DONTNEED)
                since_drain = 0
        drain(out)
        os.posix_fadvise(src.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    if not verified(partial, size, want):
        raise ValueError(f"Incomplete archive copy preserved: {partial}")
    partial.replace(target)


def stage_file(hot, cold, name, size, want, base):
    hot_file, cold_file = hot / name, cold / name
    if verified(hot_file, size, want):
        if not verified(cold_file, size, want):
            copy_verified(hot_file, cold_file, size, want)
    elif verified(cold_file, size, want):
        copy_verified(cold_file, hot_file, size, want)
    else:
        download(f"{base}/{name}", hot_file, size, want)
        copy_verified(hot_file, cold_file, size, want)
    return {"name": name, "bytes": size, "sha256": want}


def main():
    hot = Path(os.environ.get("HOT_ROOT", "/model/Maya-M"))
    cold = Path(os.environ.get("COLD_ROOT", "/archive/llmkube/glm-5.3-flash-maya-m/Maya-M"))
    hot.mkdir(parents=True, exist_ok=True)
    cold.mkdir(parents=True, exist_ok=True)
    os.environ["STAGING_LOG"] = str(hot / ".staging.log")
    fs = os.statvfs(hot)
    remaining = sum(max(0, size - max((hot / name).stat().st_size if (hot / name).exists() else 0,
                                    (hot / (name + ".partial")).stat().st_size if (hot / (name + ".partial")).exists() else 0))
                    for name, size, _ in FILES)
    if fs.f_bavail * fs.f_frsize < remaining + (8 << 30):
        raise ValueError("Backing filesystem lacks remaining pinned bytes plus 8 GiB reserve")
    log(f"START repo={REPO} revision={REVISION} hot={hot} cold={cold}")
    base = f"https://huggingface.co/{REPO}/resolve/{REVISION}/Maya-M"
    checks = [stage_file(hot, cold, name, size, want, base) for name, size, want in FILES]
    report = {"repo": REPO, "revision": REVISION, "files": checks, "completed_at": time.time()}
    for root in [hot, cold]:
        partial = root / ".verified.json.partial"
        with partial.open("w") as out:
            json.dump(report, out, indent=2)
            drain(out)
        partial.replace(root / ".verified.json")
    log("ALL_THREE_SHARDS_VERIFIED_ON_HOT_AND_NAS")


if __name__ == "__main__":
    main()
