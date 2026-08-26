# solidworks-mcp — API Reference

Complete reference for all 56 tools exposed by the SolidWorks MCP server.

---

## Table of Contents

1. [Connection](#connection)
2. [File Operations](#file-operations)
3. [Analysis](#analysis)
4. [Sheet Metal](#sheet-metal)
5. [Export](#export)
6. [Custom Properties & Materials](#custom-properties--materials)
7. [Configurations](#configurations)
8. [Measurements](#measurements)
9. [Feature Management](#feature-management)
10. [Drawings](#drawings)
11. [Assemblies](#assemblies)

---

## Connection

### `solidworks_connect`

Connect to a running SolidWorks instance, or launch a new one.

**Must be called before any other tool.**

**Returns**

| Field | Type | Description |
|---|---|---|
| `connected` | bool | `true` on success |
| `version` | string | SolidWorks revision, e.g. `"30.4.0"` (SW2022 SP4) |
| `is_new_instance` | bool | `true` if SolidWorks was launched by this call |
| `error` | string | Present only on failure |

---

### `solidworks_status`

Query the current connection state and active document.

**Returns**

| Field | Type | Description |
|---|---|---|
| `connected` | bool | Whether bridge is connected |
| `version` | string | SolidWorks version |
| `active_document` | string \| null | Full path of the active document |
| `document_type` | string \| null | `"part"`, `"assembly"`, or `"drawing"` |
| `is_sheet_metal` | bool \| null | Whether active part has a SheetMetal feature |
| `documents_open` | list[string] | Paths of all open documents |

---

### `solidworks_disconnect`

Release COM references without closing SolidWorks.

**Returns**

| Field | Type | Description |
|---|---|---|
| `disconnected` | bool | `true` on success |

---

## File Operations

### `open_file`

Open a CAD file in SolidWorks.

**Supported formats:** `.sldprt`, `.sldasm`, `.slddrw`, `.step`, `.stp`, `.iges`, `.igs`, `.x_t`, `.x_b`, `.sat`, `.stl`

> **Note:** STEP files import as "dumb" solids — no parametric features. For sheet metal bend analysis, run `convert_to_sheet_metal` afterward.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `file_path` | string | required | Absolute path to the file |
| `read_only` | bool | `false` | Open in read-only mode (safer for analysis) |

**Returns**

| Field | Type | Description |
|---|---|---|
| `success` | bool | |
| `document_path` | string | Canonical path of the opened document |
| `document_type` | string | `"part"`, `"assembly"`, or `"drawing"` |
| `is_sheet_metal` | bool | Whether a SheetMetal feature exists |
| `errors` | list[string] | Decoded SolidWorks error messages |
| `warnings` | list[string] | Decoded SolidWorks warning messages |

---

### `close_file`

Close the active document.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `save` | bool | `false` | Save before closing |

**Returns** `success`, `closed_document`, `error`

---

### `save_file`

Save the active document in-place or to a new path (Save As).

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output_path` | string \| null | `null` | Absolute path for Save As; `null` = overwrite |

**Returns** `success`, `saved_path`, `error`

---

### `list_open_documents`

List all documents currently open in SolidWorks.

**Returns**

| Field | Type | Description |
|---|---|---|
| `documents` | list[dict] | Each item: `{path, type}` |
| `count` | int | |

---

## Analysis

### `get_part_info`

Return mass, volume, material, and sheet metal flag for the active part.

> Requires a material to be assigned. If mass returns null, use `set_material` first.

**Returns**

| Field | Type | Description |
|---|---|---|
| `name` | string | Document title |
| `path` | string | File path |
| `material` | string \| null | Assigned material name |
| `mass_g` | float \| null | Mass in grams |
| `volume_mm3` | float | Volume in mm³ |
| `surface_area_mm2` | float | Surface area in mm² |
| `center_of_mass_mm` | dict | `{x, y, z}` in mm |
| `is_sheet_metal` | bool | |
| `bounding_box` | dict | See `get_bounding_box` |

---

### `get_bounding_box`

Get the axis-aligned bounding box of the active part.

**Returns**

| Field | Type | Description |
|---|---|---|
| `dimensions_mm` | list[float] | `[x, y, z]` dimensions in mm |
| `min_mm` | list[float] | Minimum corner `[x, y, z]` |
| `max_mm` | list[float] | Maximum corner `[x, y, z]` |
| `diagonal_mm` | float | Space diagonal length |

---

### `count_features_by_type`

Return a histogram of feature types in the FeatureManager tree.

**Returns**

| Field | Type | Description |
|---|---|---|
| `features` | dict[string, int] | Type name → count |
| `total` | int | Total feature count |

---

### `analyze_holes`

Identify and group all holes by diameter.

**Returns**

| Field | Type | Description |
|---|---|---|
| `holes` | list[dict] | Each: `{id, diameter_mm, depth_mm, is_through, type}` |
| `groups` | dict | Diameter → count |
| `total` | int | |

---

### `analyze_bends`

Identify and characterise all sheet metal bends.

> Requires a sheet metal part. For imported STEP files, run `convert_to_sheet_metal` first.

**Returns**

| Field | Type | Description |
|---|---|---|
| `bends` | list[dict] | Each: `{id, angle_deg, radius_mm, length_mm, k_factor}` |
| `count` | int | |
| `is_sheet_metal` | bool | |

---

### `get_geometry_stats`

Executive summary with complexity rating.

**Returns** Feature counts, hole/bend summary, bounding box, mass, sheet metal flag, complexity rating (`low` / `medium` / `high`), and manufacturing recommendations.

---

### `generate_part_report`

Full analysis report in JSON + Markdown format.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output_dir` | string \| null | `null` | Directory to save `report.json` and `report.md`. `null` = return inline only. |

**Returns** Structured report dict, optionally saved to disk.

---

### `analyze_step_standalone`

Analyse a STEP file **without opening SolidWorks** (uses CadQuery/OCC).

Fastest triage tool — works offline, no COM overhead, no license required.

> **Requires CadQuery:** `conda install -c cadquery cadquery`

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `file_path` | string | Absolute path to `.step` / `.stp` file |

**Returns**

| Field | Type | Description |
|---|---|---|
| `volume_mm3` | float | |
| `surface_area_mm2` | float | |
| `bounding_box` | dict | Min/max corners + dimensions |
| `center_of_mass_mm` | dict | `{x, y, z}` |
| `face_count` | int | Total face count |
| `face_types` | dict | Geometry type → count |
| `estimated_thickness_mm` | float | Smallest bounding-box dimension |
| `is_likely_sheet_metal` | bool | Heuristic: smallest dim < 1/5 of others |

---

### `get_moments_of_inertia`

Return mass moments of inertia and products of inertia for the active part.

> Requires a material assignment.

**Returns**

| Field | Type | Description |
|---|---|---|
| `Ixx_g_mm2` | float | Moment about X axis (g·mm²) |
| `Iyy_g_mm2` | float | Moment about Y axis (g·mm²) |
| `Izz_g_mm2` | float | Moment about Z axis (g·mm²) |
| `Ixy_g_mm2` | float | Product of inertia XY (g·mm²) |
| `Ixz_g_mm2` | float | Product of inertia XZ (g·mm²) |
| `Iyz_g_mm2` | float | Product of inertia YZ (g·mm²) |
| `centre_of_mass_mm` | dict | `{x, y, z}` in mm |
| `mass_g` | float | |

---

### `analyze_faces`

Classify all faces on the active part by geometry type.

**Returns**

| Field | Type | Description |
|---|---|---|
| `face_counts` | dict[string, int] | Type → count (`planar`, `cylindrical`, `conical`, `spherical`, `toroidal`, `spline`) |
| `face_areas_mm2` | dict[string, float] | Type → total area in mm² |
| `total_faces` | int | |
| `total_area_mm2` | float | |
| `planar_area_mm2` | float | |
| `cylindrical_area_mm2` | float | |
| `largest_face_mm2` | float | |

---

## Sheet Metal

### `is_sheet_metal`

Check whether the active part is a sheet metal part.

**Returns** `is_sheet_metal` (bool), `document_type` (string)

---

### `get_sheet_metal_properties`

Read thickness, K-factor, and default bend radius.

**Returns**

| Field | Type | Description |
|---|---|---|
| `thickness_mm` | float | |
| `default_bend_radius_mm` | float | |
| `k_factor` | float | Typically 0.38–0.50 |

---

### `convert_to_sheet_metal`

Convert an imported solid (STEP/IGES) to a SolidWorks sheet metal part.

Auto-selects the largest planar face as the fixed face. Required before `analyze_bends`, `flatten_part`, or `export_dxf` on imported parts.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `thickness` | float | required | Sheet thickness in mm |
| `bend_radius` | float | `null` | Default bend radius in mm; defaults to `thickness` |
| `k_factor` | float | `0.44` | K-factor (0.0–1.0) |

**Returns** `success`, `thickness_mm`, `bend_radius_mm`, `k_factor`

---

### `flatten_part`

Activate the flat pattern (unfold all bends).

Must be called before `export_dxf`. Always call `unflatten_part` afterward.

**Returns** `success`, `flat_pattern_name`

---

### `unflatten_part`

Return the part to its folded 3D state.

**Returns** `success`

---

## Export

### `export_dxf`

Export the flat pattern as a DXF file (for laser cutting or NC punching).

> **Requires:** Part must be flattened first (`flatten_part`).

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output_path` | string | required | Absolute output path (`.dxf`) |
| `include_bend_lines` | bool | `true` | Include bend line geometry in DXF |

**Returns** `success`, `output_path`, `file_size_kb`

---

### `export_step`

Export the active document as STEP AP214.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `output_path` | string | Absolute output path (`.step` or `.stp`) |

**Returns** `success`, `output_path`, `file_size_kb`

---

### `export_stl`

Export the active part as an STL file.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output_path` | string | required | Absolute output path (`.stl`) |
| `binary` | bool | `true` | Binary STL (smaller); `false` = ASCII |

**Returns** `success`, `output_path`, `file_size_kb`

---

### `export_pdf`

Export the active document (drawing or part) as PDF.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `output_path` | string | Absolute output path (`.pdf`) |

**Returns** `success`, `output_path`, `file_size_kb`

---

### `take_screenshot`

Capture the SolidWorks viewport as a PNG image.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output_path` | string | required | Absolute output path (`.png`) |
| `view` | string | `"isometric"` | Named view: `"isometric"`, `"front"`, `"top"`, `"right"`, etc. |

**Returns** `success`, `output_path`, `width`, `height`

---

## Custom Properties & Materials

### `get_custom_properties`

Read all custom properties (metadata) from the active document.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `config_name` | string | `""` | Configuration name, or `""` for document-level |

**Returns**

| Field | Type | Description |
|---|---|---|
| `properties` | dict | Property name → `{value, resolved_value, type}` |
| `config` | string | Which configuration was queried |
| `count` | int | |

---

### `get_custom_property`

Read a single named custom property.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Property name (e.g. `"PartNumber"`) |
| `config_name` | string | `""` | Configuration name |

**Returns** `name`, `found`, `value`, `resolved_value`, `type`

---

### `set_custom_property`

Create or update a custom property on the active document.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Property name |
| `value` | string | required | Property value |
| `config_name` | string | `""` | Configuration name |
| `prop_type` | string | `"text"` | `"text"`, `"number"`, `"date"`, `"yes_no"` |

**Returns** `success`, `name`, `value`

---

### `delete_custom_property`

Remove a custom property from the active document.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Property name to delete |
| `config_name` | string | `""` | Configuration name |

**Returns** `success`, `deleted`

---

### `set_material`

Assign a material from the SolidWorks material library to the active part.

Required for mass/inertia calculations on parts with no material assigned.

**Common material names**

```
AISI 1020 Steel
AISI 304 Stainless Steel (SS)
Aluminum 1060 Alloy
Galvanized Steel
Plain Carbon Steel
```

> Names are **case-sensitive**. Use `get_material_databases` + SolidWorks UI to verify exact strings.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `material_name` | string | required | Exact material name |
| `library_name` | string | `""` | `.sldmat` library name without extension; `""` = search all |

**Returns** `success`, `material`, `database`

---

### `get_material_databases`

List available SolidWorks material database files (`.sldmat`).

**Returns** `databases` (list[string])

---

## Configurations

### `list_configurations`

List all configurations in the active document.

**Returns**

| Field | Type | Description |
|---|---|---|
| `configurations` | list[dict] | Each: `{name, is_active, description, suppression_state}` |
| `count` | int | |
| `active` | string | Name of the active configuration |

---

### `get_active_configuration`

Get details of the currently active configuration.

**Returns** `name`, `description`, `suppression_state`, `is_design_table`

---

### `switch_configuration`

Activate a different configuration.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `config_name` | string | Exact configuration name (case-sensitive) |

**Returns** `success`, `previous`, `active`

---

### `add_configuration`

Create a new configuration as a copy of an existing one.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `config_name` | string | required | Name for the new configuration |
| `description` | string | `""` | Optional comment |
| `copy_from` | string | `""` | Source configuration; `""` = active configuration |

**Returns** `success`, `name`

---

### `delete_configuration`

Remove a configuration. Cannot delete the active or last remaining configuration.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `config_name` | string | Configuration to delete |

**Returns** `success`, `deleted`

---

### `get_configuration_properties`

Read custom properties specific to a configuration.

Config-specific properties override document-level ones for that variant.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `config_name` | string | `""` | Configuration name; `""` = active configuration |

**Returns** `properties` (dict), `config`, `count`

---

## Measurements

### `measure_distance`

Measure the distance between two named entities.

Entity names are as shown in the SolidWorks status bar (e.g. `"Boss-Extrude1@Part1"`).

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `entity1_name` | string | Selection name of first entity |
| `entity1_type` | string | `"FACE"`, `"EDGE"`, or `"VERTEX"` |
| `entity2_name` | string | Selection name of second entity |
| `entity2_type` | string | `"FACE"`, `"EDGE"`, or `"VERTEX"` |

**Returns**

| Field | Type | Description |
|---|---|---|
| `distance_mm` | float | Minimum distance |
| `delta_x_mm` | float | X component |
| `delta_y_mm` | float | Y component |
| `delta_z_mm` | float | Z component |

---

### `measure_entity`

Measure properties of a single entity.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `entity_name` | string | Selection name |
| `entity_type` | string | `"FACE"`, `"EDGE"`, or `"VERTEX"` |

**Returns** (type-dependent)

- **EDGE:** `length_mm`
- **FACE:** `area_mm2`, `perimeter_mm`
- **VERTEX:** `x_mm`, `y_mm`, `z_mm`

---

### `get_face_properties`

Get geometric properties of a face by 0-based index on the first solid body.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `face_index` | int | `0` | 0-based face index |

**Returns** `index`, `face_type`, `area_mm2`, `normal` (dict x/y/z), `centroid_mm`, `total_faces`

---

### `measure_minimum_distance`

Measure the minimum clearance between two entities (useful for assembly checks).

**Parameters** Same as `measure_distance`.

**Returns**

| Field | Type | Description |
|---|---|---|
| `minimum_distance_mm` | float | |
| `point1_mm` | dict | Closest point on entity 1 `{x, y, z}` |
| `point2_mm` | dict | Closest point on entity 2 `{x, y, z}` |

---

### `get_section_properties`

Get cross-section area, centroid, and second moments of area for a face.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `face_name` | string | `""` | Selection name; `""` = first planar face |

**Returns** `area_mm2`, `perimeter_mm`, `centroid_mm`, `Ixx_mm4`, `Iyy_mm4`, `Ixy_mm4`

---

## Feature Management

### `list_features`

List all features in the FeatureManager tree.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `include_suppressed` | bool | `true` | Include suppressed features |
| `feature_type_filter` | string | `""` | Case-insensitive substring filter on type name (e.g. `"Hole"`) |

**Returns**

| Field | Type | Description |
|---|---|---|
| `features` | list[dict] | Each: `{name, type, is_suppressed, has_error}` |
| `count` | int | Filtered count |
| `total` | int | Total before filter |

---

### `get_feature_info`

Get detailed information about a specific feature by name.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `feature_name` | string | Exact name from FeatureManager tree |

**Returns** `name`, `type`, `is_suppressed`, `has_error`, `error_code`, `error_description`

---

### `suppress_feature`

Suppress (disable) a feature in the model.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `feature_name` | string | required | Feature to suppress |
| `config_name` | string | `""` | Configuration to suppress in; `""` = active |

**Returns** `success`, `feature`, `configuration`

---

### `unsuppress_feature`

Restore a suppressed feature.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `feature_name` | string | required | Feature to unsuppress |
| `config_name` | string | `""` | Configuration; `""` = active |
| `unsuppress_children` | bool | `true` | Also unsuppress child features |

**Returns** `success`, `feature`

---

### `get_feature_dimensions`

List all parametric dimensions associated with a feature.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `feature_name` | string | Feature name |

**Returns**

| Field | Type | Description |
|---|---|---|
| `dimensions` | list[dict] | Each: `{name, full_name, value, unit}` — unit is `"mm"` or `"deg"` |
| `count` | int | |

---

### `rebuild_model`

Force a rebuild of the active document.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `force` | bool | `false` | `true` = full forced rebuild (Ctrl+Q); `false` = standard rebuild (Ctrl+B) |

**Returns** `success`

---

### `get_feature_error`

Check whether a feature has a rebuild error and describe it.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `feature_name` | string | Feature name to inspect |

**Returns** `feature`, `has_error`, `error_code`, `description`

---

## Drawings

### `create_drawing_from_part`

Create a new drawing document from the active part or assembly.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `template_path` | string | `""` | Path to `.drwdot` template; `""` = SolidWorks default |
| `paper_size` | string | `"A3"` | `"A4"`, `"A3"`, `"A2"`, `"A1"`, `"Letter"`, `"Legal"` |
| `scale_numerator` | float | `1.0` | Drawing scale numerator |
| `scale_denominator` | float | `1.0` | Drawing scale denominator |

**Returns** `success`, `drawing_title`

---

### `add_drawing_view`

Add a standard named view to the active drawing.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `view_name` | string | `"front"` | `"front"`, `"back"`, `"left"`, `"right"`, `"top"`, `"bottom"`, `"isometric"`, `"dimetric"`, `"trimetric"` |
| `x_mm` | float | `100.0` | X position on sheet (mm) |
| `y_mm` | float | `150.0` | Y position on sheet (mm) |
| `scale_numerator` | float | `1.0` | View scale numerator |
| `scale_denominator` | float | `1.0` | View scale denominator |

**Returns** `success`, `view`, `position_mm`

---

### `list_drawing_views`

List all views on the active drawing document.

**Returns**

| Field | Type | Description |
|---|---|---|
| `views` | list[dict] | Each: `{name, sheet, scale, position_mm}` |
| `count` | int | |
| `sheet_count` | int | |

---

### `get_drawing_info`

Get metadata about the active drawing document.

**Returns** `title`, `sheet_count`, `sheets`, `active_sheet`, `paper_size`, `drawing_scale`

---

### `set_drawing_scale`

Change the scale of a drawing sheet.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `numerator` | float | required | Scale numerator |
| `denominator` | float | required | Scale denominator |
| `sheet_name` | string | `""` | Sheet to modify; `""` = active sheet |

**Returns** `success`, `scale` (e.g. `"1:2"`)

---

## Assemblies

### `get_assembly_components`

List all components in the active assembly.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `recursive` | bool | `false` | `true` = all levels; `false` = top-level only |

**Returns**

| Field | Type | Description |
|---|---|---|
| `components` | list[dict] | Each: `{name, path, configuration, is_suppressed, is_lightweight, is_virtual}` |
| `count` | int | |
| `level` | string | `"top-level"` or `"all"` |

---

### `get_component_count`

Quick count of components in the active assembly.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `recursive` | bool | `true` | Count all nested components |

**Returns** `count`, `unique_parts`, `sub_assemblies`

---

### `get_assembly_bom`

Generate a Bill of Materials for the active assembly.

Reads `PartNumber` and `Description` custom properties from each component's model.

**Parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `recursive` | bool | `false` | Include sub-assembly components |

**Returns**

| Field | Type | Description |
|---|---|---|
| `bom` | list[dict] | Each: `{item_no, part_number, description, quantity, file_name, configuration}` |
| `count` | int | Number of unique line items |

---

### `list_assembly_mates`

List all mate constraints in the active assembly.

**Returns**

| Field | Type | Description |
|---|---|---|
| `mates` | list[dict] | Each: `{name, type, is_suppressed, entity_count}` |
| `count` | int | |

Mate types: `Coincident`, `Concentric`, `Parallel`, `Perpendicular`, `Distance`, `Angle`, etc.

---

### `get_component_info`

Get detailed information about a named component in the active assembly.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `component_name` | string | Component name (e.g. `"Bracket-1"`) — from `get_assembly_components` |

**Returns**

| Field | Type | Description |
|---|---|---|
| `name` | string | |
| `path` | string | File path |
| `configuration` | string | Referenced configuration |
| `is_suppressed` | bool | |
| `is_lightweight` | bool | |
| `mass_g` | float | |
| `volume_mm3` | float | |
| `bounding_box_mm` | dict | `{x, y, z}` dimensions |

---

### `get_assembly_mass`

Get total mass and centre of mass for the entire assembly.

> Each component must have a material assigned to contribute to the total.

**Returns** `mass_g`, `volume_mm3`, `surface_area_mm2`, `center_of_mass_mm`
