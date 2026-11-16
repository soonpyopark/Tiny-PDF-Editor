import {
  APP_BUILD_STAMP,
  APP_FILE_NAME,
  APP_NAME,
  APP_VERSION,
  UPDATE_REPO,
  formatAppBuildStamp,
} from '../../shared/constants.js';
import { normalizeAccentColor } from '../../shared/theme.js';
import { normalizeAllowedIpCidrs } from '../../shared/ipCidrCore.js';
import { clearLoginAudit, listLoginAudit } from '../auditService.js';
import {
  deleteBackup,
  importBackup,
  listBackups,
  readBackup,
  restoreBackup,
  runBackup,
} from '../backupService.js';
import { login, revokeMemberSessions, revokeSession } from '../authService.js';
import { isIpAllowed } from '../ipAllowlist.js';
import {
  createMember,
  deleteMember,
  isDefaultAdminPasswordActive,
  listMembers,
  updateMember,
} from '../membersService.js';
import { runtime } from '../runtime.js';
import { getPublicSettings, getSettings, updateSettings } from '../settingsService.js';
import { fetchLatestRelease } from '../updateService.js';
import { ensureTlsMaterial, getTlsStatus } from '../tlsCerts.js';
import { ApiError, RawResponse, defineApi } from './registry.js';

/** `settings.json` + OS-level values the settings UI shows together. */
function settingsPayload() {
  return {
    ...getSettings(),
    autoLaunch: runtime.autoLaunch?.get() ?? false,
    autoLaunchSupported: runtime.autoLaunch?.supported ?? false,
  };
}

