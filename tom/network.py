from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode
from json import dumps, loads


class Response:

    def __init__(self):
        self.status_code = 0
        self.headers = {}
        self.text = ""

    def json(self):
        return loads(self.text)


def _handle_request(
    url, data=None, headers={}, base64auth=None, method=None, json=None
):
    """
    Handle a request with urllib

    Args:
        url: The url of the request
        data: The data to send in the body of the request.
        headers: A dictionary of HTTP headers to send with the request.
        base64auth: A Base64-encoded string for HTTP Basic Authentication.
        method: The HTTP method to use (e.g., 'GET', 'POST', 'PUT')
        json: A JSON-serializable Python object to send in the body of the request. Overrides `data`
    """

    encoded_data = dumps(data).encode("utf-8") if data is not None else None

    if json is not None:
        encoded_data = dumps(json).encode("utf-8")
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

    elif data is not None:
        if isinstance(data, dict):
            encoded_data = urlencode(data).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif isinstance(data, bytes):
            encoded_data = data
        else:
            encoded_data = str(data).encode("utf-8")

    req = Request(url, data=encoded_data, headers=headers, method=method)
    if base64auth:
        req.add_header("Authorization", "Basic %s" % base64auth)

    result = Response()

    try:
        with urlopen(req) as r:
            result.text = r.read().decode("utf-8")
            result.status_code = r.code
            result.headers = r.headers
    except HTTPError as e:
        result.status_code = e.code
        result.text = e.read().decode("utf-8")
        result.headers = e.headers

    return result


def post(url, data=None, json=None, headers={}, auth=None):
    return _handle_request(
        url, data=data, headers=headers, base64auth=auth, method="POST", json=json
    )


def get(url, headers={}, auth=None):
    return _handle_request(
        url, data=None, headers=headers, base64auth=auth, method="GET"
    )


def head(url, headers={}, auth=None):
    return _handle_request(
        url, data=None, headers=headers, base64auth=auth, method="HEAD"
    )
