# Copyright Least Authority Enterprises.
# See LICENSE for details.

from base64 import b32encode
from json import loads

import attr

from hypothesis import given, assume

from testtools.matchers import Equals, AfterPreprocessing

from twisted.python.filepath import FilePath
from twisted.python.url import URL
from twisted.internet.defer import succeed
from twisted.internet.task import Clock

from foolscap.furl import decode_furl

from lae_util.testtools import TestCase
from lae_util.fileutil import make_dirs
from lae_automation import model, signup
from lae_automation.signup import (
    get_provisioner,
    get_wormhole_signup,
    get_email_signup,
)

from lae_automation.subscription_manager import broken_client
from lae_automation.test.strategies import (
    port_numbers, emails, old_secrets, subscription_details,
    customer_id, subscription_id,
)

from .wormholetesting import MemoryWormholeServer

# Vector data for the config file data:
from lae_automation.test.test_vectors import MOCKJSONCONFIGFILE
CONFIGFILEJSON = MOCKJSONCONFIGFILE

ZEROPRODUCT = {
  "ec2_access_key_id":    "TESTEC2EC2EC2EC2EC2E",
  "ec2_secret_path":      "mock_ec2_secret",
  "s3_access_key_id":     u"TESTS3S3S3S3S3S3S3S3",
  "s3_secret_path":       "mock_s3_secret",
}

MOCKEC2SECRETCONTENTS = 'EC2'*13+'E'
MOCKS3SECRETCONTENTS = u'S3' * 20
MONITORPUBKEY = 'MONITOR PUBLIC KEY'


class TestSignupModule(TestCase):
    def setUp(self):
        super(TestSignupModule, self).setUp()
        self.mockconfigdir = FilePath('./test_signup').child('TestSignupModule')
        make_dirs(self.mockconfigdir.path)
        self.SIGNUPSPATH = 'mock_signups.csv'
        self.CONFIGFILEPATH = 'init_test_config.json'
        self.EC2SECRETPATH = 'mock_ec2_secret'
        self.S3SECRETPATH = 'mock_s3_secret'
        self.MONITORPUBKEYPATH = 'MONITORKEYS.pub'

        self.MEMAIL = 'MEMAIL'
        self.MKEYINFO = 'MKEYINFO'
        self.MCUSTOMER_ID = u'cus_x14Charactersx'
        self.MSUBSCRIPTION_ID = u'sub_x14Characterx'
        self.MPLAN_ID = 'XX_consumer_iteration_#_GREEKLETTER#_2XXX-XX-XX'
        self.MENCODED_IDS = 'on2wex3yge2eg2dbojqwg5dfoj4a-mn2xgx3yge2eg2dbojqwg5dfojzxq'

        FilePath(self.SIGNUPSPATH).setContent('')
        FilePath(self.CONFIGFILEPATH).setContent(CONFIGFILEJSON)
        FilePath(self.EC2SECRETPATH).setContent(MOCKEC2SECRETCONTENTS)
        FilePath(self.S3SECRETPATH).setContent(MOCKS3SECRETCONTENTS)
        FilePath(self.MONITORPUBKEYPATH).setContent(MONITORPUBKEY)

        self.DEPLOYMENT_CONFIGURATION = model.DeploymentConfiguration(
            domain=u"s4.example.com",
            kubernetes_namespace=u"testing",
            subscription_manager_endpoint=URL.fromText(u"http://localhost/"),
            s3_access_key_id=ZEROPRODUCT["s3_access_key_id"],
            s3_secret_key=MOCKS3SECRETCONTENTS,

            introducer_image=u"tahoe-introducer",
            storageserver_image=u"tahoe-storageserver",
        )
        self.SUBSCRIPTION = model.SubscriptionDetails(
            bucketname="lae-" + self.MENCODED_IDS,
            oldsecrets=old_secrets().example(),
            customer_email=self.MEMAIL,
            customer_pgpinfo=self.MKEYINFO,
            product_id=u"filler",
            customer_id=self.MCUSTOMER_ID,
            subscription_id=self.MSUBSCRIPTION_ID,
            introducer_port_number=12345,
            storage_port_number=12346,
        )

    def test_get_bucket_name(self):
        self.failUnlessEqual(b32encode("abc"), "MFRGG===")
        self.failUnlessEqual(b32encode("def"), "MRSWM===")
        self.failUnlessEqual(signup.get_bucket_name("abc", "def"), "lae-mfrgg-mrswm")



# New tests for signup.  Trying to keep a healthy distance from old
# test implementation.
class SignupTests(TestCase):
    def test_subscription_manager_not_listening(self):
        """
        If the subscription manager doesn't accept the new subscription,
        ``provision_subscription`` returns a ``Deferred`` that
        fails with the details.
        """
        details = subscription_details().example()
        d = signup.provision_subscription(
            broken_client(),
            details,
        )
        self.failureResultOf(d)



