/**
 * Verified public installers for MathTutor 0.7.0.
 * Source: GitHub Releases API + docs/RELEASE_0.7.0.md.
 * Linux is intentionally omitted: no verified public artifact.
 */
export const CURRENT_VERSION = '0.7.0';
export const RELEASE_TAG = 'v0.7.0';
export const RELEASE_URL = `https://github.com/coscatld/MathTutor/releases/tag/${RELEASE_TAG}`;

export type PlatformId = 'windows-x64' | 'macos-arm64';

export type ReleaseAsset = {
  id: PlatformId;
  filename: string;
  url: string;
  sha256: string;
  sha256File: string;
  os: string;
  arch: string;
  notes: string;
  notesEn: string;
};

export const CURRENT_ASSETS: ReleaseAsset[] = [
  {
    id: 'windows-x64',
    filename: 'MathTutor-0.7.0-win-x64-r2.exe',
    url: 'https://github.com/coscatld/MathTutor/releases/download/v0.7.0/MathTutor-0.7.0-win-x64-r2.exe',
    sha256: '5f8246456f26069b81b2bc0265ee71a75ce9550d4b312420345a05d5a9e2a4ec',
    sha256File:
      'https://github.com/coscatld/MathTutor/releases/download/v0.7.0/SHA256SUMS-0.7.0-win-r2.txt',
    os: 'Windows 10/11',
    arch: 'x64',
    notes: 'NSIS 安装包，无 Authenticode 发行证书签名。SmartScreen 可能提示“仍要运行”。',
    notesEn:
      'NSIS installer. Not Authenticode-signed. SmartScreen may ask you to keep the file.',
  },
  {
    id: 'macos-arm64',
    filename: 'MathTutor-0.7.0-mac-arm64-r2.dmg',
    url: 'https://github.com/coscatld/MathTutor/releases/download/v0.7.0/MathTutor-0.7.0-mac-arm64-r2.dmg',
    sha256: 'b12cc6983eb45f52ca9d7f0ccf167f4764b1fbec8ad11af0108362c9b408642f',
    sha256File:
      'https://github.com/coscatld/MathTutor/releases/download/v0.7.0/SHA256SUMS-0.7.0-mac-r2.txt',
    os: 'macOS',
    arch: 'Apple Silicon',
    notes:
      'r2 使用完整本地 ad-hoc 签名，无 Developer ID、未公证。Gatekeeper 默认拒绝，需在“隐私与安全性”中允许。原始 Mac 包已撤回。',
    notesEn:
      'r2 is fully ad-hoc signed locally. No Developer ID and not notarized. Gatekeeper rejects it by default. The original Mac build was withdrawn.',
  },
];

export const LINUX_STATUS = {
  available: false,
  reasonZh:
    '仓库配置了 Linux x64 AppImage 目标，但平台发布矩阵将 Linux 标为 UNTESTED — NO TARGET MACHINE，GitHub Releases 也没有经过验证的 Linux 安装包，因此本页不提供下载入口。',
  reasonEn:
    'A Linux x64 AppImage target is configured, but the platform matrix marks Linux as UNTESTED — NO TARGET MACHINE, and GitHub Releases has no verified Linux installer. This page does not invent a download.',
} as const;
