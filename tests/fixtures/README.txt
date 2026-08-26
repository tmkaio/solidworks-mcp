Test Fixtures
=============

sample_part.step
----------------
A simple flat bracket for test purposes.
Geometry: 100mm x 60mm x 2mm rectangular plate with four O6mm through holes.
Intended use: smoke tests for analyze_step_standalone() and open_file().

This is a minimal STEP file included for CI tests. It is generated with
CadQuery so that it is a valid solid — a hand-written STEP will parse but
can yield a degenerate BREP that has no bounding box.

To regenerate it:

    import cadquery as cq
    plate = (
        cq.Workplane("XY")
        .box(100, 60, 2, centered=(True, True, False))
        .faces(">Z").workplane()
        .rect(80, 40, forConstruction=True).vertices()
        .hole(6)
    )
    cq.exporters.export(plate, "sample_part.step", exportType="STEP")

For full SolidWorks integration testing, replace it with a real bracket
that includes HoleWizard holes and sheet metal bends:
1. Open SolidWorks.
2. Create a new Part.
3. Sketch a 100x60mm rectangle, extrude 2mm.
4. Add 4 holes (O6mm, HoleWizard, Through All).
5. File -> Save As -> STEP AP214 -> save as sample_part.step here.
