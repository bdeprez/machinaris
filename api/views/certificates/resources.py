import datetime
import json
import os
import re
import shutil
import time
import traceback

from flask import request, Response, abort
from flask.views import MethodView

from api import app
from api.extensions.api import Blueprint

from api.commands import chia_cli, plotman_cli

blp = Blueprint(
    'Certificates',
    __name__,
    url_prefix='/certificates',
    description="Certificates to perform"
)


@blp.route('/')
class Certificates(MethodView):

    def get(self):
        if not self.allow_download():
            abort(401)
        blockchain = request.args.get('type')
        dir = "/root/.{0}/mainnet/config/ssl/ca".format(blockchain)
        zip = "/tmp/certs".format(blockchain)
        zipname = "{0}.zip".format(zip)
        try:
            os.remove(zipname)
        except:
            pass
        shutil.make_archive(zip, 'zip', dir)
        with open(zipname, 'rb') as f:
            data = f.readlines()
            os.remove(zipname)
        return Response(data, headers={
            'Content-Type': 'application/zip',
            'Content-Disposition': 'attachment; filename=certs.zip;'
        })

    def allow_download(self):
        worker_setup_marker = "/root/.chia/machinaris/tmp/worker_launch.tmp"
        if os.path.exists(worker_setup_marker):
            last_modified_date = datetime.datetime.fromtimestamp(os.path.getmtime(worker_setup_marker))
            fifteen_minutes_ago = datetime.datetime.now() - datetime.timedelta(minutes=15)
            return last_modified_date >= fifteen_minutes_ago
        return False