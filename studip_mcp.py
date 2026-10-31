#!/usr/bin/env python3
"""Read-only MCP server for Stud.IP (Uni Göttingen) via the JSON:API.

Tools: list_courses, list_course_files, read_file, view_slides.
Auth: HTTP Basic (username + password). The password is stored in the
Windows Credential Manager (keyring); run once:  python studip_mcp.py --set-password
"""
import getpass
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP, Image
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP, Image

BASE_URL = os.environ.get("STUDIP_BASE_URL", "https://studip.uni-goettingen.de/jsonapi.php/v1").rstrip("/") + "/"
USER = os.environ.get("STUDIP_USER", "")
DOWNLOAD_DIR = Path(os.environ.get("STUDIP_DOWNLOAD_DIR", str(Path.home() / "Studium")))
KEYRING_SERVICE = "studip-mcp"
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".py", ".r", ".tex", ".json", ".ipynb", ".sql", ".html"}

mcp = FastMCP("studip")

_client = None
_me_id = None
_semesters = None   # id -> (title, start_ts, end_ts)
_courses = {}       # id -> course resource
_files = {}         # file_ref id -> (course_id, folder_path, name, size)


# ---------------------------------------------------------------- helpers

def _password(user):
    try:
        import keyring
        pw = keyring.get_password(KEYRING_SERVICE, user)
        if pw:
            return pw
    except Exception:
        pass
    return os.environ.get("STUDIP_PASSWORD")


def _client_():
    global _client
    if _client is None:
        if not USER:
            raise RuntimeError("STUDIP_USER is not set in the MCP config.")
        pw = _password(USER)
        if not pw:
            raise RuntimeError("No password stored. Run once in a terminal: python studip_mcp.py --set-password")
        _client = httpx.Client(base_url=BASE_URL, auth=(USER, pw), timeout=120, follow_redirects=True)
    return _client


def _get(path, params=None):
    r = _client_().get(path, params=params)
    if r.status_code == 401:
        raise RuntimeError("Login failed (401): check username/password (python studip_mcp.py --set-password).")
    r.raise_for_status()
    return r.json()


def _get_all(path, params=None):
    out, offset = [], 0
    while True:
        p = dict(params or {})
        p["page[limit]"] = 100
        p["page[offset]"] = offset
        d = _get(path, p)
        data = d.get("data") or []
        out.extend(data)
        offset += len(data)
        total = ((d.get("meta") or {}).get("page") or {}).get("total")
        if not data or total is None or offset >= int(total):
            return out


def _rel_id(obj, name):
    data = ((obj.get("relationships") or {}).get(name) or {}).get("data")
    return data.get("id") if isinstance(data, dict) else None


