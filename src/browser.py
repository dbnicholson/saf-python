import android.activity
from datetime import datetime
from flask import (
    Flask,
    current_app,
    render_template,
    request,
    url_for,
)
from jnius import autoclass
import logging

logger = logging.getLogger(__name__)

Activity = autoclass('android.app.Activity')
DocumentFile = autoclass('androidx.documentfile.provider.DocumentFile')
DocumentsContract = autoclass('android.provider.DocumentsContract')
Intent = autoclass('android.content.Intent')
PythonActivity = autoclass('org.kivy.android.PythonActivity')
Uri = autoclass('android.net.Uri')


class Browser(Flask):
    OPEN_DIRECTORY_REQUEST_CODE = 0xf11e

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.activity = PythonActivity.mActivity
        self.content_resolver = self.activity.getContentResolver()

        android.activity.bind(on_activity_result=self.on_activity_result)

    def on_activity_result(self, request, result, intent):
        if request == self.OPEN_DIRECTORY_REQUEST_CODE:
            logger.info('Got result %d for open directory request', result)
            if result != Activity.RESULT_OK or intent is None:
                return

            uri = intent.getData()
            tree_id = DocumentsContract.getTreeDocumentId(uri)
            logger.info('User chose directory "%s" (%s)',
                        uri.toString(), tree_id)

            logger.info('Persisting read permissions for "%s"', uri.toString())
            flags = intent.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION
            self.content_resolver.takePersistableUriPermission(uri, flags)

            with self.app_context():
                url = url_for('index', uri=uri.toString())
            self.activity.loadUrl(url)

    def open_directory(self):
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
        self.activity.startActivityForResult(
            intent,
            self.OPEN_DIRECTORY_REQUEST_CODE,
        )

    def get_tree(self, uri):
        if isinstance(uri, str):
            uri = Uri.parse(uri)
        return DocumentFile.fromTreeUri(self.activity, uri)


app = Browser(__name__)
app.config['SERVER_NAME'] = '127.0.0.1:5000'


@app.route('/')
def index():
    uri = request.args.get('uri')
    if uri:
        logger.info('Rendering tree URI %s', uri)
        tree = current_app.get_tree(uri)
        directories = []
        files = []
        for doc in tree.listFiles():
            if doc.isDirectory():
                directories.append({
                    'name': doc.getName(),
                    'uri': doc.getUri().toString(),
                })
            else:
                # DocumentFile.lastModified() returns milliseconds since
                # the epoch.
                last_modified = datetime.fromtimestamp(
                    doc.lastModified() / 1000
                )
                files.append({
                    'name': doc.getName(),
                    'uri': doc.getUri().toString(),
                    'last_modified': last_modified,
                    'size': doc.length(),
                })

        name = DocumentsContract.getDocumentId(tree.getUri())
        content = {
            'name': name,
            'directories': directories,
            'files': files,
        }
    else:
        content = {}

    return render_template(
        'index.html',
        content=content,
    )


@app.route('/open')
def open_directory():
    current_app.open_directory()
    return ('', 204)
