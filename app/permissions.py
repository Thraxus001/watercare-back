import enum


class Permission(str, enum.Enum):
    """Permission codes an admin can grant to a regular user.
    Admins implicitly have all of them, plus user management."""
    PLANTS_VIEW = "plants:view"
    PLANTS_MANAGE = "plants:manage"
    MACHINES_VIEW = "machines:view"
    MACHINES_MANAGE = "machines:manage"
    CHECKLISTS_VIEW = "checklists:view"
    CHECKLISTS_MANAGE = "checklists:manage"
    INSPECTIONS_VIEW = "inspections:view"
    INSPECTIONS_CREATE = "inspections:create"
    INSPECTIONS_DELETE = "inspections:delete"
    NOTES_VIEW = "notes:view"
    NOTES_CREATE = "notes:create"


PERMISSION_DESCRIPTIONS = {
    Permission.PLANTS_VIEW: "See plants, locations, and their machines",
    Permission.PLANTS_MANAGE: "Add, edit and deactivate plants",
    Permission.MACHINES_VIEW: "See machines and their latest checkup status",
    Permission.MACHINES_MANAGE: "Add, edit and deactivate machines",
    Permission.CHECKLISTS_VIEW: "See the checklist defined for each machine type",
    Permission.CHECKLISTS_MANAGE: "Create and edit machine types and checklist items",
    Permission.INSPECTIONS_VIEW: "View submitted checkups and what was done",
    Permission.INSPECTIONS_CREATE: "Perform and submit checkups",
    Permission.INSPECTIONS_DELETE: "Delete submitted checkups",
    Permission.NOTES_VIEW: "Read notes on machines",
    Permission.NOTES_CREATE: "Write notes on machines",
}
