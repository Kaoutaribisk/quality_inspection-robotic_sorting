# GeminiKitting quality inspection

Open `QualityInspection.pbip` in Power BI Desktop, choose **Home > Refresh**, and save. The report reads the same unified `camera_inspection_log.csv`; no history, simulation code or API key is changed. The earlier report remains in its original folder.

## Using the report

- **Production overview:** five headline measures, descending surface-class counts, GOOD/SCRAP routing and a method comparison. Green means GOOD routing and red means SCRAP routing. Per-record Match and Mismatch labels also use green and red, with explicit text to keep their meaning clear.
- **Quality comparison:** expected-versus-predicted classes and per-record results. Choose **Mismatch** in Class result to review wrong surface-class predictions. Model confidence is not accuracy.
- **Inspection history:** a compact record table beside the full inspection notes. Select a row in the record table to filter its notes. Raw image paths and the restarting run-cycle field remain in the model but do not crowd the page.

Dropdown filters are page-local. Clear selections to return to all records. Tables can be scrolled; no records are dropped to fit the page. Class labels are made readable only in derived report columns; original CSV values remain unchanged.

Camera capture time measures image capture only, not Gemini processing or robot motion. Missing legacy capture times remain blank and are excluded from the camera average. Records count completed placements, not unique cycle numbers. Record numbers are import-time indices, not permanent product identifiers. All match statistics compare the sample's dataset/simulation label with Gemini's prediction; they are not a held-out industrial certification.

Refresh reloads the CSV snapshot manually. Stop production after the current cycle for a consistent snapshot. No cloud publication, API requests or recurring refresh jobs are added.

The report uses native Power BI cards, charts, matrix, tables and slicers, a registered theme, and one imported table. Structural checks and semantic-model parsing are tested. Font wrapping and native rendering must be checked after opening in Desktop.

To regenerate after relocating the scripts, use the included generator with an explicit script directory and a new output folder:

```powershell
python .\build_power_bi_report.py --project-dir "PATH_TO_SCRIPT_FOLDER" --output-dir "PATH_TO_NEW_REPORT_FOLDER"
```

Existing report folders are not overwritten. The CSV is only read, never rewritten by this generator.

Reference: [Microsoft report themes](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-report-themes).
