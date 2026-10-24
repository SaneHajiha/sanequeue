# -*- coding: utf-8 -*-

#
# Copyright (C) 2015-2022 Rodrigo Ramírez Norambuena <a@rodrigoramirez.com>
#

import re
import requests
from packaging.version import Version as LooseVersion
import qpanel


BRANCH = 'master'
REPO = 'https://github.com/SaneHajiha/sanequeue.git'
URL_STABLE_VERSION = 'https://raw.githubusercontent.com/SaneHajiha/sanequeue/' + BRANCH + '/VERSION'


def require_upgrade():
    return check_require_upgrade(get_current_version(), get_stable_version())


def check_require_upgrade(current, stable):
    if not stable or not re.match(r'^\d+(?:\.\d+){1,3}$', stable):
        return False
    a = LooseVersion(current)
    b = LooseVersion(stable)
    if a < b:
        return True
    return False


# InmplementME
def last_check_update():
    return True


def get_current_version():
    return qpanel.__version__


def get_stable_version(url=URL_STABLE_VERSION):
    stable_version = __first_line(__get_data_url(url))
    if isinstance(stable_version, str):
        stable_version = stable_version.strip()
        if re.match(r'^\d+(?:\.\d+){1,3}$', stable_version):
            return stable_version
    return None


def __get_data_url(url):
    try:
        req = requests.get(url, timeout=(3, 5))
        req.raise_for_status()
        return req.text
    except requests.RequestException:
        return None


def __first_line(content):
    tmp = ''
    if content is not None:
        tmp = content.splitlines()
    if len(tmp) >= 1:
        return tmp[0]
    return tmp
