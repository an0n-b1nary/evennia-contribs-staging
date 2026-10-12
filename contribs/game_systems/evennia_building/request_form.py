"""Settings-safe form definition; no Django model or registry imports."""

FORM_KEY = "building_interior"
FORM = {
    "owner": "evennia_building",
    "label": "Interior proposal",
    "description": "Review the exact immutable snapshot on the Building submission page.",
    "questions": [
        {"key": "snapshot", "label": "Snapshot fingerprint", "type": "text"},
        {"key": "summary", "label": "Proposal", "type": "longtext"},
        {"key": "link", "label": "Building submission page", "type": "text"},
    ],
}
