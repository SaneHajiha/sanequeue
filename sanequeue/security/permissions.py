"""Role ceilings, optional per-user sections, and independent queue grants."""
SECTIONS = frozenset(('live','queues','calls','waiting','agents','presence','pbx','features','control','wallboard','alerts','audit','settings','users','policies','shifts','directory','telephony'))
ROLE_SECTIONS = {
    'admin':SECTIONS,
    'supervisor':SECTIONS-{'settings','users','policies','pbx','telephony'},
    'agent':SECTIONS-{'settings','users','policies','pbx','control','audit','telephony'},
    'viewer':SECTIONS-{'settings','users','policies','pbx','control','audit','shifts','telephony'},
}
ROLE_ACTIONS = {
    'admin':frozenset(('view','pause','membership','monitor','hangup','priority','caller_details','transfer','park','pickup','dial')),
    'supervisor':frozenset(('view','pause','membership','monitor','hangup','priority','caller_details','transfer','park','pickup','dial')),
    'agent':frozenset(('view','pause','dial')),
    'viewer':frozenset(('view',)),
}


def validate_sections(role, sections):
    if sections is None:return None
    if not isinstance(sections,list) or len(sections)>len(SECTIONS) or any(not isinstance(s,str) or s not in ROLE_SECTIONS.get(role,()) for s in sections):
        raise ValueError('invalid_menu_permissions')
    return sorted(set(sections))


def sections_for(role, account=None):
    ceiling=ROLE_SECTIONS.get(role,frozenset())
    selected=(account or {}).get('menus')
    return ceiling if selected is None else ceiling & set(selected)
