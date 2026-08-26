# Usage Guide

## Basic workflow

1. Open SolidWorks (sign in if required)
2. Open Claude Desktop
3. Ask Claude to analyse a part — it calls tools automatically

---

## Example 1: Full analysis of a STEP file

```
Open C:\parts\door_bracket.step and give me a complete analysis.
I need the thickness, all hole diameters, bends, and estimated blank size.
```

Claude calls: `solidworks_connect` → `open_file` → `get_part_info` →
`get_bounding_box` → `analyze_holes` → `analyze_bends` → `get_sheet_metal_properties`

---

## Example 2: Export flat pattern as DXF

```
Export the flat pattern of the open part as DXF to C:\output\bracket_flat.dxf
```

Claude calls: `is_sheet_metal` → `flatten_part` →
`export_dxf(include_bend_lines=True)` → `unflatten_part`

---

## Example 3: Quick triage without SolidWorks

```
Analyse C:\inbox\customer_part.step without opening SolidWorks.
```

Claude calls `analyze_step_standalone` — uses CadQuery, no COM overhead.

Output:
```
Volume: 15 200 mm³  |  Surface: 18 400 mm²
Bounding box: 180.0 x 120.0 x 1.5 mm
Estimated thickness: 1.5 mm
Sheet metal: YES
```

---

## Example 4: Convert STEP to sheet metal and export

```
Open C:\parts\bracket.step, convert to sheet metal (thickness 1.5mm),
then export the DXF to C:\output\.
```

Claude calls: `open_file` → `convert_to_sheet_metal(thickness=1.5)` →
`analyze_bends` → `flatten_part` → `export_dxf`

---

## Example 5: Generate full report to disk

```
Generate a complete technical report for the active part
and save it to C:\reports\bracket_analysis\
```

Saves `report.json` and `report.md` to the specified directory.

---

## Tips

### Workflow order for imported STEP files

```
open_file → convert_to_sheet_metal (if needed)
→ analyze_holes + analyze_bends
→ flatten_part → export_dxf → unflatten_part → close_file
```

### Always unflatten after export

Forgetting `unflatten_part` leaves the document flat. If saved flat,
3D bend information is lost. Always unflatten before saving.

### Material assignment

`get_part_info` returns mass only if a material is assigned.
For imported STEP files, assign the material in SolidWorks manually
(right-click part → Material → select material) before calling mass tools.

### Logs

```
%USERPROFILE%\.solidworks-mcp\logs\server.log
```
