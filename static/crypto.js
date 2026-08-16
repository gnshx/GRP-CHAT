/*
 * Member 3 — Digital Signatures, client side
 * (requirement #5: "Each sender has a signing key pair"
 *  requirement #6: "Messages contain a sender signature and the signature is verified")
 *
 * Generates an ECDSA P-256 key pair in the browser using the built-in
 * Web Crypto API. The private key stays in memory in this tab only — it is
 * never sent anywhere. Only the public key (as a JWK) is sent to the server
 * at join time so it can verify signatures.
 */

let keyPair = null;

async function ensureKeyPair() {
    if (keyPair) return keyPair;

    keyPair = await crypto.subtle.generateKey(
        { name: "ECDSA", namedCurve: "P-256" },
        true,
        ["sign", "verify"]
    );

    return keyPair;
}

async function exportPublicKeyJwk() {
    const pair = await ensureKeyPair();
    return await crypto.subtle.exportKey("jwk", pair.publicKey);
}

/*
 * MUST exactly match app.py's canonical_message() on the server, or every
 * signature verification will fail.
 */
function canonicalMessage(username, text, timestamp) {
    return `${username}|${text}|${timestamp}`;
}

async function signMessage(username, text, timestamp) {
    const pair = await ensureKeyPair();

    const data = new TextEncoder().encode(
        canonicalMessage(username, text, timestamp)
    );

    const sigBuffer = await crypto.subtle.sign(
        { name: "ECDSA", hash: "SHA-256" },
        pair.privateKey,
        data
    );

    return arrayBufferToBase64(sigBuffer);
}

function arrayBufferToBase64(buffer) {
    let binary = "";
    const bytes = new Uint8Array(buffer);

    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }

    return btoa(binary);
}
