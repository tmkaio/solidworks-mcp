# solidworks-mcp

[![CI](https://github.com/tmkaio/solidworks-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/tmkaio/solidworks-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

MCP server that connects **Claude Desktop** to **SolidWorks** via COM API,
enabling automated analysis of sheet metal parts for the tooling and stamping industry.

## What it does

A tooling engineer can open Claude Desktop and say:

> "Open `bracket.step`, tell me the thickness, all hole diameters, number of bends,
> and export the flat pattern as a DXF."

Claude calls the MCP tools to:
1. Open the STEP in SolidWorks
2. Detect sheet metal, read thickness + K-factor
3. Enumerate and group all holes by diameter
4. Count and characterise each bend (angle, radius, length)
5. Flatten the part and export the flat pattern as DXF
6. Return a structured analysis report

**Time saved:** 60–90 minutes of manual inspection → ~60 seconds.

## Try it without SolidWorks

Most of this project needs a licensed SolidWorks install, but
`analyze_step_standalone` runs anywhere CadQuery does. Against the test
fixture in this repo:

```bash
pip install -e .
conda install -c cadquery cadquery   # see docs/INSTALL.md for the pip route
python -c "
from mcp.server.fastmcp import FastMCP
from solidworks_mcp.solidworks_bridge import SolidWorksBridge
from solidworks_mcp.tools.analysis import register
import json
mcp = FastMCP('demo'); register(mcp, SolidWorksBridge())
fn = mcp._tool_manager._tools['analyze_step_standalone'].fn
print(json.dumps(fn(file_path='tests/fixtures/sample_part.step'), indent=2))
"
```

Actual output for `sample_part.step` — a 100 x 60 x 2 mm plate with four
Ø6 mm through holes (abridged; the full result also carries `file_path`,
the individual bounding-box bounds, and a units note):

```json
{
  "file_size_kb": 33.48,
  "volume_mm3": 11773.81,
  "surface_area_mm2": 12564.6,
  "bounding_box": {
    "dimensions_mm": [100.0, 60.0, 2.0]
  },
  "center_of_mass_mm": { "x": 0.0, "y": 0.0, "z": 1.0 },
  "face_count": 10,
  "face_types": { "PLANE": 6, "CYLINDER": 4 },
  "estimated_thickness_mm": 2.0,
  "is_likely_sheet_metal": true
}
```

The four holes show up as the four cylindrical faces, and thickness is
inferred from the smallest bounding-box dimension.

## Prerequisites

| Requirement | Version |
|---|---|
| Windows | 10 or 11 (64-bit) |
| Python | 3.10, 3.11 or 3.12 |
| SolidWorks | Standard 2022 or newer (must be installed and licensed) |
| Claude Desktop | latest |

SolidWorks must be installed and activated on the same machine as this server.
The COM API requires the full application — SolidWorks PDM or Viewer are not sufficient.

## Quick Install

```bat
REM 1. Clone the repository
git clone https://github.com/tmkaio/solidworks-mcp.git
cd solidworks-mcp

REM 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate

REM 3. Install the package
pip install -e .

REM 4. (Optional) Install CadQuery for standalone STEP analysis
conda install -c cadquery cadquery
```

## Configure Claude Desktop

Copy `claude_desktop_config.example.json` and merge into your Claude config:

**Location:** `%APPDATA%\Claude\claude_desktop_config.json`

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

Restart Claude Desktop. A hammer icon (🔨) should appear in the chat toolbar.

See [docs/INSTALL.md](docs/INSTALL.md) for a step-by-step guide.

## Example conversation

```
You: Open C:\parts\door_hinge.step and give me a full analysis.

Claude: [calls open_file, get_part_info, analyze_holes, analyze_bends]

        The door hinge is a sheet metal part:
        - Thickness: 2.00 mm (K-factor: 0.44)
        - Bounding box: 120 x 80 x 45 mm
        - Mass: 312 g
        - 12 holes: Ø6mm x 4, Ø8mm x 4, Ø12mm x 4
        - 3 bends: 90° x R2mm (two) and 45° x R3mm (one)
        - Complexity: medium

You: Export the flat pattern as DXF to C:\output\hinge_flat.dxf

Claude: [calls flatten_part, export_dxf, unflatten_part]
        Flat pattern exported: C:\output\hinge_flat.dxf (18.4 KB)
        Flat dimensions: 310 x 80 mm
```

## Available tools

### Connection
| Tool | Description |
|---|---|
| `solidworks_connect` | Connect to SolidWorks (start if not running) |
| `solidworks_status` | Check connection state and active document |
| `solidworks_disconnect` | Release COM references |

### Files
| Tool | Description |
|---|---|
| `open_file` | Open STEP, SLDPRT, IGES, etc. |
| `close_file` | Close active document |
| `save_file` | Save / Save As |
| `list_open_documents` | List all open files |

### Analysis
| Tool | Description |
|---|---|
| `get_part_info` | Mass, volume, material, sheet metal flag |
| `get_bounding_box` | L x W x H + diagonal |
| `count_features_by_type` | Feature histogram |
| `analyze_holes` | All holes grouped by diameter |
| `analyze_bends` | All bends with angle/radius/length |
| `get_geometry_stats` | Executive summary + complexity rating |
| `generate_part_report` | Full JSON + Markdown report |
| `analyze_step_standalone` | **No SolidWorks needed** — uses CadQuery |
| `get_moments_of_inertia` | Ixx/Iyy/Izz + products of inertia |
| `analyze_faces` | Face type breakdown (planar/cylindrical/etc.) |

### Sheet Metal
| Tool | Description |
|---|---|
| `is_sheet_metal` | True/False check |
| `get_sheet_metal_properties` | Thickness, K-factor, bend radius |
| `convert_to_sheet_metal` | Convert imported solid to sheet metal |
| `flatten_part` | Activate flat pattern |
| `unflatten_part` | Return to folded state |

### Export
| Tool | Description |
|---|---|
| `export_dxf` | Flat pattern -> DXF (for laser / NC) |
| `export_step` | Part -> STEP AP214 |
| `export_stl` | Part -> STL |
| `export_pdf` | Document -> PDF |
| `take_screenshot` | Viewport -> PNG |

### Custom Properties & Materials
| Tool | Description |
|---|---|
| `get_custom_properties` | Read all custom properties from active document |
| `get_custom_property` | Read a single named property |
| `set_custom_property` | Create or update a custom property |
| `delete_custom_property` | Remove a custom property |
| `set_material` | Assign a material from the SolidWorks library |
| `get_material_databases` | List available .sldmat material databases |

### Configurations
| Tool | Description |
|---|---|
| `list_configurations` | List all configurations with active flag |
| `get_active_configuration` | Details of the current active configuration |
| `switch_configuration` | Activate a different configuration |
| `add_configuration` | Create a new configuration (copy of existing) |
| `delete_configuration` | Remove a configuration |
| `get_configuration_properties` | Config-specific custom properties |

### Measurements
| Tool | Description |
|---|---|
| `measure_distance` | Distance between two named entities |
| `measure_entity` | Length/area/coordinates of a single entity |
| `get_face_properties` | Area, normal, centroid of a face by index |
| `measure_minimum_distance` | Minimum clearance between two entities |
| `get_section_properties` | Cross-section Ixx/Iyy/area/centroid |

### Feature Management
| Tool | Description |
|---|---|
| `list_features` | List FeatureManager tree (with type filter) |
| `get_feature_info` | Type, suppression state, error for a feature |
| `suppress_feature` | Suppress a feature in a configuration |
| `unsuppress_feature` | Restore a suppressed feature |
| `get_feature_dimensions` | Parametric dimensions on a feature |
| `rebuild_model` | Force rebuild (standard or full) |
| `get_feature_error` | Describe a feature rebuild error |

### Drawings
| Tool | Description |
|---|---|
| `create_drawing_from_part` | Create new drawing from active part/assembly |
| `add_drawing_view` | Add standard/isometric view to drawing |
| `list_drawing_views` | List all views on the drawing |
| `get_drawing_info` | Sheet count, scale, paper size |
| `set_drawing_scale` | Change drawing sheet scale |

### Assemblies
| Tool | Description |
|---|---|
| `get_assembly_components` | List all components (top-level or recursive) |
| `get_component_count` | Quick component count |
| `get_assembly_bom` | Bill of Materials with quantities |
| `list_assembly_mates` | List all mate constraints |
| `get_component_info` | Mass, path, bbox for a named component |
| `get_assembly_mass` | Total assembly mass and centre of mass |

## Limitations (v0.1)

- **Assembly support is read-only.** Components, BOM, mates and mass can be
  read; creating mates or inserting components is not supported.
- **No parametric editing.** Features can be listed, suppressed and
  unsuppressed, but dimensions cannot be driven.
- **STEP files import as "dumb" solids.** `convert_to_sheet_metal` must run
  before bend analysis will return anything.
- **No strip layout / progressive die design.**
- **Windows only**, and requires a licensed local SolidWorks install — the
  COM API needs the full application. The one exception is
  `analyze_step_standalone`, which runs anywhere via CadQuery.

## Roadmap

| Version | Feature |
|---|---|
| v0.2 | Strip layout tools — station configuration |
| v0.3 | Force calculations (cut, bend, draw) |

Beyond that: formability and undercut detection, GD&T annotation on
generated drawings, and nesting integration are all plausible directions,
but nothing is committed.

## Development

The test suite mocks the COM layer, so it runs on any platform — no Windows
and no SolidWorks licence required:

```bash
pip install -e ".[dev]"
ruff check src tests
pytest -v
```

On Windows that is the whole story. CI runs the same two commands on Linux,
but installs the pure-Python dependencies directly rather than via
`pip install -e .`, because `pywin32` has no Linux wheel.

Tests that need CadQuery (`analyze_step_standalone`) skip themselves when it
is not installed.

## Logs

Server logs: `%USERPROFILE%\.solidworks-mcp\logs\server.log`

Claude Desktop logs: `%APPDATA%\Claude\logs\`

## License

MIT
