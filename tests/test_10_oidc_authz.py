import json
import os

import pytest
from cryptojwt.key_jar import build_keyjar
from oidcendpoint.authz import AuthzHandling
from oidcendpoint.authz import Implicit
from oidcendpoint.authz import factory
from oidcendpoint.cookie import CookieDealer
from oidcendpoint.cookie import new_cookie
from oidcendpoint.endpoint_context import EndpointContext
from oidcendpoint.oidc import userinfo
from oidcendpoint.oidc.authorization import Authorization
from oidcendpoint.oidc.provider_config import ProviderConfiguration
from oidcendpoint.oidc.registration import Registration
from oidcendpoint.oidc.session import Session
from oidcendpoint.oidc.token import AccessToken
from oidcendpoint.user_authn.authn_context import INTERNETPROTOCOLPASSWORD
from oidcendpoint.user_info import UserInfo

ISS = "https://example.com/"

KEYDEFS = [
    {"type": "RSA", "use": ["sig"]},
    {"type": "EC", "crv": "P-256", "use": ["sig"]},
]

KEYJAR = build_keyjar(KEYDEFS)
KEYJAR.import_jwks(KEYJAR.export_jwks(private=True, issuer=""), issuer=ISS)

RESPONSE_TYPES_SUPPORTED = [
    ["code"],
    ["token"],
    ["id_token"],
    ["code", "token"],
    ["code", "id_token"],
    ["id_token", "token"],
    ["code", "id_token", "token"],
    ["none"],
]

CAPABILITIES = {
    "response_types_supported": [" ".join(x) for x in RESPONSE_TYPES_SUPPORTED],
    "token_endpoint_auth_methods_supported": [
        "client_secret_post",
        "client_secret_basic",
        "client_secret_jwt",
        "private_key_jwt",
    ],
    "response_modes_supported": ["query", "fragment", "form_post"],
    "subject_types_supported": ["public", "pairwise"],
    "grant_types_supported": [
        "authorization_code",
        "implicit",
        "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "refresh_token",
    ],
    "claim_types_supported": ["normal", "aggregated", "distributed"],
    "claims_parameter_supported": True,
    "request_parameter_supported": True,
    "request_uri_parameter_supported": True,
}

BASEDIR = os.path.abspath(os.path.dirname(__file__))


def full_path(local_file):
    return os.path.join(BASEDIR, local_file)


USERINFO_db = json.loads(open(full_path("users.json")).read())


class TestAuthz(object):
    @pytest.fixture(autouse=True)
    def create_ec(self):
        conf = {
            "issuer": ISS,
            "password": "mycket hemlig zebra",
            "token_expires_in": 600,
            "grant_expires_in": 300,
            "refresh_token_expires_in": 86400,
            "verify_ssl": False,
            "capabilities": CAPABILITIES,
            "jwks": {"uri_path": "jwks.json", "key_defs": KEYDEFS},
            "endpoint": {
                "provider_config": {
                    "path": "{}/.well-known/openid-configuration",
                    "class": ProviderConfiguration,
                    "kwargs": {"client_authn_method": None},
                },
                "registration": {
                    "path": "{}/registration",
                    "class": Registration,
                    "kwargs": {"client_authn_method": None},
                },
                "authorization": {
                    "path": "{}/authorization",
                    "class": Authorization,
                    "kwargs": {"client_authn_method": None},
                },
                "token": {"path": "{}/token", "class": AccessToken, "kwargs": {}},
                "userinfo": {
                    "path": "{}/userinfo",
                    "class": userinfo.UserInfo,
                    "kwargs": {"db_file": "users.json"},
                },
                "session": {
                    "path": "{}/end_session",
                    "class": Session,
                    "kwargs": {
                        "signing_alg": "ES256",
                        "logout_verify_url": "{}/verify_logout".format(ISS),
                    },
                },
            },
            "authentication": {
                "anon": {
                    "acr": INTERNETPROTOCOLPASSWORD,
                    "class": "oidcendpoint.user_authn.user.NoAuthn",
                    "kwargs": {"user": "diana"},
                }
            },
            "userinfo": {"class": UserInfo, "kwargs": {"db": USERINFO_db}},
            "template_dir": "template",
            "authz": {"class": AuthzHandling, "kwargs": {}},
            "cookie_dealer": {
                "class": CookieDealer,
                "kwargs": {
                    "sign_key": "ghsNKDDLshZTPn974nOsIGhedULrsqnsGoBFBLwUKuJhE2ch",
                    "default_values": {
                        "name": "oidcop",
                        "domain": "127.0.0.1",
                        "path": "/",
                        "max_age": 3600,
                    },
                },
            },
        }

        self.endpoint_context = EndpointContext(conf, keyjar=KEYJAR)

    def _create_cookie(self, user, sid, state, client_id, typ="sso", name=""):
        ec = self.endpoint_context
        if not name:
            name = ec.cookie_name["session"]
        return new_cookie(
            ec,
            sub=user,
            sid=sid,
            state=state,
            client_id=client_id,
            typ=typ,
            cookie_name=name,
        )

    def test_init_authz(self):
        authz = AuthzHandling(self.endpoint_context)
        assert authz

    def test_authz_set_get(self):
        authz = self.endpoint_context.authz
        authz.set("diana", "client_1", ["email", "phone"])
        assert authz.get("diana", "client_1") == ["email", "phone"]

    def test_authz_cookie(self):
        authz = self.endpoint_context.authz
        authz.set("diana", "client_1", ["email", "phone"])
        cookie = self._create_cookie("diana", "_sid_", "1234567", "client_1")
        perm = authz.permissions(cookie)
        assert set(perm) == {"email", "phone"}

    def test_authz_cookie_wrong_client(self):
        authz = self.endpoint_context.authz
        authz.set("diana", "client_1", ["email", "phone"])
        cookie = self._create_cookie("diana", "_sid_", "1234567", "client_2")
        perm = authz.permissions(cookie)
        assert perm is None

    def tests_implicit(self):
        authz = Implicit(self.endpoint_context, "any")
        perm = authz.get("foo", "bar")
        assert perm == "any"

    def test_factory_implicit(self):
        authz = factory("Implicit", self.endpoint_context, permission="all")
        assert authz.get("foo", "bar") == "all"

    def test_factory_authz_handling(self):
        authz = factory("AuthzHandling", self.endpoint_context)
        authz.set("diana", "client_1", ["email", "phone"])
        assert authz.get("diana", "client_1") == ["email", "phone"]

    def test_authz_cookie_none(self):
        authz = self.endpoint_context.authz
        authz.set("diana", "client_1", ["email", "phone"])
        assert authz.permissions(None) is None

    def test_authz_cookie_other(self):
        authz = self.endpoint_context.authz
        authz.set("diana", "client_1", ["email", "phone"])
        cookie = self._create_cookie(
            "diana", "_sid_", "1234567", "client_1", name="foo"
        )
        assert authz.permissions(cookie) is None
