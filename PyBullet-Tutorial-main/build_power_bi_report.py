"""Build a local Power BI project bound to the unified production CSV."""

import argparse
import json
from pathlib import Path

from inspection_records import FIELDS

SCHEMAS = "https://developer.microsoft.com/json-schemas/fabric/"
TABLE = "Inspections"
MEASURES = {
    "Total products": ("COUNTROWS(Inspections)", "#,0"),
    "GOOD routed": ('CALCULATE([Total products], KEEPFILTERS(Inspections[destination] = "GOOD")) + 0', "#,0"),
    "SCRAP routed": ('CALCULATE([Total products], KEEPFILTERS(Inspections[destination] = "SCRAP")) + 0', "#,0"),
    "Scrap share": ("DIVIDE([SCRAP routed], [Total products])", "0.0%"),
    "Exact class match": ("DIVIDE(CALCULATE([Total products], KEEPFILTERS(Inspections[class_match] = TRUE())) + 0, [Total products])", "0.0%"),
    "Condition match": ("DIVIDE(CALCULATE([Total products], KEEPFILTERS(Inspections[condition_match] = TRUE())) + 0, [Total products])", "0.0%"),
    "Mean confidence": ("AVERAGE(Inspections[confidence])", "0.0%"),
    "Mean capture seconds": ('CALCULATE(AVERAGE(Inspections[capture_seconds]), KEEPFILTERS(Inspections[inspection_source] = "Camera"))', "0.000"),
    "False accepts": ('CALCULATE([Total products], KEEPFILTERS(Inspections[expected_condition] = "DEFECTIVE"), KEEPFILTERS(Inspections[destination] = "GOOD")) + 0', "#,0"),
    "False rejects": ('CALCULATE([Total products], KEEPFILTERS(Inspections[expected_condition] = "GOOD"), KEEPFILTERS(Inspections[destination] = "SCRAP")) + 0', "#,0"),
}


def power_query(csv_path):
    path = str(csv_path).replace('"', '""')
    fields = ", ".join('"' + field + '"' for field in FIELDS)
    text_types = ", ".join('{"' + field + '", type text}' for field in FIELDS if field not in ("cycle", "confidence", "type_match", "capture_seconds"))
    return f'''let
    Source = Csv.Document(File.Contents("{path}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Required = Table.SelectColumns(Headers, {{{fields}}}),
    TextTypes = Table.TransformColumnTypes(Required, {{{text_types}}}, "en-US"),
    Typed = Table.TransformColumns(TextTypes, {{
        {{"cycle", each Int64.From(Number.FromText(_, "en-US")), Int64.Type}},
        {{"confidence", each Number.FromText(_, "en-US"), type number}},
        {{"type_match", each Logical.FromText(Text.Lower(_)), type logical}},
        {{"capture_seconds", each if _ = null or _ = "" then null else Number.FromText(_, "en-US"), type nullable number}}
    }}),
    ClassMatch = Table.AddColumn(Typed, "class_match", each [expected_type] = [gemini_type], type logical),
    ConditionMatch = Table.AddColumn(ClassMatch, "condition_match", each [expected_condition] = [gemini_condition], type logical),
    Records = Table.AddIndexColumn(ConditionMatch, "record_number", 1, 1, Int64.Type)
in
    Records'''


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def field(name, measure=False):
    return {"Measure" if measure else "Column": {"Expression": {"SourceRef": {"Entity": TABLE}}, "Property": name}}


def projection(name, measure=False):
    return {"field": field(name, measure), "queryRef": f"{TABLE}.{name}", "nativeQueryRef": name}


def literal(value):
    if isinstance(value, bool):
        value = str(value).lower()
    elif isinstance(value, str):
        value = "'" + value.replace("'", "''") + "'"
    else:
        value = str(value) + "D"
    return {"expr": {"Literal": {"Value": value}}}


def visual(name, kind, title, x, y, width, height, roles):
    return {
        "$schema": SCHEMAS + "item/report/definition/visualContainer/2.0.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "width": width, "height": height, "tabOrder": 0},
        "visual": {
            "visualType": kind,
            "query": {"queryState": {role: {"projections": [projection(column, measure) for column, measure in columns]} for role, columns in roles.items()}},
            "visualContainerObjects": {
                "title": [{"properties": {"show": literal(True), "text": literal(title), "fontSize": literal(12)}}],
                "background": [{"properties": {"show": literal(True), "color": {"solid": {"color": literal("#FFFFFF")}}, "transparency": literal(0)}}],
            },
            "drillFilterOtherVisuals": True,
        },
    }


