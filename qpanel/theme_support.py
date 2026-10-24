"""Small Flask-native replacement for the unmaintained Flask-Themes package."""
import os
from flask import abort, g, render_template, send_from_directory, url_for
from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader


def setup_themes(app, app_identifier=None):
    roots = {name: os.path.join(app.root_path, 'themes', name) for name in ('qpanel', 'old')}
    loaders = {'qpanel': FileSystemLoader(os.path.join(roots['qpanel'], 'templates')),
               'old': app.jinja_loader}
    app.jinja_loader = ChoiceLoader([app.jinja_loader, PrefixLoader(loaders)])

    @app.route('/_themes/<theme_name>/<path:filename>')
    def theme_assets(theme_name, filename):
        if theme_name not in roots:
            abort(404)
        return send_from_directory(os.path.join(roots[theme_name], 'static'), filename)

    @app.context_processor
    def helpers():
        current = getattr(g, 'active_theme', 'qpanel')
        return dict(theme=lambda template: current + '/' + template,
                    theme_static=lambda filename: url_for('theme_assets', theme_name=current, filename=filename))


def render_theme_template(theme, template, **context):
    if theme not in ('qpanel', 'old'):
        theme = 'qpanel'
    g.active_theme = theme
    return render_template(theme + '/' + template, **context)
