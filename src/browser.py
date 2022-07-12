import android.activity
from contextlib import closing
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
import os

logger = logging.getLogger(__name__)

Activity = autoclass('android.app.Activity')
Document = autoclass('android.provider.DocumentsContract$Document')
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
        self.preferences = self.activity.getSharedPreferences(
            self.activity.getLocalClassName(), Activity.MODE_PRIVATE
        )

        android.activity.bind(on_activity_result=self.on_activity_result)

    def get_default_tree_uri(self):
        uri = self.preferences.getString('tree_uri', None)
        logger.info('Found default tree URI %s', uri)
        return uri

    def set_default_tree_uri(self, uri):
        uri = uri.toString()
        editor = self.preferences.edit()
        logger.info('Setting default tree URI to %s', uri)
        editor.putString('tree_uri', uri)
        editor.commit()

    def on_activity_result(self, request, result, intent):
        if request == self.OPEN_DIRECTORY_REQUEST_CODE:
            logger.info('Got result %d for open directory request', result)
            if result != Activity.RESULT_OK or intent is None:
                return

            uri = intent.getData()
            tree_id = DocumentsContract.getTreeDocumentId(uri)
            logger.info('User chose directory "%s" (%s)',
                        uri.toString(), tree_id)
            self.set_default_tree_uri(uri)

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

    def file_opener(self, path, flags):
        # Convert from open flags to Java File modes.
        #
        # https://developer.android.com/reference/android/os/ParcelFileDescriptor#parseMode(java.lang.String)
        logger.debug('Requested opening %s with flags %s', path, bin(flags))
        if flags & os.O_RDWR:
            mode = 'rw'
        elif flags & os.O_WRONLY:
            mode = 'w'
        else:
            mode = 'r'

        if flags & os.O_APPEND:
            mode += 'a'
        if flags & os.O_TRUNC:
            mode += 't'

        uri = Uri.parse(path)
        afd = self.content_resolver.openAssetFileDescriptor(uri, mode)
        pfd = afd.getParcelFileDescriptor()
        return pfd.detachFd()

    def open_file(self, uri, mode='r', **kwargs):
        if isinstance(uri, Uri):
            uri = uri.toString()
        kwargs['opener'] = self.file_opener
        return open(uri, mode, **kwargs)

    def get_tree(self, uri):
        if isinstance(uri, str):
            uri = Uri.parse(uri)
        return DocumentFile.fromTreeUri(self.activity, uri)

    def get_file(self, uri):
        if isinstance(uri, str):
            uri = Uri.parse(uri)
        return DocumentFile.fromSingleUri(self.activity, uri)

    def list_files(self, tree_doc_uri):
        tree_doc_id = DocumentsContract.getDocumentId(tree_doc_uri)
        children_uri = DocumentsContract.buildChildDocumentsUriUsingTree(
            tree_doc_uri, tree_doc_id
        )

        columns = [
            Document.COLUMN_DISPLAY_NAME,
            Document.COLUMN_DOCUMENT_ID,
            Document.COLUMN_LAST_MODIFIED,
            Document.COLUMN_MIME_TYPE,
            Document.COLUMN_SIZE,
        ]
        results = []
        with closing(
            self.content_resolver.query(children_uri, columns, None, None)
        ) as cursor:
            while cursor.moveToNext():
                entry = {
                    'name': cursor.getString(0),
                    'id': cursor.getString(1),
                    'last_modified': cursor.getLong(2),
                    'mime_type': cursor.getString(3),
                    'size': cursor.getLong(4),
                }
                doc_uri = DocumentsContract.buildDocumentUriUsingTree(
                    tree_doc_uri, entry['id']
                )
                entry['uri'] = doc_uri.toString()
                results.append(entry)

        return results


app = Browser(__name__)
app.config['SERVER_NAME'] = '127.0.0.1:5000'


@app.route('/')
def index():
    uri = request.args.get('uri')
    if not uri:
        uri = current_app.get_default_tree_uri()

    if uri:
        logger.info('Rendering tree URI %s', uri)
        tree_doc_uri = current_app.get_tree(uri).getUri()
        directories = []
        files = []
        for doc in current_app.list_files(tree_doc_uri):
            if doc['mime_type'] == Document.MIME_TYPE_DIR:
                directories.append({
                    'name': doc['name'],
                    'uri': doc['uri'],
                })
            else:
                # Document.COLUMN_LAST_MODIFIED returns milliseconds
                # since the epoch.
                last_modified = datetime.fromtimestamp(
                    doc['last_modified'] / 1000
                )
                files.append({
                    'name': doc['name'],
                    'uri': doc['uri'],
                    'last_modified': last_modified,
                    'size': doc['size'],
                })

        name = DocumentsContract.getDocumentId(tree_doc_uri)
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
        with current_app.open_file(uri, 'rb') as f:
            text = f.read()
        return (text, 200)

    return ('Cannot view file', 415)
