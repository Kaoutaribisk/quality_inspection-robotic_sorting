# Quality Inspection and Robotic Sorting

### AI-assisted surface inspection, automated material handling, and production analytics

A Python-based industrial simulation combining conveyor transport, camera acquisition, visual defect inspection, robotic sorting, and Power BI reporting.

Products leave a simulated painting station, move toward an inspection area, and undergo top-surface inspection. A robotic arm then transfers each product into a **GOOD** or **SCRAP** box according to the inspection result. Completed placements are recorded in a unified CSV history for quality analysis.

> **Scope:** This project is a simulation and integration prototype. It is not a certified industrial inspection system or a controller for a physical robot.

## Project objectives

- Demonstrate an automated inspection and sorting workflow.
- Connect camera imagery with AI-assisted surface-defect classification.
- Coordinate conveyor movement and robotic pick-and-place operations.
- Run repeated production cycles through a desktop control interface.
- Preserve inspection results for traceability and comparison.
- Provide interactive production and quality analysis through Power BI.

## Production workflow

```text
Painting station / product generation
                 │
                 ▼
          Conveyor transport
                 │
                 ▼
       Inspection and pickup station
                 │
                 ▼
        Top-surface camera capture
                 │
                 ▼
      AI-assisted defect classification
                 │
                 ▼
          Sorting destination
          ┌──────┴──────┐
          ▼             ▼
       GOOD box      SCRAP box
          └──────┬──────┘
                 ▼
        Robotic pick-and-place
                 │
                 ▼
       Completed placement logged
                 │
                 ▼
          Power BI analysis
                 │
                 ▼
          Next production cycle
```

Python coordinates the workflow. The inspection result informs the sorting decision, while dedicated motion code controls the simulated robot.

## Main functionalities

### Production environment

- Simulated painting station represented by a black enclosure.
- Repeated product generation with randomized positions.
- Conveyor transport toward an inspection and pickup area.
- Coordinated conveyor stopping for inspection and handling.
- Separate GOOD and SCRAP collection boxes.
- Continuous, repeated production cycles.

### Desktop production controls

A Tkinter control window provides production start and stop controls alongside the PyBullet simulation.

The application coordinates product transport, inspection, sorting, robot movement, and recording. Inspection feedback is displayed within the simulation.

Request a production stop and allow active handling to finish before closing the application or refreshing its data in Power BI.

### Quality inspection

- Top-surface image acquisition.
- AI-assisted GOOD/DEFECTIVE condition assessment.
- Surface-defect classification.
- Inspection descriptions and model-reported confidence.
- Comparison between reference labels and predicted results.
- Routing to the appropriate collection box.
- Persistent inspection history.

## Camera inspection

The simulated inspection camera is positioned near the painting-station exit to capture the product’s top surface.

The camera pipeline produces scene captures and top-surface inspection imagery. Image references are associated with inspection records when available, allowing results to be traced back to their visual input.

The current inspection scope is the **top surface only**. Hidden faces, underside defects, and internal defects are outside that scope.

Camera-capture duration is recorded separately from the inspection result. It does not represent AI inference time or complete production-cycle duration.

## Gemini Robotics ER vision

The project communicates with Gemini through the Python `google-genai` SDK.

**ER means embodied reasoning.** Gemini Robotics ER is a vision-language model family for visual and spatial reasoning. It is not an augmented-reality interface; the project does not implement an AR headset or overlay.

The vision workflow uses images to obtain information such as:

- Product condition.
- Predicted surface-defect class.
- Visible surface characteristics.
- Model-reported confidence.
- Information used to select a sorting destination.

A separate scene-analysis demonstration identifies workstation zones, the robotic arm, objects, and their spatial relationships.

### Separation of responsibilities

| Layer | Responsibility |
| --- | --- |
| Camera | Acquires inspection imagery. |
| Vision model | Interprets the supplied image. |
| Python coordinator | Handles the result and determines the destination. |
| Motion controller | Executes the simulated pick-and-place operation. |
| Record handler | Saves the completed operation. |
| Power BI | Analyses the saved history. |

The vision model does not directly control physical actuators.

### Inspection sources and caching

The project evolved from direct texture-image inspection to camera-based inspection. The unified history distinguishes these sources as **Texture** and **Camera**.

A local inspection cache supports reuse of previously obtained results. Cached results are not new API calls and should not be treated as independent fresh evaluations.

Review cached results when changing the model, prompt, or reference images.

## Robotic handling

The workstation uses a simulated **Franka Emika Panda** arm with a parallel gripper.

The handling sequence includes:

1. Approach the pickup location.
2. Position the end effector.
3. Perform the simulated grasp.
4. Lift the product clear of the conveyor.
5. Move toward the selected box.
6. Lower and release the product.
7. Transition into the next production cycle.

The motion code supports coordinated movement and cycle transitions. Pickup accuracy depends on simulated geometry, target coordinates, timing, and grasp implementation.

