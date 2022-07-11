import android.activity
from datetime import datetime
from flask import (
    Flask,
    current_app,
    render_template,
    request,
    url_for,
)
from jnius import autoclass, JavaException
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

    def view_file(self, uri):
        if isinstance(uri, str):
            uri = Uri.parse(uri)
        intent = Intent(Intent.ACTION_VIEW, uri)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try:
            self.activity.startActivity(intent)
            return True
        except JavaException as err:
            if err.classname == 'android.content.ActivityNotFoundException':
                return False
            raise

    def read_file(self, uri):
        if isinstance(uri, str):
            uri = Uri.parse(uri)
        stream = self.content_resolver.openInputStream(uri)
        content = bytearray()
        while True:
            buf = bytearray(8192)
            num = stream.read(buf)
            if num == -1:
                break
            content += buf[:num]
        return content

    def get_tree(self, uri):
        if isinstance(uri, str):
            uri = Uri.parse(uri)
        return DocumentFile.fromTreeUri(self.activity, uri)

    def get_file(self, uri):
        if isinstance(uri, str):
            uri = Uri.parse(uri)
        return DocumentFile.fromSingleUri(self.activity, uri)


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


@app.route('/view')
def view_file():
    uri = request.args.get('uri')
    if uri is None:
        return ('No uri argument specified', 400)

    doc_uri = Uri.parse(uri)
    if current_app.view_file(doc_uri):
        return ('', 204)

    doc = current_app.get_file(doc_uri)
    doc_type = doc.getType()
    text_doc_types = (
        'application/json',
        'text/plain',
    )
    logger.info('Document %s MIME: %s', uri, doc_type)
    if doc_type in text_doc_types:
        text = current_app.read_file(doc_uri).decode('utf-8')
        return (text, 200)

    return ('Cannot view file', 415)
