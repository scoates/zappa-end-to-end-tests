import pytest
import os
from distutils.dir_util import copy_tree
from virtualenv import create_environment
import logging
import sys
import socket
import hashlib
from jinja2 import Template
from zappa_e2e import PreservableTemporaryDirectory, DeployedZappaApp, venv_cmd, chdir, ENV_CONFIG


DIR = os.path.realpath(os.path.dirname(__file__))
APPS_PREFIX = os.path.join(DIR, "apps")
logger = logging.getLogger()

ZAPPA_S3_BUCKET = os.environ.get('ZAPPA_S3_BUCKET', "zappa-e2e-" + str(hashlib.md5(socket.gethostname().encode()).hexdigest()))
logger.debug("Zappa E2E: using s3 bucket " + ZAPPA_S3_BUCKET)


def _path_to_app(path):
    str_path = str(path)
    if str_path.startswith(APPS_PREFIX):
        apps_path = str_path[len(APPS_PREFIX)+1:]
        return apps_path.split('/', 1)
    return None, None


def pytest_collect_file(parent, path):
    app_name, sub_path = _path_to_app(path)
    if sub_path == 'zappa_settings.json.j2':
        return ZappaAppFile(path, parent)


class ZappaAppFile(pytest.File):
    def __init__(self, name, parent=None, config=None, session=None, nodeid=None):
        super(ZappaAppFile, self).__init__(name, parent, config, session, nodeid=nodeid)

        app_name, sub_path = _path_to_app(name)
        self.app_name = app_name
        self.app_path = os.path.join(APPS_PREFIX, app_name)

    def collect(self):
        yield ZappaAppTest(self.app_name, self)


class ZappaAppTest(pytest.Item):
    def __init__(self, name, parent):
        super(ZappaAppTest, self).__init__(name, parent)
        self.app_name = parent.app_name
        self.app_path = parent.app_path


    def _venv_cmd(self, cmd, params, as_json=False, check=False):
        return venv_cmd(self.venv_dir, cmd, params, as_json, check)


    def runtest(self):

        with PreservableTemporaryDirectory(self.app_name) as (app_tmp_dir, ptd):
            self.app_test_dir = os.path.join(app_tmp_dir, self.app_name)
            copy_tree(self.app_path, self.app_test_dir)
            chdir(self.app_test_dir)

            self.venv_dir = os.path.join(app_tmp_dir, 'venv')
            requirements_txt_path = os.path.join(self.app_test_dir, 'requirements.txt')

            if not os.path.isdir(self.venv_dir):
                create_environment(self.venv_dir)

            ret, _, _ = self._venv_cmd('pip', ['install', '-r', 'requirements.txt'], check=True)

            template_file = os.path.join(self.app_test_dir, "zappa_settings.json.j2")
            with open(template_file) as f:
                template_source = f.read()

            template = Template(template_source)
            rendered_template = template.render(
                ZAPPA_S3_BUCKET=ZAPPA_S3_BUCKET
            )

            settings_file = os.path.join(self.app_test_dir, "zappa_settings.json")
            with open(settings_file, 'w') as zsj:
                zsj.write(rendered_template)
                logger.debug("Zappa E2E: wrote settings file {} from template {}".format(
                    settings_file, template_file
                ))

            with DeployedZappaApp(self.app_test_dir, self.venv_dir, ptd) as zappa_app:

                # undeployed handled in DeployedZappaApp
                if not ENV_CONFIG['undeploy_only']:

                    ret, status, _ = self._venv_cmd('zappa', ['status'], as_json=True)
                    assert ret == 0, "Got Zappa app status"
