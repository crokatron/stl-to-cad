# STL to CAD Converter — visual user manual

[Project overview](../README.md) · [Offline interactive demo](../demo.html)

Start with the numbered picture guide. Each number identifies the exact highlighted control. Work through one step at a time; the longer reference is below it.

### Actual tool · controls at a glance

Actual application screenshot. Numbered boxes point to the controls described below. 

![STL to CAD Converter — numbered controls](images/guide-1.jpg)

1. **Start with an STL.** Drop or choose a small closed mesh whose size you know.
2. **Choose the tradeoff.** Faceted is heavier; analytic approaches need extra inspection.
3. **Convert, then validate.** Inspect the result and solid status before using a downloaded CAD body.

### Try the working offline example

Screenshot of this project’s interactive demo. Side-by-side services are explicitly simulated.

![STL to CAD Converter — numbered controls](images/guide-2.jpg)

1. **Explore mesh complexity.** Change the illustration’s detail before trying the example conversion.
2. **Compare the strategy.** Faceted and analytic concepts illustrate the choice; no CAD kernel is running.
3. **Check the result boundary.** The demo labels real solid validity as not evaluated.

## Detailed task reference

### Convert a first part

1. Start with a small, closed STL whose scale you know. Keep the original unchanged.
2. Upload the STL, choose faceted as the baseline and inspect the triangle target. Decimation changes the mesh used for subsequent work, so document that choice.
3. Choose Convert and wait for the job result. Do not treat an output file alone as proof of a closed solid.
4. Read the validation result: closure, solid count, dimensions, volume and deviation. Inspect holes and thin features visually.

### Compare a compact analytic result

1. Save the baseline result, then try an analytic method with explicit tolerance values.
2. Inspect By type to see which surfaces were fitted and Deviation to locate differences. A compact file is not automatically the more accurate one.
3. Arcwise is experimental and may leave open edges or a sheet body. Decide whether repair in your CAD tool is acceptable rather than describing every output as watertight.

### Take the result into CAD

1. Download STEP for interchange or BREP for OpenCascade-compatible tools.
2. Import it into your CAD application and check units, solid status, hole geometry and overall dimensions.
3. Keep the source mesh and conversion settings with the output. A faceted solid is still faceted; converting the file format does not produce editable sketches and dimensions.

## Keep your work

Treat conversion jobs as temporary working results and download the outputs you need. The source repository does not contain uploaded meshes or the NAS job store. Back up original meshes independently.

## If something looks wrong

- Dense mesh stalls or fails: reduce triangle count intentionally and try a smaller representative section.
- Open edges: repair the input or inspect the experimental method’s output as a sheet.
- Unexpected size: verify source units and CAD import units.
- Heavy STEP: normal for triangle-per-face conversion; compact fitting is a separate tradeoff.

## What this manual does not promise

A local static server cannot perform CAD conversion. The package needs the configured OpenCascade/Python environment or the NAS conversion service. No new full CAD integration test was performed for this documentation update.

Screenshots show the actual application where captured. The offline demo is a deliberately smaller simulation and identifies its dummy services. It never controls devices, sends notifications, uploads files or launches printing.
