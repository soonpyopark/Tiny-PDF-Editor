import { X509Certificate, generateKeyPair } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';
import forge from 'node-forge';
import { APP_NAME } from '../shared/constants.js';
import { normalizeTlsHostnames } from '../shared/httpsConfig.js';
import { statePath } from './context.js';
import { getLocalIPv4Addresses } from './networkInfo.js';
import { getSettings } from './settingsService.js';

/**
 * Local certificate authority + server certificate for the HTTPS option.
 *
 *   <state>/tls/ca.crt, ca.key      created once, 10 years — install ca.crt on other devices
 *   <state>/tls/server.crt, .key    re-issued when the LAN IPs / extra host names change
 *   <state>/tls/meta.json           SANs + expiry of the current server certificate
 *
 * Living in the state folder, the certificates travel with backups and
 * with the portable zip.
 */

const CA_CERT = 'ca.crt';
const CA_KEY = 'ca.key';
const SERVER_CERT = 'server.crt';
const SERVER_KEY = 'server.key';
const META = 'meta.json';

const CA_YEARS = 10;
const SERVER_DAYS = 825;

const generateKeyPairAsync = promisify(generateKeyPair);

export function getTlsDir() {
  return statePath('tls');
}

function files() {
  const dir = getTlsDir();
  return {
    dir,
    caCert: path.join(dir, CA_CERT),
    caKey: path.join(dir, CA_KEY),
    serverCert: path.join(dir, SERVER_CERT),
    serverKey: path.join(dir, SERVER_KEY),
    meta: path.join(dir, META),
  };
}

/** @param {string} file */
function readText(file) {
  try {
    return fs.readFileSync(file, 'utf8');
  } catch {
    return '';
  }
}

function readMeta() {
  try {
    return JSON.parse(fs.readFileSync(files().meta, 'utf8'));
  } catch {
    return null;
  }
}

/** @param {string} value */
const isIpv4 = (value) => /^\d{1,3}(?:\.\d{1,3}){3}$/.test(value);

/** Names the server certificate must cover: localhost, this PC's IPs, extra host names. */
export function desiredTlsSans(extraHostnames = getSettings().tlsHostnames) {
  const sans = new Set(['localhost', '127.0.0.1']);
  for (const address of getLocalIPv4Addresses()) sans.add(address);
  for (const host of normalizeTlsHostnames(extraHostnames)) sans.add(host);
  return [...sans];
}

/**
 * @param {string[]} needed
 * @param {unknown} have
 */
function sansCover(needed, have) {
  if (!Array.isArray(have) || have.length === 0) return false;
  const set = new Set(have.map((item) => String(item).toLowerCase()));
  return needed.every((item) => set.has(item.toLowerCase()));
}

async function newKeyPair() {
  const { publicKey, privateKey } = await generateKeyPairAsync('rsa', {
    modulusLength: 2048,
    publicKeyEncoding: { type: 'spki', format: 'pem' },
    privateKeyEncoding: { type: 'pkcs1', format: 'pem' },
  });
  return {
    publicKey: forge.pki.publicKeyFromPem(publicKey),
    privateKey: forge.pki.privateKeyFromPem(privateKey),
    privateKeyPem: privateKey,
  };
}

const randomSerial = () => `01${forge.util.bytesToHex(forge.random.getBytesSync(15))}`;

async function createCa() {
  const keys = await newKeyPair();
  const cert = forge.pki.createCertificate();
  cert.publicKey = keys.publicKey;
  cert.serialNumber = randomSerial();
  cert.validity.notBefore = new Date(Date.now() - 60_000);
  cert.validity.notAfter = new Date();
  cert.validity.notAfter.setFullYear(cert.validity.notBefore.getFullYear() + CA_YEARS);
  const subject = [
    { name: 'commonName', value: `${APP_NAME} Local CA` },
    { name: 'organizationName', value: APP_NAME },
  ];
  cert.setSubject(subject);
  cert.setIssuer(subject);
  cert.setExtensions([
    { name: 'basicConstraints', cA: true, pathLenConstraint: 0, critical: true },
    { name: 'keyUsage', keyCertSign: true, cRLSign: true, critical: true },
    { name: 'subjectKeyIdentifier' },
  ]);
  cert.sign(keys.privateKey, forge.md.sha256.create());
  return { certPem: forge.pki.certificateToPem(cert), keyPem: keys.privateKeyPem };
}

/**
 * @param {string} caCertPem
 * @param {string} caKeyPem
 * @param {string[]} sans
 */