def _ts(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def _me():
    global _me_id
    if _me_id is None:
        _me_id = _get("users/me")["data"]["id"]
    return _me_id


def _sems():
    global _semesters
    if _semesters is None:
        _semesters = {}
        for s in _get_all("semesters"):
            a = s.get("attributes") or {}
            _semesters[s["id"]] = (a.get("title", "?"), _ts(a.get("start")), _ts(a.get("end")))
    return _semesters


def _course(cid):
    if cid not in _courses:
        _courses[cid] = _get(f"courses/{cid}")["data"]
    return _courses[cid]


def _semester_title(course):
    return _sems().get(_rel_id(course, "start-semester"), ("unknown semester", 0, 0))[0]


def _safe(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return name[:120] or "_"


def _size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _file_info(fid):
    if fid not in _files:
        d = _get(f"file-refs/{fid}")["data"]
        a = d.get("attributes") or {}
        folder = ""
        pid = _rel_id(d, "parent")
        if pid:
            try:
                folder = _get(f"folders/{pid}")["data"]["attributes"].get("name", "")
            except Exception:
                pass
        _files[fid] = (_rel_id(d, "range"), folder, a.get("name", fid), a.get("filesize"))
    return _files[fid]


def _download(fid):
    cid, folder, name, size = _file_info(fid)
    target = DOWNLOAD_DIR
    if cid:
        c = _course(cid)
        target = target / _safe(_semester_title(c)) / _safe(c["attributes"].get("title", cid))
    else:
        target = target / "_other"
    for part in [p for p in folder.split("/") if p]:
        target = target / _safe(part)
    target = target / _safe(name)

    try:
        if target.exists() and size is not None and target.stat().st_size == int(size):
            return target
    except (TypeError, ValueError):
        pass

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    with _client_().stream("GET", f"file-refs/{fid}/content") as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(target)
    return target


def _parse_pages(spec, count):
    """'1-5,8' -> [0,1,2,3,4,7] (0-based, clipped). Empty -> all pages."""
    if not spec or not str(spec).strip():
        return list(range(count))
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a.strip() else 1
            b = int(b) if b.strip() else count
            out.extend(range(a - 1, b))
        else:
            out.append(int(part) - 1)
    return [i for i in dict.fromkeys(out) if 0 <= i < count]


# ------------------------------------------------------------------ tools

@mcp.tool()
def list_courses(semester: str = "current") -> str:
    """List the user's Stud.IP courses with their ids, grouped by semester (newest first).

    semester: "current" (default) = the semester running today, "all" = every semester,
    or a text filter on the semester title, e.g. "WiSe 2025".
    """
    sems = _sems()
    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for c in _get_all(f"users/{_me()}/courses"):
        _courses[c["id"]] = c
        a = c.get("attributes") or {}
        title, start, end = sems.get(_rel_id(c, "start-semester"), ("unknown semester", 0, 0))
        rows.append((start, end, title, a.get("title", ""), a.get("subtitle") or "", c["id"]))

    sel = (semester or "current").strip().lower()
    if sel == "current":
        running = [r for r in rows if r[1] and r[0] <= now <= r[1]]
        if not running:  # e.g. between semesters: take the newest one
            newest = max((r[0] for r in rows), default=0)
            running = [r for r in rows if r[0] == newest]
        rows = running
    elif sel != "all":
        rows = [r for r in rows if sel in r[2].lower()]

    if not rows:
        return "No courses found for this filter."
    rows.sort(key=lambda r: (-r[0], r[3].lower()))
    out, last = [], None
    for _, _, sem, title, sub, cid in rows:
        if sem != last:
            out.append(f"\n## {sem}")
            last = sem
        out.append(f"- {title}" + (f" ({sub})" if sub else "") + f"  [course_id: {cid}]")
    return "\n".join(out).strip()


@mcp.tool()
def list_course_files(course_id: str) -> str:
    """List all folders and files of a course (ids from list_courses). Returns file ids for read_file/view_slides."""
    folders = _get_all(f"courses/{course_id}/folders")
    by_id = {f["id"]: f for f in folders}

    def path(f):
        parts, cur, seen = [], f, set()
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            parent = by_id.get(_rel_id(cur, "parent"))
            if parent is None:  # cur is the course's root folder
                break
            parts.append((cur.get("attributes") or {}).get("name", ""))
            cur = parent
        return "/".join(reversed(parts))

    out = []
    for p, f in sorted(((path(f), f) for f in folders), key=lambda x: x[0].lower()):
        files = _get_all(f"folders/{f['id']}/file-refs")
        if not files:
            continue
        out.append(f"\n## {p or '(main folder)'}")
        for fr in sorted(files, key=lambda x: (x.get("attributes") or {}).get("name", "").lower()):
            a = fr.get("attributes") or {}
            _files[fr["id"]] = (course_id, p, a.get("name", fr["id"]), a.get("filesize"))
            date = str(a.get("chdate") or a.get("mkdate") or "")[:10]
            out.append(f"- {a.get('name')}  ({_size(a.get('filesize'))}, {date})  [file_id: {fr['id']}]")
    return "\n".join(out).strip() or "This course has no files."


@mcp.tool()
def read_file(file_id: str, pages: str = "", max_chars: int = 60000) -> str:
    """Download a file (cached under ~/Studium/<semester>/<course>/<folder>/) and return its text.

    For PDFs the text is split by page. pages: e.g. "1-10" or "3,5,7-9" (empty = all).
    Long output is cut at max_chars; request the remaining pages with `pages`.
    """
    path = _download(file_id)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf as fitz
        with fitz.open(path) as doc:
            idx = _parse_pages(pages, doc.page_count)
            parts, total, last = [], 0, None
            for i in idx:
                chunk = f"--- Page {i + 1} ---\n{doc[i].get_text().strip()}\n"
                if total + len(chunk) > max_chars and parts:
                    break
                parts.append(chunk)
                total += len(chunk)
                last = i
            head = f"File: {path}\nPages total: {doc.page_count}\n"
            if last is not None and idx and last != idx[-1]:
                head += f"Truncated after page {last + 1}; continue with pages=\"{last + 2}-{idx[-1] + 1}\".\n"
            return head + "\n" + "\n".join(parts)
    if suffix in TEXT_SUFFIXES:
        text = path.read_text(encoding="utf-8", errors="replace")
        return f"File: {path}\n\n{text[:max_chars]}"
    return f"Saved to {path}. No text extraction for {suffix or 'this'} files."


@mcp.tool()
def view_slides(file_id: str, pages: str = "1-4", zoom: float = 1.3):
    """Render PDF pages as images (for figures, formulas, diagrams). Max 8 pages per call. pages: e.g. "5-8"."""
    import pymupdf as fitz
    path = _download(file_id)
    if path.suffix.lower() != ".pdf":
        return [f"Not a PDF: {path}"]
    out = []
    with fitz.open(path) as doc:
        n = doc.page_count
        idx = _parse_pages(pages, n)[:8]
        for i in idx:
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            out.append(f"Page {i + 1} of {n}")
            out.append(Image(data=pix.tobytes("jpeg"), format="jpeg"))
    return out or [f"No valid pages in '{pages}' (document has pages 1-{n})."]


# ------------------------------------------------------------------- setup

def _print_config():
    """Print the 'studip' entry for claude_desktop_config.json, with this machine's paths filled in.

    The config file's location differs between Claude Desktop versions and installers, so the user
    pastes the entry via Settings -> Developer -> Edit Config instead of us guessing the path."""
    if not USER:
        raise SystemExit("STUDIP_USER must be set.")
    entry = {"command": sys.executable, "args": [str(Path(__file__).resolve())], "env": {"STUDIP_USER": USER}}
    print(f'"studip": {json.dumps(entry, indent=2)}')


# ------------------------------------------------------------------- main

if __name__ == "__main__":
    if "--set-password" in sys.argv:
        import keyring
        user = USER or input("Stud.IP username: ").strip()
        keyring.set_password(KEYRING_SERVICE, user, getpass.getpass(f"Password for {user}: "))
        print("Saved to Windows Credential Manager.")
    elif "--test" in sys.argv:
        if not USER:
            USER = input("Stud.IP username: ").strip()
        try:
            print(list_courses("current"))
        except Exception as e:  # short message instead of a traceback for setup.ps1 users
            raise SystemExit(f"Error: {e}")
    elif "--print-config" in sys.argv:
        _print_config()
    else:
        mcp.run()
