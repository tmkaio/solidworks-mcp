# Installation Guide

## Prerequisites

- **Windows 10 or 11** (64-bit)
- **SolidWorks 2022 or newer** — installed, activated, and able to open a file
- **Python 3.10, 3.11 or 3.12** — from [python.org](https://www.python.org/downloads/). Install to a path **without spaces** (e.g. `C:\Python312`)
- **Claude Desktop** — latest version

---

## Step 1: Clone the repository

```bat
git clone https://github.com/yourusername/solidworks-mcp.git
cd solidworks-mcp
```

---

## Step 2: Create a virtual environment

```bat
python -m venv .venv
.venv\Scripts\activate
```

Your prompt should show `(.venv)`.

---

## Step 3: Install the package

```bat
pip install -e .
```

Verify pywin32:
```bat
python -c "import win32com.client; print('pywin32 OK')"
```

---

## Step 4: (Optional) Install CadQuery

CadQuery enables `analyze_step_standalone` without SolidWorks running.

**Option A: Conda (recommended)**
```bat
conda install -c cadquery cadquery
```

**Option B: pip**
```bat
pip install cadquery
```

Verify:
```bat
python -c "import cadquery; print('CadQuery', cadquery.__version__, 'OK')"
```

---

## Step 5: Configure Claude Desktop

Locate: `%APPDATA%\Claude\claude_desktop_config.json`

Add the `solidworks` server. Replace the path with your actual clone location:

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "C:\\path\\to\\solidworks-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "solidworks_mcp.server"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\solidworks-mcp\\src",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

> Use **absolute paths** everywhere. Relative paths fail when Claude Desktop
> launches the server from a different working directory.

---

## Step 6: Restart Claude Desktop

Fully quit and relaunch. A hammer icon (🔨) should appear in the chat toolbar.

---

## Step 7: Test the connection

Open SolidWorks manually. In Claude Desktop:

```
Call solidworks_connect and tell me the SolidWorks version.
```

Expected response: `Connected to SolidWorks 30.4.0` (version varies by install).

---

## Step 8: Run the test suite

```bat
.venv\Scripts\activate
pytest tests/ -v
```

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Developer setup

```bat
pip install -e ".[dev]"
ruff check src/ tests/
ruff format src/ tests/
```
