"""Generate E2E architecture PDF with flowchart images."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT_DIR = Path(__file__).resolve().parent
IMG_DIR = OUT_DIR / "_pdf_assets"
PDF_PATH = OUT_DIR / "09-e2e-architecture.pdf"

TEAL = (15, 118, 110)
TEAL_LIGHT = (204, 232, 229)
INK = (20, 32, 51)
MUTED = (91, 107, 124)
WHITE = (255, 255, 255)
LINE = (180, 190, 200)
AMBER = (180, 83, 9)
PANEL = (248, 250, 252)


def _font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    bold_candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]
    paths = bold_candidates if bold else candidates
    for p in paths:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _rounded_box(draw, xy, fill, outline=LINE, radius=14, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _center_text(draw, box, text, font, fill=INK):
    x0, y0, x1, y1 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((x0 + x1 - tw) / 2, (y0 + y1 - th) / 2), text, font=font, fill=fill)


def _arrow(draw, start, end, fill=TEAL):
    draw.line([start, end], fill=fill, width=3)
    x0, y0 = start
    x1, y1 = end
    # simple arrow head
    if abs(x1 - x0) >= abs(y1 - y0):
        # horizontal
        direction = 1 if x1 > x0 else -1
        draw.polygon(
            [(x1, y1), (x1 - 10 * direction, y1 - 6), (x1 - 10 * direction, y1 + 6)],
            fill=fill,
        )
    else:
        direction = 1 if y1 > y0 else -1
        draw.polygon(
            [(x1, y1), (x1 - 6, y1 - 10 * direction), (x1 + 6, y1 - 10 * direction)],
            fill=fill,
        )


def draw_architecture() -> Path:
    w, h = 1100, 520
    img = Image.new("RGB", (w, h), WHITE)
    draw = ImageDraw.Draw(img)
    title_f = _font(22, True)
    body_f = _font(15)
    small_f = _font(13)

    draw.text((30, 18), "Figure 1 — Big picture architecture", font=title_f, fill=TEAL)

    # Outside box
    _rounded_box(draw, (30, 70, 520, 470), PANEL, TEAL, 18)
    draw.text((50, 85), "Outside our app", font=_font(16, True), fill=TEAL)

    src = (60, 140, 240, 210)
    etl = (150, 250, 400, 320)
    tgt = (280, 140, 490, 210)
    _rounded_box(draw, src, TEAL_LIGHT, TEAL)
    _rounded_box(draw, etl, (255, 236, 210), AMBER)
    _rounded_box(draw, tgt, TEAL_LIGHT, TEAL)
    _center_text(draw, src, "Source DB", body_f)
    _center_text(draw, etl, "ETL tool (dbt / Airflow)", body_f)
    _center_text(draw, tgt, "Target DB", body_f)

    _arrow(draw, (150, 210), (220, 250))
    _arrow(draw, (340, 250), (380, 210))
    draw.text((175, 220), "business data", font=small_f, fill=MUTED)
    draw.text((350, 220), "load", font=small_f, fill=MUTED)

    # Our platform box
    _rounded_box(draw, (560, 70, 1070, 470), PANEL, TEAL, 18)
    draw.text((580, 85), "Our platform", font=_font(16, True), fill=TEAL)

    boxes = [
        ((590, 150, 780, 220), "Observability\nconnectors", TEAL_LIGHT),
        ((810, 150, 990, 220), "Normalization", (230, 240, 255)),
        ((700, 270, 920, 350), "Metadata MySQL", (220, 245, 235)),
        ((700, 380, 920, 450), "UI / AI later", (255, 245, 230)),
    ]
    for box, label, fill in boxes:
        _rounded_box(draw, box, fill, TEAL)
        lines = label.split("\n")
        x0, y0, x1, y1 = box
        total_h = len(lines) * 20
        y = (y0 + y1 - total_h) / 2
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=body_f)
            tw = bbox[2] - bbox[0]
            draw.text(((x0 + x1 - tw) / 2, y + i * 20), line, font=body_f, fill=INK)

    # Sync arrows from outside to connectors
    _arrow(draw, (490, 175), (590, 175))
    draw.text((500, 150), "catalog Sync", font=small_f, fill=MUTED)
    _arrow(draw, (400, 285), (590, 200))
    draw.text((430, 300), "run logs Sync", font=small_f, fill=MUTED)
    _arrow(draw, (780, 185), (810, 185))
    _arrow(draw, (900, 220), (820, 270))
    _arrow(draw, (810, 350), (810, 380))

    path = IMG_DIR / "fig1_architecture.png"
    img.save(path, "PNG")
    return path


def draw_pipeline_id() -> Path:
    w, h = 900, 480
    img = Image.new("RGB", (w, h), WHITE)
    draw = ImageDraw.Draw(img)
    title_f = _font(22, True)
    body_f = _font(15)

    draw.text((30, 18), "Figure 2 — Pipeline ID attachments", font=title_f, fill=TEAL)

    root = (300, 60, 600, 120)
    _rounded_box(draw, root, TEAL, TEAL)
    _center_text(draw, root, "pipeline_id = stock_etl", _font(17, True), WHITE)

    attachments = [
        ((60, 180, 300, 250), "Source DB\nconnector", TEAL_LIGHT),
        ((320, 180, 580, 250), "ETL tool\nconnector", (255, 236, 210)),
        ((600, 180, 840, 250), "Target DB\nconnector", TEAL_LIGHT),
    ]
    for box, label, fill in attachments:
        _rounded_box(draw, box, fill, TEAL)
        lines = label.split("\n")
        x0, y0, x1, y1 = box
        y = y0 + 22
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=body_f)
            tw = bbox[2] - bbox[0]
            draw.text(((x0 + x1 - tw) / 2, y + i * 22), line, font=body_f, fill=INK)

    _arrow(draw, (380, 120), (180, 180))
    _arrow(draw, (450, 120), (450, 180))
    _arrow(draw, (520, 120), (720, 180))

    results = [
        ((60, 310, 300, 400), "datasets\n(from source Sync)"),
        ((320, 310, 580, 400), "executions +\nerror logs"),
        ((600, 310, 840, 400), "datasets\n(from target Sync)"),
    ]
    for box, label in results:
        _rounded_box(draw, box, PANEL, TEAL)
        lines = label.split("\n")
        x0, y0, x1, y1 = box
        y = y0 + 28
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=body_f)
            tw = bbox[2] - bbox[0]
            draw.text(((x0 + x1 - tw) / 2, y + i * 22), line, font=body_f, fill=INK)

    _arrow(draw, (180, 250), (180, 310))
    _arrow(draw, (450, 250), (450, 310))
    _arrow(draw, (720, 250), (720, 310))

    draw.text(
        (60, 430),
        "Everything is found again using the same pipeline_id.",
        font=_font(14),
        fill=MUTED,
    )

    path = IMG_DIR / "fig2_pipeline.png"
    img.save(path, "PNG")
    return path


def draw_connector_flow() -> Path:
    w, h = 1000, 280
    img = Image.new("RGB", (w, h), WHITE)
    draw = ImageDraw.Draw(img)
    title_f = _font(22, True)
    body_f = _font(14)

    draw.text((30, 18), "Figure 3 — Connector day-to-day flow", font=title_f, fill=TEAL)

    steps = [
        (40, "1. Create\nconnection"),
        (230, "2. Secrets\nin .env"),
        (420, "3. Test"),
        (580, "4. Sync"),
        (740, "5. Normalize\n+ store"),
    ]
    for x, label in steps:
        box = (x, 90, x + 160, 180)
        _rounded_box(draw, box, TEAL_LIGHT, TEAL)
        lines = label.split("\n")
        y = 115
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=body_f)
            tw = bbox[2] - bbox[0]
            draw.text((x + (160 - tw) / 2, y + i * 22), line, font=body_f, fill=INK)
        if x < 740:
            _arrow(draw, (x + 160, 135), (x + 190, 135))

    draw.text(
        (40, 210),
        "Test = login works.  Sync = pull metadata/logs into Metadata MySQL.",
        font=_font(14),
        fill=MUTED,
    )

    path = IMG_DIR / "fig3_connector_flow.png"
    img.save(path, "PNG")
    return path


def draw_metadata_uses() -> Path:
    w, h = 950, 360
    img = Image.new("RGB", (w, h), WHITE)
    draw = ImageDraw.Draw(img)
    title_f = _font(22, True)
    body_f = _font(15)

    draw.text((30, 18), "Figure 4 — What we can do with Metadata", font=title_f, fill=TEAL)

    center = (360, 140, 590, 230)
    _rounded_box(draw, center, TEAL, TEAL)
    _center_text(draw, center, "Metadata MySQL", _font(17, True), WHITE)

    outs = [
        ((40, 80, 260, 150), "Fail / error\ndashboard"),
        ((40, 200, 260, 270), "Source / ETL /\ntarget view"),
        ((690, 80, 910, 150), "One AI\nassistant"),
        ((690, 200, 910, 270), "Reports later\n(BIRT / Superset)"),
    ]
    for box, label in outs:
        _rounded_box(draw, box, TEAL_LIGHT, TEAL)
        lines = label.split("\n")
        x0, y0, x1, y1 = box
        y = y0 + 18
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=body_f)
            tw = bbox[2] - bbox[0]
            draw.text(((x0 + x1 - tw) / 2, y + i * 22), line, font=body_f, fill=INK)

    _arrow(draw, (360, 160), (260, 115))
    _arrow(draw, (360, 200), (260, 235))
    _arrow(draw, (590, 160), (690, 115))
    _arrow(draw, (590, 200), (690, 235))

    draw.text(
        (40, 300),
        "AI and UI read only Metadata — not live Snowflake/dbt at chat time.",
        font=_font(14),
        fill=MUTED,
    )

    path = IMG_DIR / "fig4_metadata_uses.png"
    img.save(path, "PNG")
    return path


def make_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=styles["Title"],
            fontSize=22,
            textColor=colors.HexColor("#0f766e"),
            spaceAfter=12,
            leading=28,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H1Doc",
            parent=styles["Heading1"],
            fontSize=14,
            textColor=colors.HexColor("#0f766e"),
            spaceBefore=14,
            spaceAfter=8,
            leading=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H2Doc",
            parent=styles["Heading2"],
            fontSize=12,
            textColor=colors.HexColor("#115e59"),
            spaceBefore=10,
            spaceAfter=6,
            leading=15,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyDoc",
            parent=styles["Normal"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#142033"),
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletDoc",
            parent=styles["Normal"],
            fontSize=10,
            leading=13,
            leftIndent=12,
            textColor=colors.HexColor("#142033"),
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CodeBlock",
            parent=styles["Code"],
            fontSize=9,
            leading=12,
            backColor=colors.HexColor("#f1f5f9"),
            textColor=colors.HexColor("#142033"),
            leftIndent=6,
            rightIndent=6,
            spaceBefore=4,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Caption",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#5b6b7c"),
            alignment=TA_CENTER,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Cell",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#142033"),
        )
    )
    return styles


def table(data, col_widths, styles):
    cell = styles["Cell"]
    wrapped = [[Paragraph(str(c), cell) for c in row] for row in data]
    t = Table(wrapped, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ]
        )
    )
    return t


def add_image(path: Path, width=170 * mm):
    # preserve aspect
    with Image.open(path) as im:
        w, h = im.size
    height = width * h / w
    return RLImage(str(path), width=width, height=height)


def build_pdf(fig_paths: dict[str, Path]):
    styles = make_styles()
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="ETL Observability — End-to-End Architecture",
        author="ETL Observability Platform",
    )
    story = []

    story.append(Paragraph("ETL Observability Platform", styles["CoverTitle"]))
    story.append(Paragraph("End-to-end architecture (simple guide)", styles["H1Doc"]))
    story.append(
        Paragraph(
            "We do <b>not</b> rebuild ETL. We <b>watch</b> databases and ETL tools, "
            "<b>normalize</b> their metadata and logs, and <b>store</b> them in "
            "<b>one Metadata database</b> so we can see, for each pipeline: "
            "source, ETL tool, target, and errors.",
            styles["BodyDoc"],
        )
    )
    story.append(
        Paragraph(
            "<b>Open ETL tools (dbt / Airflow) move the data.<br/>"
            "Our platform stores the story of that data movement.</b>",
            styles["BodyDoc"],
        )
    )

    # Section 2
    story.append(Paragraph("1. Big picture architecture", styles["H1Doc"]))
    story.append(add_image(fig_paths["arch"]))
    story.append(Paragraph("Figure 1 — Outside tools sync into our Metadata DB", styles["Caption"]))
    bullets = [
        "Source DB / Target DB — real warehouses (e.g. Snowflake). Business data lives there.",
        "ETL tool — dbt or Airflow. It already has extract/load connectors. It runs the pipeline.",
        "Our connectors — thin readers. They Sync metadata and logs into our DB. They do not move business rows.",
        "Normalization — turns each tool’s messy JSON into one standard shape.",
        "Metadata MySQL — one place for pipelines, tables, runs, errors, links.",
        "UI / AI — later read only Metadata (not live Snowflake at chat time).",
    ]
    for b in bullets:
        story.append(Paragraph(f"• {b}", styles["BulletDoc"]))

    story.append(Paragraph("Two meanings of “connector”", styles["H2Doc"]))
    story.append(
        table(
            [
                ["Kind", "Who owns it", "Job"],
                ["ETL extract/load connectors", "dbt / Airflow", "Move data source → target"],
                [
                    "Our observability connectors",
                    "Our platform",
                    "Collect metadata + logs into Metadata DB",
                ],
            ],
            [55 * mm, 40 * mm, 70 * mm],
            styles,
        )
    )

    # Section pipeline
    story.append(Paragraph("2. How a pipeline is recognized (pipeline_id)", styles["H1Doc"]))
    story.append(
        Paragraph(
            "You create one <b>pipeline</b> and attach three things: "
            "Source DB connector, ETL tool connector, Target DB connector. "
            "Usual MVP: <b>1 ETL + 2 DB roles</b>.",
            styles["BodyDoc"],
        )
    )
    story.append(add_image(fig_paths["pipeline"], width=155 * mm))
    story.append(Paragraph("Figure 2 — Attachments under one pipeline_id", styles["Caption"]))
    for b in [
        "pipeline_id is the folder name for one data flow.",
        "After Sync: show source tables, target tables, last failures for that id.",
        "Linking is stored in etl_pipeline_io. Without it, Snowflake and dbt stay separate piles.",
    ]:
        story.append(Paragraph(f"• {b}", styles["BulletDoc"]))

    story.append(PageBreak())

    # Connectors
    story.append(Paragraph("3. How connectors work", styles["H1Doc"]))
    story.append(add_image(fig_paths["flow"], width=165 * mm))
    story.append(Paragraph("Figure 3 — Create → Test → Sync → Store", styles["Caption"]))
    story.append(
        table(
            [
                ["Connector", "Pulls from", "Main result in our DB"],
                ["Snowflake", "INFORMATION_SCHEMA", "Tables, row_count, last_updated"],
                ["dbt Cloud", "Runs API / artifacts", "Job status, error_message"],
                ["Airflow (later)", "REST / metadata DB", "DAG/task runs, errors"],
                ["MySQL (later)", "information_schema", "Tables like Snowflake"],
            ],
            [35 * mm, 55 * mm, 75 * mm],
            styles,
        )
    )
    story.append(Spacer(1, 6))
    for b in [
        "Secrets never go in the database — only env var names.",
        "Assistants never call Snowflake/dbt directly; they read Metadata.",
    ]:
        story.append(Paragraph(f"• {b}", styles["BulletDoc"]))

    story.append(Paragraph("4. Two transforms (do not confuse them)", styles["H1Doc"]))
    story.append(
        table(
            [
                ["Transform", "Where", "What it does"],
                ["Business ETL transform", "Inside dbt/Airflow", "Clean/join business rows"],
                [
                    "Metadata transform",
                    "Our Normalization",
                    "Raw logs/catalog → structured Metadata tables",
                ],
            ],
            [45 * mm, 45 * mm, 75 * mm],
            styles,
        )
    )
    story.append(
        Paragraph(
            "R&amp;D for us = better mapping rules and source/target linking — "
            "<b>not</b> replacing dbt SQL.",
            styles["BodyDoc"],
        )
    )

    # Tables
    story.append(Paragraph("5. What we store (clear tables &amp; columns)", styles["H1Doc"]))
    story.append(
        Paragraph(
            "All tables live in one MySQL database (e.g. <b>metadata</b>). Prefix: <b>etl_</b>.",
            styles["BodyDoc"],
        )
    )

    story.append(Paragraph("A. Connections — etl_connector_instances", styles["H2Doc"]))
    story.append(
        table(
            [
                ["Column", "Meaning"],
                ["tenant_id", "Customer/space (e.g. demo)"],
                ["instance_id", "Unique connection id"],
                ["tool_id", "snowflake / dbt / airflow"],
                ["name", "Display name"],
                ["config", "Non-secret settings (account, database, …)"],
                ["secrets_ref", "Env var names only"],
                ["status", "created / ready / synced / error"],
                ["last_sync_at", "Last successful Sync"],
                ["last_error", "Last error text"],
            ],
            [45 * mm, 120 * mm],
            styles,
        )
    )

    story.append(Paragraph("B. Pipeline identity — etl_pipelines", styles["H2Doc"]))
    story.append(
        table(
            [
                ["Column", "Meaning"],
                ["pipeline_id", "Our id (e.g. stock_etl)"],
                ["name", "Human name"],
                ["source_tool", "Main ETL tool (dbt, …)"],
                ["status", "Latest known status"],
            ],
            [45 * mm, 120 * mm],
            styles,
        )
    )

    story.append(Paragraph("etl_pipeline_io (source ↔ target)", styles["H2Doc"]))
    story.append(
        table(
            [
                ["Column", "Meaning"],
                ["pipeline_id", "Which pipeline"],
                ["upstream_dataset_id", "Source table id"],
                ["downstream_dataset_id", "Target table id"],
                ["source_tool", "Tool that declared the link"],
            ],
            [50 * mm, 115 * mm],
            styles,
        )
    )

    story.append(PageBreak())

    story.append(Paragraph("C. From databases — etl_datasets", styles["H2Doc"]))
    story.append(
        table(
            [
                ["Column", "Meaning"],
                ["dataset_id", "Full name e.g. ANALYTICS_DB.RAW.STOCK_DATA_RAW"],
                ["name", "Short table name"],
                ["database_name", "Database"],
                ["schema_name", "Schema"],
                ["platform", "snowflake / mysql"],
                ["row_count", "Approx rows (for volume later)"],
                ["last_updated_at", "Last change time (for freshness later)"],
            ],
            [45 * mm, 120 * mm],
            styles,
        )
    )

    story.append(Paragraph("etl_dataset_columns (later — schema diff)", styles["H2Doc"]))
    story.append(
        table(
            [
                ["Column", "Meaning"],
                ["dataset_id", "Parent table"],
                ["column_name", "Column"],
                ["data_type", "Type (VARCHAR, NUMBER, …)"],
                ["is_nullable", "Null allowed?"],
            ],
            [45 * mm, 120 * mm],
            styles,
        )
    )

    story.append(Paragraph("D. From ETL tools — etl_executions (logs)", styles["H2Doc"]))
    story.append(
        table(
            [
                ["Column", "Meaning"],
                ["execution_id", "Run id from the tool"],
                ["pipeline_id", "Which pipeline"],
                ["task_id", "Step/model if any"],
                ["source_tool", "dbt / airflow"],
                ["status", "succeeded / failed / running"],
                ["started_at / finished_at", "Run times"],
                ["error_message", "The log / error text"],
                ["attempt", "Retry number"],
            ],
            [50 * mm, 115 * mm],
            styles,
        )
    )

    story.append(
        Paragraph(
            "<b>MVP focus:</b> connections + pipelines + pipeline_io + datasets + "
            "executions (with error_message).",
            styles["BodyDoc"],
        )
    )

    # Example
    story.append(Paragraph("6. Example: one real pipeline", styles["H1Doc"]))
    story.append(
        Paragraph(
            "<b>pipeline_id:</b> stock_etl<br/>"
            "<b>Source:</b> ANALYTICS_DB.RAW.STOCK_DATA_RAW<br/>"
            "<b>ETL:</b> dbt Cloud (runs in etl_executions)<br/>"
            "<b>Target:</b> ANALYTICS_DB.STAGING_STAGING.STG_STOCK_DATA",
            styles["BodyDoc"],
        )
    )
    for b in [
        "Sync Snowflake → rows in etl_datasets",
        "Sync dbt → rows in etl_executions (status + error_message)",
        "Link → row in etl_pipeline_io",
        "Then answer: failed runs? error text? source/target tables?",
    ]:
        story.append(Paragraph(f"• {b}", styles["BulletDoc"]))

    story.append(Paragraph("7. Freshness (later — not MVP UI)", styles["H1Doc"]))
    story.append(
        Paragraph(
            "Freshness = “is the <b>table</b> updated recently enough?” using "
            "last_updated_at vs a time rule. Use it when a job looks green but the "
            "target is still old. Failed pipeline counts come from "
            "<b>etl_executions</b>, not freshness.",
            styles["BodyDoc"],
        )
    )

    # Uses
    story.append(Paragraph("8. What we can do using this Metadata DB", styles["H1Doc"]))
    story.append(add_image(fig_paths["uses"], width=155 * mm))
    story.append(Paragraph("Figure 4 — Downstream uses of Metadata", styles["Caption"]))
    for i, b in enumerate(
        [
            "List pipelines and show running / failed counts.",
            "Open a pipeline and see source DB, ETL tool, target DB.",
            "Show error logs from error_message without opening dbt Cloud.",
            "List tables discovered from Snowflake Sync.",
            "Filter everything by pipeline_id.",
            "Feed one AI assistant with tools that only query Metadata.",
            "Later: reports (BIRT / Superset); freshness/volume; lineage UI.",
            "Later: schema diff when column types change between Syncs.",
        ],
        1,
    ):
        story.append(Paragraph(f"{i}. {b}", styles["BulletDoc"]))

    story.append(PageBreak())
    story.append(Paragraph("9. Point-wise summary (whole story)", styles["H1Doc"]))
    for i, b in enumerate(
        [
            "ETL tools run pipelines; we observe them.",
            "Each tool type has an observability connector (Snowflake, dbt, …).",
            "Sync pulls metadata/logs; Normalization standardizes them.",
            "Everything lands in one MySQL Metadata DB.",
            "A pipeline_id attaches source DB + ETL + target DB.",
            "DB connectors fill datasets; ETL connectors fill executions (logs).",
            "pipeline_io links source table → target table for that pipeline.",
            "MVP UI: fails, errors, attachments — not freshness-first.",
            "AI and reports sit on Metadata, not on live tools.",
            "We do not rebuild extract/load; we store the story so people and AI can understand it.",
        ],
        1,
    ):
        story.append(Paragraph(f"{i}. {b}", styles["BulletDoc"]))

    story.append(Spacer(1, 16))
    story.append(
        Paragraph(
            "Document source: docs/fresh-start/09-e2e-architecture.md",
            styles["Caption"],
        )
    )

    doc.build(story)
    return PDF_PATH


def main():
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    figs = {
        "arch": draw_architecture(),
        "pipeline": draw_pipeline_id(),
        "flow": draw_connector_flow(),
        "uses": draw_metadata_uses(),
    }
    path = build_pdf(figs)
    print(f"PDF written: {path}")
    print(f"Size bytes: {path.stat().st_size}")


if __name__ == "__main__":
    main()
