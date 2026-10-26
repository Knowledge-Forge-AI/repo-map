"""Candidate-only AMD package observation from CI68; product defaults remain held."""

from types import MappingProxyType
from typing import Mapping

from .release import DebPackage, PlatformPackages
from .python_payload import AMD64_BASELINE_IMPORTS

D12_CANDIDATE_LIBPQ_VERSION = 180006
CI68_MANIFEST_SHA256 = '13f616f876ebc6e2ef6c9772e55e39426184944a15cce61ef2690187b2ef0273'

D12_CANDIDATE_PACKAGE_MANIFEST: Mapping[str, PlatformPackages] = MappingProxyType({
    "amd64": PlatformPackages(
        postgres_config_digest='sha256:066167ff39c2a612402ce99b734ea1cff92a9d1f2ac52f697a5f0384f0d88d6b',
        pgdg_source=(
            '/etc/apt/sources.list.d/pgdg.list',
            'c070ae8f9f72df1c4f03a4a4a04629b0546a9fa92be2620ebd92285722999805',
        ),
        pgdg_keyring=(
            '/usr/local/share/keyrings/postgres.gpg.asc',
            'ab3ea5fa18220d88318cd9e41d1e4e709c9003c71494f9022cbd76353ba7c5e1',
        ),
        key_fingerprints=('B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8',),
        libpq_path='/usr/lib/x86_64-linux-gnu/libpq.so.5.18',
        libpq_sha256='9cce9bfae9405a71e0d642457d9d8748093cea9fdc0f785b5d2ed9575aec168d',
        libpq5_version='18.6-1.pgdg13+2',
        builder=(
            DebPackage(
                'binutils', '2.44-3', 'amd64',
                '6bc08c02539ba53b5e748142397144c499f9b20b5fa9bb56431545db124addeb',
            ),
            DebPackage(
                'binutils-common', '2.44-3', 'amd64',
                '002da5d23f8757dee97a2c0a40e0e1d4d85a43da094488ee2ee7068d4d3691f9',
            ),
            DebPackage(
                'binutils-x86-64-linux-gnu', '2.44-3', 'amd64',
                'e6741ce95ff0f7a131c8d9faa3528ccbbc453078bbc62a97da81340ed7462c53',
            ),
            DebPackage(
                'cpp', '4:14.2.0-1', 'amd64',
                'a6ba40550aadec80437813e0fce5516574945ff40e72306a5b378c03af3a6544',
            ),
            DebPackage(
                'cpp-14', '14.2.0-19', 'amd64',
                '3bae5fe03c56c6d021900ab4fb79e35c6f75eee72a73fccc6f28a39db559d6a0',
            ),
            DebPackage(
                'cpp-14-x86-64-linux-gnu', '14.2.0-19', 'amd64',
                'ef274b5379f5f97fc71619d39ecc84d039d3e184570d207b909c90afaa5d79e0',
            ),
            DebPackage(
                'cpp-x86-64-linux-gnu', '4:14.2.0-1', 'amd64',
                'd902f484e38bce59e82efc0df2fe20139a0932ca759ecafdfe6e5b6c72238eb8',
            ),
            DebPackage(
                'gcc', '4:14.2.0-1', 'amd64',
                'eee65c41a441c57c05f754ced1b9d093956966a1c7da9938c3ec00d3dc2f905d',
            ),
            DebPackage(
                'gcc-14', '14.2.0-19', 'amd64',
                '21500408b5019d8d29f70ce58488e2eea469a1adb4b5fd7db45e819b5efcac4e',
            ),
            DebPackage(
                'gcc-14-x86-64-linux-gnu', '14.2.0-19', 'amd64',
                'a17ef039f1ba482051c3efb5c2c24070002e60dd0bd09fd456ec31481a11b725',
            ),
            DebPackage(
                'gcc-x86-64-linux-gnu', '4:14.2.0-1', 'amd64',
                '04c28c2760b0094b3d7758154ac095303dd00599b63ebad4086a325b607308b7',
            ),
            DebPackage(
                'libasan8', '14.2.0-19', 'amd64',
                '771899ade7310fe31aa538a509354c33d62bbe4e408b4e5fc1e513988dc42645',
            ),
            DebPackage(
                'libatomic1', '14.2.0-19', 'amd64',
                '212b399aae2f7299203d261a57e49372e09565a9a5ea971905f94a3960366c05',
            ),
            DebPackage(
                'libbinutils', '2.44-3', 'amd64',
                '4f4664c8a8f0ad0c8631c39fab02e3d8d86ccc6f4436a1d59f059dbcb0492679',
            ),
            DebPackage(
                'libc-dev-bin', '2.41-12+deb13u4', 'amd64',
                '2c21175d6a8283ed566d154c0c0bc06f60836e53b0b9e1f74c14eac586b68c24',
            ),
            DebPackage(
                'libc6-dev', '2.41-12+deb13u4', 'amd64',
                '1fda734dabcd80b77266a09ab62b0f1e3e16d8091db62899890b2200745632a2',
            ),
            DebPackage(
                'libcc1-0', '14.2.0-19', 'amd64',
                '2d587e3bfba4aec701946b7ba0c1640b97b6d8dd0a34ba1c70ae85261ecedefa',
            ),
            DebPackage(
                'libcom-err2', '1.47.2-3+b12', 'amd64',
                'bd43e020b8fed399db3eebf098111f10fba4c436fff99ccad72cc7e27c9764ec',
            ),
            DebPackage(
                'libcrypt-dev', '1:4.4.38-1', 'amd64',
                '98e2333aea8d64ca68f9b75c16256d3a05492fd8f9e6dba96adbc6f19e4f5a09',
            ),
            DebPackage(
                'libctf-nobfd0', '2.44-3', 'amd64',
                'e280b2be3db6e584500e865c251605b95c346767d87ccb2524e44992048fc657',
            ),
            DebPackage(
                'libctf0', '2.44-3', 'amd64',
                '120cafcd93132a276fa92a8fb4cf39b23d14e5a3e348f4f5580638d71ca95ac5',
            ),
            DebPackage(
                'libgcc-14-dev', '14.2.0-19', 'amd64',
                'ca6f2d36d96b19b3eb71405b0b80134d8c89380b02204a2512e5c58ceb090628',
            ),
            DebPackage(
                'libgomp1', '14.2.0-19', 'amd64',
                '72b7a1a33c48f3195efeb044111b34ae684b1e640bb6495c832443b798601cd5',
            ),
            DebPackage(
                'libgprofng0', '2.44-3', 'amd64',
                '0d36d0bde85c467ac6735dded08e19dd30ae1369e3908b9eb48ccc0d6ff66648',
            ),
            DebPackage(
                'libgssapi-krb5-2', '1.21.3-5+deb13u1', 'amd64',
                '30847c1fde4240567d7ed3aeab4f655dd591203758b857e85e824045aae70299',
            ),
            DebPackage(
                'libhwasan0', '14.2.0-19', 'amd64',
                '2cdaf797cad8ac30a964ab081370682dd065ae1b0305a0be9d8e0e14cd0657d7',
            ),
            DebPackage(
                'libisl23', '0.27-1', 'amd64',
                'ac8518042e81c00de1effb72bba7e88ac4ecd488f7ea8b9e3ebc63159cb53b35',
            ),
            DebPackage(
                'libitm1', '14.2.0-19', 'amd64',
                'febdb3c528cde1a3abe952e17a1d3cfa7ccaca5b6f506d983d34385dad199490',
            ),
            DebPackage(
                'libjansson4', '2.14-2+b3', 'amd64',
                '60707a62fe6c1228c3389b12a13ca4efd76defc5532473e547a29e99cf7d2a6e',
            ),
            DebPackage(
                'libk5crypto3', '1.21.3-5+deb13u1', 'amd64',
                '7da07ee674b47f1f0be7cc89317c25310086a1f1761217d0f72e6ae2c5a69b84',
            ),
            DebPackage(
                'libkeyutils1', '1.6.3-6', 'amd64',
                '0b11ad17be0300b63ad4eeb4c6450fed24d34b7b740f23e5363dcb29ee6d5eba',
            ),
            DebPackage(
                'libkrb5-3', '1.21.3-5+deb13u1', 'amd64',
                '47d71d6a7f2e59b9bae5f89602397594805113b95889ad18fa703cd53abafc97',
            ),
            DebPackage(
                'libkrb5support0', '1.21.3-5+deb13u1', 'amd64',
                '3a0acd8b37955c0e102c756b52c97df2a31f67b96453c35dab70df218d309117',
            ),
            DebPackage(
                'libldap2', '2.6.10+dfsg-1', 'amd64',
                '60069e4a550ca890113fa89d3001417781b18e146ec5d637d31e368dec9909bd',
            ),
            DebPackage(
                'liblsan0', '14.2.0-19', 'amd64',
                'a0df07da76287a45e665d584363dc2a6a1c4e240aee41b8bbc0f67cdff97cd68',
            ),
            DebPackage(
                'libmpc3', '1.3.1-1+b3', 'amd64',
                '2af0a5c128e03694a41c0b011bd8a958b7297436cdb3a15ddad7866dae8c300b',
            ),
            DebPackage(
                'libmpfr6', '4.2.2-1', 'amd64',
                '75dddce11dabc7fc543712c33dc27b7f2ee66a111763eb5eac654d010b42cd92',
            ),
            DebPackage(
                'libpq-dev', '18.6-1.pgdg13+2', 'amd64',
                'b2add61e7fe0e9328140de456a85c96737b517f9cf62b44fd88e86aa2b765f29',
            ),
            DebPackage(
                'libpq5', '18.6-1.pgdg13+2', 'amd64',
                'c6cc459bb499db4697686533e50bf5943f7e7d6929c04ef55eec184d5436859b',
            ),
            DebPackage(
                'libquadmath0', '14.2.0-19', 'amd64',
                'f5b51cf0ece3ec3bb7494d0cdbff3ce715ae00cfb2b6ed787f7db91319d64a7b',
            ),
            DebPackage(
                'libsasl2-2', '2.1.28+dfsg1-9', 'amd64',
                '66e49d7ae026811b49a0050f18b0325960a2625ffd1ff60d91b7844a815fa9d2',
            ),
            DebPackage(
                'libsasl2-modules-db', '2.1.28+dfsg1-9', 'amd64',
                'a5c38659fbd62c33c6d9bfa2be43e75a572d1818531aad32dd74d0a58cc4bd19',
            ),
            DebPackage(
                'libsframe1', '2.44-3', 'amd64',
                '38f625dfdc582717029ac3a3e97c51d994ec2e7a0e9b230c6b44e40d1276311f',
            ),
            DebPackage(
                'libssl-dev', '3.5.7-1~deb13u3', 'amd64',
                'c5f5f0383cac45209fefe85b3c3308e5ef6743663597d89bedcb96aaa06b8342',
            ),
            DebPackage(
                'libtsan2', '14.2.0-19', 'amd64',
                '529d7f68227d16975076c5f842e8b687faea1b5df8e0dcf62e436d5402844ca5',
            ),
            DebPackage(
                'libubsan1', '14.2.0-19', 'amd64',
                '9205a1bef7d6a52ffc06548e0cde169ff303e688c12d9be3a98f734449077e22',
            ),
            DebPackage(
                'linux-libc-dev', '6.12.113-1', 'all',
                'b2d475e01aaf0030c72bd3a0300d311f8be64aa9e82d82eae5da1a04f4010071',
            ),
            DebPackage(
                'rpcsvc-proto', '1.4.3-1', 'amd64',
                '32ac0692694f8a34cc90c895f4fc739680fb2ef0e2d4870a68833682bf1c81a3',
            ),
        ),
        closure=(
        ),
        lib_dynload=AMD64_BASELINE_IMPORTS,
    ),
})
