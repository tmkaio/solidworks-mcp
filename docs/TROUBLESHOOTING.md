# Troubleshooting

## Hammer icon does not appear in Claude Desktop

1. Check logs: `%APPDATA%\Claude\logs\`
2. Validate `claude_desktop_config.json` is valid JSON
3. Test the server directly:
   ```bat
   .venv\Scripts\activate
   python -m solidworks_mcp.server
   ```
   Should hang waiting for stdin. Any import error appears here.
4. Verify PYTHONPATH:
   ```bat
   set PYTHONPATH=C:\path\to\solidworks-mcp\src
   python -c "from solidworks_mcp.server import mcp; print('OK')"
   ```
5. Fully quit Claude Desktop (check Task Manager — it runs in the tray).

---

## `SolidWorksNotRunningError`

- Open SolidWorks manually and sign in before calling `solidworks_connect`.
- Claude Desktop must run as the **same user** as the SolidWorks session.
  COM server access is user-session bound.

---

## `SolidWorksConnectionError: Not connected`

Call `solidworks_connect` first in every session.

---

## `open_file` returns error code `0x800401E3`

COM class not registered (`MK_E_UNAVAILABLE`).

1. Re-run the pywin32 post-install:
   ```bat
   python Scripts\pywin32_postinstall.py -install
   ```
2. Confirm you are using **64-bit Python**:
   ```bat
   python -c "import platform; print(platform.architecture())"
   # Must show: ('64bit', 'WindowsPE')
   ```

---

## `open_file` returns error code `0x80010108`

`RPC_E_DISCONNECTED` — SolidWorks crashed or was closed.

1. Force-kill `SOLIDWORKS.exe` in Task Manager.
2. Reopen SolidWorks.
3. Call `solidworks_connect` again.

---

## `get_part_info` returns "GetMassProperties2 returned None"

The part has no material assigned.

1. In SolidWorks, right-click the part → **Material** → select a material.
2. Rebuild (Ctrl+B).
3. Call `get_part_info` again.

---

## `analyze_bends` returns "not a sheet metal part"

The part was imported from STEP and has no SheetMetal feature.

1. Call `convert_to_sheet_metal(thickness=<mm>)`.
2. Then call `analyze_bends`.

Use `analyze_step_standalone` to estimate the thickness first.

---

## `flatten_part` fails

1. Verify the part is sheet metal (`is_sheet_metal` tool).
2. Open in SolidWorks and check the FeatureManager for errors (red items).
3. Force rebuild: `Ctrl+Q`.

---

## `export_dxf` creates an empty file

The part was not in flat pattern state when exported.

1. Call `flatten_part`.
2. Call `export_dxf`.
3. Call `unflatten_part`.

---

## `analyze_step_standalone` returns "CadQuery is not installed"

```bat
conda install -c cadquery cadquery
```

See [INSTALL.md](INSTALL.md).

---

## SolidWorks asks for login every time

Sign in manually before starting Claude Desktop so credentials are cached
for the Windows session.

---

## Reporting bugs

Include:
- SolidWorks version (`solidworks_status` → `version` field)
- Python version (`python --version`)
- Tool name + exact error message
- Relevant lines from `%USERPROFILE%\.solidworks-mcp\logs\server.log`