Successful movement in PyBullet does not establish physical grasp reliability or readiness for deployment on industrial hardware.

## Python architecture

Python connects the production environment, camera, inspection service, robotic motion, controls, and records.

### Main components

| Component | Purpose |
| --- | --- |
| `defect_inspection_kitting.py` | Main inspection and robotic-sorting application. |
| `conveyor_kitting.py` | Conveyor workstation and shared simulation helpers. |
| `production_motion.py` | Production-oriented robot movement and cycle transitions. |
| `inspection_camera.py` | Camera acquisition and top-surface imagery. |
| `inspection_records.py` | Unified records, CSV validation, and history consolidation. |
| `industrial_kitting.py` | Earlier industrial pick-and-place demonstration. |
| `test_robotics_er.py` | Standalone visual scene-analysis test. |
| `build_power_bi_report.py` | Power BI report and CSV-bound model generation. |
| `requirements.txt` | Python dependency versions from the working environment. |
| `assets/` | Local simulation geometry and visual assets. |
| `tests/` | Project tests, where included in the distributed version. |

Keep shared modules and required assets together. Copying only the main application can cause missing-module or resource errors.

### Technology stack

| Technology | Role |
| --- | --- |
| Python 3.11 | Application and workflow coordination. |
| PyBullet | Workstation, robot, conveyor, and object simulation. |
| NumPy | Numerical and image-data operations. |
| Pillow | Image loading and processing. |
| `google-genai` | Gemini API communication. |
| Tkinter | Desktop production-control interface. |
| CSV | Inspection history and analytics input. |
| JSON | Local result storage and report definitions. |
| Power BI Desktop | Interactive production and quality reporting. |

The verified Windows environment used the `pybullet-arm64` distribution, imported in Python as `pybullet`. Preserve the dependency configuration that works on the target machine rather than installing conflicting PyBullet distributions.

## Dataset and reference surfaces

The project uses surface-defect imagery associated with the **NEU Surface Defect Database**.

The six defect categories are:

| Surface class | Project label |
| --- | --- |
| Crazing | `crazing` |
| Inclusion | `inclusion` |
| Patches | `patches` |
| Pitted surface | `pitted_surface` |
| Rolled-in scale | `rolled-in_scale` |
| Scratches | `scratches` |

GOOD reference surfaces are maintained separately for the simulation. **GOOD is not a seventh defect category supplied by the original NEU database.**

### Data preparation

- Obtain the dataset separately from its published source.
- Preserve the directory structure expected by the inspection application.
- Maintain dataset resources under `neu_defect_data/`.
- Keep the simulation’s GOOD reference available.
- Exclude dataset credentials from the repository.

A Kaggle `kernels pull` command downloads a notebook or kernel; it should not be assumed to download the complete underlying dataset.

External datasets and assets retain their upstream attribution and usage requirements.

## Inspection records

### Unified history

The main analytics source is:

```text
neu_defect_data/camera_inspection_log.csv
```

The unified history combines earlier texture-based records with camera-based records while retaining the inspection source.

The earlier `inspection_log.csv` remains a legacy source rather than being silently removed.

### Logged fields

| Field | Meaning |
| --- | --- |
| `cycle` | Production-run cycle number; it can restart between runs. |
| `image` | Inspection input or source-image reference. |
| `expected_condition` | Reference GOOD/DEFECTIVE condition. |
| `expected_type` | Reference surface class. |
| `gemini_condition` | Predicted condition. |
| `gemini_type` | Predicted surface class. |
| `confidence` | Model-reported confidence, represented as a fraction. |
| `type_match` | Recorded reference-versus-prediction class agreement. |
| `destination` | Recorded sorting destination. |
| `description` | Inspection explanation. |
| `camera_frame` | Camera-frame reference, when available. |
| `camera_top_surface` | Top-surface image reference, when available. |
| `capture_seconds` | Camera-capture duration, when available. |
| `inspection_source` | Camera or Texture inspection source. |

One logged record represents a completed placement.

**Cycle numbers are not globally unique product identifiers.** Missing legacy camera fields remain missing rather than being replaced with invented measurements.

## Power BI dashboard

The Power BI report reads the unified inspection CSV and provides three complementary pages.

### Production overview

- Completed-product count.
- GOOD and SCRAP routing counts.
- Exact surface-class agreement.
- Predicted surface-class distribution.
- GOOD/SCRAP routing distribution.
- Inspection-method counts.
- Class mismatches by expected class.
- Inspection-source comparison.

The dark dashboard version uses four headline KPI cards and six supporting panels.

### Quality comparison

- Expected-versus-predicted class matrix.
- Exact class match.
- GOOD/DEFECTIVE condition match.
- False accepts and false rejects.
- Model-reported confidence.
- Per-record classification review.
- Filters for inspection method and class result.

