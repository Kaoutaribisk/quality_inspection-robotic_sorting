"""Build a local Power BI project bound to the unified production CSV."""

import argparse
import json
from pathlib import Path

from inspection_records import FIELDS

SCHEMAS = "https://developer.microsoft.com/json-schemas/fabric/"
TABLE = "Inspections"
COLORS = {"ink": "#172B4D", "muted": "#52657D", "blue": "#2563EB", "good": "#16856B", "scrap": "#CF4C59", "canvas": "#F3F6FA", "line": "#DEE5EF", "white": "#FFFFFF"}
DISPLAY_NAMES = {
    "record_number": "Record", "cycle": "Run cycle", "inspection_source": "Method",
    "expected_label": "Expected class", "predicted_label": "Predicted class",
    "match_label": "Class result", "confidence": "Confidence", "destination": "Destination",
    "description": "Inspection notes", "capture_seconds": "Capture (s)",
    "Total products": "Records", "GOOD routed": "GOOD", "SCRAP routed": "SCRAP",
    "Exact class match": "Class match", "Mean capture seconds": "Capture (s)",
    "Mean confidence": "Model confidence",
}
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
    "Camera records": ('CALCULATE([Total products], KEEPFILTERS(Inspections[inspection_source] = "Camera")) + 0', "#,0"),
    "Mismatched classes": ('CALCULATE([Total products], KEEPFILTERS(Inspections[class_match] = FALSE())) + 0', "#,0"),
    "Class result color": ('SWITCH(SELECTEDVALUE(Inspections[match_label]), "Match", "#16856B", "Mismatch", "#CF4C59", "#172B4D")', ""),
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
    Records = Table.AddIndexColumn(ConditionMatch, "record_number", 1, 1, Int64.Type),
    ClassLabels = [GOOD="Good surface", crazing="Crazing", inclusion="Inclusion", patches="Patches", pitted_surface="Pitted surface", #"rolled-in_scale"="Rolled-in scale", scratches="Scratches"],
    ExpectedLabels = Table.AddColumn(Records, "expected_label", each Record.FieldOrDefault(ClassLabels, [expected_type], [expected_type]), type text),
    PredictionLabels = Table.AddColumn(ExpectedLabels, "predicted_label", each Record.FieldOrDefault(ClassLabels, [gemini_type], [gemini_type]), type text),
    MatchLabels = Table.AddColumn(PredictionLabels, "match_label", each if [class_match] then "Match" else "Mismatch", type text)
in
    MatchLabels'''


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def field(name, measure=False):
    return {"Measure" if measure else "Column": {"Expression": {"SourceRef": {"Entity": TABLE}}, "Property": name}}


def projection(name, measure=False):
    return {"field": field(name, measure), "queryRef": f"{TABLE}.{name}", "nativeQueryRef": name, "displayName": DISPLAY_NAMES.get(name, name)}


def literal(value):
    if isinstance(value, bool):
        value = str(value).lower()
    elif isinstance(value, str):
        value = "'" + value.replace("'", "''") + "'"
    else:
        value = str(value) + "D"
    return {"expr": {"Literal": {"Value": value}}}


def fill(value):
    return {"solid": {"color": literal(value)}}


def object_properties(**properties):
    return [{"properties": properties}]


def category_color(column, value, color):
    return {"properties": {"fill": fill(color)}, "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0, "Left": field(column), "Right": literal(value)["expr"]}}}]}}


def visual(name, kind, title, x, y, width, height, roles, accent=None):
    accent = accent or COLORS["blue"]
    spec = {
        "$schema": SCHEMAS + "item/report/definition/visualContainer/2.0.0/schema.json",
        "name": name,
        "position": {"x": x, "y": y, "z": 0, "width": width, "height": height, "tabOrder": 0},
        "visual": {
            "visualType": kind,
            "query": {"queryState": {role: {"projections": [projection(column, measure) for column, measure in columns]} for role, columns in roles.items()}},
            "visualContainerObjects": {
                "title": object_properties(show=literal(True), text=literal(title), fontSize=literal(14), fontFamily=literal("Segoe UI Semibold"), fontColor=fill(COLORS["ink"]), alignment=literal("left")),
                "background": object_properties(show=literal(True), color=fill(COLORS["white"]), transparency=literal(0)),
                "border": object_properties(show=literal(True), color=fill(COLORS["line"]), radius=literal(8)),
                "visualHeader": object_properties(show=literal(False)),
            },
            "drillFilterOtherVisuals": True,
        },
    }
    objects = {}
    if kind == "card":
        objects = {
            "labels": object_properties(fontSize=literal(34), fontFamily=literal("Segoe UI Semibold"), color=fill(accent), labelDisplayUnits=literal(0)),
            "categoryLabels": object_properties(show=literal(False)),
            "wordWrap": object_properties(show=literal(False)),
        }
    elif kind == "slicer":
        # A dropdown needs room for both its header and input; do not compress it.
        spec["visual"]["visualContainerObjects"]["title"] = object_properties(show=literal(False))
        objects = {
            "data": object_properties(mode=literal("Dropdown")),
            "header": object_properties(show=literal(True), text=literal(title), fontSize=literal(12), fontFamily=literal("Segoe UI Semibold"), fontColor=fill(COLORS["ink"]), background=fill(COLORS["white"])),
            "items": object_properties(fontSize=literal(14), fontFamily=literal("Segoe UI"), fontColor=fill(COLORS["ink"]), background=fill(COLORS["white"])),
            "selection": object_properties(singleSelect=literal(False), strictSingleSelect=literal(False)),
        }
    elif kind in ("tableEx", "pivotTable"):
        objects = {
            "columnHeaders": object_properties(fontSize=literal(13), fontFamily=literal("Segoe UI Semibold"), fontColor=fill(COLORS["ink"]), backColor=fill("#EDF2F8"), wordWrap=literal(True), autoSizeColumnWidth=literal(True)),
            "values": object_properties(fontSize=literal(13), fontFamily=literal("Segoe UI"), fontColorPrimary=fill(COLORS["ink"]), fontColorSecondary=fill(COLORS["ink"]), backColorPrimary=fill(COLORS["white"]), backColorSecondary=fill("#F7F9FC"), wordWrap=literal(name == "evidence")),
            "grid": object_properties(rowPadding=literal(6), gridVertical=literal(False), gridHorizontal=literal(True), gridHorizontalColor=fill("#EDF2F8")),
        }
        spec["visual"]["visualContainerObjects"]["stylePreset"] = object_properties(name=literal("None"))
        if kind == "tableEx":
            objects["total"] = object_properties(show=literal(name == "methods"), fontSize=literal(13), fontColor=fill(COLORS["ink"]), backColor=fill("#EDF2F8"))
            spec["visual"]["query"]["sortDefinition"] = {"sort": [{"field": field("inspection_source" if name == "methods" else "record_number"), "direction": "Ascending"}], "isDefaultSort": False}
            if any(column == "match_label" for column, _ in roles["Values"]):
                objects["values"].append({"properties": {"fontColor": {"solid": {"color": {"expr": field("Class result color", True)}}}}, "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "Inspections.match_label"}})
        else:
            objects["rowHeaders"] = object_properties(fontSize=literal(13), fontColor=fill(COLORS["ink"]), backColor=fill(COLORS["white"]), wordWrap=literal(True))
    elif kind == "barChart":
        objects = {
            "categoryAxis": object_properties(fontSize=literal(14), labelColor=fill(COLORS["muted"]), showAxisTitle=literal(False)),
            "valueAxis": object_properties(fontSize=literal(12), labelColor=fill(COLORS["muted"]), showAxisTitle=literal(False), start=literal(0), gridlineShow=literal(False)),
            "dataPoint": object_properties(defaultColor=fill(accent)),
            "labels": object_properties(show=literal(True), fontSize=literal(13), color=fill(COLORS["ink"]), labelDisplayUnits=literal(0)),
            "legend": object_properties(show=literal(False)),
        }
        spec["visual"]["query"]["sortDefinition"] = {"sort": [{"field": field("Total products", True), "direction": "Descending"}], "isDefaultSort": False}
    elif kind == "donutChart":
        objects = {
            "dataPoint": [category_color("destination", "GOOD", COLORS["good"]), category_color("destination", "SCRAP", COLORS["scrap"])],
            "legend": object_properties(show=literal(True), position=literal("Bottom"), fontSize=literal(14), labelColor=fill(COLORS["muted"]), showTitle=literal(False)),
            "labels": object_properties(show=literal(True), fontSize=literal(14), color=fill(COLORS["ink"]), labelDisplayUnits=literal(0), labelStyle=literal("Data value")),
        }
    spec["visual"]["objects"] = objects
    return spec


def text_visual(name, title, subtitle, width=800):
    paragraphs = [{"textRuns": [{"value": title, "textStyle": {"fontFamily": "Segoe UI Semibold", "fontSize": "26pt", "color": COLORS["ink"]}}]}]
    if subtitle:
        paragraphs.append({"textRuns": [{"value": subtitle, "textStyle": {"fontFamily": "Segoe UI", "fontSize": "11pt", "color": COLORS["muted"]}}]})
    return {
        "$schema": SCHEMAS + "item/report/definition/visualContainer/2.0.0/schema.json", "name": name,
        "position": {"x": 24, "y": 16, "z": 0, "width": width, "height": 76, "tabOrder": 0},
        "visual": {"visualType": "textbox", "objects": {"general": object_properties(paragraphs=paragraphs)}, "visualContainerObjects": {"background": object_properties(show=literal(False)), "visualHeader": object_properties(show=literal(False))}},
    }


def build(project_directory, output_directory):
    project_directory = Path(project_directory).resolve()
    output_directory = Path(output_directory).resolve()
    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError("Use a new output folder. Existing reports are never overwritten.")
    csv_path = project_directory / "neu_defect_data" / "camera_inspection_log.csv"
    report = output_directory / "QualityInspection.Report"
    model = output_directory / "QualityInspection.SemanticModel"
    query = power_query(csv_path)
    types = {"cycle": "int64", "confidence": "double", "type_match": "boolean", "capture_seconds": "double", "record_number": "int64", "class_match": "boolean", "condition_match": "boolean"}
    columns = []
    for name in FIELDS + ["record_number", "class_match", "condition_match", "expected_label", "predicted_label", "match_label"]:
        column = {"name": name, "dataType": types.get(name, "string"), "sourceColumn": name, "summarizeBy": "none"}
        if name == "confidence":
            column["formatString"] = "0.0%"
        elif name == "capture_seconds":
            column["formatString"] = "0.000"
        if name in ("image", "camera_frame", "camera_top_surface", "type_match"):
            column["isHidden"] = True
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
                        "measures": [{"name": name, "expression": expression, "formatString": fmt, "isHidden": name == "Class result color"} for name, (expression, fmt) in MEASURES.items()],
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
        "layoutOptimization": "None",
        "themeCollection": {"customTheme": {"name": "GeminiKitting", "reportVersionAtImport": "5.55", "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": "GeminiKitting", "path": "GeminiKitting.json", "type": "CustomTheme"}]}],
        "objects": {"outspacePane": object_properties(expanded=literal(False))},
        "settings": {"pagesPosition": "Bottom", "useEnhancedTooltips": True},
    })
    write_json(report / "StaticResources" / "RegisteredResources" / "GeminiKitting.json", {
        "name": "GeminiKitting", "dataColors": [COLORS["blue"], COLORS["good"], COLORS["scrap"], "#7C6CC4", "#D29B38", "#548CAE"],
        "background": COLORS["white"], "foreground": COLORS["ink"], "foregroundNeutralSecondary": COLORS["muted"],
        "backgroundLight": COLORS["line"], "foregroundNeutralTertiary": COLORS["muted"], "tableAccent": COLORS["line"],
        "good": COLORS["good"], "bad": COLORS["scrap"], "neutral": COLORS["muted"],
        "textClasses": {key: {"fontFace": "Segoe UI", "fontSize": size, "color": COLORS["ink"]} for key, size in (("label", 13), ("title", 14), ("header", 14), ("callout", 34))},
    })
    write_json(definition / "pages" / "pages.json", {
        "$schema": SCHEMAS + "item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": ["production", "quality", "history"], "activePageName": "production",
    })

    def page(name, title, interactions=None):
        path = definition / "pages" / name
        write_json(path / "page.json", {
            "$schema": SCHEMAS + "item/report/definition/page/1.0.0/schema.json",
            "name": name, "displayName": title, "displayOption": "FitToPage", "width": 1280, "height": 720,
            "objects": {"background": object_properties(color=fill(COLORS["canvas"]), transparency=literal(0))},
            "visualInteractions": interactions or [],
        })
        return path

    def add(path, spec):
        write_json(path / "visuals" / spec["name"] / "visual.json", spec)

    def cards(path, names):
        width = (1232 - 16 * (len(names) - 1)) / len(names)
        accents = {"GOOD routed": COLORS["good"], "SCRAP routed": COLORS["scrap"], "Scrap share": COLORS["scrap"], "False accepts": COLORS["scrap"], "False rejects": COLORS["scrap"]}
        for index, (name, title) in enumerate(names):
            add(path, visual(f"kpi{index}", "card", title, 24 + index * (width + 16), 112, width, 104, {"Values": [(name, True)]}, accents.get(name, COLORS["blue"])))

    production = page("production", "Production overview")
    add(production, text_visual("heading", "Production overview", "GeminiKitting surface inspection", 788))
    cards(production, [("Total products", "Completed products"), ("GOOD routed", "GOOD routed"), ("SCRAP routed", "SCRAP routed"), ("Scrap share", "Scrap share"), ("Exact class match", "Exact class match")])
    add(production, visual("source", "slicer", "Inspection method", 832, 16, 204, 80, {"Values": [("inspection_source", False)]}))
    add(production, visual("destination", "slicer", "Destination", 1052, 16, 204, 80, {"Values": [("destination", False)]}))
    add(production, visual("defects", "barChart", "Predicted surface classes", 24, 240, 752, 270, {"Category": [("predicted_label", False)], "Y": [("Total products", True)]}))
    add(production, visual("routing", "donutChart", "GOOD and SCRAP routing", 792, 240, 464, 270, {"Category": [("destination", False)], "Y": [("Total products", True)]}))
    add(production, visual("methods", "tableEx", "Inspection method comparison", 24, 534, 1232, 162, {"Values": [("inspection_source", False), ("Total products", True), ("GOOD routed", True), ("SCRAP routed", True), ("Exact class match", True), ("Mean confidence", True), ("Mean capture seconds", True)]}))

    quality = page("quality", "Quality comparison")
    add(quality, text_visual("heading", "Quality comparison", "Expected dataset labels compared with Gemini predictions", 788))
    cards(quality, [("Total products", "Completed products"), ("Exact class match", "Exact class match"), ("Condition match", "Condition match"), ("False accepts", "False accepts"), ("False rejects", "False rejects"), ("Mean confidence", "Model confidence")])
    add(quality, visual("source", "slicer", "Inspection method", 832, 16, 204, 80, {"Values": [("inspection_source", False)]}))
    add(quality, visual("result", "slicer", "Class result", 1052, 16, 204, 80, {"Values": [("match_label", False)]}))
    add(quality, visual("confusion", "pivotTable", "Expected class (rows) and predicted class (columns)", 24, 240, 1232, 268, {"Rows": [("expected_label", False)], "Columns": [("predicted_label", False)], "Values": [("Total products", True)]}))
    add(quality, visual("mistakes", "tableEx", "Classification review", 24, 532, 1232, 164, {"Values": [("record_number", False), ("inspection_source", False), ("expected_label", False), ("predicted_label", False), ("match_label", False), ("confidence", False), ("destination", False)]}))

    history = page("history", "Inspection history", [{"source": "records", "target": "evidence", "type": "DataFilter"}, {"source": "evidence", "target": "records", "type": "NoFilter"}])
    add(history, text_visual("heading", "Inspection history", "Select a record to read its inspection notes", 568))
    add(history, visual("source", "slicer", "Method", 612, 16, 188, 80, {"Values": [("inspection_source", False)]}))
    add(history, visual("class", "slicer", "Predicted class", 816, 16, 220, 80, {"Values": [("predicted_label", False)]}))
    add(history, visual("destination", "slicer", "Destination", 1052, 16, 204, 80, {"Values": [("destination", False)]}))
    cards(history, [("Total products", "Completed products"), ("Camera records", "Camera records"), ("Mismatched classes", "Class mismatches"), ("Mean capture seconds", "Camera capture (s)")])
    add(history, visual("records", "tableEx", "Inspection records", 24, 240, 816, 456, {"Values": [("record_number", False), ("inspection_source", False), ("expected_label", False), ("predicted_label", False), ("match_label", False), ("confidence", False), ("destination", False)]}))
    add(history, visual("evidence", "tableEx", "Inspection notes", 856, 240, 400, 456, {"Values": [("record_number", False), ("description", False)]}))

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
