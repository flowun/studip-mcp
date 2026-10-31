# Stud.IP MCP (read-only)

A small [MCP](https://modelcontextprotocol.io) server that gives Claude Desktop read-only access to your
courses and files on [Stud.IP](https://www.studip.de/) via its JSON:API. Defaults to the Uni Göttingen
instance; other Stud.IP installations work via `STUDIP_BASE_URL`.

This is an unofficial tool, not affiliated with Stud.IP e.V. or the University of Göttingen. It only reads data
your account can already see, using your own login.

## Requirements

- Windows with Claude Desktop
- Python 3.10+
- A Stud.IP account that can log in with username + password (HTTP Basic auth on the JSON:API)

## Setup (once)

1. Clone or copy this folder somewhere permanent.
2. In PowerShell, inside that folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```

   The script
   - asks for your Stud.IP username (remembered in `.studip_user`, which is git-ignored),
   - creates `.venv` and installs the dependencies into it,
   - asks for your Stud.IP password and stores it in the Windows Credential Manager (never in a file),
   - tests the connection by printing your current courses,
   - prints the `studip` entry for Claude Desktop's config, with your paths and username filled in,
     and copies it to the clipboard.
3. Add that entry to Claude Desktop's config:
   1. In Claude Desktop open **Settings → Developer → Edit Config** to find `claude_desktop_config.json`.
      Use this menu rather than looking for the file yourself: its location differs between
      Claude Desktop versions and installers.
   2. Quit Claude Desktop completely (tray icon → Quit). Claude Desktop also saves its own settings to this file
      and can overwrite your change while it is running.
   3. Open the file in a text editor and paste the entry inside `"mcpServers"`. Keep everything else in the file
      (other servers, `preferences`, …).
      The result looks like this, with your own paths:

      ```json
      {
        "mcpServers": {
          "other-server": { "...": "..." },
          "studip": {
            "command": "C:\\path\\to\\studip-mcp\\.venv\\Scripts\\python.exe",
            "args": ["C:\\path\\to\\studip-mcp\\studip_mcp.py"],
            "env": { "STUDIP_USER": "your-username" }
          }
        },
        "preferences": { "...": "..." }
      }
      ```

      Entries are separated by commas. If there is no `"mcpServers"` yet, add it as shown.
      Backslashes in paths must be doubled (`\\`); the printed entry already does this. Save the file.
   4. Start Claude Desktop again.

Re-run later (e.g. after updating the script, or to print the config entry again) without re-entering the password:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -KeepPassword
```

The username can also be passed directly: `setup.ps1 -User <username>`.

The script looks for Python 3.10+ via the `py` launcher, `python` on PATH (ignoring the Microsoft Store alias),
python.org installs and Anaconda/Miniconda. To use a specific interpreter: `setup.ps1 -Python C:\path\to\python.exe`.

## Tools

| Tool | Description |
|---|---|
| `list_courses(semester)` | `"current"` (default), `"all"`, or a filter on the semester title such as `"SoSe 2026"` |
| `list_course_files(course_id)` | Folders and files of a course, with file ids |
| `read_file(file_id, pages, max_chars)` | Downloads a file and returns its text (PDFs per page) |
| `view_slides(file_id, pages, zoom)` | Renders up to 8 PDF pages as images |

Downloads are cached in `%USERPROFILE%\Studium\<semester>\<course>\<folder>\`.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `STUDIP_USER` | — (in the config entry `setup.ps1` prints) | Stud.IP username |
| `STUDIP_BASE_URL` | `https://studip.uni-goettingen.de/jsonapi.php/v1` | JSON:API endpoint |
| `STUDIP_DOWNLOAD_DIR` | `%USERPROFILE%\Studium` | Download cache |
| `STUDIP_PASSWORD` | — | Fallback if no password is stored in the Credential Manager |

## License

MIT, see [LICENSE](LICENSE). The PDF features use [PyMuPDF](https://pymupdf.readthedocs.io/), which is
licensed separately under AGPL-3.0.
