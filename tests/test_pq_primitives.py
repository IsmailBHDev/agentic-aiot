"""IOT-173 : disponibilité et tailles des primitives post-quantiques retenues.

Ces tests hors réseau vérifient, sous Windows et Linux, que la version de
`cryptography` épinglée dans requirements.txt fournit ML-DSA (FIPS 204),
ML-KEM (FIPS 203) et Ed25519, avec les tailles fixées par les standards.
Ils ne touchent ni aux données, ni au seuil B2, ni aux résultats historiques.
"""

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519, mldsa, mlkem

MESSAGE = (
    b'{"v":1,"id":"test","src":{"agent":"node-01"},'
    b'"payload":{"temperature":25.742,"vibration":0.175}}'
)

# Tailles en octets : (clé publique, signature)
ML_DSA_SIZES = {
    mldsa.MLDSA44PrivateKey: (1312, 2420),
    mldsa.MLDSA65PrivateKey: (1952, 3309),
    mldsa.MLDSA87PrivateKey: (2592, 4627),
}

# Tailles en octets : (clé publique, texte chiffré)
ML_KEM_SIZES = {
    mlkem.MLKEM768PrivateKey: (1184, 1088),
    mlkem.MLKEM1024PrivateKey: (1568, 1568),
}


@pytest.mark.parametrize("key_class", list(ML_DSA_SIZES), ids=lambda c: c.__name__)
def test_ml_dsa_round_trip_and_sizes(key_class):
    private_key = key_class.generate()
    public_key = private_key.public_key()
    signature = private_key.sign(MESSAGE)

    public_key.verify(signature, MESSAGE)
    assert (len(public_key.public_bytes_raw()), len(signature)) == ML_DSA_SIZES[key_class]


@pytest.mark.parametrize("key_class", list(ML_DSA_SIZES), ids=lambda c: c.__name__)
def test_ml_dsa_rejects_modified_message(key_class):
    private_key = key_class.generate()
    signature = private_key.sign(MESSAGE)
    tampered = MESSAGE.replace(b"25.742", b"29.242")

    with pytest.raises(InvalidSignature):
        private_key.public_key().verify(signature, tampered)


def test_ml_dsa_rejects_other_sensor_key():
    signature = mldsa.MLDSA44PrivateKey.generate().sign(MESSAGE)
    other_public_key = mldsa.MLDSA44PrivateKey.generate().public_key()

    with pytest.raises(InvalidSignature):
        other_public_key.verify(signature, MESSAGE)


@pytest.mark.parametrize("key_class", list(ML_KEM_SIZES), ids=lambda c: c.__name__)
def test_ml_kem_shared_secret_and_sizes(key_class):
    private_key = key_class.generate()
    public_key = private_key.public_key()
    shared_secret, ciphertext = public_key.encapsulate()

    assert private_key.decapsulate(ciphertext) == shared_secret
    assert len(shared_secret) == 32
    assert (len(public_key.public_bytes_raw()), len(ciphertext)) == ML_KEM_SIZES[key_class]


def test_ed25519_reference_round_trip():
    private_key = ed25519.Ed25519PrivateKey.generate()
    signature = private_key.sign(MESSAGE)

    private_key.public_key().verify(signature, MESSAGE)
    assert len(signature) == 64
    with pytest.raises(InvalidSignature):
        private_key.public_key().verify(signature, MESSAGE + b" ")
