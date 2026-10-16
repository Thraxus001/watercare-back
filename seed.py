"""Seed script to populate MongoDB Atlas with realistic demo data for WaterCare.

Usage:
    python seed.py          # Seeds demo data (skips if data already exists, or pass --drop to reset)
    python seed.py --drop   # Clears existing collections and reseeds fresh demo data
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import logging
import sys

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.models import CheckCategory, InputType, UserRole
from app.mongo import create_indexes
from app.permissions import Permission
from app.security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("seed")


async def seed(drop: bool = False):
    url = settings.effective_mongo_url
    if not url:
        log.error("No MONGODB_URL configured in .env!")
        sys.exit(1)

    masked_url = url
    if "@" in url:
        prefix, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        masked_url = f"{prefix}://*****@{host}"

    log.info("Connecting to MongoDB Atlas (%s)...", masked_url)
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=8000)
    db = client[settings.mongodb_db_name]

    try:
        await client.admin.command("ping")
        log.info("Connected successfully to database '%s'", settings.mongodb_db_name)
    except Exception as exc:
        log.error("Failed to connect to MongoDB Atlas: %s", exc)
        sys.exit(1)

    collections = ["users", "plants", "machine_types", "check_items", "machines", "inspections", "notes", "counters"]

    if drop:
        log.warning("Dropping existing collections for clean seed...")
        for c in collections:
            await db[c].drop()
        log.info("Collections cleared.")

    # Verify indexes
    await create_indexes(db)

    # Check if already seeded
    user_count = await db["users"].count_documents({})
    if user_count > 0 and not drop:
        log.info("Database already contains %d user(s). Pass --drop to reset and re-seed.", user_count)
        client.close()
        return

    now = datetime.now(timezone.utc)
    one_day = timedelta(days=1)

    # ───────────── 1. Users ─────────────
    log.info("Seeding users...")
    password_hash = hash_password("ChangeMe123!")

    all_permissions = [p.value for p in Permission]
    tech_permissions = [
        Permission.MACHINES_VIEW.value,
        Permission.MACHINES_MANAGE.value,
        Permission.CHECKLISTS_VIEW.value,
        Permission.INSPECTIONS_VIEW.value,
        Permission.INSPECTIONS_CREATE.value,
        Permission.NOTES_VIEW.value,
        Permission.NOTES_CREATE.value,
    ]
    operator_permissions = [
        Permission.MACHINES_VIEW.value,
        Permission.INSPECTIONS_VIEW.value,
        Permission.INSPECTIONS_CREATE.value,
        Permission.NOTES_VIEW.value,
        Permission.NOTES_CREATE.value,
    ]

    users = [
        {
            "id": 1,
            "email": settings.first_admin_email.lower(),
            "full_name": settings.first_admin_name,
            "hashed_password": hash_password(settings.first_admin_password),
            "role": UserRole.admin.value,
            "is_active": True,
            "created_at": now - 30 * one_day,
            "permissions": all_permissions,
        },
        {
            "id": 2,
            "email": "john.tech@watercare.local",
            "full_name": "John Doe (Lead Technician)",
            "hashed_password": password_hash,
            "role": UserRole.user.value,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "permissions": tech_permissions,
        },
        {
            "id": 3,
            "email": "sarah.operator@watercare.local",
            "full_name": "Sarah Connor (Plant Operator)",
            "hashed_password": password_hash,
            "role": UserRole.user.value,
            "is_active": True,
            "created_at": now - 20 * one_day,
            "permissions": operator_permissions,
        },
    ]
    await db["users"].insert_many(users)

    # ───────────── 2. Machine Types ─────────────
    log.info("Seeding machine types...")
    machine_types = [
        {
            "id": 1,
            "name": "Commercial Reverse Osmosis (RO) System",
            "description": "High-recovery RO membrane skid for industrial process water and desalination.",
        },
        {
            "id": 2,
            "name": "Industrial Water Softener (Ion Exchange)",
            "description": "Dual-tank automatic water softener for hardness and scale control.",
        },
        {
            "id": 3,
            "name": "Ultraviolet (UV) Disinfection Unit",
            "description": "Inline germicidal UV reactor with monitoring sensor and wiper mechanism.",
        },
        {
            "id": 4,
            "name": "Effluent Treatment Plant (ETP)",
            "description": "Biological and chemical wastewater treatment system with clarification and filtration.",
        },
    ]
    await db["machine_types"].insert_many(machine_types)

    # ───────────── 3. Checklists (Items & Options) ─────────────
    log.info("Seeding checklists...")
    # Global option ID counter for embedded options
    opt_id = 1

    check_items = [
        # RO System Checks (type_id = 1)
        {
            "id": 1,
            "machine_type_id": 1,
            "category": CheckCategory.operation.value,
            "label": "Inlet Feed Pressure & Differential Pressure (ΔP)",
            "description": "Inspect cartridge and membrane pressure gauges.",
            "input_type": InputType.radio.value,
            "is_required": True,
            "sort_order": 1,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 1, "label": "Normal (ΔP < 15 psi)", "sort_order": 1, "is_active": True},
                {"id": 2, "label": "Elevated ΔP (15-25 psi - Schedule Filter Wash)", "sort_order": 2, "is_active": True},
                {"id": 3, "label": "Critical (> 25 psi - Immediate Replacement)", "sort_order": 3, "is_active": True},
            ],
        },
        {
            "id": 2,
            "machine_type_id": 1,
            "category": CheckCategory.operation.value,
            "label": "Permeate Water Conductivity (TDS)",
            "description": "Sample collected from product port.",
            "input_type": InputType.radio.value,
            "is_required": True,
            "sort_order": 2,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 4, "label": "< 20 µS/cm (Optimal rejection > 98%)", "sort_order": 1, "is_active": True},
                {"id": 5, "label": "20 - 50 µS/cm (Acceptable)", "sort_order": 2, "is_active": True},
                {"id": 6, "label": "> 50 µS/cm (High salinity - Membrane check needed)", "sort_order": 3, "is_active": True},
            ],
        },
        {
            "id": 3,
            "machine_type_id": 1,
            "category": CheckCategory.maintenance.value,
            "label": "Pre-treatment Cartridge Filter Condition",
            "description": "5-micron sediment filter checks.",
            "input_type": InputType.checkbox.value,
            "is_required": False,
            "sort_order": 1,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 7, "label": "Filter element inspected and clean", "sort_order": 1, "is_active": True},
                {"id": 8, "label": "Housing O-ring lubricated and sealed", "sort_order": 2, "is_active": True},
                {"id": 9, "label": "Air bleed valve purged", "sort_order": 3, "is_active": True},
            ],
        },
        {
            "id": 4,
            "machine_type_id": 1,
            "category": CheckCategory.maintenance.value,
            "label": "Antiscalant Chemical Dosing Level",
            "description": "Inspect dosing tank volume and metering pump operation.",
            "input_type": InputType.radio.value,
            "is_required": True,
            "sort_order": 2,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 10, "label": "Tank Level > 50%", "sort_order": 1, "is_active": True},
                {"id": 11, "label": "Tank Level 25 - 50% (Refill Soon)", "sort_order": 2, "is_active": True},
                {"id": 12, "label": "Tank Level < 25% (Refill Required)", "sort_order": 3, "is_active": True},
            ],
        },
        # Water Softener Checks (type_id = 2)
        {
            "id": 5,
            "machine_type_id": 2,
            "category": CheckCategory.operation.value,
            "label": "Treated Water Hardness Test (Titration / Strips)",
            "description": "Measure effluent hardness post-resin tank.",
            "input_type": InputType.radio.value,
            "is_required": True,
            "sort_order": 1,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 13, "label": "< 5 ppm CaCO3 (Soft - OK)", "sort_order": 1, "is_active": True},
                {"id": 14, "label": "5 - 15 ppm CaCO3 (Moderate hardness)", "sort_order": 2, "is_active": True},
                {"id": 15, "label": "> 15 ppm CaCO3 (Hardness breakthrough - Regenerate)", "sort_order": 3, "is_active": True},
            ],
        },
        {
            "id": 6,
            "machine_type_id": 2,
            "category": CheckCategory.maintenance.value,
            "label": "Brine Tank Salt Level & Condition",
            "description": "Check solar salt inventory and look for salt bridges.",
            "input_type": InputType.radio.value,
            "is_required": True,
            "sort_order": 1,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 16, "label": "Salt level above water mark (> 50%)", "sort_order": 1, "is_active": True},
                {"id": 17, "label": "Salt low (< 25% - Add bags)", "sort_order": 2, "is_active": True},
                {"id": 18, "label": "Salt bridge formed (Broken & dissolved)", "sort_order": 3, "is_active": True},
            ],
        },
        # UV Disinfection Checks (type_id = 3)
        {
            "id": 7,
            "machine_type_id": 3,
            "category": CheckCategory.operation.value,
            "label": "UV Lamp Intensity Sensor Status",
            "description": "Sensor display on ballast controller panel.",
            "input_type": InputType.radio.value,
            "is_required": True,
            "sort_order": 1,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 19, "label": "Intensity > 85% (Optimal germicidal dose)", "sort_order": 1, "is_active": True},
                {"id": 20, "label": "Intensity 70 - 85% (Warning - Plan quartz cleaning)", "sort_order": 2, "is_active": True},
                {"id": 21, "label": "Intensity < 70% (Alarm - Replace lamp / clean)", "sort_order": 3, "is_active": True},
            ],
        },
        {
            "id": 8,
            "machine_type_id": 3,
            "category": CheckCategory.maintenance.value,
            "label": "Quartz Sleeve Wiper & Seal Integrity",
            "description": "Verify wiper strokes and check for moisture in end caps.",
            "input_type": InputType.checkbox.value,
            "is_required": False,
            "sort_order": 1,
            "is_active": True,
            "created_at": now - 25 * one_day,
            "options": [
                {"id": 22, "label": "Wiper cycle executed smoothly", "sort_order": 1, "is_active": True},
                {"id": 23, "label": "No moisture inside quartz chamber seals", "sort_order": 2, "is_active": True},
                {"id": 24, "label": "Ballast cooling fan working properly", "sort_order": 3, "is_active": True},
            ],
        },
    ]
    await db["check_items"].insert_many(check_items)

    # ───────────── 4. Plants ─────────────
    log.info("Seeding plants...")
    plants = [
        {
            "id": 1,
            "name": "Reverse Osmosis Treatment Plant",
            "code": "PLT-RO-01",
            "location": "Main Water Facility",
            "description": "Primary high-recovery RO membrane skid and backup line for process water.",
            "is_active": True,
            "created_at": now - 365 * one_day,
        },
        {
            "id": 2,
            "name": "Water Softening & Utility Plant",
            "code": "PLT-SFT-02",
            "location": "Utility Wing",
            "description": "Dual-tank automatic water softener for hardness and scale control.",
            "is_active": True,
            "created_at": now - 300 * one_day,
        },
        {
            "id": 3,
            "name": "UV Disinfection Plant",
            "code": "PLT-UV-03",
            "location": "Cleanroom Facility",
            "description": "Inline germicidal UV reactor with lamp intensity and sleeve monitors.",
            "is_active": True,
            "created_at": now - 120 * one_day,
        },
        {
            "id": 4,
            "name": "Effluent Treatment Plant (ETP)",
            "code": "PLT-ETP-04",
            "location": "South Industrial Yard",
            "description": "Biological and chemical wastewater treatment system with clarification and filtration.",
            "is_active": True,
            "created_at": now - 500 * one_day,
        },
    ]
    await db["plants"].insert_many(plants)

    # ───────────── 5. Machines ─────────────
    log.info("Seeding machines...")
    machines = [
        {
            "id": 1,
            "plant_id": 1,
            "machine_type_id": 1,
            "name": "RO Line A (Primary 50 GPM)",
            "serial_number": "RO-SKID-50G-001",
            "location": "Main Water Facility - Bay 1",
            "installed_on": (now - 365 * one_day).strftime("%Y-%m-%d"),
            "is_active": True,
            "created_at": now - 365 * one_day,
        },
        {
            "id": 2,
            "plant_id": 1,
            "machine_type_id": 1,
            "name": "RO Line B (Backup 25 GPM)",
            "serial_number": "RO-SKID-25G-002",
            "location": "Main Water Facility - Bay 2",
            "installed_on": (now - 200 * one_day).strftime("%Y-%m-%d"),
            "is_active": True,
            "created_at": now - 200 * one_day,
        },
        {
            "id": 3,
            "plant_id": 2,
            "machine_type_id": 2,
            "name": "Boiler Feed Water Softener (Twin Tank)",
            "serial_number": "WS-TWIN-2023-018",
            "location": "Utility Wing - Boiler Skid",
            "installed_on": (now - 300 * one_day).strftime("%Y-%m-%d"),
            "is_active": True,
            "created_at": now - 300 * one_day,
        },
        {
            "id": 4,
            "plant_id": 2,
            "machine_type_id": 2,
            "name": "Cooling Tower Make-Up Softener",
            "serial_number": "WS-CT-2024-044",
            "location": "Utility Wing - North Tower",
            "installed_on": (now - 90 * one_day).strftime("%Y-%m-%d"),
            "is_active": True,
            "created_at": now - 90 * one_day,
        },
        {
            "id": 5,
            "plant_id": 3,
            "machine_type_id": 3,
            "name": "Distribution Loop UV Purifier",
            "serial_number": "UV-REACTOR-400W-009",
            "location": "Cleanroom Facility - Mezzanine Loop",
            "installed_on": (now - 120 * one_day).strftime("%Y-%m-%d"),
            "is_active": True,
            "created_at": now - 120 * one_day,
        },
        {
            "id": 6,
            "plant_id": 4,
            "machine_type_id": 4,
            "name": "Effluent Clarifier Skid #1",
            "serial_number": "ETP-CLAR-500K-001",
            "location": "South Industrial Yard - Station A",
            "installed_on": (now - 500 * one_day).strftime("%Y-%m-%d"),
            "is_active": True,
            "created_at": now - 500 * one_day,
        },
    ]
    await db["machines"].insert_many(machines)

    # ───────────── 5. Inspections & Answers ─────────────
    log.info("Seeding inspections and checkups...")
    inspections = [
        {
            "id": 1,
            "machine_id": 1,
            "performed_by": 2,  # John Doe
            "performed_at": now - 3 * one_day,
            "summary": "Routine weekly operational and maintenance inspection. System operating within design specs.",
            "answers": [
                {
                    "check_item_id": 1,
                    "check_item_label": "Inlet Feed Pressure & Differential Pressure (ΔP)",
                    "category": CheckCategory.operation.value,
                    "input_type": InputType.radio.value,
                    "options": [
                        {"option_id": 1, "option_label": "Normal (ΔP < 15 psi)", "is_checked": True},
                        {"option_id": 2, "option_label": "Elevated ΔP (15-25 psi - Schedule Filter Wash)", "is_checked": False},
                        {"option_id": 3, "option_label": "Critical (> 25 psi - Immediate Replacement)", "is_checked": False},
                    ],
                },
                {
                    "check_item_id": 2,
                    "check_item_label": "Permeate Water Conductivity (TDS)",
                    "category": CheckCategory.operation.value,
                    "input_type": InputType.radio.value,
                    "options": [
                        {"option_id": 4, "option_label": "< 20 µS/cm (Optimal rejection > 98%)", "is_checked": True},
                        {"option_id": 5, "option_label": "20 - 50 µS/cm (Acceptable)", "is_checked": False},
                        {"option_id": 6, "option_label": "> 50 µS/cm (High salinity - Membrane check needed)", "is_checked": False},
                    ],
                },
                {
                    "check_item_id": 3,
                    "check_item_label": "Pre-treatment Cartridge Filter Condition",
                    "category": CheckCategory.maintenance.value,
                    "input_type": InputType.checkbox.value,
                    "options": [
                        {"option_id": 7, "option_label": "Filter element inspected and clean", "is_checked": True},
                        {"option_id": 8, "option_label": "Housing O-ring lubricated and sealed", "is_checked": True},
                        {"option_id": 9, "option_label": "Air bleed valve purged", "is_checked": True},
                    ],
                },
                {
                    "check_item_id": 4,
                    "check_item_label": "Antiscalant Chemical Dosing Level",
                    "category": CheckCategory.maintenance.value,
                    "input_type": InputType.radio.value,
                    "options": [
                        {"option_id": 10, "option_label": "Tank Level > 50%", "is_checked": True},
                        {"option_id": 11, "option_label": "Tank Level 25 - 50% (Refill Soon)", "is_checked": False},
                        {"option_id": 12, "option_label": "Tank Level < 25% (Refill Required)", "is_checked": False},
                    ],
                },
            ],
        },
        {
            "id": 2,
            "machine_id": 3,
            "performed_by": 3,  # Sarah Connor
            "performed_at": now - 1 * one_day,
            "summary": "Hardness tested at 2 ppm. Added coarse solar salt to brine tank.",
            "answers": [
                {
                    "check_item_id": 5,
                    "check_item_label": "Treated Water Hardness Test (Titration / Strips)",
                    "category": CheckCategory.operation.value,
                    "input_type": InputType.radio.value,
                    "options": [
                        {"option_id": 13, "option_label": "< 5 ppm CaCO3 (Soft - OK)", "is_checked": True},
                        {"option_id": 14, "option_label": "5 - 15 ppm CaCO3 (Moderate hardness)", "is_checked": False},
                        {"option_id": 15, "option_label": "> 15 ppm CaCO3 (Hardness breakthrough - Regenerate)", "is_checked": False},
                    ],
                },
                {
                    "check_item_id": 6,
                    "check_item_label": "Brine Tank Salt Level & Condition",
                    "category": CheckCategory.maintenance.value,
                    "input_type": InputType.radio.value,
                    "options": [
                        {"option_id": 16, "option_label": "Salt level above water mark (> 50%)", "is_checked": False},
                        {"option_id": 17, "option_label": "Salt low (< 25% - Add bags)", "is_checked": True},
                        {"option_id": 18, "option_label": "Salt bridge formed (Broken & dissolved)", "is_checked": False},
                    ],
                },
            ],
        },
        {
            "id": 3,
            "machine_id": 5,
            "performed_by": 2,  # John Doe
            "performed_at": now - 4 * one_day,
            "summary": "UV intensity normal at 92%. Automatic quartz wiper tested cleanly.",
            "answers": [
                {
                    "check_item_id": 7,
                    "check_item_label": "UV Lamp Intensity Sensor Status",
                    "category": CheckCategory.operation.value,
                    "input_type": InputType.radio.value,
                    "options": [
                        {"option_id": 19, "option_label": "Intensity > 85% (Optimal germicidal dose)", "is_checked": True},
                        {"option_id": 20, "option_label": "Intensity 70 - 85% (Warning - Plan quartz cleaning)", "is_checked": False},
                        {"option_id": 21, "option_label": "Intensity < 70% (Alarm - Replace lamp / clean)", "is_checked": False},
                    ],
                },
                {
                    "check_item_id": 8,
                    "check_item_label": "Quartz Sleeve Wiper & Seal Integrity",
                    "category": CheckCategory.maintenance.value,
                    "input_type": InputType.checkbox.value,
                    "options": [
                        {"option_id": 22, "option_label": "Wiper cycle executed smoothly", "is_checked": True},
                        {"option_id": 23, "option_label": "No moisture inside quartz chamber seals", "is_checked": True},
                        {"option_id": 24, "option_label": "Ballast cooling fan working properly", "is_checked": True},
                    ],
                },
            ],
        },
    ]
    await db["inspections"].insert_many(inspections)

    # ───────────── 6. Notes ─────────────
    log.info("Seeding machine notes...")
    notes = [
        {
            "id": 1,
            "machine_id": 1,
            "inspection_id": 1,
            "author_id": 2,
            "body": "Replaced 5-micron pre-filter cartridge during scheduled shift maintenance. Feed ΔP returned to 8 psi.",
            "created_at": now - 3 * one_day,
            "updated_at": now - 3 * one_day,
        },
        {
            "id": 2,
            "machine_id": 3,
            "inspection_id": 2,
            "author_id": 3,
            "body": "Added 200 kg coarse solar salt to brine tank. Tested hardness post-regen at 2 ppm.",
            "created_at": now - 1 * one_day,
            "updated_at": now - 1 * one_day,
        },
        {
            "id": 3,
            "machine_id": 5,
            "inspection_id": 3,
            "author_id": 2,
            "body": "Lamp run hours currently at 4,120 hrs. Recommended replacement at 9,000 hrs (est. Nov 2026).",
            "created_at": now - 4 * one_day,
            "updated_at": now - 4 * one_day,
        },
        {
            "id": 4,
            "machine_id": 2,
            "inspection_id": None,
            "author_id": 1,
            "body": "RO Line B is in standby mode. Valve manifold isolated and nitrogen-purged.",
            "created_at": now - 10 * one_day,
            "updated_at": now - 10 * one_day,
        },
    ]
    await db["notes"].insert_many(notes)

    # ───────────── 7. Synchronize Counters ─────────────
    log.info("Synchronizing sequence counters...")
    counters = [
        {"_id": "user_id", "seq": 3},
        {"_id": "plant_id", "seq": 4},
        {"_id": "machine_type_id", "seq": 4},
        {"_id": "check_item_id", "seq": 8},
        {"_id": "option_id", "seq": 24},
        {"_id": "machine_id", "seq": 6},
        {"_id": "inspection_id", "seq": 3},
        {"_id": "note_id", "seq": 4},
    ]
    for c in counters:
        await db["counters"].update_one({"_id": c["_id"]}, {"$set": {"seq": c["seq"]}}, upsert=True)

    log.info("==========================================")
    log.info("Demo data seeding completed successfully!")
    log.info("==========================================")
    log.info("Admin login: %s / %s", settings.first_admin_email, settings.first_admin_password)
    log.info("Tech login:  john.tech@watercare.local / ChangeMe123!")
    log.info("Operator:    sarah.operator@watercare.local / ChangeMe123!")
    log.info("Machines:    6 machines across 4 machine types")
    log.info("Checkups:    3 inspections with detailed answer histories")
    log.info("Notes:       4 operational notes")

    client.close()


def main():
    parser = argparse.ArgumentParser(description="Seed WaterCare MongoDB Atlas database with demo data.")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop existing collections before seeding (recommended for a clean demo state)",
    )
    args = parser.parse_args()
    asyncio.run(seed(drop=args.drop))


if __name__ == "__main__":
    main()