export function registerCoreApi() {
  /* ---------------------------------------------------------------- public */

  defineApi('app.info', 'public', () => ({
    name: APP_NAME,
    fileName: APP_FILE_NAME,
    version: APP_VERSION,
    buildStamp: APP_BUILD_STAMP,
    buildStampLabel: formatAppBuildStamp(APP_BUILD_STAMP),
    updateConfigured: Boolean(UPDATE_REPO),
    ...getPublicSettings(),
  }));

  defineApi('auth.hint', 'public', () => ({
    showDefaultAdminHint: isDefaultAdminPasswordActive(),
  }));

  defineApi('auth.login', 'public', async (body, ctx) => {
    const result = await login(body.id, body.password, {
      remember: Boolean(body.remember),
      clientIp: ctx.clientIp,
    });
    if (result.success) return { ...result, clientIp: ctx.clientIp };
    if (result.locked) {
      throw new ApiError(
        `로그인 시도가 너무 많습니다. ${Math.ceil(result.retryAfterSec / 60)}분 뒤에 다시 시도해 주세요.`,
        429,
        { locked: true, retryAfterSec: result.retryAfterSec },
      );
    }
    throw new ApiError('아이디 또는 비밀번호가 올바르지 않습니다.', 401);
  });

  /* ------------------------------------------------------------------ user */

  defineApi('auth.me', 'user', (_body, ctx) => ({ user: ctx.user, clientIp: ctx.clientIp }));

  defineApi('auth.logout', 'user', (_body, ctx) => {
    revokeSession(ctx.token);
    return { ok: true };
  });

  defineApi('update.check', 'user', () => fetchLatestRelease());

  /* ----------------------------------------------------- settings: 일반 */

  defineApi('settings.get', 'admin', () => settingsPayload());

  defineApi('settings.update', 'admin', async (body) => {
    /** @type {Record<string, unknown>} */
    const patch = {};
    if ('accentColor' in body) patch.accentColor = normalizeAccentColor(body.accentColor);
    if ('loginLockoutEnabled' in body) patch.loginLockoutEnabled = Boolean(body.loginLockoutEnabled);
    if ('startupUpdateCheck' in body) patch.startupUpdateCheck = Boolean(body.startupUpdateCheck);
    if ('autoLaunch' in body && runtime.autoLaunch?.supported) {
      runtime.autoLaunch.set(Boolean(body.autoLaunch));
    }
    await updateSettings(patch);
    return settingsPayload();
  });

  /* ---------------------------------------------------- settings: 서버 관리 */

  defineApi('server.info', 'admin', () => ({
    ...runtime.server?.info(),
    tlsHostnames: getSettings().tlsHostnames,
    tls: getTlsStatus(),
    stateRoot: runtime.stateRoot,
    portable: runtime.portable,
  }));

  defineApi('server.apply', 'admin', (body) => {
    if (!runtime.server) throw new ApiError('서버를 사용할 수 없습니다.', 503);
    return runtime.server.applyConfig({
      port: body.port,
      mode: body.mode,
      httpsEnabled: body.httpsEnabled,
      tlsHostnames: body.tlsHostnames,
      regenerateTls: body.regenerateTls === true,
    });
  });

  /** CA certificate other devices install to trust the HTTPS server (created on first use). */
  defineApi('server.caDownload', 'admin', async () => {
    const { ca } = await ensureTlsMaterial();
    return new RawResponse(Buffer.from(ca, 'utf8'), {
      fileName: `${APP_FILE_NAME}-ca.crt`,
      contentType: 'application/x-x509-ca-cert',
    });
  });

  /* ------------------------------------------- settings: 접근가능 IP 대역 */

  defineApi('ip.set', 'admin', async (body, ctx) => {
    const list = normalizeAllowedIpCidrs(body.allowedIpCidrs);
    // Refuse a list that would lock out the very browser saving it.
    if (list.length > 0 && !isIpAllowed(ctx.clientIp, list)) {
      throw new ApiError(
        `현재 접속 IP(${ctx.clientIp})가 목록에 포함되어 있지 않아 저장할 수 없습니다.\n본인 IP 또는 대역을 함께 등록해 주세요.`,
      );
    }
    await updateSettings({ allowedIpCidrs: list });
    return { allowedIpCidrs: list };
  });

  /* ------------------------------------------------- settings: 회원 관리 */

  defineApi('members.list', 'admin', () => ({ members: listMembers() }));

  defineApi('members.create', 'admin', async (body) => ({ member: await createMember(body) }));

  defineApi('members.update', 'admin', async (body, ctx) => {
    if (body.id === ctx.user?.id) {
      if (body.active === false) throw new ApiError('현재 로그인한 계정은 비활성화할 수 없습니다.');
      if (body.role && body.role !== 'super_admin') {
        throw new ApiError('현재 로그인한 계정의 권한은 낮출 수 없습니다.');
      }
    }
    const member = await updateMember(String(body.id ?? ''), {
      displayName: body.displayName,
      role: body.role,
      active: body.active,
      password: body.password || undefined,
    });
    if (body.password || body.active === false) revokeMemberSessions(member.id);
    return { member };
  });

  defineApi('members.delete', 'admin', async (body, ctx) => {
    if (body.id === ctx.user?.id) throw new ApiError('현재 로그인한 계정은 삭제할 수 없습니다.');
    const member = await deleteMember(String(body.id ?? ''));
    revokeMemberSessions(member.id);
    return { member };
  });

  defineApi('audit.list', 'admin', () => ({ entries: listLoginAudit() }));

  defineApi('audit.clear', 'admin', async () => {
    await clearLoginAudit();
    return { ok: true };
  });

  /* ------------------------------------------------- settings: 백업 관리 */

  defineApi('backup.status', 'admin', async () => ({
    entries: await listBackups(),
    config: getSettings().backup,
    stateRoot: runtime.stateRoot,
  }));

  defineApi('backup.saveConfig', 'admin', async (body) => {
    const settings = await updateSettings({
      backup: {
        autoEnabled: Boolean(body.autoEnabled),
        intervalHours: body.intervalHours,
        keepCount: body.keepCount,
      },
    });
    return { config: settings.backup };
  });

  defineApi('backup.run', 'admin', async () => ({ entry: await runBackup('manual') }));

  defineApi('backup.delete', 'admin', async (body) => {
    await deleteBackup(body.fileName);
    return { ok: true };
  });

  defineApi('backup.download', 'admin', async (body) => {
    return new RawResponse(await readBackup(body.fileName), {
      fileName: String(body.fileName),
      contentType: 'application/zip',
    });
  });

  defineApi('backup.import', 'admin', async (body) => {
    if (typeof body.dataBase64 !== 'string' || !body.dataBase64) {
      throw new ApiError('백업 파일이 비어 있습니다.');
    }
    return { entry: await importBackup(Buffer.from(body.dataBase64, 'base64')) };
  });

  defineApi('backup.restore', 'admin', async (body) => restoreBackup(body.fileName));
}
