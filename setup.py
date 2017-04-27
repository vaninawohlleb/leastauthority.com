from setuptools import find_packages, setup

setup(
    name="leastauthority.com",
    zip_safe=False,
    packages=find_packages(),
    py_modules=["twisted.plugins.lae_dropin"],
    include_package_data=True,
    dependency_links=[
        "https://tahoe-lafs.org/deps/",
    ],
    install_requires=[
        "python-dateutil",
        "stripe==1.41.1",
        "pem==16.1.0",
        "foolscap",
        "Fabric",
        "filepath",
        "jinja2",
        "mock",
        "pyOpenSSL",
        "simplejson",
        "twisted!=17.1.0",
        "service_identity",
        "attrs",
        "eliot==0.12.0",

        "txAWS==0.3.0",

        # If we had a dev extra ourselves, the [dev] part of this would
        # probably be better placed there.
        "txkube[dev]==0.1.0",

        # For the test suite.
        "hypothesis==3.6.0",
        "testtools==2.2.0",
        "fixtures==3.0.0",
        "deepdiff==3.1.2",

        # So we can generate tahoe configuration parameters.
        "tahoe-lafs==1.11.0",
    ],
)