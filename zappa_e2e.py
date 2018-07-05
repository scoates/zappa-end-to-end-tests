import subprocess
import tempfile
import logging
import os
import json
import sys


logger = logging.getLogger()


class PreservableTemporaryDirectory(tempfile.TemporaryDirectory):

    def preserve(self):
        self._preserve = True
        self._finalizer.detach()


    @property
    def preserved(self):
        return self._preserve


    def __enter__(self):
        self._preserve = False
        return self.name, self


    def __exit__(self, exc, value, tb):
        logger.debug("Exiting PreservableTemporaryDirectory {} with preserve={}".format(
            self.name, "True" if self._preserve else "False"
        ))
        if not self._preserve:
            self.cleanup()


class DeployedZappaApp:
    def __init__(self, app_dir, venv_dir, ptd, stage="test"):
        self.skip_cleanup = False
        self.app_dir = app_dir
        self.venv_dir = venv_dir
        self.ptd = ptd
        self.failed = False
        self.stage = stage
        self.post_deploy_status = {}


    @property
    def status(self):
        """ example:
{
    "Lambda Versions": 2,
    "Lambda Name": "hello-world-test",
    "Lambda ARN": "arn:aws:lambda:us-east-1:REDACTED:function:hello-world-test",
    "Lambda Role ARN": "arn:aws:iam::REDACTED:role/hello-world-test-ZappaLambdaExecutionRole",
    "Lambda Handler": "handler.lambda_handler",
    "Lambda Code Size": 19346351,
    "Lambda Version": "$LATEST",
    "Lambda Last Modified": "2018-07-05T00:26:52.796+0000",
    "Lambda Memory Size": 512,
    "Lambda Timeout": 30,
    "Lambda Runtime": "python3.6",
    "Lambda VPC ID": null,
    "Invocations (24h)": 7,
    "Errors (24h)": 0,
    "Error Rate (24h)": "0.00%",
    "API Gateway URL": "https://REDACTED.execute-api.us-east-1.amazonaws.com/test",
    "Domain URL": "None Supplied",
    "Num. Event Rules": 1,
    "Events": [
        {
            "Event Rule Name": "hello-world-test-zappa-keep-warm-handler.keep_warm_callback",
            "Event Rule Schedule": "rate(4 minutes)",
            "Event Rule State": "Enabled",
            "Event Rule ARN": "arn:aws:events:us-east-1:REDACTED:rule/hello-world-test-zappa-keep-warm-handler.keep_warm_callback"
        }
    ]
}
        """
        return self.post_deploy_status


    @property
    def name(self):
        return self.post_deploy_status.get('Lambda Name', '(no name)')


    def __repr__(self):
        return "<{} {!r}>".format(self.__class__.__name__, self.name)


    def __enter__(self):
        os.chdir(self.app_dir)
        ret, _, _ = venv_cmd(self.venv_dir, 'zappa', ['status'])
        if ret != 1:
            logger.error("{}: Status succeeded before deploy. This probably means that the app is already deployed. Bailing.".format(
                self.__class__.__name__
            ))
            self.skip_cleanup = True
            return None

        ret, out, _ = venv_cmd(self.venv_dir, 'zappa', ['deploy', self.stage])
        if ret != 0:
            logger.error("{}: failed to deploy with message '{}'. Bailing.".format(
                self.__class__.__name__, out
            ))
            self.skip_cleanup = True
            return None

        ret, out, _ = venv_cmd(self.venv_dir, 'zappa', ['status', self.stage], as_json=True)
        if ret != 0:
            logger.error("{}: something went wrong with the post-deploy status check.".format(
                self.__class__.__name__
            ))
            self.failed = True
            return None

        self.post_deploy_status = out
        logger.info("{}: zappa app {}:{} deployed.".format(
            self.__class__.__name__, self.name, self.stage
        ))

        return self.name


    def __exit__(self, exc, value, tb):
        self.cleanup()


    def _preserve_and_fail(self, msg):
        self.failed = True
        self.ptd.preserve()
        logger.error("{}: failing with message '{}'. App directory preserved at: {}".format(
            self.__class__.__name__, msg, self.ptd.name
        ))


    def cleanup(self):
        if self.skip_cleanup:
            logger.warn("{}: Skipping cleanup for {} in {}".format(
                self.__class__.__name__, self.name, self.app_dir
            ))
            if self.failed:
                self._preserve_and_fail("Failed before cleanup.")
        else:
            logger.debug("{}: Cleaning up for {} in {}".format(
                self.__class__.__name__, self.name, self.app_dir
            ))
            if self.failed:
                self._preserve_and_fail("Failed before cleanup.")
            else:
                os.chdir(self.app_dir)
                ret, out, err = venv_cmd(self.venv_dir, 'zappa', ['undeploy', '-y', self.stage])
                if ret == 0:
                    ret, out, _ = venv_cmd(self.venv_dir, 'zappa', ['status'])
                    if ret != 1:
                        self._preserve_and_fail("Zappa status should have returned 1. Returned {}. With output: {}".format(
                            ret, out
                        ))

                else:
                    self._preserve_and_fail("Could not undeploy")
                    logger.error("{}: Zappa failed to undeploy.\nstderr={}\nstdout={}".format(
                        self.__class__.__name__, err, out
                    ))

            if self.failed:
                sys.exit(1)


def venv_cmd(venv_dir, cmd, params, as_json=False, check=False):
    args = [os.path.join(venv_dir, 'bin', cmd)]
    args.extend(params)
    if as_json:
        args.append('--json')
    logger.debug("Calling '{}'".format(" ".join(args)))
    cmd = subprocess.run(args, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if as_json:
        return cmd.returncode, json.loads(cmd.stdout), cmd
    else:
        return cmd.returncode, cmd.stdout, cmd