async function createServerCert(caCertPem, caKeyPem, sans) {
  const caCert = forge.pki.certificateFromPem(caCertPem);
  const caKey = forge.pki.privateKeyFromPem(caKeyPem);
  const keys = await newKeyPair();
  const cert = forge.pki.createCertificate();
  cert.publicKey = keys.publicKey;
  cert.serialNumber = randomSerial();
  cert.validity.notBefore = new Date(Date.now() - 60_000);
  cert.validity.notAfter = new Date();
  cert.validity.notAfter.setDate(cert.validity.notBefore.getDate() + SERVER_DAYS);
  cert.setSubject([
    { name: 'commonName', value: APP_NAME },
    { name: 'organizationName', value: APP_NAME },
  ]);
  cert.setIssuer(caCert.subject.attributes);
  cert.setExtensions([
    { name: 'basicConstraints', cA: false },
    { name: 'keyUsage', digitalSignature: true, keyEncipherment: true },
    { name: 'extKeyUsage', serverAuth: true },
    {
      name: 'subjectAltName',
      altNames: sans.map((value) => (isIpv4(value) ? { type: 7, ip: value } : { type: 2, value })),
    },
    { name: 'subjectKeyIdentifier' },
    // Must be the *CA's* key id; `keyIdentifier: true` would hash this certificate's own key.
    { name: 'authorityKeyIdentifier', keyIdentifier: caCert.generateSubjectKeyIdentifier().getBytes() },
  ]);
  cert.sign(caKey, forge.md.sha256.create());
  return {
    certPem: forge.pki.certificateToPem(cert),
    keyPem: keys.privateKeyPem,
    notAfter: cert.validity.notAfter.toISOString(),
  };
}

/**
 * Makes sure a CA and a server certificate covering the current SANs exist.
 *
 * @param {{ force?: boolean }} [options] force = issue a new server certificate
 * @returns {Promise<{ key: string, cert: string, ca: string, sans: string[], regenerated: boolean }>}
 */
export async function ensureTlsMaterial({ force = false } = {}) {
  const f = files();
  fs.mkdirSync(f.dir, { recursive: true });

  let caCert = readText(f.caCert);
  let caKey = readText(f.caKey);
  if (!caCert || !caKey) {
    const created = await createCa();
    caCert = created.certPem;
    caKey = created.keyPem;
    fs.writeFileSync(f.caCert, caCert, 'utf8');
    fs.writeFileSync(f.caKey, caKey, { encoding: 'utf8', mode: 0o600 });
    force = true; // a new CA invalidates any older server certificate
  }

  const sans = desiredTlsSans();
  const haveServer = fs.existsSync(f.serverCert) && fs.existsSync(f.serverKey);
  const regenerated = force || !haveServer || !sansCover(sans, readMeta()?.sans);

  if (regenerated) {
    const server = await createServerCert(caCert, caKey, sans);
    fs.writeFileSync(f.serverCert, server.certPem, 'utf8');
    fs.writeFileSync(f.serverKey, server.keyPem, { encoding: 'utf8', mode: 0o600 });
    fs.writeFileSync(
      f.meta,
      `${JSON.stringify({ sans, notAfter: server.notAfter, generatedAt: new Date().toISOString() }, null, 2)}\n`,
      'utf8',
    );
  }

  return {
    key: readText(f.serverKey),
    cert: readText(f.serverCert),
    ca: caCert,
    sans: readMeta()?.sans ?? sans,
    regenerated,
  };
}

/** PEM of the CA certificate to install on other devices ('' if none yet). */
export function readCaPem() {
  return readText(files().caCert);
}

export function getTlsStatus() {
  const f = files();
  const meta = readMeta();
  let notAfter = typeof meta?.notAfter === 'string' ? meta.notAfter : '';
  let fingerprint256 = '';
  const serverPem = readText(f.serverCert);
  if (serverPem) {
    try {
      const x509 = new X509Certificate(serverPem);
      fingerprint256 = x509.fingerprint256;
      notAfter = new Date(x509.validTo).toISOString();
    } catch {
      // keep meta values
    }
  }
  return {
    dir: f.dir,
    hasCa: fs.existsSync(f.caCert) && fs.existsSync(f.caKey),
    hasServer: Boolean(serverPem) && fs.existsSync(f.serverKey),
    sans: Array.isArray(meta?.sans) ? meta.sans : [],
    notAfter,
    fingerprint256,
  };
}

/**
 * The Electron window trusts exactly the certificate this app issued, so it
 * works without installing the CA on the PC itself.
 *
 * @param {{ data?: string } | null | undefined} certificate
 */
export function isOwnServerCertificate(certificate) {
  const ours = readText(files().serverCert);
  if (!ours || !certificate) return false;
  try {
    const mine = new X509Certificate(ours);
    const data = String(certificate.data ?? '').trim();
    if (!data) return false;
    const pem = data.includes('BEGIN CERTIFICATE')
      ? data
      : `-----BEGIN CERTIFICATE-----\n${data}\n-----END CERTIFICATE-----`;
    return new X509Certificate(pem).fingerprint256 === mine.fingerprint256;
  } catch {
    return false;
  }
}
