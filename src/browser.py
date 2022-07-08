from flask import (
    Flask,
    render_template,
)


class Browser(Flask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


app = Browser(__name__)


@app.route('/')
def index():
    return render_template(
        'index.html',
    )