def build(project_directory, output_directory):
    project_directory = Path(project_directory).resolve()
    output_directory = Path(output_directory).resolve()
    csv_path = project_directory / "neu_defect_data" / "camera_inspection_log.csv"
    report = output_directory / "QualityInspection.Report"
    model = output_directory / "QualityInspection.SemanticModel"
    query = power_query(csv_path)
    types = {"cycle": "int64", "confidence": "double", "type_match": "boolean", "capture_seconds": "double", "record_number": "int64", "class_match": "boolean", "condition_match": "boolean"}
    columns = []
    for name in FIELDS + ["record_number", "class_match", "condition_match"]:
        column = {"name": name, "dataType": types.get(name, "string"), "sourceColumn": name, "summarizeBy": "none"}
        if name == "confidence":
            column["formatString"] = "0.0%"
        elif name == "capture_seconds":
            column["formatString"] = "0.000"
        columns.append(column)
    write_json(model / "definition.pbism", {
        "$schema": SCHEMAS + "item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "1.0", "settings": {"qnaEnabled": False},
    })
    write_json(model / "model.bim", {
        "name": "QualityInspection", "compatibilityLevel": 1600,
        "model": {
            "culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
            "annotations": [{"name": "PBI_QueryOrder", "value": '["Inspections"]'}],
            "tables": [{"name": TABLE, "columns": columns,
                        "measures": [{"name": name, "expression": expression, "formatString": fmt} for name, (expression, fmt) in MEASURES.items()],
                        "partitions": [{"name": TABLE, "mode": "import", "source": {"type": "m", "expression": query.splitlines()}}]}],
        },
    })
    write_json(output_directory / "QualityInspection.pbip", {
        "$schema": SCHEMAS + "pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": report.name}}],
        "settings": {"enableAutoRecovery": True},
    })
    write_json(report / "definition.pbir", {
        "$schema": SCHEMAS + "item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": "../" + model.name}},
    })
    definition = report / "definition"
    write_json(definition / "version.json", {
        "$schema": SCHEMAS + "item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0",
    })
    write_json(definition / "report.json", {
        "$schema": SCHEMAS + "item/report/definition/report/1.0.0/schema.json",
        "layoutOptimization": "None", "themeCollection": {},
        "settings": {"pagesPosition": "Bottom", "useEnhancedTooltips": True},
    })
    write_json(definition / "pages" / "pages.json", {
        "$schema": SCHEMAS + "item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": ["production", "quality", "history"], "activePageName": "production",
    })

    def page(name, title):
        path = definition / "pages" / name
        write_json(path / "page.json", {
            "$schema": SCHEMAS + "item/report/definition/page/1.0.0/schema.json",
            "name": name, "displayName": title, "displayOption": "FitToPage", "width": 1280, "height": 840,
        })
        return path

    def add(path, spec):
        write_json(path / "visuals" / spec["name"] / "visual.json", spec)

    def cards(path, names):
        for index, name in enumerate(names):
            add(path, visual(f"kpi{index}", "card", name, 20 + index * 207, 20, 190, 105, {"Values": [(name, True)]}))

    production = page("production", "Production overview")
    cards(production, ["Total products", "GOOD routed", "SCRAP routed", "Scrap share", "Exact class match", "Mean capture seconds"])
    add(production, visual("source", "slicer", "Inspection method", 20, 145, 195, 200, {"Values": [("inspection_source", False)]}))
    add(production, visual("destination", "slicer", "Destination", 20, 365, 195, 210, {"Values": [("destination", False)]}))
    add(production, visual("defects", "barChart", "Predicted surface class", 235, 145, 620, 430, {"Category": [("gemini_type", False)], "Y": [("Total products", True)]}))
    add(production, visual("routing", "donutChart", "Routing decisions", 875, 145, 385, 430, {"Category": [("destination", False)], "Y": [("Total products", True)]}))
    add(production, visual("methods", "tableEx", "Texture and camera records (capture time is not API time)", 20, 595, 1240, 225, {"Values": [("inspection_source", False), ("Total products", True), ("GOOD routed", True), ("SCRAP routed", True), ("Exact class match", True), ("Mean confidence", True), ("Mean capture seconds", True)]}))

    quality = page("quality", "Quality comparison")
    cards(quality, ["Total products", "Exact class match", "Condition match", "False accepts", "False rejects", "Mean confidence"])
    add(quality, visual("source", "slicer", "Inspection method", 20, 145, 195, 205, {"Values": [("inspection_source", False)]}))
    add(quality, visual("confusion", "pivotTable", "Expected class (rows) versus predicted class (columns)", 235, 145, 1025, 360, {"Rows": [("expected_type", False)], "Columns": [("gemini_type", False)], "Values": [("Total products", True)]}))
    add(quality, visual("mistakes", "tableEx", "Per-record comparison: confidence is not accuracy", 20, 525, 1240, 295, {"Values": [("record_number", False), ("inspection_source", False), ("expected_type", False), ("gemini_type", False), ("class_match", False), ("confidence", False), ("destination", False)]}))

    history = page("history", "Inspection history")
    add(history, visual("source", "slicer", "Inspection method", 20, 20, 290, 165, {"Values": [("inspection_source", False)]}))
    add(history, visual("class", "slicer", "Predicted class", 330, 20, 500, 165, {"Values": [("gemini_type", False)]}))
    add(history, visual("destination", "slicer", "Destination", 850, 20, 410, 165, {"Values": [("destination", False)]}))
    add(history, visual("records", "tableEx", "Completed placements only - cycle numbers restart each run", 20, 205, 1240, 615, {"Values": [("record_number", False), ("cycle", False), ("inspection_source", False), ("expected_type", False), ("gemini_type", False), ("confidence", False), ("destination", False), ("description", False), ("capture_seconds", False), ("camera_top_surface", False), ("image", False)]}))

    (output_directory / "InspectionQuery.pq").write_text(query + "\n", encoding="utf-8")
    (output_directory / "Measures.dax").write_text("\n\n".join(name + " = " + expression for name, (expression, _) in MEASURES.items()) + "\n", encoding="utf-8")
    print(f"Power BI project prepared: {output_directory / 'QualityInspection.pbip'}")
    return output_directory / "QualityInspection.pbip"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a local Power BI report. Does not publish or call an API.")
    parser.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    build(args.project_dir, args.output_dir or args.project_dir / "power_bi")
