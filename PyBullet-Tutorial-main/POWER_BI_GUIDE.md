# Quality inspection dashboard

## First open

1. Exit the simulation and install this update from the GeminiKitting folder using `install_power_bi_update.ps1` from the update package. The installer validates the existing logs and source version, backs up replaced files, merges the history and creates the report beside the scripts.
2. Open `PyBullet-Tutorial-main\power_bi\QualityInspection.pbip` with Power BI Desktop (or `power_bi\QualityInspection.pbip` if scripts are directly in GeminiKitting).
3. Choose **Home > Refresh**. The project ships definitions, not an imported data cache. An empty report before the first Refresh is expected.
4. If a local file permission/privacy prompt appears, approve access to your own inspection CSV. No Google API key or Google sign-in is used by the report.
5. View **Production overview**, **Quality comparison**, and **Inspection history**. Select Camera in the method slicer to evaluate only the new overhead-camera workflow. Slicers are page-local.
6. Save the report. To make a single-file report, use Desktop **File > Save as > .pbix**, if available in the installed version. Keep the original project folders together.

If Desktop says project files are disabled, check **File > Options and settings > Options > Preview features** for the Power BI project/PBIP feature, enable it if present, and restart Desktop. The exact feature label depends on the installed version.

The generated PBIR/TMSL definitions are checked structurally and the data migration is tested, but their first rendering must be verified in Desktop. If an opening or visual error occurs, keep the error text; do not reinstall Python or recreate the dataset.

## Refresh

Production continues appending to `neu_defect_data\camera_inspection_log.csv`. Click **Refresh** to reread it. For a consistent snapshot, stop production after the current cycle completes before refreshing. There is no real-time push connection or scheduled refresh in this local report. Publishing is optional and not part of this update; a Power BI service report reading local files needs a separately configured refresh/gateway arrangement.

## Data definitions

| Metric | Meaning |
| --- | --- |
| Total products | Number of completed placement records, not the largest cycle number |
| GOOD/SCRAP routed | Counts by actual logged destination |
| Scrap share | SCRAP routed divided by total records |
| Exact class match | Expected surface class equals predicted surface class |
| Condition match | Expected GOOD/DEFECTIVE equals predicted GOOD/DEFECTIVE |
| False accepts | Labelled DEFECTIVE records routed to GOOD |
| False rejects | Labelled GOOD records routed to SCRAP |
| Mean confidence | Average model-reported confidence; not accuracy |
| Mean capture seconds | Average available Camera capture durations, excluding missing legacy values |

The Texture/Camera provenance survives the merge. Camera fields are blank for old texture records. No timestamps or API/cycle durations are invented. Source labels come from the simulation's dataset class, including its synthetic GOOD reference; these metrics do not establish real-world quality assurance accuracy. Images are local path text, not publicly hosted images.

## Manual fallback

If project opening is unavailable, create an empty Desktop report, choose **Get data > Blank query**, open **Advanced Editor**, and paste `power_bi\InspectionQuery.pq`. Name the query **Inspections**, then **Close & Apply**. The query parses decimal numbers with `en-US` even on a French Windows installation. Add each measure from `power_bi\Measures.dax` using **New measure**, one definition at a time. Set the two match rates, scrap share and mean confidence to percentage formatting, and capture seconds to three decimals.

Add cards for the overview measures; a bar chart with `gemini_type` on Category and Total products on Values; a donut chart by `destination`; a matrix with `expected_type` on Rows, `gemini_type` on Columns and Total products on Values; and a table for the record fields. Add slicers for `inspection_source` and `destination`.

## References

- [Power BI project files](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
- [PBIR report definitions](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report)
- [Text/CSV connector](https://learn.microsoft.com/en-us/power-query/connectors/text-csv)
- [Refreshing local Desktop data](https://learn.microsoft.com/en-us/power-bi/connect-data/refresh-desktop-file-local-drive)