### Inspection history

- Individual inspection records.
- Reference and predicted classes.
- Sorting destinations.
- Confidence values.
- Inspection notes.
- Filters by method, predicted class, and destination.

Selecting a record in the history table filters its associated inspection notes.

### Metric definitions

| Metric | Interpretation |
| --- | --- |
| Completed products | Number of logged completed placements. |
| Scrap share | SCRAP-routed records divided by all records in the current filter context. |
| Exact class match | Agreement between reference and predicted surface class. |
| Condition match | Agreement between reference and predicted GOOD/DEFECTIVE condition. |
| False accepts | Defective-reference products routed to GOOD. |
| False rejects | GOOD-reference products routed to SCRAP. |
| Mean confidence | Average model-reported confidence—not measured accuracy. |
| Mean capture seconds | Average camera-capture duration for eligible Camera records. |

Class and condition agreement compare predictions with the project’s dataset or simulation references. They are not independently certified industrial performance results.

### Opening the report

1. Open `QualityInspection.pbip` in Power BI Desktop.
2. Select **Home → Refresh**.
3. Review the records and active filters.
4. Save the report.

The included dashboard is located at:

```text
PyBullet-Tutorial-main/power_bi_professional/QualityInspection.pbip
```

The `.pbip` file, `QualityInspection.Report` folder, and `QualityInspection.SemanticModel` folder must remain together.

The report currently references the original workstation’s CSV location. On another computer, open **Transform data → Data source settings → Change Source**, select that computer’s `camera_inspection_log.csv`, then apply the changes and refresh.

Inspection logs are generated locally and are not included in this repository. Run production cycles before refreshing the dashboard. Refresh is manual, not a live connection to the simulation.

## Installation and execution

### Prerequisites

- Python 3.11 with Tkinter support.
- A Gemini API key with access to the model configured in the application.
- The NEU-DET dataset, downloaded separately.
- Power BI Desktop for the optional dashboard.

Download this repository using **Code → Download ZIP**, extract it, and open the extracted repository folder in VS Code.

### Install Python dependencies

From the repository’s top-level folder, run these commands separately:

```powershell
py -3.11 -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\PyBullet-Tutorial-main\requirements.txt
```

```powershell
.\.venv\Scripts\python.exe -m pip check
```

Virtual environments are created locally; they are not included in the repository.

### Prepare the dataset

Arrange the downloaded training images in this exact structure:

```text
PyBullet-Tutorial-main/
└── neu_defect_data/
    ├── good_reference.png
    └── dataset/
        └── NEU-DET/
            └── train/
                └── images/
                    ├── crazing/
                    ├── inclusion/
                    ├── patches/
                    ├── pitted_surface/
                    ├── rolled-in_scale/
                    └── scratches/
```

Each defect-class folder must contain its corresponding `.jpg` images. Dataset files are intentionally excluded from this repository. Respect the dataset provider’s usage requirements.

### Configure Gemini access

The application reads the API key from the `GEMINI_API_KEY` environment variable. Never put a real key in source code, documentation, or committed files.

To enter the key without displaying it, run the following in the PowerShell terminal used to launch the application:

```powershell
$InspectionSecureKey = Read-Host "Enter your Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $InspectionSecureKey).Password
Remove-Variable InspectionSecureKey
```

This sets the key for the current terminal session only. API usage is subject to the provider’s access permissions, quotas, and pricing.

### Run production

From the repository’s top-level folder:

```powershell
cd .\PyBullet-Tutorial-main
```

```powershell
..\.venv\Scripts\python.exe .\defect_inspection_kitting.py
```

Use the desktop controls to start production, run a single cycle, or request a stop. Allow active handling to finish before closing the application.

Completed placements are saved to:

```text
neu_defect_data/camera_inspection_log.csv
```

### Run standalone scene analysis

From inside `PyBullet-Tutorial-main`:

```powershell
..\.venv\Scripts\python.exe .\test_robotics_er.py
```

This demonstration analyses the included `workspace_view.png` image; it does not control the production robot.

## Troubleshooting

- **Missing Python module:** install dependencies using the repository’s virtual-environment interpreter.
- **Dataset incomplete:** check the six class folders and their `.jpg` images against the structure above.
- **Missing API key:** configure `GEMINI_API_KEY` in the terminal that launches the program.
- **API permission or model error:** verify access to the model configured in the Python script.
- **Blank Power BI dashboard:** generate inspection records, select the correct CSV source, and refresh.
- **Missing simulation asset:** preserve the repository’s folder structure.

## Limitations

This project demonstrates simulated industrial integration. It does not establish physical robot safety, certified defect-detection accuracy, or deployment readiness.

Inspection covers the photographed top surface only. Cached classifications are reused results, not fresh independent evaluations. Model confidence is not measured accuracy.

External datasets, robot models, and other third-party assets retain their original licenses and attribution.