class ActivateTests(TestCase):
    @given(
        emails(), customer_id(), subscription_id(), old_secrets(),
        port_numbers(), port_numbers(),
    )
    def test_emailed_introducer_furl(
            self,
            customer_email,
            customer_id,
            subscription_id,
            old_secrets,
            introducer_port_number,
            storage_port_number,
    ):
        """
        The email signup mechanism sends an activation email including an
        introducer furl which points at the server and port identified by the
        activated subscription detail object.
        """
        assume(introducer_port_number != storage_port_number)

        emails = []

        def provision_subscription(
                smclient, subscription,
        ):
            return succeed(
                attr.assoc(
                    subscription,
                    introducer_port_number=introducer_port_number,
                    storage_port_number=storage_port_number,
                    oldsecrets=old_secrets,
                ),
            )

        def send_signup_confirmation(
                customer_email, external_introducer_furl, customer_keyinfo, stdout, stderr,
        ):
            emails.append((customer_email, "success", external_introducer_furl))
            return succeed(None)

        def send_notify_failure(
                reason, customer_email, logfilename, stdout, stderr,
        ):
            emails.append((customer_email, "failure", reason))
            return succeed(None)

        plan_identifier = u"foobar"

        reactor = object()
        signup = get_email_signup(
            reactor,
            get_provisioner(
                reactor,
                URL.fromText(u"http://subscription-manager/"),
                provision_subscription,
            ),
            send_signup_confirmation,
            send_notify_failure,
        )
        d = signup.signup(customer_email, customer_id, subscription_id, plan_identifier)
        self.successResultOf(d)

        [(recipient, result, rest)] = emails
        self.expectThat(recipient, Equals(customer_email))
        self.expectThat(result, Equals("success"))

        def get_hint_port(furl):
            tub_id, location_hints, name = decode_furl(furl)
            host, port = location_hints[0].split(u":")
            return int(port)

        self.expectThat(
            rest,
            AfterPreprocessing(
                get_hint_port,
                Equals(introducer_port_number),
            ),
        )


    @given(
        emails(), customer_id(), subscription_id(), old_secrets(),
        port_numbers(), port_numbers(),
    )
    def test_wormhole_tahoe_configuration(
            self,
            customer_email,
            customer_id,
            subscription_id,
            old_secrets,
            introducer_port_number,
            storage_port_number,
    ):
        """
        The wormhole signup mechanism sends a JSON blob of Tahoe-LAFS
        configuration via a magic wormhole identified by a wormhole code
        produced during signup.
        """
        assume(introducer_port_number != storage_port_number)

        provisioned = []
        def provision_subscription(
                smclient, subscription,
        ):
            p = attr.assoc(
                subscription,
                introducer_port_number=introducer_port_number,
                storage_port_number=storage_port_number,
                oldsecrets=old_secrets,
            )
            provisioned.append(p)
            return succeed(p)

        plan_identifier = u"foobar"
        reactor = Clock()
        server = MemoryWormholeServer()

        provisioner = get_provisioner(
            reactor,
            URL.fromText(u"http://subscription-manager/"),
            provision_subscription,
        )

        signup = get_wormhole_signup(
            reactor,
            provisioner,
            server,
            URL.fromText(u"ws://foo.invalid/"),
            FilePath(self.mktemp()),
        )
        d = signup.signup(customer_email, customer_id, subscription_id, plan_identifier)
        wormhole_claim = self.successResultOf(d)

        wh = server.create(
            u"tahoe-lafs.org/tahoe-lafs/v1",
            u"ws://foo.invalid/",
            reactor,
        )

        wh.set_code(wormhole_claim.code)
        d = wh.when_code()

        def foo(x):
            wh.send_message('{"abilities": {"client-v1": {}}}')
            return wh.get_message()
        d.addCallback(foo)

        def bar(arg):
            self.assertEqual(
                loads(arg),
                {"abilities": {"server-v1":{}}}
            )
            return wh.get_message()
        d.addCallback(bar)

        received = self.successResultOf(d)
        received_config = loads(received)
        self.assertThat(
            received_config["introducer"],
            Equals(provisioned[0].external_introducer_furl),
        )



class MemoryWormholeTests(TestCase):
    """
    Smoke test for the in-memory ``IWormhole`` implementation used by other
    application tests.
    """

    def test_send_receive(self):
        appid = "memory-wormhole-tests"
        url = "ws://foo.invalid/"
        reactor = object()
        to_send = u"Hello, world."

        server = MemoryWormholeServer()

        wh_a = server.create(appid, url, reactor)
        wh_b = server.create(appid, url, reactor)

        wh_a.allocate_code()
        code = self.successResultOf(wh_a.get_code())

        to_send = 'this is a message'
        wh_a.send_message(to_send)
        wh_b.set_code(code)

        received = self.successResultOf(wh_b.get_message())

        self.assertThat(received, Equals(to_send))
