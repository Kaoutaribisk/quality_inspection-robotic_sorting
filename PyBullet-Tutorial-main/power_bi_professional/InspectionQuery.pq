let
    Source = Csv.Document(File.Contents("C:\Users\KAOUTAR\Documents\project-20260930T081454Z-1-001\project\GeminiKitting\PyBullet-Tutorial-main\neu_defect_data\camera_inspection_log.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Required = Table.SelectColumns(Headers, {"cycle", "image", "expected_condition", "expected_type", "gemini_condition", "gemini_type", "confidence", "type_match", "destination", "description", "camera_frame", "camera_top_surface", "capture_seconds", "inspection_source"}),
    TextTypes = Table.TransformColumnTypes(Required, {{"image", type text}, {"expected_condition", type text}, {"expected_type", type text}, {"gemini_condition", type text}, {"gemini_type", type text}, {"destination", type text}, {"description", type text}, {"camera_frame", type text}, {"camera_top_surface", type text}, {"inspection_source", type text}}, "en-US"),
    Typed = Table.TransformColumns(TextTypes, {
        {"cycle", each Int64.From(Number.FromText(_, "en-US")), Int64.Type},
        {"confidence", each Number.FromText(_, "en-US"), type number},
        {"type_match", each Logical.FromText(Text.Lower(_)), type logical},
        {"capture_seconds", each if _ = null or _ = "" then null else Number.FromText(_, "en-US"), type nullable number}
    }),
    ClassMatch = Table.AddColumn(Typed, "class_match", each [expected_type] = [gemini_type], type logical),
    ConditionMatch = Table.AddColumn(ClassMatch, "condition_match", each [expected_condition] = [gemini_condition], type logical),
    Records = Table.AddIndexColumn(ConditionMatch, "record_number", 1, 1, Int64.Type),
    ClassLabels = [GOOD="Good surface", crazing="Crazing", inclusion="Inclusion", patches="Patches", pitted_surface="Pitted surface", #"rolled-in_scale"="Rolled-in scale", scratches="Scratches"],
    ExpectedLabels = Table.AddColumn(Records, "expected_label", each Record.FieldOrDefault(ClassLabels, [expected_type], [expected_type]), type text),
    PredictionLabels = Table.AddColumn(ExpectedLabels, "predicted_label", each Record.FieldOrDefault(ClassLabels, [gemini_type], [gemini_type]), type text),
    MatchLabels = Table.AddColumn(PredictionLabels, "match_label", each if [class_match] then "Match" else "Mismatch", type text)
in
    MatchLabels
