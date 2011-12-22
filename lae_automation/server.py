"""
-- The EC2Admin public keys, corresponding to the EC2Admin private keys they specify will live on the web server.  
-- These are transferred to the new EC2 instance in /home/customer/.ssh, and /home/ubuntu/.ssh
"""

from cStringIO import StringIO
import simplejson

from fabric import api
from fabric.context_managers import cd


TAHOE_CFG_TEMPLATE = """# -*- mode: conf; coding: utf-8 -*-

# This file controls the configuration of the Tahoe node that
# lives in this directory. It is only read at node startup.
# For details about the keys that can be set here, please
# read the 'docs/configuration.rst' file that came with your
# Tahoe installation.


[node]
nickname = %(nickname)s
web.port =
web.static = public_html
tub.location = %(public_host)s:12346,%(private_host)s:12346

[client]
# Which services should this client connect to?
introducer.furl = %(introducer_furl)s
helper.furl =

[storage]
# Shall this node provide storage service?
enabled = true
backend = s3
s3.access_key_id = %(access_key_id)s
s3.bucket = %(bucket_name)s

[helper]
# Shall this node run a helper service that clients can use?
enabled = false

[drop_upload]
# Shall this node automatically upload files created or modified in a local directory?
enabled = false
upload.dircap =
local.directory =
"""

class NotListeningError(Exception):
    pass


# The default 'pty=True' behaviour is unsafe because, when we are invoked via flapp,
# we don't want the flapp client to be able to influence the ssh remote command's stdin.
# pty=False will cause fabric to echo stdin, but that's fine.

def run(argstring, **kwargs):
    return api.run(argstring, pty=False, **kwargs)

def sudo(argstring, **kwargs):
    return api.sudo(argstring, pty=False, **kwargs)

def set_host_and_key(public_host, key_filename, username="ubuntu"):
    api.env.host_string = '%s@%s' % (username, public_host)
    api.env.reject_unknown_hosts = False  # FIXME allows MITM attacks
    api.env.key_filename = key_filename
    api.env.abort_on_prompts = True

    try:
        whoami = run('whoami')
    except SystemExit:
        # fabric stupidly aborts if the host is not listening for ssh connections
        # zooko: and this is why SystemExit needs to be catchable ;-)
        raise NotListeningError()
    assert whoami.strip() == username, (whoami, username)

def sudo_apt_get(argstring):
    sudo('apt-get %s' % argstring)

def sudo_easy_install(argstring):
    sudo('easy_install %s' % argstring)

def write(remote_path, value, mode=None):
    return api.put(StringIO(value), remote_path, mode=mode)


def delete_customer(public_host, key_filename):
    set_host_and_key(public_host, key_filename)

    sudo('deluser customer')
    sudo('rm -rf /home/customer*')


def install_server(public_host, key_filename, stdout, stderr):
    set_host_and_key(public_host, key_filename)

    print >>stdout, "Updating server..."
    sudo_apt_get('update')
    sudo_apt_get('upgrade -y')
    sudo_apt_get('install -y linux-ec2 linux-image-ec2')

    print >>stdout, "Rebooting server..."
    api.reboot(60)

    print >>stdout, "Installing dependencies..."
    sudo_apt_get('install -y python-dev')
    sudo_apt_get('install -y python-setuptools')
    sudo_apt_get('install -y exim4-base')
    sudo_apt_get('install -y darcs')
    sudo_easy_install('foolscap')
    run('wget https://leastauthority.com/static/patches/txAWS-0.2.1.post2.tar.gz')
    run('tar -xzvf txAWS-0.2.1.post2.tar.gz')
    with cd('/home/ubuntu/txAWS-0.2.1.post2'):
        sudo('python ./setup.py install')

    print >>stdout, "Setting up customer account..."
    sudo('adduser --disabled-password --gecos "" customer || echo Assuming that user already exists.')
    sudo('mkdir -p /home/customer/.ssh/')
    sudo('chown customer:customer /home/customer/.ssh')
    sudo('cp /home/ubuntu/.ssh/authorized_keys /home/customer/.ssh/authorized_keys')
    sudo('chown customer:customer /home/customer/.ssh/authorized_keys')
    sudo('chmod 400 /home/customer/.ssh/authorized_keys')
    sudo('chmod 700 /home/customer/.ssh/')

    set_host_and_key(public_host, key_filename, username="customer")

    print >>stdout, "Getting Tahoe-LAFS..."
    run('rm -rf /home/customer/LAFS_source')
    run('darcs get --lazy https://tahoe-lafs.org/source/tahoe/ticket999-S3-backend LAFS_source')

    print >>stdout, "Building Tahoe-LAFS..."
    with cd('/home/customer/LAFS_source'):
        run('python ./setup.py build')

    print >>stdout, "Creating introducer and storage server..."
    run('mkdir -p introducer storageserver')
    run('LAFS_source/bin/tahoe create-introducer introducer || echo Assuming that introducer already exists.')
    run('LAFS_source/bin/tahoe create-node storageserver || echo Assuming that storage server already exists.')

    print >>stdout, "Finished server installation."


