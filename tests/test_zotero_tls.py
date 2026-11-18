import io
import ssl
from unittest.mock import patch

from koi.literature.zotero import _request_json


def test_zotero_loads_trusted_ca_when_system_store_is_empty():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    assert not context.get_ca_certs()

    def open_request(request, *, timeout, context):
        assert context.get_ca_certs()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        response = io.BytesIO(b'{"ok": true}')
        response.headers = {}
        return response

    with (
        patch("koi.literature.zotero.ssl.create_default_context", return_value=context),
        patch("koi.literature.zotero.urllib.request.urlopen", side_effect=open_request),
    ):
        payload, headers = _request_json("/test", api_key="test-key")
    assert payload == {"ok": True}
    assert headers == {}
