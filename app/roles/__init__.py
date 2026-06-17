"""Role registry. Each agent is one Role object (config + tool pack); the kernel
runs them all. Add a new agent by writing ``roles/<name>.py`` and registering it
here — never by forking the codebase.

When WhatsApp routing by phone_number_id lands, the webhook will map a number to
a role name and look it up here; until then the admin role is the default.
"""
from . import admin, seo

ROLES = {
    admin.ROLE.name: admin.ROLE,
    seo.ROLE.name: seo.ROLE,
}


def get(name: str):
    """Return the named role, falling back to admin."""
    return ROLES.get(name, admin.ROLE)
