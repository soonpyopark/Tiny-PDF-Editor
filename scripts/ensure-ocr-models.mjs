#!/usr/bin/env node
/**
 * Official PP-OCRv5 ONNX weights in ocr/models.
 *
 *   node scripts/ensure-ocr-models.mjs           # missing/wrong hash → download (pinned sha)
 *   node scripts/ensure-ocr-models.mjs --update  # fetch upstream; if hash changed, replace + update pins
 */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MODELS_DIR = path.join(ROOT, "ocr", "models");
const ENSURE_SCRIPT = fileURLToPath(import.meta.url);
const OCR_MODELS_PY = path.join(ROOT, "pdf_editor", "ocr_models.py");

/** @type {{ name: string, filename: string, url: string, sha256: string }[]} */
const MODELS = [
  {
    name: "PP-OCRv5 mobile det",
    filename: "det.onnx",
    url: "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/inference.onnx",
    sha256: "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d",
  },
  {
    name: "PP-OCRv5 korean rec",
    filename: "rec_korean.onnx",
    url: "https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx",
    sha256: "92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08",
  },
  {
    name: "PP-OCRv5 korean dict",
    filename: "rec_korean.yml",
    url: "https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml",
    sha256: "f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998",
  },
];

function sha256File(filePath) {
  const digest = createHash("sha256");
  digest.update(fs.readFileSync(filePath));
  return digest.digest("hex");
}

function sha256Buffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

/**
 * @param {{ name: string, url: string }} spec
 * @returns {Promise<Buffer>}
 */
async function fetchModelBytes(spec) {
  const response = await fetch(spec.url, {
    headers: { "User-Agent": "TinyPDFEditor-NEO/ocr-models" },
    redirect: "follow",
  });
  if (!response.ok) {
    throw new Error(`${spec.name} 다운로드 실패 (HTTP ${response.status})`);
  }
  return Buffer.from(await response.arrayBuffer());
}

/**
 * @param {{ name: string, filename: string, url: string, sha256: string }} spec
 * @param {string} dest
 */
async function downloadPinned(spec, dest) {
  const body = await fetchModelBytes(spec);
  const digest = sha256Buffer(body);
  if (digest !== spec.sha256) {
    throw new Error(
      `${spec.name} 해시가 핀과 다릅니다.\n  기대: ${spec.sha256}\n  실제: ${digest}\n` +
        `upstream 이 바뀌었으면: node scripts/ensure-ocr-models.mjs --update`,
    );
  }
  const tmp = `${dest}.part`;
  fs.writeFileSync(tmp, body);
  fs.renameSync(tmp, dest);
}

/**
 * @param {string} filename
 * @param {string} newSha
 */
function updatePinnedHashes(filename, newSha) {
  const escaped = filename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  let ensureText = fs.readFileSync(ENSURE_SCRIPT, "utf8");
  const ensureNext = ensureText.replace(
    new RegExp(`(filename:\\s*"${escaped}",[\\s\\S]*?sha256:\\s*")[a-f0-9]{64}(")`),
    `$1${newSha}$2`,
  );
  if (ensureNext === ensureText) {
    throw new Error(`ensure-ocr-models.mjs 에서 ${filename} sha256 핀을 찾지 못했습니다.`);
  }
  fs.writeFileSync(ENSURE_SCRIPT, ensureNext, "utf8");

  let pyText = fs.readFileSync(OCR_MODELS_PY, "utf8");
  const pyNext = pyText.replace(
    new RegExp(`(filename="${escaped}",\\s*sha256=")[a-f0-9]{64}(")`),
    `$1${newSha}$2`,
  );
  if (pyNext === pyText) {
    throw new Error(`ocr_models.py 에서 ${filename} sha256 핀을 찾지 못했습니다.`);
  }
  fs.writeFileSync(OCR_MODELS_PY, pyNext, "utf8");

  const entry = MODELS.find((item) => item.filename === filename);
  if (entry) entry.sha256 = newSha;
}

/**
 * Missing / wrong local hash → download matching the pinned sha256.
 */
export async function ensureOcrModels() {
  fs.mkdirSync(MODELS_DIR, { recursive: true });
  for (const spec of MODELS) {
    const dest = path.join(MODELS_DIR, spec.filename);
    if (fs.existsSync(dest) && sha256File(dest) === spec.sha256) {
      continue;
    }
    console.log(`[ocr] ${spec.name} 받는 중 (핀 해시)…`);
    await downloadPinned(spec, dest);
  }
  return MODELS.map((spec) => path.join(MODELS_DIR, spec.filename));
}

/**
 * Fetch upstream; if content hash differs from the pin, replace the file and
 * update sha256 in ensure-ocr-models.mjs + pdf_editor/ocr_models.py.
 *
 * @returns {Promise<{ updated: string[], unchanged: string[] }>}
 */
export async function updateOcrModelsFromUpstream() {
  fs.mkdirSync(MODELS_DIR, { recursive: true });
  /** @type {string[]} */
  const updated = [];
  /** @type {string[]} */
  const unchanged = [];

  for (const spec of MODELS) {
    const dest = path.join(MODELS_DIR, spec.filename);
    console.log(`[ocr] ${spec.name} upstream 확인 중…`);
    const body = await fetchModelBytes(spec);
    const digest = sha256Buffer(body);

    if (digest === spec.sha256) {
      if (!fs.existsSync(dest) || sha256File(dest) !== digest) {
        const tmp = `${dest}.part`;
        fs.writeFileSync(tmp, body);
        fs.renameSync(tmp, dest);
        console.log(`[ocr] ${spec.name}: 핀과 동일 — 로컬 파일만 맞춤`);
      } else {
        console.log(`[ocr] ${spec.name}: 최신 (변경 없음)`);
      }
      unchanged.push(spec.filename);
      continue;
    }

    console.log(`[ocr] ${spec.name}: upstream 변경 감지`);
    console.log(`[ocr]   이전 핀: ${spec.sha256}`);
    console.log(`[ocr]   새 해시: ${digest}`);
    const tmp = `${dest}.part`;
    fs.writeFileSync(tmp, body);
    fs.renameSync(tmp, dest);
    updatePinnedHashes(spec.filename, digest);
    updated.push(spec.filename);
    console.log(`[ocr] ${spec.name}: 파일·핀 갱신 완료`);
  }

  if (updated.length) {
    console.log(`[ocr] 업데이트됨: ${updated.join(", ")}`);
  } else {
    console.log("[ocr] upstream 변경 없음 — 핀 유지");
  }
  return { updated, unchanged };
}

const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  const doUpdate = process.argv.includes("--update");
  const run = doUpdate ? updateOcrModelsFromUpstream : ensureOcrModels;
  run()
    .then((result) => {
      if (doUpdate) {
        console.log("[ocr] upstream 확인 완료");
        return;
      }
      const files = /** @type {string[]} */ (result);
      for (const file of files) {
        if (!fs.existsSync(file)) {
          throw new Error(`OCR model missing: ${file}`);
        }
      }
      console.log("[ocr] verified OCR models");
    })
    .catch((error) => {
      console.error(error instanceof Error ? error.message : error);
      process.exit(1);
    });
}
