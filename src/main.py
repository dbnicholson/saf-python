from browser import app
import logging


logging.basicConfig(level=logging.DEBUG)
logging.getLogger('jnius').setLevel(logging.INFO)
app.run(debug=False)
