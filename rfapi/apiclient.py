# Copyright 2016,2017 Recorded Future, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Client library for the Recorded Future API."""
import copy
import logging
import requests
import sys
import platform
import requests.auth

# pylint: disable=redefined-builtin
from future.utils import raise_from
from requests.adapters import HTTPAdapter

from .auth import RFTokenAuth

from .query import JSONQueryResponse, \
    CSVQueryResponse, \
    BaseQueryResponse

from .error import JsonParseError, \
    MissingAuthError, \
    AuthenticationError, \
    HttpError

from . import APP_ID
# Get from tuple with index for 2.6.x compatibility
if sys.version_info[0] > 2:
    from past.builtins import basestring

LOG = logging.getLogger(__name__)

# connection and read timeouts in seconds
DEFAULT_TIMEOUT = (10, 120)

# number of retries for read timeouts
DEFAULT_RETRIES = 3

# authentication method
DEFAULT_AUTH = 'auto'

REQUESTS_POOL_MAXSIZE = 16


class BaseApiClient(object):
    """Internal class with common base methods
    for raw and connect api clients"""

    def __init__(self,
                 auth,
                 url,
                 proxies=None,
                 timeout=DEFAULT_TIMEOUT,
                 app_name=None,
                 app_version=None,
                 pkg_name=None,
                 pkg_version=None,
                 accept_gzip=True,
                 platform_id=None,
                 api_version=1,
                 verify=True):
        self._url = url
        self._proxies = proxies
        self._timeout = timeout
        self._accept_gzip = accept_gzip
        self.verify = verify

        if app_name is None:
            raise ValueError("Parameter app_name required to make calls to RecordedFuture!")

        if app_version is None:
            app_version = "1.0.0"

        if platform_id is None:
            platform_id = platform.platform()

        if pkg_name is None:
            pkg_name = ""

        if pkg_version is None:
            pkg_version = ""

        pkg_info = ""
        if pkg_name is not None or pkg_version is not None:
            pkg_name = pkg_name or "package"
            pkg_version = pkg_version or "1.0.0"
            pkg_info = "{pkg_name}/{pkg_ver}".format(pkg_name=pkg_name, pkg_ver=pkg_version)

        # User Agent Fix required by
        # https://support.recordedfuture.com/hc/en-us/articles/360003936573-Adding-a-User-Agent-request-header-to-help-track-API-Calls
        self._app_id = "{name}+{ver} ({platform}) {pkg_info}".format(
            name=app_name,
            ver=app_version,
            platform=platform_id,
            pkg_info=pkg_info
        )

        self._request_session = requests.Session()
        adapter = HTTPAdapter(
            pool_maxsize=REQUESTS_POOL_MAXSIZE,
            pool_block=True
        )
        self._request_session.mount('http://', adapter)
        self._request_session.mount('https://', adapter)

        # set auth method if any. we defer checking auth method until querying
        self._auth = None
        if isinstance(auth, requests.auth.AuthBase):
            self._auth = auth
        elif isinstance(auth, basestring):
            self._auth = RFTokenAuth(auth, api_version)

    def _check_auth(self):
        if not self._auth:
            raise MissingAuthError()

    @staticmethod
    def _raise_http_error(response, req_http_err):
        try:
            ct = response.headers.get('content-type')
            if ct is not None and 'application/json' in ct:
                resp = response.json()
                error_msg = resp.get('error')
                if response.status_code == 401:
                    auth_err = AuthenticationError(error_msg, response)
                    raise_from(auth_err, req_http_err)
                elif error_msg is not None:
                    http_err = HttpError(error_msg, response)
                    raise_from(http_err, req_http_err)
        except ValueError:
            pass

        raise req_http_err

    def _prepare_params(self, params):
        if params is None:
            params = {}
        else:
            params = copy.deepcopy(params)

        # Add info about app and library to request.
        params['app_id'] = self._app_id
        return params

    def _prepare_headers(self):
        headers = {
            'X-RF-USER-Agent': self._app_id
        }

        if not self._accept_gzip:
            headers['Accept-Encoding'] = ''
        return headers

    def _parse_json_response(self, response):
        try:
            resp = response.json()
        except ValueError as err:
            errc = JsonParseError(str(err), response)
            raise_from(errc, err)

        self._validate_json_response(resp)
        return resp

    def _validate_json_response(self, resp):
        pass

    @staticmethod
    def _make_json_response(resp, response):
        return JSONQueryResponse(resp, response)

    def _make_response(self, expect_json, response):
        if expect_json:
            resp = self._parse_json_response(response)
            return self._make_json_response(resp, response)
        else:
            if 'csv' in response.headers.get('content-type', ''):
                return CSVQueryResponse(response.text, response)
            else:
                return BaseQueryResponse(response.text, response)