INTRODUCER_PORT = '12345'
SERVER_PORT = '12346'

def bounce_server(public_host, key_filename, private_host, creds, user_token, product_token, bucket_name,
                  stdout, stderr, secretsfile):
    access_key_id = creds.access_key
    secret_key = creds.secret_key
    nickname = bucket_name

    set_host_and_key(public_host, key_filename, username="customer")

    print >>stdout, "Starting introducer..."
    run('rm -f /home/customer/introducer/introducer.furl')
    write('/home/customer/introducer/introducer.port', INTRODUCER_PORT + '\n')
    write('/home/customer/storageserver/client.port', SERVER_PORT + '\n')
    run('LAFS_source/bin/tahoe restart introducer && sleep 5')
    internal_introducer_furl = run('cat /home/customer/introducer/introducer.furl').strip()
    assert '\n' not in internal_introducer_furl, internal_introducer_furl

    tahoe_cfg = TAHOE_CFG_TEMPLATE % {'nickname': nickname,
                                      'public_host': public_host,
                                      'private_host': private_host,
                                      'introducer_furl': internal_introducer_furl,
                                      'access_key_id': access_key_id,
                                      'bucket_name': bucket_name}
    write('/home/customer/storageserver/tahoe.cfg', tahoe_cfg)
    run('chmod u+w /home/customer/storageserver/private/s3* || echo Assuming there are no existing s3 secret files.')
    write('/home/customer/storageserver/private/s3secret', secret_key, mode=0440)
    write('/home/customer/storageserver/private/s3usertoken', user_token, mode=0440)
    write('/home/customer/storageserver/private/s3producttoken', product_token, mode=0440)

    print >>stdout, "Starting storage server..."
    run('LAFS_source/bin/tahoe restart storageserver && sleep 5')
    run('ps -fC tahoe')
    run('netstat -atW')

    introducer_node_pem = run('cat /home/customer/introducer/private/node.pem')
    introducer_nodeid   = run('cat /home/customer/introducer/my_nodeid')
    server_node_pem     = run('cat /home/customer/storageserver/private/node.pem')
    server_nodeid       = run('cat /home/customer/storageserver/my_nodeid')

    print >>stdout, "The introducer and storage server are running."

    (prefix, atsign, suffix) = internal_introducer_furl.partition('@')
    assert atsign, internal_introducer_furl
    (location, slash, swissnum) = suffix.partition('/')
    assert slash, internal_introducer_furl
    external_introducer_furl = "%s@%s:%s/%s" % (prefix, public_host, INTRODUCER_PORT, swissnum)

    # The webserver will HTML-escape the FURL in its output, so no need to escape here.
    print >>stdout, """
The settings for your gateway's tahoe.cfg are:

[client]
introducer.furl = %s

shares.needed = 1
shares.happy = 1
shares.total = 1

[storage]
enabled = false

""" % (external_introducer_furl,)

    print >>secretsfile, simplejson.dumps({
        'public_host':              public_host,
        'private_host':             private_host,
        'access_key_id':            access_key_id,
        'secret_key':               secret_key,
        'user_token':               user_token,
        'product_token':            product_token,
        'bucket_name':              bucket_name,
        'introducer_node_pem':      introducer_node_pem,
        'introducer_nodeid':        introducer_nodeid,
        'server_node_pem':          server_node_pem,
        'server_nodeid':            server_nodeid,
        'internal_introducer_furl': internal_introducer_furl,
        'external_introducer_furl': external_introducer_furl,
    })
    secretsfile.flush()

    return external_introducer_furl
