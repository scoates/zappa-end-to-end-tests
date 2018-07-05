import pytest
import os
import shutil
from virtualenv import create_environment
import logging


from zappa_e2e import PreservableTemporaryDirectory, DeployedZappaApp, venv_cmd


DIR = os.path.realpath(os.path.dirname(__file__))
APPS_PREFIX = os.path.join(DIR, "apps")
logger = logging.getLogger()

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

        with PreservableTemporaryDirectory() as (app_tmp_dir, ptd):
            self.app_test_dir = os.path.join(app_tmp_dir, self.app_name)
            shutil.copytree(self.app_path, self.app_test_dir)
            os.chdir(self.app_test_dir)

            self.venv_dir = os.path.join(app_tmp_dir, 'venv')
            create_environment(self.venv_dir)

            if os.path.isfile(os.path.join(self.app_test_dir, 'requirements.txt')):
                ret, _, _ = self._venv_cmd('pip', ['install', '-r', 'requirements.txt'], check=True)

            with DeployedZappaApp(self.app_test_dir, self.venv_dir, ptd):

                ret, status, _ = self._venv_cmd('zappa', ['status'], as_json=True)
                assert ret == 0, "Got Zappa app status"

                print(status)

            # # always do this
            # ret, _, _ = self._venv_cmd('zappa', ['undeploy', '-y'])
            # assert ret == 0, "Zappa app successfully undeployed"

